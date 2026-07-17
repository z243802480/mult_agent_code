// Cross-run guard (S87). Pure functions, so the routing table is testable without a server.
// Binds no port.
import assert from "node:assert/strict";
import { READ_ONLY_MODES, blockedNotice, blockingJob, mutatesWorkspace } from "../lib/run-conflict.mjs";

let passed = 0;
function check(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

const running = (mode, extra = {}) => ({ job_id: `j-${mode}`, status: "running", mode, ...extra });

// --- which modes count as writers -------------------------------------------------------------
// Each of these was traced to its command; see lib/run-conflict.mjs for the file:line per mode.
for (const mode of ["run", "continue", "resume", "accept", "debug"]) {
  check(`${mode} mutates the workspace`, () => assert.equal(mutatesWorkspace(mode), true));
}
for (const mode of ["chat", "review", "plan", "decide"]) {
  check(`${mode} is read-only`, () => assert.equal(mutatesWorkspace(mode), false));
}

// The whole point of the inverted set: a mode nobody has classified is treated as a writer, so
// adding one later fails toward an annoying refusal rather than silent file loss.
check("an unknown mode is assumed to write", () =>
  assert.equal(mutatesWorkspace("some-future-mode"), true),
);
check("a missing mode is assumed to write", () => {
  assert.equal(mutatesWorkspace(undefined), true);
  assert.equal(mutatesWorkspace(null), true);
  assert.equal(mutatesWorkspace(""), true);
});
check("mode matching ignores case", () => assert.equal(mutatesWorkspace("CHAT"), false));
check("READ_ONLY_MODES is exactly the four traced modes", () =>
  assert.deepEqual([...READ_ONLY_MODES].sort(), ["chat", "decide", "plan", "review"]),
);

// --- blocking ---------------------------------------------------------------------------------
check("a writer blocks another writer", () =>
  assert.equal(blockingJob([running("run")], "run").job_id, "j-run"),
);
check("a writer blocks a writer of a different mode", () =>
  assert.equal(blockingJob([running("run")], "accept").job_id, "j-run"),
);
check("nothing running -> nothing blocks", () => assert.equal(blockingJob([], "run"), null));
check("a finished writer does not block", () =>
  assert.equal(blockingJob([{ ...running("run"), status: "completed" }], "run"), null),
);
check("a failed writer does not block", () =>
  assert.equal(blockingJob([{ ...running("run"), status: "failed" }], "run"), null),
);

// Asking a question while a run is in flight has always worked; the guard must not take that away.
check("a read-only mode is never blocked", () => {
  for (const mode of ["chat", "review", "plan", "decide"]) {
    assert.equal(blockingJob([running("run")], mode), null, mode);
  }
});
check("a running read-only job blocks nobody", () => {
  for (const mode of ["chat", "review", "plan", "decide"]) {
    assert.equal(blockingJob([running(mode)], "run"), null, mode);
  }
});
check("the first running writer is the one reported", () =>
  assert.equal(blockingJob([running("chat"), running("resume"), running("run")], "run").job_id, "j-resume"),
);
check("an unknown running mode blocks (inverted default, both directions)", () => {
  assert.equal(blockingJob([running("some-future-mode")], "run").job_id, "j-some-future-mode");
  assert.equal(blockingJob([running("run")], "some-future-mode").job_id, "j-run");
});
check("junk job list does not throw", () => {
  assert.equal(blockingJob(null, "run"), null);
  assert.equal(blockingJob([null, undefined], "run"), null);
});

// --- the notice -------------------------------------------------------------------------------
check("the notice names the blocking run's goal", () => {
  const notice = blockedNotice(running("run", { goal: "修 login bug" }));
  assert.ok(notice.body.includes("修 login bug"));
});
check("the notice survives a blocker with no goal", () => {
  const notice = blockedNotice(running("run"));
  assert.ok(notice.title);
  assert.ok(notice.body.includes("另一个会话"));
  assert.ok(!notice.body.includes("undefined"));
});
check("a long goal is truncated rather than becoming the wall", () => {
  const notice = blockedNotice(running("run", { goal: "改".repeat(400) }));
  assert.ok(notice.body.includes("…"));
  assert.ok(notice.body.length < 400);
});
// The one thing the notice must never imply. A user who reads "failed" and assumes a half-written
// file is a user who goes looking for damage that does not exist.
check("the notice says the files were not touched, and does not claim a breakage", () => {
  const notice = blockedNotice(running("run", { goal: "x" }));
  assert.ok(notice.body.includes("你的文件没有被动过"));
  assert.ok(notice.title.includes("没有开始"));
});
check("the notice tells the user what to do next", () => {
  const notice = blockedNotice(running("run", { goal: "x" }));
  assert.ok(notice.body.includes("等它跑完") && notice.body.includes("停掉"));
});

console.log(`\n${passed} checks passed`);
