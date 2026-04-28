from pathlib import Path

from agent_runtime.commands.sessions_command import SessionsCommand, SessionsResult


RunsResult = SessionsResult


class RunsCommand(SessionsCommand):
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        set_current: bool = False,
        limit: int = 20,
    ) -> None:
        super().__init__(
            root=root,
            session_id=run_id,
            set_current=set_current,
            limit=limit,
        )
