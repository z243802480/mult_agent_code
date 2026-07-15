import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

/**
 * The Node backend's whole source surface: server.mjs plus every module it was split into.
 *
 * White-box smokes grep this for a wiring SYMBOL to prove it still EXISTS in the source — an
 * anti-rename canary, not a behavior test (a passing grep does not prove the capability runs; that
 * needs a black-box smoke). Pointing the grep at server.mjs alone couples it to *which file* the code
 * happens to live in, so every extraction into lib/ silently rots it — `compact:` moved out in the
 * run-detail cut and the s45-parity assertion went stale on main without anyone noticing. Grep the
 * whole surface, not the file, so a move doesn't read as a deletion.
 */
export function readServerSurface(root) {
  const libDir = path.join(root, "lib");
  const parts = [readFileSync(path.join(root, "server.mjs"), "utf8")];
  for (const name of readdirSync(libDir).filter((f) => f.endsWith(".mjs"))) {
    parts.push(readFileSync(path.join(libDir, name), "utf8"));
  }
  return parts.join("\n");
}
