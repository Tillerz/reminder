#!/usr/bin/env python3
"""UserPromptExpansion hook: answers the read-only /reminder commands
(help, list, next, or no argument) straight from reminder.py and stops the
prompt, so Claude is never called and no tokens are spent. Anything else
(/reminder add|edit|delete|sync, other commands) passes through untouched.
"""
import json
import os
import shlex
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))

try:
    ev = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
if ev.get("command_name") != "reminder":
    sys.exit(0)
try:
    args = shlex.split(ev.get("command_args") or "")
except ValueError:
    sys.exit(0)
if args and args[0] not in ("help", "list", "next"):
    sys.exit(0)

res = subprocess.run([os.path.join(DIR, "venv/bin/python3"), os.path.join(DIR, "reminder.py"), *args],
                     capture_output=True, text=True)
out = (res.stdout + res.stderr).rstrip() or "(no output)"
print(json.dumps({"continue": False, "stopReason": "\n" + out}))
