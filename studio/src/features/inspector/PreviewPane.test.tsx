import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { WorkspaceFile } from "../../types";
import { PreviewPane } from "./PreviewPane";

function file(path: string): WorkspaceFile {
  return { path } as WorkspaceFile;
}

describe("PreviewPane session scoping (another session's artifacts must not leak in)", () => {
  it("shows only HTML this session touched, not the whole workspace", () => {
    const out = renderToStaticMarkup(
      <PreviewPane
        files={[file("snake-game.html"), file("report.html")]}
        sessionPaths={["report.html"]}
      />,
    );
    expect(out).toContain("report.html");
    expect(out).not.toContain("snake-game.html");
  });

  it("renders an honest empty state for a session that produced no web output", () => {
    const out = renderToStaticMarkup(
      <PreviewPane files={[file("snake-game.html")]} sessionPaths={[]} />,
    );
    expect(out).toContain("本会话暂无可预览的网页产出");
    expect(out).not.toContain("snake-game.html");
  });

  it("matches when events recorded a workspace-absolute path for a relative file", () => {
    const out = renderToStaticMarkup(
      <PreviewPane
        files={[file("site/index.html")]}
        sessionPaths={["H:/workspace/site/index.html"]}
      />,
    );
    expect(out).toContain("site/index.html");
  });
});
