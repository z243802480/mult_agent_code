import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// G17 刀二 — proves the attachment endpoint end to end against a real server: binary upload lands
// on disk intact (the utf8 body reader would have corrupted it), the GET echo serves it back with
// an image content-type, and neither route can be talked into touching anything outside the
// session's own attachment directory.

const studioDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(studioDir, "..");
const port = Number(process.env.ASTERIA_STUDIO_ATTACHMENT_PORT || 18817);
const base = `http://127.0.0.1:${port}`;

// A real 1x1 PNG — binary bytes with a signature the sniffer must accept.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

const workspace = await fs.mkdtemp(path.join(os.tmpdir(), "asteria-attach-smoke-"));
await fs.writeFile(path.join(workspace, ".env"), "SECRET=xyz", "utf8");

const server = spawn(
  process.execPath,
  ["server.mjs", "--workspace", workspace, "--runtime-root", repoRoot, "--port", String(port)],
  { cwd: studioDir, stdio: ["ignore", "pipe", "pipe"] },
);

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

try {
  await waitForHealth();

  const upload = await postBytes(`${base}/api/studio/attachments?session=smoke-1`, PNG);
  assert(upload.ok === true, `upload failed: ${JSON.stringify(upload)}`);
  assert(
    /^\.asteria\/attachments\/smoke-1\/[a-f0-9]{16}\.png$/.test(upload.path),
    `unexpected stored path: ${upload.path}`,
  );

  // Bytes must survive the round trip: readRequestBodyRaw decodes to utf8 and would mangle these.
  const onDisk = await fs.readFile(path.join(workspace, upload.path));
  assert(onDisk.equals(PNG), "stored attachment does not match the uploaded bytes");

  // Content addressing: the same image twice is one file.
  const again = await postBytes(`${base}/api/studio/attachments?session=smoke-1`, PNG);
  assert(again.path === upload.path, "same bytes produced a different path");

  const echo = await fetch(`${base}/api/studio/attachments?path=${encodeURIComponent(upload.path)}`);
  assert(echo.status === 200, `echo GET failed: ${echo.status}`);
  assert(
    /image\/png/.test(echo.headers.get("content-type") || ""),
    `echo content-type wrong: ${echo.headers.get("content-type")}`,
  );
  assert(Buffer.from(await echo.arrayBuffer()).equals(PNG), "echoed bytes differ from the original");

  // Non-image content must be refused whatever it is named.
  const bogus = await postBytes(
    `${base}/api/studio/attachments?session=smoke-1`,
    Buffer.from("MZ this is an executable, not a picture"),
  );
  assert(bogus.ok === false, "non-image upload was accepted");

  const badSession = await postBytes(`${base}/api/studio/attachments?session=../evil`, PNG);
  assert(badSession.ok === false, "traversal session id was accepted");

  // The GET route must not become a read-any-file hole.
  for (const attempt of [".env", "../../etc/passwd", ".asteria/memory/active_goal.json"]) {
    const res = await fetch(`${base}/api/studio/attachments?path=${encodeURIComponent(attempt)}`);
    assert(res.status === 400 || res.status === 404, `${attempt} served with ${res.status}`);
  }

  console.log("Studio attachment smoke passed (binary round trip, content addressing, path safety)");
} finally {
  server.kill("SIGTERM");
  await fs.rm(workspace, { recursive: true, force: true });
}

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health`);
      if ((await r.json()).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Studio server did not become healthy");
}

async function postBytes(url, buffer) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: buffer,
  });
  return res.json();
}
