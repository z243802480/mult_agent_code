import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

/**
 * The Node backend's whole source surface: server.mjs plus every module it was split into.
 *
 * White-box smokes assert that a capability exists in the backend by grepping its source. Pointing
 * those assertions at server.mjs alone couples them to *which file* the code happens to live in, so
 * every extraction into lib/ silently rots them — `compact:` moved out in the run-detail cut and the
 * s45-parity assertion went stale on main without anyone noticing. Grep the surface, not the file.
 */
export function readServerSurface(root) {
  const libDir = path.join(root, "lib");
  const parts = [readFileSync(path.join(root, "server.mjs"), "utf8")];
  for (const name of readdirSync(libDir).filter((f) => f.endsWith(".mjs"))) {
    parts.push(readFileSync(path.join(libDir, name), "utf8"));
  }
  return parts.join("\n");
}
