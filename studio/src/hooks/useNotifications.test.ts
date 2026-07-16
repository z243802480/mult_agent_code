import { describe, expect, it } from "vitest";
import { notificationForTransition } from "./useNotifications";

const base = { isRunning: false, waiting: false, interrupted: false, sessionTitle: "修复 CI" };

describe("notificationForTransition (notify only on real transitions)", () => {
  it("fires '任务已结束' when a run settles", () => {
    const out = notificationForTransition({ isRunning: true, waiting: false }, base);
    expect(out?.title).toBe("任务已结束");
    expect(out?.body).toContain("修复 CI");
  });

  it("fires '运行已中断' when the run died instead of finishing", () => {
    const out = notificationForTransition(
      { isRunning: true, waiting: false },
      { ...base, interrupted: true },
    );
    expect(out?.title).toBe("运行已中断");
  });

  it("fires '需要你的确认' on the waiting rising edge — and not again while still waiting", () => {
    const rise = notificationForTransition(
      { isRunning: true, waiting: false },
      { ...base, isRunning: true, waiting: true },
    );
    expect(rise?.title).toBe("需要你的确认");
    const still = notificationForTransition(
      { isRunning: true, waiting: true },
      { ...base, isRunning: true, waiting: true },
    );
    expect(still).toBeNull();
  });

  it("stays quiet while running, while idle, and when settling INTO a waiting pause", () => {
    expect(
      notificationForTransition({ isRunning: true, waiting: false }, { ...base, isRunning: true }),
    ).toBeNull();
    expect(notificationForTransition({ isRunning: false, waiting: false }, base)).toBeNull();
    // running → waiting settles via the waiting branch only (one notification, not two).
    const out = notificationForTransition(
      { isRunning: true, waiting: false },
      { ...base, waiting: true },
    );
    expect(out?.title).toBe("需要你的确认");
  });
});
