import path from "node:path";
import { fileURLToPath } from "node:url";

// Source-checkout tests spawn Python from temporary workspaces. Resolve the runtime
// relative to this file so they do not depend on an editable install in that interpreter.
export function testRuntimeEnv(env = process.env) {
  const source = fileURLToPath(new URL("../../src", import.meta.url));
  return {
    ...env,
    PYTHONPATH: [source, env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  };
}
