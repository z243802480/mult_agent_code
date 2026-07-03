import React, { useEffect, useState } from "react";
import { Globe, RefreshCw } from "lucide-react";
import type { WorkspaceFile } from "../../types";
import { api } from "../../api";

// Live browser preview (like Claude Code artifacts / Cursor / v0): render the workspace's HTML output
// in a sandboxed iframe so the user SEES and interacts with the built result. Frontend-only — reuses
// the file-preview endpoint and srcDoc. `sandbox="allow-scripts"` runs the page's JS (interactive apps
// like games) but withholds same-origin, so the frame can't reach the parent, cookies, or storage.
// Caveat: best for self-contained HTML (inline CSS/JS); multi-file apps with relative asset URLs won't
// resolve under srcDoc, and content is redacted + size-capped by the preview endpoint.

function isHtml(path: string): boolean {
  return /\.html?$/i.test(path);
}

function pickDefault(htmlFiles: WorkspaceFile[]): string {
  const index = htmlFiles.find((file) => /(^|\/)index\.html?$/i.test(file.path));
  return (index ?? htmlFiles[0])?.path ?? "";
}

export function PreviewPane({ files }: { files: WorkspaceFile[] }) {
  const htmlFiles = files.filter((file) => isHtml(file.path));
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Default the selection once the html file set is known (or re-pick if the current one disappeared).
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

  useEffect(() => {
    if (!selected) {
      setContent(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .previewFile(selected)
      .then((res) => {
        if (cancelled) return;
        if (res.ok && typeof res.content === "string") {
          setContent(res.content);
        } else {
          setContent(null);
          setError(res.error || "Could not load this file.");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setContent(null);
          setError(String((err as Error).message || err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, reloadKey]);

  if (!htmlFiles.length) {
    return (
      <div className="previewPane empty">
        <Globe size={22} />
        <p>No web output to preview yet.</p>
        <small>HTML files in your workspace render here — live and interactive.</small>
      </div>
    );
  }

  return (
    <div className="previewPane">
      <div className="previewBar">
        {htmlFiles.length > 1 ? (
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
        {loading && <div className="previewStatus muted">Loading…</div>}
        {error && <div className="previewStatus bad">{error}</div>}
        {content != null && (
          <iframe
            key={`${selected}-${reloadKey}`}
            className="previewFrame"
            title="Workspace preview"
            sandbox="allow-scripts"
            srcDoc={content}
          />
        )}
      </div>
    </div>
  );
}
