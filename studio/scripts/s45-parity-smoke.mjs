// White-box source-presence guard (anti-rename canary) — NOT a behavior test. Each assertion only
// proves a wiring symbol still exists in the source; green means the symbols are present and haven't
// been renamed/removed, it does NOT prove the feature works at runtime (that needs a black-box smoke
// driving the UI/server). Kept because a silent rename would break the wiring these files depend on.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerSurface } from "./server-surface.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const files = [
  "src/components/DiffPreview.tsx",
  "src/components/ContextPanel.tsx",
  "src/components/AggregateDiffChip.tsx",
  "src/components/MarkdownBody.tsx",
  "src/contextSummary.ts",
].map((rel) => readFileSync(path.join(root, rel), "utf8"));

const [diffPreview, contextPanel, aggregateChip, markdownBody, contextSummary] = files;
const server = readServerSurface(root);

assert.match(diffPreview, /layout === "split"/, '`layout === "split"` present in DiffPreview.tsx');
assert.match(diffPreview, /stage === "staged"/, '`stage === "staged"` present in DiffPreview.tsx');
assert.match(
  contextPanel,
  /contextPressureBar/,
  "`contextPressureBar` present in ContextPanel.tsx",
);
assert.match(
  aggregateChip,
  /aggregateDiffChip/,
  "`aggregateDiffChip` present in AggregateDiffChip.tsx",
);
assert.match(
  markdownBody,
  /parseMarkdownBlocks/,
  "`parseMarkdownBlocks` present in MarkdownBody.tsx",
);
assert.match(
  contextSummary,
  /contextSectionLabel/,
  "`contextSectionLabel` present in contextSummary.ts",
);
assert.match(server, /stageWorkspaceGitFile/, "`stageWorkspaceGitFile` present in server surface");
assert.match(server, /updateSession/, "`updateSession` present in server surface");
assert.match(server, /compact:/, "`compact:` runtime-action key present in server surface");

console.log("s45-parity source-presence smoke passed");
