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

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\//, "").trim();
}

// Touched-by-this-session check — tolerant of one side carrying a directory prefix the other lacks
// (events sometimes record workspace-absolute paths while the file list is workspace-relative).
function sessionTouched(filePath: string, touched: string[]): boolean {
  const p = normalizePath(filePath);
  return touched.some((raw) => {
    const t = normalizePath(raw);
    return t === p || t.endsWith(`/${p}`) || p.endsWith(`/${t}`);
  });
}

export function PreviewPane({
  files,
  sessionPaths,
}: {
  files: WorkspaceFile[];
  sessionPaths: string[];
}) {
  // Only this session's own artifacts are preview candidates — the workspace is shared across
  // sessions and surfacing another session's page here reads as an unrelated project (real
  // user friction, 2026-07-16). The dev-server proxy mode stays workspace-level by design: it
  // is an explicit backend flag, not a per-session artifact.
  const htmlFiles = files.filter(
    (file) => isHtml(file.path) && sessionTouched(file.path, sessionPaths),
  );
  // Lazy-init to the default pick so the first frame already names a file (the effect below only
  // re-picks when the workspace file set changes later).
  const [selected, setSelected] = useState(() => pickDefault(htmlFiles));
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
        setProxyTarget(res.mode === "proxy" ? (res.target ?? null) : null);
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewPort(null);
          setProxyTarget(null);
        }
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
        if (!cancelled)
          setFallbackContent(res.ok && typeof res.content === "string" ? res.content : null);
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
        <p>本会话暂无可预览的网页产出。</p>
        <small>本会话中产出的 HTML 会在此实时、可交互地渲染；其他会话的产物不在此显示。</small>
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
          <span className="previewPath" title={`反向代理开发服务器 ${proxyTarget}`}>
            开发服务器
          </span>
        ) : htmlFiles.length > 1 ? (
          <select
            className="previewSelect"
            aria-label="预览文件"
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
          <span className="previewPath" title={selected}>
            {selected}
          </span>
        )}
        {proxyMode ? (
          <span className="previewLive" title={`反向代理 ${proxyTarget}(HMR 实时)`}>
            开发 · HMR
          </span>
        ) : (
          src && (
            <span className="previewLive" title="工作区文件变化时自动刷新">
              实时
            </span>
          )
        )}
        <button
          type="button"
          className="previewRefresh"
          title="重新加载预览"
          aria-label="重新加载预览"
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
            title="工作区预览"
            sandbox="allow-scripts allow-same-origin allow-forms"
            src={src}
          />
        ) : fallbackContent != null ? (
          <iframe
            key={`fallback-${selected}-${reloadKey}`}
            className="previewFrame"
            title="工作区预览"
            sandbox="allow-scripts"
            srcDoc={fallbackContent}
          />
        ) : (
          <div className="previewStatus muted">{portResolved ? "加载预览中…" : "启动预览中…"}</div>
        )}
      </div>
    </div>
  );
}
