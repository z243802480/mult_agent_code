from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class InitResult:
    root: Path
    created: list[str]
    updated: list[str]
    preserved: list[str]
    warnings: list[str]

    def to_text(self) -> str:
        lines = [f"Initialized agent workspace: {self.root}"]
        if self.created:
            lines.append("Created:")
            lines.extend(f"  - {item}" for item in self.created)
        if self.updated:
            lines.append("Updated:")
            lines.extend(f"  - {item}" for item in self.updated)
        if self.preserved:
            lines.append("Preserved:")
            lines.extend(f"  - {item}" for item in self.preserved)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {item}" for item in self.warnings)
        return "\n".join(lines)


class InitCommand:
    def __init__(self, root: Path, profile: str = "auto", force: bool = False) -> None:
        self.root = root.resolve()
        self.profile = profile
        self.force = force
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> InitResult:
        self.root.mkdir(parents=True, exist_ok=True)
        agent_dir = self.root / ".agent"
        context_dir = agent_dir / "context"
        tasks_dir = agent_dir / "tasks"
        runs_dir = agent_dir / "runs"
        memory_dir = agent_dir / "memory"

        created: list[str] = []
        updated: list[str] = []
        preserved: list[str] = []
        warnings: list[str] = []

        for directory in [agent_dir, context_dir, tasks_dir, runs_dir, memory_dir]:
            if not directory.exists():
                directory.mkdir(parents=True)
                created.append(self._rel(directory))

        project_config = self._build_project_config()
        policies = self._load_default_policies()
        root_snapshot = self._build_root_snapshot(project_config)
        backlog = self._build_backlog()

        self._write_json(agent_dir / "project.json", "project_config", project_config, created, updated)
        self._write_json(agent_dir / "policies.json", "policy_config", policies, created, updated)
        self._write_json(
            context_dir / "root_snapshot.json",
            "context_snapshot",
            root_snapshot,
            created,
            updated,
        )
        self._write_json(tasks_dir / "backlog.json", "task_board", backlog, created, updated)

        agents_path = self.root / "AGENTS.md"
        if agents_path.exists():
            preserved.append(self._rel(agents_path))
        else:
            agents_path.write_text(self._render_agents_template(project_config, policies), encoding="utf-8")
            created.append(self._rel(agents_path))

        if not (self.root / ".git").exists():
            warnings.append("No .git directory found; workspace isolation will use controlled writes for now.")

        return InitResult(self.root, created, updated, preserved, warnings)

    def _write_json(
        self,
        path: Path,
        schema_name: str,
        data: dict,
        created: list[str],
        updated: list[str],
    ) -> None:
        existed = path.exists()
        self.store.write(path, data, schema_name=schema_name)
        (updated if existed else created).append(self._rel(path))

    def _build_project_config(self) -> dict:
        now = self._now()
        workspace_type = self._detect_workspace_type()
        commands = self._detect_commands()
        important_paths = self._detect_important_paths()
        languages = self._detect_languages()

        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": "project-0001",
            "name": self.root.name,
            "workspace_type": workspace_type,
            "created_at": now,
            "updated_at": now,
            "languages": languages,
            "frameworks": [],
            "package_managers": self._detect_package_managers(),
            "commands": commands,
            "important_paths": important_paths,
            "protected_paths": [
                ".env",
                ".env.*",
                "secrets/",
                ".git/",
                "*.pem",
                "*.key",
                "id_rsa",
                "id_ed25519",
            ],
            "root_guidance_path": "AGENTS.md",
            "default_policy_path": ".agent/policies.json",
        }

    def _load_default_policies(self) -> dict:
        template = Path(__file__).resolve().parents[3] / "templates" / "policies.default.json"
        return json.loads(template.read_text(encoding="utf-8"))

    def _build_root_snapshot(self, project_config: dict) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": "snapshot-root",
            "run_id": None,
            "created_at": self._now(),
            "focus": "initial workspace context",
            "goal_summary": "Workspace initialized for agentic development.",
            "definition_of_done": [],
            "accepted_decisions": [],
            "active_tasks": [],
            "modified_files": [],
            "verification": [],
            "failures": [],
            "research_claims": [],
            "open_risks": [],
            "next_actions": [
                "Run `agent plan` with a concrete goal.",
                "Review AGENTS.md and .agent/policies.json.",
            ],
            "project": {
                "name": project_config["name"],
                "workspace_type": project_config["workspace_type"],
                "important_paths": project_config["important_paths"],
            },
        }

    def _build_backlog(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "tasks": [],
        }

    def _render_agents_template(self, project_config: dict, policies: dict) -> str:
        template = (Path(__file__).resolve().parents[3] / "templates" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        replacements = {
            "{{PROJECT_PURPOSE}}": "Initialized workspace. Update this section with the project goal.",
            "{{NON_GOALS}}": "Not specified yet.",
            "{{ASSUMPTIONS}}": "Not specified yet.",
            "{{ARCHITECTURE_NOTES}}": "Not specified yet.",
            "{{INSTALL_COMMAND}}": str(project_config["commands"]["install"]),
            "{{RUN_COMMAND}}": str(project_config["commands"]["run"]),
            "{{TEST_COMMAND}}": str(project_config["commands"]["test"]),
            "{{LINT_COMMAND}}": str(project_config["commands"]["lint"]),
            "{{TYPECHECK_COMMAND}}": str(project_config["commands"]["typecheck"]),
            "{{BUILD_COMMAND}}": str(project_config["commands"]["build"]),
            "{{FORMAT_COMMAND}}": str(project_config["commands"]["format"]),
            "{{CODING_CONVENTIONS}}": "Follow existing project conventions.",
            "{{UI_CONVENTIONS}}": "Choose output medium based on task fit.",
            "{{PROTECTED_PATHS}}": "\n".join(project_config["protected_paths"]),
            "{{DECISION_GRANULARITY}}": policies["decision_granularity"],
            "{{MAX_MODEL_CALLS_PER_GOAL}}": str(policies["budgets"]["max_model_calls_per_goal"]),
            "{{MAX_TOOL_CALLS_PER_GOAL}}": str(policies["budgets"]["max_tool_calls_per_goal"]),
            "{{MAX_ITERATIONS_PER_GOAL}}": str(policies["budgets"]["max_iterations_per_goal"]),
            "{{MAX_REPAIR_ATTEMPTS_PER_TASK}}": str(
                policies["budgets"]["max_repair_attempts_per_task"]
            ),
            "{{CONTEXT_COMPACTION_THRESHOLD}}": str(
                policies["context"]["compaction_threshold"]
            ),
        }
        for key, value in replacements.items():
            template = template.replace(key, value)
        return template

    def _detect_workspace_type(self) -> str:
        if self.profile != "auto":
            return {
                "planning": "planning_workspace",
                "codebase": "codebase",
                "empty": "empty_workspace",
            }[self.profile]
        entries = [path for path in self.root.iterdir() if path.name != ".agent"]
        if not entries:
            return "empty_workspace"
        if any((self.root / name).exists() for name in ["pyproject.toml", "package.json", "Cargo.toml"]):
            return "codebase"
        if (self.root / "docs").exists():
            return "planning_workspace"
        return "mixed"

    def _detect_package_managers(self) -> list[str]:
        managers = []
        if (self.root / "pyproject.toml").exists():
            managers.append("python")
        if (self.root / "package.json").exists():
            managers.append("npm")
        if (self.root / "pnpm-lock.yaml").exists():
            managers.append("pnpm")
        if (self.root / "uv.lock").exists():
            managers.append("uv")
        return managers

    def _detect_languages(self) -> list[str]:
        suffixes = {path.suffix.lower() for path in self.root.rglob("*") if path.is_file()}
        languages = []
        if ".py" in suffixes or (self.root / "pyproject.toml").exists():
            languages.append("python")
        if ".ts" in suffixes or ".js" in suffixes or (self.root / "package.json").exists():
            languages.append("javascript")
        if ".md" in suffixes:
            languages.append("markdown")
        return languages or ["unknown"]

    def _detect_commands(self) -> dict[str, str | None]:
        commands: dict[str, str | None] = {
            "install": None,
            "run": None,
            "test": None,
            "lint": None,
            "typecheck": None,
            "build": None,
            "format": None,
        }
        if (self.root / "pyproject.toml").exists():
            commands["test"] = "pytest"
            commands["lint"] = "ruff check ."
            commands["typecheck"] = "mypy src"
            commands["format"] = "ruff format ."
        if (self.root / "package.json").exists():
            commands["install"] = "npm install"
            commands["test"] = commands["test"] or "npm test"
            commands["run"] = "npm run dev"
            commands["build"] = "npm run build"
        return commands

    def _detect_important_paths(self) -> list[str]:
        candidates = ["src/", "tests/", "docs/", "docs/zh/", "schemas/", "templates/"]
        return [path for path in candidates if (self.root / path).exists()]

    def _now(self) -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

    def _rel(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")
