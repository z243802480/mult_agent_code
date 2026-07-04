import React, { useEffect, useState } from "react";
import { Globe, RefreshCw } from "lucide-react";
import type { WorkspaceFile } from "../../types";
import { api } from "../../api";

// Live browser preview (PREVIEW-1, VS Code Live Preview / live-server model): the studio backend runs
// a dedicated localhost static server for the workspace, so the iframe loads a real URL and MULTI-FILE
// sites resolve their relative/absolute assets (CSS/JS/images). If that server didn't bind, we fall
// back to srcDoc rendering of a self-contained HTML file so the tab still works.
// The frame is cross-origin from the studio (separate port) AND sandboxed, so it cannot reach the
// studio page, its cookies, or storage. Served static content is raw (unredacted) but protected paths
// are refused server-side.
// PREVIEW-3: when the backend is started with --preview-proxy <url|port> (or ASTERIA_PREVIEW_PROXY),
// the preview server reverse-proxies a running dev server (Vite/Next/CRA) — HTTP + websocket HMR — so
// framework/SPA apps (which need a bundler, not static files) preview at the root. This tab detects
// that via preview-info.mode and frames the dev-server root instead of a picked workspace file.

function isHtml(path: string): boolean {
  return /\.html?$/i.test(path);
}

function pickDefault(htmlFiles: WorkspaceFile[]): string {
  const index = htmlFiles.find((file) => /(^|\/)index\.html?$/i.test(file.path));
  return (index ?? htmlFiles[0])?.path ?? "";
}

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function PreviewPane({ files }: { files: WorkspaceFile[] }) {
  const htmlFiles = files.filter((file) => isHtml(file.path));
  const [selected, setSelected] = useState("");
  const [previewPort, setPreviewPort] = useState<number | null>(null);
  const [portResolved, setPortResolved] = useState(false);
  const [fallbackContent, setFallbackContent] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // PREVIEW-3: when the backend reverse-proxies a dev server, the app lives at the preview root — there
  // are no static workspace HTML files to pick, so the whole tab switches to a single framed SPA.
  const [proxyTarget, setProxyTarget] = useState<string | null>(null);

  // Resolve the dedicated preview server's port + mode once.
  useEffect(() => {
    let cancelled = false;
    api
      .previewInfo()
      .then((res) => {
        if (cancelled) return;
        setPreviewPort(res.ok && res.port ? res.port : null);
        setProxyTarget(res.mode === "proxy" ? res.target ?? null : null);
      })
      .catch(() => {
        if (!cancelled) { setPreviewPort(null); setProxyTarget(null); }
      })
      .finally(() => {
        if (!cancelled) setPortResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const proxyMode = Boolean(proxyTarget && previewPort);

  // Default / re-pick the selected html file as the workspace file set changes.
  useEffect(() => {
    if (!htmlFiles.length) {
      setSelected("");
      return;
    }
    if (!selected || !htmlFiles.some((file) => file.path === selected)) {
      setSelected(pickDefault(htmlFiles));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  // Fallback path (srcDoc) only when the dedicated preview server is unavailable.
  useEffect(() => {
    if (!portResolved || previewPort || !selected) {
      setFallbackContent(null);
      return;
    }
    let cancelled = false;
    api
      .previewFile(selected)
      .then((res) => {
        if (!cancelled) setFallbackContent(res.ok && typeof res.content === "string" ? res.content : null);
      })
      .catch(() => {
        if (!cancelled) setFallbackContent(null);
      });
    return () => {
      cancelled = true;
    };
  }, [portResolved, previewPort, selected, reloadKey]);

  if (!htmlFiles.length && !proxyMode) {
    return (
      <div className="previewPane empty">
        <Globe size={22} />
        <p>No web output to preview yet.</p>
        <small>HTML files in your workspace render here — live and interactive.</small>
      </div>
    );
  }

  const src = previewPort
    ? proxyMode
      ? `${window.location.protocol}//${window.location.hostname}:${previewPort}/`
      : `${window.location.protocol}//${window.location.hostname}:${previewPort}/${encodePath(selected)}`
    : null;

  return (
    <div className="previewPane">
      <div className="previewBar">
        {proxyMode ? (
          <span className="previewPath" title={`Reverse-proxying dev server ${proxyTarget}`}>Dev server</span>
        ) : htmlFiles.length > 1 ? (
          <select
            className="previewSelect"
            aria-label="Preview file"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            {htmlFiles.map((file) => (
              <option key={file.path} value={file.path}>
                {file.path}
              </option>
            ))}
          </select>
        ) : (
          <span className="previewPath" title={selected}>{selected}</span>
        )}
        {proxyMode ? (
          <span className="previewLive" title={`Reverse-proxying ${proxyTarget} (HMR live)`}>Dev · HMR</span>
        ) : (
          src && <span className="previewLive" title="Auto-refreshes when workspace files change">Live</span>
        )}
        <button
          type="button"
          className="previewRefresh"
          title="Reload preview"
          aria-label="Reload preview"
          onClick={() => setReloadKey((key) => key + 1)}
        >
          <RefreshCw size={13} />
        </button>
      </div>
      <div className="previewFrameWrap">
        {src ? (
          <iframe
            key={`${src}-${reloadKey}`}
            className="previewFrame"
            title="Workspace preview"
            sandbox="allow-scripts allow-same-origin allow-forms"
            src={src}
          />
        ) : fallbackContent != null ? (
          <iframe
            key={`fallback-${selected}-${reloadKey}`}
            className="previewFrame"
            title="Workspace preview"
            sandbox="allow-scripts"
            srcDoc={fallbackContent}
          />
        ) : (
          <div className="previewStatus muted">{portResolved ? "Loading preview…" : "Starting preview…"}</div>
        )}
      </div>
    </div>
  );
}
