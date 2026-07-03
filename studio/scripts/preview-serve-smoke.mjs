import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Proves the PREVIEW-1 dedicated static workspace server: serves multi-file sites with correct
// content-types + index defaulting + subfolders, and refuses traversal / protected paths.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const mainPort = Number(process.env.ASTERIA_STUDIO_PREVIEW_PORT || 18820);
const mainBase = `http://127.0.0.1:${mainPort}`;

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-preview-smoke-"));
await fs.writeFile(path.join(workspace, "index.html"),
  '<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><h1 id="t">HELLO_PREVIEW</h1><script src="app.js"></script></body></html>', "utf8");
await fs.writeFile(path.join(workspace, "style.css"), "h1{color:red}", "utf8");
await fs.writeFile(path.join(workspace, "app.js"), "window.__ok=1;", "utf8");
await fs.mkdir(path.join(workspace, "img"), { recursive: true });
await fs.writeFile(path.join(workspace, "img", "logo.svg"), '<svg xmlns="http://www.w3.org/2000/svg"></svg>', "utf8");
await fs.mkdir(path.join(workspace, "page"), { recursive: true });
await fs.writeFile(path.join(workspace, "page", "about.html"), "<h1>ABOUT_PAGE</h1>", "utf8");
await fs.writeFile(path.join(workspace, ".env"), "SECRET=xyz", "utf8"); // must be refused

const server = spawn(process.execPath, [
  "server.mjs", "--workspace", workspace, "--runtime-root", repoRoot, "--port", String(mainPort),
], { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] });

function assert(cond, message) { if (!cond) throw new Error(message); }

try {
  await waitForHealth();
  const info = await fetchJson(`${mainBase}/api/studio/preview-info`);
  assert(info.ok && info.port, `preview server not up: ${JSON.stringify(info)}`);
  const pv = `http://127.0.0.1:${info.port}`;

  // index defaulting + html content-type + marker
  const root = await fetchRaw(`${pv}/`);
  assert(root.status === 200 && /text\/html/.test(root.type), `root not html: ${root.status} ${root.type}`);
  assert(root.body.includes("HELLO_PREVIEW"), "index.html content missing");

  const css = await fetchRaw(`${pv}/style.css`);
  assert(css.status === 200 && /text\/css/.test(css.type) && css.body.includes("color:red"), `css wrong: ${css.status} ${css.type}`);

  const js = await fetchRaw(`${pv}/app.js`);
  assert(js.status === 200 && /javascript/.test(js.type), `js wrong: ${js.status} ${js.type}`);

  const svg = await fetchRaw(`${pv}/img/logo.svg`);
  assert(svg.status === 200 && /image\/svg/.test(svg.type), `svg wrong: ${svg.status} ${svg.type}`);

  const about = await fetchRaw(`${pv}/page/about.html`);
  assert(about.status === 200 && about.body.includes("ABOUT_PAGE"), `subfolder html wrong: ${about.status}`);

  // Protected + traversal + missing must NOT serve
  const env = await fetchRaw(`${pv}/.env`);
  assert(env.status === 403, `.env should be forbidden, got ${env.status}`);
  const trav = await fetchRaw(`${pv}/../server.mjs`);
  assert(trav.status === 403 || trav.status === 404, `traversal should be blocked, got ${trav.status}`);
  const missing = await fetchRaw(`${pv}/nope.html`);
  assert(missing.status === 404, `missing should be 404, got ${missing.status}`);

  console.log("Studio preview-serve smoke passed (multi-file serve, content-types, path-safety)");
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${mainBase}/api/health`);
      if ((await r.json()).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function fetchJson(url) {
  const r = await fetch(url);
  const t = await r.text();
  if (!r.ok) throw new Error(`${url} -> ${r.status}: ${t}`);
  return JSON.parse(t);
}

async function fetchRaw(url) {
  const r = await fetch(url, { redirect: "manual" });
  return { status: r.status, type: r.headers.get("content-type") || "", body: await r.text() };
}
