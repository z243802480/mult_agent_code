from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_runtime.security.path_guard import PathGuard


@dataclass(frozen=True)
class ResearchSourceRecord:
    source_id: str
    title: str
    source_type: str
    reference: str
    content: str

    def summary(self, max_chars: int = 500) -> str:
        text = " ".join(self.content.split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."


class ResearchSource(Protocol):
    def collect(self, query: str) -> list[ResearchSourceRecord]:
        ...


class LocalDocumentSource:
    def __init__(
        self,
        root: Path,
        protected_paths: list[str],
        include_globs: list[str] | None = None,
        max_files: int = 12,
        max_chars_per_file: int = 4000,
    ) -> None:
        self.root = root
        self.guard = PathGuard(root, protected_paths)
        self.include_globs = include_globs or ["docs/**/*.md", "README.md", "AGENTS.md"]
        self.max_files = max_files
        self.max_chars_per_file = max_chars_per_file

    def collect(self, query: str) -> list[ResearchSourceRecord]:
        terms = [term.lower() for term in query.split() if len(term) >= 2]
        candidates: list[Path] = []
        for pattern in self.include_globs:
            candidates.extend(self.root.glob(pattern))
        records: list[ResearchSourceRecord] = []
        seen: set[Path] = set()
        for path in sorted(candidates, key=lambda item: item.as_posix()):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            rel = path.relative_to(self.root).as_posix()
            try:
                self.guard.resolve_for_read(rel)
            except PermissionError:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            lower = content.lower()
            if terms and not any(term in lower or term in rel.lower() for term in terms):
                continue
            records.append(
                ResearchSourceRecord(
                    source_id=f"local-{len(records) + 1:04d}",
                    title=rel,
                    source_type="local",
                    reference=rel,
                    content=content[: self.max_chars_per_file],
                )
            )
            if len(records) >= self.max_files:
                break
        return records


class UrlSource:
    def __init__(self, urls: list[str], allow_network: bool, timeout_seconds: int = 20) -> None:
        self.urls = urls
        self.allow_network = allow_network
        self.timeout_seconds = timeout_seconds

    def collect(self, query: str) -> list[ResearchSourceRecord]:
        if not self.urls:
            return []
        if not self.allow_network:
            raise PermissionError("Network research is disabled by policy")
        records: list[ResearchSourceRecord] = []
        for url in self.urls:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "agent-runtime-research/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read(120_000).decode("utf-8", errors="replace")
            except urllib.error.URLError as exc:
                body = f"Failed to fetch {url}: {exc}"
            records.append(
                ResearchSourceRecord(
                    source_id=f"url-{len(records) + 1:04d}",
                    title=url,
                    source_type="url",
                    reference=url,
                    content=body,
                )
            )
        return records


class SerperSearchSource:
    def __init__(self, allow_network: bool, api_key: str | None = None, max_results: int = 5) -> None:
        self.allow_network = allow_network
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        self.max_results = max_results

    def collect(self, query: str) -> list[ResearchSourceRecord]:
        if not self.api_key:
            return []
        if not self.allow_network:
            raise PermissionError("Network research is disabled by policy")
        payload = json.dumps({"q": query, "num": self.max_results}).encode("utf-8")
        request = urllib.request.Request(
            "https://google.serper.dev/search",
            data=payload,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        records: list[ResearchSourceRecord] = []
        for item in data.get("organic", [])[: self.max_results]:
            title = item.get("title") or item.get("link") or "Untitled result"
            link = item.get("link") or ""
            snippet = item.get("snippet") or ""
            records.append(
                ResearchSourceRecord(
                    source_id=f"search-{len(records) + 1:04d}",
                    title=title,
                    source_type="search",
                    reference=link,
                    content=snippet,
                )
            )
        return records
