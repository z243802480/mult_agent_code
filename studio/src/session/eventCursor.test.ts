import { describe, expect, it } from "vitest";
// @ts-expect-error - server-side lib module, no type declarations (plain .mjs).
import { eventsAfter, parseSince } from "../../lib/event-cursor.mjs";

type Ev = { event_id: string; seq?: number };

const transcript: Ev[] = [
  { event_id: "a", seq: 0 },
  { event_id: "b", seq: 1 },
  { event_id: "c", seq: 2 },
];

describe("parseSince", () => {
  it("treats a missing or unparseable cursor as 'I have nothing'", () => {
    expect(parseSince(null)).toBe(-1);
    expect(parseSince("")).toBe(-1);
    expect(parseSince("garbage")).toBe(-1);
  });

  it("reads a numeric cursor", () => {
    expect(parseSince("0")).toBe(0);
    expect(parseSince("41")).toBe(41);
  });
});

describe("eventsAfter", () => {
  it("replays everything for an empty cursor — including seq 0", () => {
    expect(eventsAfter(transcript, -1)).toHaveLength(3);
    expect(eventsAfter(transcript, parseSince(null))).toEqual(transcript);
  });

  it("returns only events strictly newer than the cursor", () => {
    expect(eventsAfter(transcript, 0).map((e: Ev) => e.event_id)).toEqual(["b", "c"]);
    expect(eventsAfter(transcript, 2)).toEqual([]);
  });

  it("keeps events that carry no seq, rather than silently dropping transcript", () => {
    // Transcripts written before seq existed. Filtering them out would lose history on reconnect.
    const legacy: Ev[] = [{ event_id: "old" }, { event_id: "new", seq: 5 }];
    expect(eventsAfter(legacy, 4).map((e: Ev) => e.event_id)).toEqual(["old", "new"]);
  });
});
