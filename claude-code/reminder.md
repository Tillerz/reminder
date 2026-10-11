---
description: Add, delete, edit or list the spoken reminders
disable-model-invocation: true
shell: bash
---

!`~/.claude/scripts/tts/venv/bin/python3 ~/.claude/scripts/tts/reminder.py $ARGUMENTS 2>&1 | grep -viE "futurewarning|weightnorm|super\(\)\.__init__|repo_id"`

The user ran `/reminder $ARGUMENTS`. Report the result of the shell output above
briefly and in plain language — what changed, and when it next speaks. Don't dump
the raw output verbatim. If it starts with `ERROR:`, say what went wrong and show
the relevant usage below.

- `/reminder help` — full usage with examples
- `/reminder list` — all reminders
- `/reminder next [days]` — preview upcoming pings (default 14 days)
- `/reminder sync` — re-render voices and rebuild the scheduled tasks
- `/reminder add <name> --at HH:MM --repeat <spec> [--lead <min>] --text <words...>`
- `/reminder edit <name> [--at HH:MM] [--repeat <spec>] [--lead <min>] [--text <words...>]`
- `/reminder delete <name>`

Repeat specs: `daily` · `tue` (any weekday) · `2weeks@2026-09-01` (every N weeks
from a date) · `fri:1,3,5` (1st/3rd/5th Friday of the month) · `day:15` (day of
the month) · `once@2026-10-07` (a single date) · `yearly@03-30` (every year,
e.g. birthdays). `--lead` is the early-warning ping in minutes, default 30, `0` = none.
