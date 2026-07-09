// PREVIEW subsystem for the Studio server, extracted verbatim from server.mjs.
//
// A dedicated localhost-only static server (own port) that serves the workspace so the Preview
// tab's iframe can load MULTI-FILE sites with real asset resolution, plus a live-reload SSE
// channel + workspace watcher, plus an opt-in reverse-proxy mode to a dev server (Vite/Next/…).
//
// `createPreviewSubsystem` owns all the mutable state (bound port, SSE clients, debounce timer)
// internally and exposes only `startPreviewServer` + `getPreviewPort`. It reads the active
// workspace via `getWorkspace()` at start (the original captured `workspace` once at bootstrap).
// `previewProxyTarget` is computed by the caller (from args/env) and injected. Bodies are otherwise
// byte-identical to the original.
import { createServer, request as httpRequest } from "node:http";
import { existsSync, statSync, watch as fsWatch, promises as fs } from "node:fs";
import path from "node:path";
import { isSafeWorkspacePath } from "./workspace-paths.mjs";

const PREVIEW_MIME = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".avif": "image/avif",
  ".ico": "image/x-icon",
  ".bmp": "image/bmp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".txt": "text/plain; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".webmanifest": "application/manifest+json",
};

function previewContentType(filePath) {
  return PREVIEW_MIME[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

// Accept a full URL ("http://127.0.0.1:5173"), host:port ("localhost:3000"), or a bare port ("5173",
// → 127.0.0.1:5173). Only http is proxied (local dev servers are http); returns null when unset/invalid.
export function normalizeProxyTarget(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return normalizeProxyTarget(`http://127.0.0.1:${raw}`);
  try {
    const url = new URL(/^https?:\/\//i.test(raw) ? raw : `http://${raw}`);
    if (url.protocol !== "http:") return null;
    const targetPort = url.port || "80";
    return {
      hostname: url.hostname,
      port: targetPort,
      origin: `http://${url.hostname}:${targetPort}`,
    };
  } catch {
    return null;
  }
}

export function createPreviewSubsystem({ getWorkspace, previewProxyTarget }) {
  let previewPort = null; // PREVIEW-1: port of the dedicated static workspace server (null until bound)
  const previewSseClients = new Set(); // PREVIEW-2: live-reload SSE connections from preview iframes
  let previewReloadTimer = null;

  // PREVIEW-1: a dedicated static server (own port, localhost-only) that serves the workspace so the
  // Preview tab's iframe can load MULTI-FILE sites with real relative/absolute asset resolution — the
  // live-server / VS Code Live Preview model, not the srcDoc self-contained-only hack. Path-safe:
  // reuses isSafeWorkspacePath (no traversal; .env/secrets/.git/keys/node_modules/dist refused);
  // serves files only, no directory listing; a trailing slash defaults to index.html.
  function startPreviewServer(startPort) {
    const workspaceRoot = path.resolve(getWorkspace());
    let attempt = 0;
    const server = createServer(async (req, res) => {
      try {
        // PREVIEW-3: in proxy mode every request is reverse-proxied to the dev server, which owns
        // routing, bundling and its own HMR — we do not serve static files or inject a reload client.
        if (previewProxyTarget) {
          proxyToDevServer(req, res, previewProxyTarget);
          return;
        }
        if (req.method !== "GET" && req.method !== "HEAD") {
          res.writeHead(405);
          res.end("method not allowed");
          return;
        }
        let pathname = decodeURIComponent((req.url || "/").split("?")[0].split("#")[0]);
        // PREVIEW-2: live-reload SSE channel — the injected script (below) connects here; the workspace
        // watcher broadcasts "reload" so the preview refreshes when the agent edits files.
        if (pathname === "/__livereload") {
          res.writeHead(200, {
            "content-type": "text/event-stream; charset=utf-8",
            "cache-control": "no-cache",
            connection: "keep-alive",
          });
          res.write(": connected\n\n");
          previewSseClients.add(res);
          const ping = setInterval(() => {
            try {
              res.write(": ping\n\n");
            } catch {}
          }, 20000);
          req.on("close", () => {
            clearInterval(ping);
            previewSseClients.delete(res);
          });
          return;
        }
        if (pathname.endsWith("/")) pathname += "index.html";
        const rel = pathname.replace(/^\/+/, "") || "index.html";
        if (!isSafeWorkspacePath(rel)) {
          res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
          res.end("Forbidden");
          return;
        }
        const abs = path.resolve(workspaceRoot, rel);
        if (abs !== workspaceRoot && !abs.startsWith(workspaceRoot + path.sep)) {
          res.writeHead(403);
          res.end("Forbidden");
          return;
        }
        if (!existsSync(abs) || !statSync(abs).isFile()) {
          res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
          res.end("Not found");
          return;
        }
        const contentType = previewContentType(abs);
        const body = await fs.readFile(abs);
        // PREVIEW-2: inject the live-reload client into served HTML so edits auto-refresh the preview.
        if (contentType.startsWith("text/html") && req.method !== "HEAD") {
          let html = body.toString("utf8");
          const snippet =
            '\n<script>(function(){try{var s=new EventSource("/__livereload");s.onmessage=function(e){if(e.data==="reload")location.reload();};}catch(_){}})();</script>\n';
          html = html.includes("</body>")
            ? html.replace("</body>", `${snippet}</body>`)
            : html + snippet;
          res.writeHead(200, {
            "content-type": contentType,
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
          });
          res.end(html);
          return;
        }
        res.writeHead(200, {
          "content-type": contentType,
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        });
        res.end(req.method === "HEAD" ? undefined : body);
      } catch {
        res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
        res.end("Preview error");
      }
    });
    // PREVIEW-3: proxy the websocket upgrade too, so the dev server's HMR socket keeps working through
    // the preview iframe (Vite/Next live-update the app without a full reload).
    server.on("upgrade", (req, socket, head) => {
      if (!previewProxyTarget) {
        socket.destroy();
        return;
      }
      const upstream = httpRequest({
        hostname: previewProxyTarget.hostname,
        port: previewProxyTarget.port,
        path: req.url,
        method: req.method,
        headers: {
          ...req.headers,
          host: `${previewProxyTarget.hostname}:${previewProxyTarget.port}`,
        },
      });
      upstream.on("upgrade", (upRes, upSocket, upHead) => {
        const statusLine = `HTTP/1.1 ${upRes.statusCode} ${upRes.statusMessage}\r\n`;
        const headerLines = Object.entries(upRes.headers)
          .map(([k, v]) => `${k}: ${v}`)
          .join("\r\n");
        socket.write(`${statusLine}${headerLines}\r\n\r\n`);
        if (upHead?.length) upSocket.unshift(upHead);
        upSocket.pipe(socket);
        socket.pipe(upSocket);
        upSocket.on("error", () => socket.destroy());
        socket.on("error", () => upSocket.destroy());
      });
      upstream.on("error", () => socket.destroy());
      if (head?.length) upstream.write(head);
      upstream.end();
    });
    const tryPort = (p) => {
      const onError = (err) => {
        if (err && err.code === "EADDRINUSE" && attempt < 15) {
          attempt += 1;
          tryPort(p + 1);
        } else {
          previewPort = null;
          console.error(`Asteria preview server failed: ${err?.message || err}`);
        }
      };
      server.once("error", onError);
      server.listen(p, "127.0.0.1", () => {
        server.removeListener("error", onError);
        previewPort = p;
        if (previewProxyTarget) {
          console.log(
            `Asteria preview server on http://127.0.0.1:${p} (proxy → ${previewProxyTarget.origin})`,
          );
        } else {
          console.log(`Asteria preview server on http://127.0.0.1:${p} (workspace static)`);
          startPreviewWatcher();
        }
      });
    };
    tryPort(startPort);
  }

  // PREVIEW-3: reverse-proxy one HTTP request to the configured dev server. A dead dev server yields a
  // clear 502 with the origin, not a hang, so the Preview tab can tell the user to start their server.
  function proxyToDevServer(req, res, target) {
    const upstream = httpRequest(
      {
        hostname: target.hostname,
        port: target.port,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: `${target.hostname}:${target.port}` },
      },
      (upRes) => {
        res.writeHead(upRes.statusCode || 502, upRes.headers);
        upRes.pipe(res);
      },
    );
    upstream.on("error", (err) => {
      if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end(
        `Preview proxy: dev server ${target.origin} is unreachable (${err.code || err.message}). Start it, then reload.`,
      );
    });
    req.pipe(upstream);
  }

  function broadcastPreviewReload() {
    for (const res of [...previewSseClients]) {
      try {
        res.write("data: reload\n\n");
      } catch {
        previewSseClients.delete(res);
      }
    }
  }

  // PREVIEW-2: watch the workspace and tell connected previews to reload on change. Ignore runtime
  // churn (.asteria writes constantly during a run) and heavy/generated dirs, or the preview would
  // reload-storm. Debounced so a burst of writes coalesces into one reload.
  function startPreviewWatcher() {
    const root = path.resolve(getWorkspace());
    try {
      fsWatch(root, { recursive: true }, (_event, filename) => {
        if (!filename) return;
        const rel = String(filename).replace(/\\/g, "/");
        if (/(^|\/)(\.asteria|\.git|node_modules|dist|\.venv|__pycache__)(\/|$)/i.test(rel)) return;
        if (previewReloadTimer) return;
        previewReloadTimer = setTimeout(() => {
          previewReloadTimer = null;
          broadcastPreviewReload();
        }, 150);
      });
    } catch (err) {
      console.error(`Asteria preview watcher failed: ${err?.message || err}`);
    }
  }

  return {
    startPreviewServer,
    getPreviewPort: () => previewPort,
  };
}
