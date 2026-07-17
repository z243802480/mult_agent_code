import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeStorage } from "../testing/fakeStorage";
import { renderToStaticMarkup } from "react-dom/server";
import { Composer } from "./Composer";
import { queueKey } from "../session/composerQueue";

// The queue chips (G9): each queued message is editable (click = pull back into the composer),
// removable, and reorderable — Cursor's queued messages reorder; Claude Code users filed issues
// about queued messages being uneditable (#71726).

const SESSION = "session-queue-test";

beforeEach(() => {
  vi.stubGlobal(
    "localStorage",
    fakeStorage({ [queueKey(SESSION)]: JSON.stringify(["第一条", "第二条"]) }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("composer queue chips are editable and reorderable", () => {
  it("renders edit / move / remove affordances for queued messages", () => {
    const html = renderToStaticMarkup(
      <Composer onSend={async () => {}} sessionId={SESSION} isRunning runStateKnown />,
    );
    expect(html).toContain("2 条已排队");
    expect(html).toContain("第一条");
    expect(html).toContain("点击放回输入框编辑");
    expect(html).toContain("上移排队消息");
    expect(html).toContain("下移排队消息");
    expect(html).toContain("移除排队消息");
  });

  it("hides reorder buttons when only one message is queued (nothing to reorder)", () => {
    vi.stubGlobal(
      "localStorage",
      fakeStorage({ [queueKey(SESSION)]: JSON.stringify(["唯一一条"]) }),
    );
    const html = renderToStaticMarkup(
      <Composer onSend={async () => {}} sessionId={SESSION} isRunning runStateKnown />,
    );
    expect(html).toContain("唯一一条");
    expect(html).not.toContain("上移排队消息");
    expect(html).toContain("移除排队消息");
  });
});
