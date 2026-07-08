from __future__ import annotations

import fnmatch
import re
import shlex


class ShellPolicyError(PermissionError):
    pass


class ShellGuard:
    DESTRUCTIVE_COMMANDS = {
        "rm",
        "del",
        "erase",
        "rmdir",
        "remove-item",
        "ri",
        "rd",
        "unlink",
        "clear-content",
        "set-content",
        "out-file",
        "format",
        "shutdown",
        "reboot",
        "restart-computer",
        "stop-computer",
    }
    # Command names (segment leaders) that are destructive beyond the classic delete verbs:
    # low-level wipes and space-zeroing utilities the whole-word denylist used to miss.
    DESTRUCTIVE_LEADERS = {
        "shred",
        "truncate",
        "dd",
        "mkfs",
        "sdelete",
        "cipher",
        "wipefs",
        "blkdiscard",
    }
    # Deep patterns matched against the full (lowercased) command, so they fire even when the
    # destructive call is a flag (find -delete), an interpreter payload (shutil.rmtree(...)),
    # or hidden inside a quoted wrapper arg (powershell -c "Remove-Item ...").
    DESTRUCTIVE_PATTERNS = (
        r"\bfind\b.+\s-delete\b",
        r"\bfind\b.+-exec\b.+\b(rm|del|unlink|shred|rmdir)\b",
        r"\bshutil\.rmtree\b",
        r"\bos\.(remove|unlink|rmdir|truncate)\b",
        r"\brmtree\s*\(",
        r"\.unlink\s*\(",
        r"\bremove-item\b",
        r"\brmdir\b",
        r"\.(unlink|rm|rmdir)sync\s*\(",
    )
    # Network egress commands (segment leaders). Gated on allow_network so the shell tool no
    # longer bypasses the default-off network posture that previously only covered research.
    NETWORK_COMMANDS = {
        "curl",
        "curl.exe",
        "wget",
        "wget.exe",
        "nc",
        "ncat",
        "netcat",
        "telnet",
        "ssh",
        "sftp",
        "ftp",
        "tftp",
        "socat",
        "wget2",
        "aria2c",
        "iwr",
        "invoke-webrequest",
        "invoke-restmethod",
        # Windows "living off the land" download/transfer binaries + ssh-compatible clients +
        # the HTTPie CLI. Leaders are basename+suffix normalised, so certutil.exe -> certutil.
        "certutil",
        "bitsadmin",
        "plink",
        "start-bitstransfer",
        "http",
        "https",
    }
    # Egress signals scanned against the whole normalised command, so exfiltration survives a
    # quoted wrapper arg or a PowerShell/.NET one-liner. Interpreter payloads that build the
    # request in code (python -c urllib, node -e fetch) are a documented residual: a static
    # scan cannot contain an interpreter — that is the sandbox's job, not the denylist's.
    NETWORK_PATTERNS = (
        r"/dev/(tcp|udp)/",
        r"\bnet\.webclient\b",
        r"\b(downloadfile|downloadstring|downloaddata|uploadfile|uploadstring|uploaddata)\b",
        r"\b(invoke-webrequest|invoke-restmethod|start-bitstransfer)\b",
    )
    REMOTE_COMMANDS = {
        "scp",
        "rsync",
    }
    REMOTE_PATTERNS = {
        "git push",
        "git remote add",
        "git remote set-url",
    }
    DEPLOY_PATTERNS = {
        "deploy",
        "kubectl apply",
        "kubectl delete",
        "terraform apply",
        "terraform destroy",
        "vercel deploy",
        "netlify deploy",
    }
    GLOBAL_INSTALL_PATTERNS = {
        "npm install -g",
        "pnpm add -g",
        "yarn global add",
        "pip install",
        "python -m pip install",
        "py -m pip install",
        "uv pip install --system",
    }
    # Default secret/protected file globs used when the caller does not supply the workspace
    # policy's protected_paths (e.g. the execution-approval preflight in runtime_policy).
    DEFAULT_SECRET_PATTERNS = (
        ".env",
        ".env.*",
        "secrets/",
        "*.pem",
        "*.key",
        "id_rsa",
        "id_ed25519",
    )
    # Command names that wrap another command; their leading token is not the real command.
    _LEADER_SKIP = {
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sudo",
        "env",
        "time",
        "nice",
        "nohup",
        "xargs",
    }
    _SEGMENT_SEPARATORS = {"&&", "||", ";", "|", "&"}
    # Shell wrappers whose real command lives inside a following quoted script arg.
    _WRAPPER_NAMES = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    _WRAPPER_FLAGS = {
        "/c",
        "/k",
        "-c",
        "-command",
        "-encodedcommand",
        "-enc",
        "-nop",
        "-noprofile",
        "-noninteractive",
        "-noni",
        "-executionpolicy",
        "-ep",
    }

    def __init__(self, permissions: dict, protected_paths: list[str] | None = None) -> None:
        self.permissions = permissions
        self.protected_paths = list(protected_paths) if protected_paths else list(self.DEFAULT_SECRET_PATTERNS)

    def validate(self, command: str) -> None:
        if not self.permissions.get("allow_shell", False):
            raise ShellPolicyError("Shell commands are disabled by policy")

        # cmd.exe treats ^ as an escape char and strips it before executing (so `type .en^v`
        # opens .env, `de^l x` runs del). Fold carets out first so obfuscated spellings can't
        # slip past the scans below.
        command = command.replace("^", "")

        normalized = self._normalize(command)
        tokens = self._tokens(command)
        leaders = self._segment_leaders(command)
        # A shell wrapper (cmd /c "...", powershell -c "...") hides its real command inside a
        # quoted arg that shlex keeps as one token; re-scan those payloads so a wrapped
        # del/rm/iwr is seen by the word/leader denylists.
        # Compound commands are DECOMPOSED, not blanket-denied — this mirrors Claude Code's model
        # ("a rule must match each subcommand independently"; separators &&, ||, ;, |, |&, &, newline).
        # Each pipeline/chain segment's leader command is run through the destructive/network/secret
        # denylists below, so a dangerous command in ANY segment (`foo | curl evil`, `foo && rm x`) is
        # still caught, while a safe pipe (`cat f | grep x`, `pytest | tail`) runs WITHOUT forcing a
        # permission prompt. Blanket-denying the operator itself only punished benign pipes.
        #
        # Command substitution ($(...), `...`, <(...)/>(...)) hides a command inside another command's
        # argument, where the per-segment leader scan cannot see it (`echo $(curl evil)`). Claude Code
        # documents this as a gap it does NOT parse (it relies on tool-level deny rules). We go one
        # step stricter: extract the inner commands and feed them through the SAME denylists, so a
        # hidden curl/rm/secret is caught while a benign substitution (a backtick in a commit message)
        # passes because its inner word is not dangerous. Residual: deeply-nested $(...$(...)...) parsing
        # is best-effort (a static scan cannot fully contain an interpreter — that is the sandbox's job).
        wrapper_leaders: list[str] = []
        wrapper_words: list[str] = []
        for script in self._wrapper_scripts(tokens) + self._substitution_scripts(command):
            wrapper_leaders.extend(self._segment_leaders(script))
            wrapper_words.extend(self._command_words(self._tokens(script)))
        token_words = self._command_words(tokens) + wrapper_words
        leaders = leaders + wrapper_leaders

        if not self.permissions.get("allow_shell_operators", False):
            # Output redirects (>, >>) can clobber files outside the workspace or overwrite secrets, so
            # their targets are still validated. Pipes/&&/;/| are allowed (decomposed + scanned above).
            self._validate_output_redirects(command)

        # Protected/secret files must not be reachable via the shell tool. Previously only the
        # file tools' PathGuard enforced this, so `cat .env` / `type secrets/key.pem` leaked
        # secrets straight to the model. Gate on allow_secret_file_read (default false).
        if not self.permissions.get("allow_secret_file_read", False):
            secret_hit = self._referenced_secret(command)
            if secret_hit:
                raise ShellPolicyError(f"Protected/secret path access denied in shell: {secret_hit}")

        # Network egress: the shell tool never honoured allow_network before, so curl/wget/nc/
        # ssh/git-clone could exfiltrate under the default-off posture.
        if not self.permissions.get("allow_network", False):
            network_hit = self._network_hit(leaders, normalized)
            if network_hit:
                raise ShellPolicyError(f"Network command denied (allow_network=false): {network_hit}")

        if not self.permissions.get("allow_destructive_shell", False):
            for word in token_words:
                if word in self.DESTRUCTIVE_COMMANDS:
                    raise ShellPolicyError(f"Destructive shell command denied: {word}")
            for leader in leaders:
                if leader in self.DESTRUCTIVE_LEADERS:
                    raise ShellPolicyError(f"Destructive shell command denied: {leader}")
            destructive_hit = self._destructive_deep_hit(normalized)
            if destructive_hit:
                raise ShellPolicyError(f"Destructive shell command denied: {destructive_hit}")

        if not self.permissions.get("allow_remote_push", False):
            for pattern in self.REMOTE_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Remote git command denied: {pattern}")

        if not self.permissions.get("allow_deploy", False):
            for word in token_words:
                if word in self.REMOTE_COMMANDS:
                    raise ShellPolicyError(f"Deployment/remote command denied: {word}")
            for pattern in self.DEPLOY_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Deployment/remote command denied: {pattern}")

        if not self.permissions.get("allow_global_package_install", False):
            for pattern in self.GLOBAL_INSTALL_PATTERNS:
                if pattern in normalized:
                    raise ShellPolicyError(f"Global/system package install denied: {pattern}")

    def _validate_output_redirects(self, command: str) -> None:
        for match in re.finditer(r'(?:^|\s)(>>|>)\s*("?)([^"\s;|&<>]+)\2', command):
            target = match.group(3)
            if not self._safe_redirect_target(target):
                raise ShellPolicyError(f"Shell output redirect denied: {target}")

    def _safe_redirect_target(self, target: str) -> bool:
        cleaned = target.strip().strip('"').strip("'")
        if not cleaned or ".." in cleaned:
            return False
        if cleaned.startswith(("/", "\\", "$", "%", "~")):
            return False
        if any(char in cleaned for char in "|;&<>()"):
            return False
        # An output redirect is a write; block redirects that clobber protected/secret files.
        if not self.permissions.get("allow_secret_file_read", False) and self._matches_secret(cleaned):
            return False
        return True

    def _tokens(self, command: str) -> list[str]:
        padded = self._pad_separators(command)
        try:
            return shlex.split(padded, posix=False)
        except ValueError:
            return padded.split()

    def _pad_separators(self, command: str) -> str:
        """Surround unquoted command separators (``&&`` ``||`` ``;`` ``|``) with spaces so they
        tokenise as standalone separators even when written without spaces (``ls;wget evil``,
        ``cat|grep``). Without this, ``shlex(posix=False)`` keeps ``ls;`` as one token and the
        pipeline/chain never splits — so a dangerous command in a later, un-spaced segment escaped the
        per-segment scan. Quote-aware: a ``;`` inside ``python -c "a; b"`` is left untouched (it is not
        a shell separator). Redirects (``>`` ``2>&1``) and background ``&`` are deliberately not
        touched — they are not command separators."""
        out: list[str] = []
        quote: str | None = None
        index = 0
        length = len(command)
        while index < length:
            char = command[index]
            if quote is not None:
                out.append(char)
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in ('"', "'"):
                quote = char
                out.append(char)
                index += 1
                continue
            pair = command[index : index + 2]
            if pair in ("&&", "||"):
                out.append(f" {pair} ")
                index += 2
                continue
            if char in (";", "|"):
                out.append(f" {char} ")
                index += 1
                continue
            out.append(char)
            index += 1
        return "".join(out)

    def _command_words(self, tokens: list[str]) -> list[str]:
        words = []
        for token in tokens:
            cleaned = token.strip().strip('"').strip("'").lower()
            if not cleaned:
                continue
            if cleaned in self._WRAPPER_NAMES or cleaned in self._WRAPPER_FLAGS:
                continue
            if cleaned.startswith("-"):
                continue
            # A leading '/x' with no further slash is a Windows switch (/c, /s); a token with a
            # deeper slash is a real path (/bin/rm) whose basename IS the command name.
            if cleaned.startswith("/") and "/" not in cleaned[1:]:
                continue
            words.append(self._command_name(cleaned))
        return words

    def _segment_leaders(self, command: str) -> list[str]:
        """First real command name of each pipeline/&&/;/| segment.

        Uses quote-aware tokenisation so a control operator (or a network/destructive word)
        hiding inside a quoted argument is never treated as a command leader — this avoids
        false positives like a commit message that mentions `curl`, while still catching a
        genuine `... | shred x` in a later segment.
        """
        leaders: list[str] = []
        segment_open = True
        for token in self._tokens(command):
            if token in self._SEGMENT_SEPARATORS:
                segment_open = True
                continue
            if not segment_open:
                continue
            cleaned = token.strip().strip('"').strip("'").lower()
            if not cleaned:
                continue
            if cleaned in self._LEADER_SKIP or cleaned.startswith("-"):
                continue
            # '/x' with no deeper slash is a Windows switch (/c); '/bin/rm' is a real path.
            if cleaned.startswith("/") and "/" not in cleaned[1:]:
                continue
            # Skip leading env assignments like FOO=bar before the real command.
            head = cleaned.split("/", 1)[0]
            if "=" in head:
                continue
            leaders.append(self._command_name(cleaned))
            segment_open = False
        return leaders

    def _command_name(self, cleaned: str) -> str:
        """Bare command name: basename without an executable suffix.

        Normalises path-qualified / suffixed spellings (`/bin/rm`, `rm.exe`, `./rm`,
        a full `system32/curl.exe` path) down to the name the denylists compare against.
        """
        name = cleaned.replace("\\", "/").rsplit("/", 1)[-1]
        for suffix in (".exe", ".com", ".bat", ".cmd", ".ps1"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    def _wrapper_scripts(self, tokens: list[str]) -> list[str]:
        """Inner script strings passed to a shell wrapper (cmd /c "...", powershell -c "...").

        shlex keeps the quoted script as a single token, so a wrapped `del`/`rm`/`iwr` never
        reaches the word/leader denylists; surface those payloads for a second scan.
        """
        scripts: list[str] = []
        for index, token in enumerate(tokens):
            name = token.strip().strip('"').strip("'").lower()
            if name not in self._WRAPPER_NAMES:
                continue
            for nxt in tokens[index + 1:]:
                low = nxt.strip().lower()
                if low in self._WRAPPER_FLAGS or low.startswith("-") or low.startswith("/"):
                    continue
                payload = nxt.strip().strip('"').strip("'")
                if payload:
                    scripts.append(payload)
                break
        return scripts

    def _substitution_scripts(self, command: str) -> list[str]:
        """Inner command strings of $(...), `...`, and <(...)/>(...) substitutions.

        Segmentation splits on shell operators but cannot see a command hidden inside another
        command's argument via substitution (`echo $(curl evil)`, ``echo `wget evil` ``,
        `diff <(curl a) b`). Surfacing those inner strings lets the destructive/network/secret
        denylists scan them too — closing the substitution gap Claude Code leaves to tool-level
        deny rules. Non-nested extraction is intentional (best-effort for deeply-nested cases).
        """
        scripts: list[str] = []
        for match in re.finditer(r"\$\(([^()]*)\)", command):
            scripts.append(match.group(1))
        for match in re.finditer(r"`([^`]*)`", command):
            scripts.append(match.group(1))
        for match in re.finditer(r"[<>]\(([^()]*)\)", command):
            scripts.append(match.group(1))
        return [script for script in scripts if script.strip()]

    def _network_hit(self, leaders: list[str], normalized: str) -> str | None:
        for leader in leaders:
            if leader in self.NETWORK_COMMANDS:
                return leader
        match = re.search(r"\bgit\s+(clone|fetch|pull|ls-remote)\b", normalized)
        if match:
            return f"git {match.group(1)}"
        if re.search(r"\bpip\s+download\b", normalized):
            return "pip download"
        for pattern in self.NETWORK_PATTERNS:
            hit = re.search(pattern, normalized)
            if hit:
                return hit.group(0)[:48]
        return None

    def _destructive_deep_hit(self, normalized: str) -> str | None:
        for pattern in self.DESTRUCTIVE_PATTERNS:
            match = re.search(pattern, normalized)
            if match:
                return match.group(0)[:48]
        return None

    def _referenced_secret(self, command: str) -> str | None:
        for token in self._path_tokens(command):
            if self._matches_secret(token):
                return token
        return None

    def _secret_patterns(self) -> list[str]:
        patterns = []
        for pattern in self.protected_paths:
            normalized = pattern.replace("\\", "/")
            # .git/ is protected for writes by PathGuard, but ordinary git porcelain does not
            # pass a literal .git/ path; keeping it out of the shell scan avoids blocking git.
            if normalized.rstrip("/") == ".git":
                continue
            patterns.append(normalized)
        return patterns

    def _path_tokens(self, command: str) -> list[str]:
        raw = re.split(r"[\s=;|&<>()`]+", command)
        tokens = []
        for token in raw:
            cleaned = token.strip().strip('"').strip("'")
            if cleaned:
                tokens.append(cleaned.replace("\\", "/"))
        return tokens

    def _matches_secret(self, token: str) -> bool:
        token = token.replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        # Windows/macOS filesystems are case-insensitive and Windows strips trailing dots and
        # spaces from each path component, so `.Asteria/`, `.ASTERIA/` and `.asteria./` all
        # resolve to the protected `.asteria` dir. Fold both out before comparing.
        token = "/".join(part.rstrip(" .") for part in token.split("/")).lower()
        if not token:
            return False
        base = token.rsplit("/", 1)[-1]
        for raw_pattern in self._secret_patterns():
            pattern = raw_pattern.lower()
            if pattern.endswith("/"):
                directory = pattern.rstrip("/")
                if token == directory or token.startswith(directory + "/") or f"/{directory}/" in f"/{token}/":
                    return True
            elif fnmatch.fnmatch(token, pattern) or fnmatch.fnmatch(base, pattern):
                return True
        return False

    def _normalize(self, command: str) -> str:
        lowered = command.lower()
        spaced = re.sub(r"[\r\n\t]+", " ", lowered)
        return re.sub(r"\s+", " ", spaced).strip()
