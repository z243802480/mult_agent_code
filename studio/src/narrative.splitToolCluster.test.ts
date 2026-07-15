import { describe, expect, it } from "vitest";
import { splitToolCluster, TOOL_CLUSTER_LIMIT, TOOL_CLUSTER_TAIL } from "./narrative";

const seq = (n: number) => Array.from({ length: n }, (_, i) => i);

describe("splitToolCluster", () => {
  it("folds nothing at or below the limit (short/normal runs render unchanged)", () => {
    const steps = seq(TOOL_CLUSTER_LIMIT);
    const { earlier, recent } = splitToolCluster(steps);
    expect(earlier).toEqual([]);
    expect(recent).toEqual(steps);
  });

  it("folds the older steps once past the limit, keeping the recent tail visible", () => {
    // A 30-card repair storm: only the most-recent TAIL stays expanded; the rest fold behind a toggle.
    const steps = seq(30);
    const { earlier, recent } = splitToolCluster(steps);
    expect(recent).toHaveLength(TOOL_CLUSTER_TAIL);
    expect(earlier).toHaveLength(30 - TOOL_CLUSTER_TAIL);
    // The tail is the LAST steps (what just happened), not the first.
    expect(recent).toEqual(seq(30).slice(30 - TOOL_CLUSTER_TAIL));
    // Nothing is dropped — earlier + recent reconstructs the full ordered list.
    expect([...earlier, ...recent]).toEqual(steps);
  });

  it("honors custom limit/tail", () => {
    const { earlier, recent } = splitToolCluster(seq(10), 4, 2);
    expect(earlier).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(recent).toEqual([8, 9]);
  });
});
