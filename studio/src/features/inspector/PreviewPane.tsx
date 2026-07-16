import React, { useEffect, useState } from "react";
import { ExternalLink, Globe, RefreshCw, TriangleAlert, X } from "lucide-react";
import type { WorkspaceFile } from "../../types";
import { api } from "../../api";
import {
  DEVICE_PRESETS,
  isPreviewErrorMessage,
  pushPreviewError,
  type DevicePresetId,
} from "./previewConsole";

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
  // G10 预览控制台: page errors forwarded by the injected preview client (static mode only — the
  // proxied dev server owns its own error overlay), plus responsive device-width presets.
  const [pageErrors, setPageErrors] = useState<string[]>([]);
  const [errorsOpen, setErrorsOpen] = useState(false);
  const [device, setDevice] = useState<DevicePresetId>("fit");

  useEffect(() => {
    // Same-host origins only + the injected client's distinctive envelope. Deliberately NOT gated
    // on the previewPort state: a synchronous console.error fires while previewInfo is still in
    // flight, and a port-state gate dropped exactly those earliest errors (observed live).
    const originPrefix = `${window.location.protocol}//${window.location.hostname}:`;
    function onMessage(event: MessageEvent) {
      if (!event.origin.startsWith(originPrefix)) return;
      if (!isPreviewErrorMessage(event.data)) return;
      const message = event.data.message;
      setPageErrors((errors) => pushPreviewError(errors, message));
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // Errors belong to the page instance that produced them: switching file/session (a new iframe
  // mount) starts a fresh slate, same as the reload button.
  useEffect(() => {
    setPageErrors([]);
  }, [selected]);

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

  // Default / re-pick the selected html file as the candidate set changes. Keyed on BOTH inputs of
  // htmlFiles: the workspace file list AND the session's touched paths — a session switch changes
  // only the latter, and keying on [files] alone left `selected` empty after switching into a
  // session that has artifacts (observed live 2026-07-17: iframe stuck on the server root).
  useEffect(() => {
    if (!htmlFiles.length) {
      setSelected("");
      return;
    }
    if (!selected || !htmlFiles.some((file) => file.path === selected)) {
      setSelected(pickDefault(htmlFiles));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, sessionPaths]);

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
        <div className="previewDevices" role="group" aria-label="预览宽度">
          {DEVICE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={device === preset.id ? "active" : ""}
              title={preset.width ? `${preset.width}px 宽度` : "填满面板宽度"}
              onClick={() => setDevice(preset.id)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        {src && (
          <a
            className="previewRefresh"
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            title="在浏览器中打开"
            aria-label="在浏览器中打开"
          >
            <ExternalLink size={13} />
          </a>
        )}
        <button
          type="button"
          className="previewRefresh"
          title="重新加载预览"
          aria-label="重新加载预览"
          onClick={() => {
            setPageErrors([]);
            setReloadKey((key) => key + 1);
          }}
        >
          <RefreshCw size={13} />
        </button>
      </div>
      <div className="previewFrameWrap">
        {src ? (
          <iframe
            key={`${src}-${reloadKey}`}
            className={`previewFrame${device !== "fit" ? " deviceWidth" : ""}`}
            style={
              device !== "fit"
                ? { width: DEVICE_PRESETS.find((p) => p.id === device)?.width ?? undefined }
                : undefined
            }
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
      {pageErrors.length > 0 && (
        <div className="previewErrorBar">
          <button
            type="button"
            className="previewErrorHead"
            onClick={() => setErrorsOpen(!errorsOpen)}
            aria-expanded={errorsOpen}
          >
            <TriangleAlert size={13} />
            <span>页面报错 {pageErrors.length} 条</span>
          </button>
          <button
            type="button"
            className="previewErrorClear"
            title="清空报错"
            aria-label="清空报错"
            onClick={() => setPageErrors([])}
          >
            <X size={13} />
          </button>
          {errorsOpen && (
            <ul className="previewErrorList">
              {pageErrors.map((error, index) => (
                <li key={`${index}-${error.slice(0, 20)}`}>{error}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
