"""Bounded shell lexical inspection. Never executes, repairs or returns rewritten commands.

This is not an interpreter sandbox. Unsupported/dynamic nested shell syntax is
refused rather than treating its quoted script as a harmless literal argument.
"""
from dataclasses import dataclass
import re


class ShellSyntaxUnknown(ValueError):
    pass


@dataclass(frozen=True)
class _Token:
    value: str
    operator: bool = False


_DIALECTS = {"posix", "cmd", "powershell"}
_SHELLS = {"sh": "posix", "bash": "posix", "dash": "posix", "zsh": "posix",
           "ksh": "posix", "cmd": "cmd", "powershell": "powershell", "pwsh": "powershell"}


def output_redirect_targets(command: str, dialect: str, *, _depth: int = 0) -> list[str]:
    if dialect not in _DIALECTS or _depth > 8 or len(command) > 131_072:
        raise ShellSyntaxUnknown("Shell syntax inspection limit or unsupported dialect")
    tokens, nested = _tokens(command, dialect)
    if any(t.operator and t.value == "<<" for t in tokens) and ">" in command:
        # Do not let a here-document body change the quote state of commands
        # after its delimiter. Full here-document expansion is outside this lexer.
        raise ShellSyntaxUnknown("Here-document with output syntax needs explicit approval")
    targets: list[str] = []
    for index, token in enumerate(tokens):
        if token.operator and token.value.startswith(">"):
            if index + 1 >= len(tokens) or tokens[index + 1].operator:
                raise ShellSyntaxUnknown("Shell redirect has no unambiguous target")
            target = tokens[index + 1].value
            if token.value == ">&" and (target.isdigit() or target == "-"):
                continue  # A file descriptor binding is not a file write target.
            targets.append(target)
    for script in nested:
        targets.extend(output_redirect_targets(script, "posix", _depth=_depth + 1))
    segment: list[_Token] = []
    for token in [*tokens, _Token(";", True)]:
        if token.operator and token.value in {";", "&", "|", "&&", "||", "(", ")"}:
            targets.extend(_nested_targets(segment, _depth, dialect))
            segment = []
        else:
            segment.append(token)
    return targets


def _nested_targets(segment: list[_Token], depth: int, dialect: str) -> list[str]:
    words = [t.value for t in segment if not t.operator]
    while words and (words[0] in {"env", "exec", "command", "sudo"}
                     or words[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
        words.pop(0)
    if not words:
        return []
    name = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    if name == "eval":
        script = " ".join(words[1:])
        if any(ch in script for ch in "$%!"):
            raise ShellSyntaxUnknown("Dynamic eval needs explicit approval")
        return output_redirect_targets(script, dialect, _depth=depth + 1)
    # Wrappers such as timeout/xargs can prefix an inline shell. Inspect the
    # first explicit shell rather than exempting its quoted script as data.
    if name not in _SHELLS:
        found = next((i for i, w in enumerate(words[1:], 1)
                      if w.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe") in _SHELLS), None)
        if found is not None:
            return _nested_targets([_Token(w) for w in words[found:]], depth, dialect)
        if any(ch in words[0] for ch in "$%!"):
            raise ShellSyntaxUnknown("Dynamic command leader needs explicit approval")
        return []
    child = _SHELLS[name]
    for index, word in enumerate(words[1:], 1):
        low = word.lower()
        if child == "powershell" and low.startswith("-e"):
            raise ShellSyntaxUnknown("Encoded nested shell cannot be inspected as literal syntax")
        is_command = (low in {"/c", "/k"} if child == "cmd" else
                      low in {"-c", "-command"} if child == "powershell" else
                      low == "--command" or low.startswith("-") and "c" in low[1:])
        if not is_command:
            if child == "powershell" and low.startswith("-") and low not in {
                "-noprofile", "-nologo", "-noninteractive", "-noexit", "-sta", "-mta",
            }:
                raise ShellSyntaxUnknown("Unsupported nested PowerShell option needs explicit approval")
            continue
        rest = words[index + 1:]
        if not rest:
            raise ShellSyntaxUnknown("Nested shell command payload is missing")
        script = rest[0] if child == "posix" else " ".join(rest)
        dynamic_chars = "%!" if child == "cmd" else "$`"
        if any(ch in script for ch in dynamic_chars):
            raise ShellSyntaxUnknown("Dynamic nested shell payload needs explicit approval")
        return output_redirect_targets(script, child, _depth=depth + 1)
    return []  # A shell script file is not an inline script; no content is inferred.


def _tokens(command: str, dialect: str) -> tuple[list[_Token], list[str]]:
    tokens: list[_Token] = []
    nested: list[str] = []
    word: list[str] = []
    active = False
    quote: str | None = None
    i = 0

    def flush() -> None:
        nonlocal active
        if active:
            tokens.append(_Token("".join(word)))
            word.clear()
            active = False

    while i < len(command):
        ch = command[i]
        escape = ((dialect == "posix" and ch == "\\" and quote != "'")
                  or (dialect == "cmd" and ch == "^" and quote is None)
                  or (dialect == "powershell" and ch == "`" and quote != "'"))
        if escape:
            if i + 1 >= len(command):
                raise ShellSyntaxUnknown("Unfinished shell escape")
            nxt = command[i + 1]
            if dialect == "posix" and quote == '"' and nxt not in '$`"\\\n':
                word.append(ch)
                active = True
                i += 1
                continue
            if nxt != "\n":
                word.append(nxt)
                active = True
            i += 2
            continue
        if quote != "'" and dialect == "posix" and (command.startswith("$(", i) or ch == "`"):
            if ch == "`":
                end = command.find("`", i + 1)
                if end < 0:
                    raise ShellSyntaxUnknown("Unfinished command substitution")
                nested.append(command[i + 1:end])
            else:
                end = _substitution_end(command, i + 2)
                nested.append(command[i + 2:end])
            word.append(command[i:end + 1])
            active = True
            i = end + 1
            continue
        if quote is not None:
            if ch == quote:
                if dialect == "powershell" and quote == "'" and command[i:i + 2] == "''":
                    word.append("'")
                    i += 2
                    continue
                quote = None
            else:
                word.append(ch)
            active = True
            i += 1
            continue
        if ch == '"' or ch == "'" and dialect != "cmd":
            quote = ch
            active = True
            i += 1
        elif ch.isspace():
            flush()
            if ch == "\n":
                tokens.append(_Token(";", True))
            i += 1
        elif ch in "><;|&()":
            flush()
            pair = command[i:i + 2]
            if pair in {"<(", ">("}:
                raise ShellSyntaxUnknown("Process substitution needs explicit approval")
            op = pair if pair in {">>", ">&", ">|", "<<", "&&", "||"} else ch
            tokens.append(_Token(op, True))
            i += len(op)
        else:
            word.append(ch)
            active = True
            i += 1
    if quote:
        raise ShellSyntaxUnknown("Unfinished shell quote")
    flush()
    return tokens, nested


def _substitution_end(command: str, start: int) -> int:
    depth = 1
    quote: str | None = None
    i = start
    while i < len(command):
        ch = command[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ShellSyntaxUnknown("Unfinished command substitution")
