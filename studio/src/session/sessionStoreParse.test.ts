import { describe, expect, it } from "vitest";
import { parseSessionText } from "../../lib/session-store.mjs";

describe("parseSessionText", () => {
  it("reads an intact session", () => {
    expect(parseSessionText('{"session_id":"s1","title":"hi"}')).toEqual({
      session_id: "s1",
      title: "hi",
    });
  });

  it("salvages a torn file — the bug it was written for", () => {
    // Concurrent bare writes interleave and leave trailing garbage; JSON.parse throws and the
    // session used to vanish from the list silently.
    expect(parseSessionText('{"session_id":"s1","title":"hi"}}')).toEqual({
      session_id: "s1",
      title: "hi",
    });
    expect(parseSessionText('{"session_id":"s1","ui":{"diffLayout":"split"}}{"ses')).toEqual({
      session_id: "s1",
      ui: { diffLayout: "split" },
    });
  });

  it("rejects valid JSON that is not a session", () => {
    // Salvage takes the longest prefix that PARSES, which is not the same as the longest prefix
    // that is a session. Callers rebuild from the id they hold when this returns null, so a
    // non-session would be worse than nothing.
    expect(parseSessionText("[1,2]}")).toBeNull();
    expect(parseSessionText('{"title":"no id here"}')).toBeNull();
    expect(parseSessionText('{"session_id":""}')).toBeNull();
    expect(parseSessionText('{"session_id":42}')).toBeNull();
  });

  it("returns null for unreadable input rather than throwing", () => {
    expect(parseSessionText("")).toBeNull();
    expect(parseSessionText(null)).toBeNull();
    expect(parseSessionText("not json at all")).toBeNull();
    expect(parseSessionText("{{{{")).toBeNull();
  });

  it("keeps walking back past a prefix that parses but is not a session", () => {
    // The inner object parses on its own; the walk must not stop there and must find the session.
    expect(parseSessionText('{"session_id":"s1","a":{"b":1}} trailing {"b":2}')).toEqual({
      session_id: "s1",
      a: { b: 1 },
    });
  });
});
