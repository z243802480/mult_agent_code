import { spawn } from "node:child_process";
import { createServer } from "node:http";
import net from "node:net";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Proves PREVIEW-3: when --preview-proxy points at a running dev server, the dedicated preview server
// reverse-proxies HTTP requests AND the websocket (HMR) upgrade to it, and preview-info reports proxy
// mode. This is what lets SPA/framework apps (Vite/Next/CRA) preview instead of raw static files.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
function assert(cond, message) {
  if (!cond) throw new Error(message);
}

// Ports are allocated at runtime instead of hard-coded: fixed ports made this smoke fail
// intermittently when an earlier run's socket was still bound or another smoke held one.
// The preview port is not allocated here — the server picks its own and reports it via preview-info.
function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

// Fake dev server: answers HTTP with distinctive markers and completes a websocket upgrade so we can
// prove both proxy paths without pulling in Vite.
const devServer = createServer((req, res) => {
  if (req.url === "/assets/app.js") {
    res.writeHead(200, { "content-type": "application/javascript" });
    res.end("DEV_ASSET_MARKER");
    return;
  }
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(`<h1>DEV_ROOT_MARKER ${req.url}</h1>`);
});
devServer.on("upgrade", (req, socket) => {
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nX-Dev-Upgrade: DEV_WS_MARKER\r\n\r\n",
  );
});
await new Promise((resolve) => devServer.listen(0, "127.0.0.1", resolve));
const devPort = devServer.address().port;

const mainPort = Number(process.env.ASTERIA_STUDIO_PREVIEW_PROXY_PORT) || (await freePort());
const mainBase = `http://127.0.0.1:${mainPort}`;

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-preview-proxy-smoke-"));
// A static file that must be IGNORED in proxy mode (everything is forwarded to the dev server).
await fs.writeFile(path.join(workspace, "index.html"), "<h1>STATIC_SHOULD_NOT_SHOW</h1>", "utf8");

const server = spawn(
  process.execPath,
  [
    "server.mjs",
    "--workspace",
    workspace,
    "--runtime-root",
    repoRoot,
    "--port",
    String(mainPort),
    "--preview-proxy",
    `http://127.0.0.1:${devPort}`,
  ],
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);

try {
  await waitForHealth();
  const info = await fetchJson(`${mainBase}/api/studio/preview-info`);
  assert(info.ok && info.port, `preview server not up: ${JSON.stringify(info)}`);
  assert(info.mode === "proxy", `expected proxy mode, got ${info.mode}`);
  assert(info.target === `http://127.0.0.1:${devPort}`, `wrong proxy target: ${info.target}`);
  const pv = `http://127.0.0.1:${info.port}`;

  // Root is proxied to the dev server (NOT the workspace's static index.html).
  const root = await fetchRaw(`${pv}/`);
  assert(
    root.status === 200 && root.body.includes("DEV_ROOT_MARKER"),
    `root not proxied: ${root.status} ${root.body.slice(0, 60)}`,
  );
  assert(!root.body.includes("STATIC_SHOULD_NOT_SHOW"), "static file leaked through in proxy mode");

  // A deep asset path forwards with the dev server's content-type.
  const asset = await fetchRaw(`${pv}/assets/app.js`);
  assert(
    asset.status === 200 &&
      /javascript/.test(asset.type) &&
      asset.body.includes("DEV_ASSET_MARKER"),
    `asset not proxied: ${asset.status} ${asset.type}`,
  );

  // Websocket (HMR) upgrade is proxied end-to-end: the dev server's 101 + marker header comes back.
  const upgraded = await rawUpgrade(info.port);
  assert(
    /101 Switching Protocols/.test(upgraded),
    `no 101 from proxied upgrade: ${upgraded.slice(0, 80)}`,
  );
  assert(
    /DEV_WS_MARKER/.test(upgraded),
    `dev server upgrade header not forwarded: ${upgraded.slice(0, 120)}`,
  );

  console.log(
    "Studio preview-proxy smoke passed (HTTP reverse-proxy, asset forwarding, websocket upgrade, proxy-mode info)",
  );
} finally {
  server.kill("SIGTERM");
  devServer.close();
  await fs.rm(workspace, { recursive: true, force: true });
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${mainBase}/api/health`);
      if ((await r.json()).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url) {
  const r = await fetch(url);
  const t = await r.text();
  if (!r.ok) throw new Error(`${url} -> ${r.status}: ${t}`);
  return JSON.parse(t);
}

async function fetchRaw(url) {
  const r = await fetch(url, { redirect: "manual" });
  return { status: r.status, type: r.headers.get("content-type") || "", body: await r.text() };
}

// Send a raw websocket-style Upgrade request to the preview port and return the response head.
function rawUpgrade(previewPort) {
  return new Promise((resolve, reject) => {
    const sock = net.connect(previewPort, "127.0.0.1", () => {
      sock.write(
        "GET /__hmr HTTP/1.1\r\n" +
          `Host: 127.0.0.1:${previewPort}\r\n` +
          "Upgrade: websocket\r\n" +
          "Connection: Upgrade\r\n" +
          "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n" +
          "Sec-WebSocket-Version: 13\r\n\r\n",
      );
    });
    let buf = "";
    const done = setTimeout(() => {
      sock.destroy();
      resolve(buf);
    }, 3000);
    sock.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      if (buf.includes("\r\n\r\n")) {
        clearTimeout(done);
        sock.destroy();
        resolve(buf);
      }
    });
    sock.on("error", (err) => {
      clearTimeout(done);
      reject(err);
    });
  });
}
