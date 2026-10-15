import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";

afterEach(() => vi.restoreAllMocks());

describe("permission confirmation", () => {
  it("rejects an HTTP 200 response when the server did not resolve the job", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: false, error: "job not found" }), { status: 200 }),
    );
    await expect(api.permitJob("session", "missing-job", "allow")).rejects.toThrow("job not found");
  });

  it("accepts the server's confirmed resolution", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, started: true }), { status: 200 }),
    );
    await expect(api.permitJob("session", "job-1", "allow")).resolves.toMatchObject({
      ok: true,
    });
  });
});
