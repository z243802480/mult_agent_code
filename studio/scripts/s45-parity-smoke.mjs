import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const files = [
  "src/components/DiffPreview.tsx",
  "src/components/ContextPanel.tsx",
  "src/components/AggregateDiffChip.tsx",
  "src/components/MarkdownBody.tsx",
  "src/contextSummary.ts",
  "server.mjs",
].map((rel) => readFileSync(path.join(root, rel), "utf8"));

const [diffPreview, contextPanel, aggregateChip, markdownBody, contextSummary, server] = files;

assert.match(diffPreview, /layout === "split"/, "DiffPreview must support split layout");
assert.match(diffPreview, /stage === "staged"/, "DiffPreview must support staged view");
assert.match(contextPanel, /contextPressureBar/, "ContextPanel must show pressure bar");
assert.match(aggregateChip, /aggregateDiffChip/, "AggregateDiffChip must exist");
assert.match(markdownBody, /parseMarkdownBlocks/, "MarkdownBody must parse markdown");
assert.match(contextSummary, /contextSectionLabel/, "contextSummary shared module");
assert.match(server, /stageWorkspaceGitFile/, "server must expose git stage API");
assert.match(server, /updateSession/, "server must support session PATCH rename");
assert.match(server, /compact:/, "server must map compact runtime action");

console.log("s45-parity smoke passed");
