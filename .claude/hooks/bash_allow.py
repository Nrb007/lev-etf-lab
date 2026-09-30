#!/usr/bin/env python3
"""PreToolUse hook: let the skeptic run test commands and nothing else (SPEC Sections 8 and 9.3).

Usage: ``bash_allow.py '<command prefix>' ['<command prefix>' ...]``. A Bash call is allowed only
if its command starts with one of the prefixes (whole words) and contains no shell control
characters (``; & | < > ` $ ( )``, newline, backslash), so a permitted prefix cannot be chained
onto another command or redirected into a file. Exits 2 to block; fails closed.

This inspects command text. It is a speed bump, not a wall: it does not sandbox what an allowed
test command itself does (a test can write files). docs/methodology.md states that limitation.
"""

from __future__ import annotations

import json
import re
import sys

SHELL_CONTROL = re.compile(r"[;&|<>`$()\\\n\r]")


def decide(payload: dict, prefixes) -> str | None:
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return "no command to check"
    command = command.strip()
    if SHELL_CONTROL.search(command):
        return "shell control characters are not allowed"
    words = command.split()
    for prefix in prefixes:
        head = prefix.split()
        if words[: len(head)] == head:
            return None
    return f"only these commands are allowed: {', '.join(prefixes)}"


def main(argv) -> int:
    prefixes = argv[1:]
    if not prefixes:
        print("bash_allow.py: no allowed commands given; blocking", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input is not a JSON object")
    except ValueError as exc:
        print(f"bash_allow.py: unreadable hook input ({exc}); blocking", file=sys.stderr)
        return 2
    reason = decide(payload, prefixes)
    if reason:
        print(f"BLOCKED by bash_allow: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
