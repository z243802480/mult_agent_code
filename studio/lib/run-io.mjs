// Filesystem read helpers for run evidence — extracted verbatim from server.mjs. Leaf IO
// utilities with no server state: tolerantly read a JSON file, or tail a JSONL file into parsed
// records. redactText keeps any unparseable line safe before it reaches the UI.
import { promises as fs } from "node:fs";
import { redactText } from "./text-utils.mjs";

export async function readJson(file) {
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch {
    return {};
  }
}

export async function readJsonlTail(file, limit) {
  try {
    return (await fs.readFile(file, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-limit)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return { raw: redactText(line) };
        }
      });
  } catch {
    return [];
  }
}
