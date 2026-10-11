#!/usr/bin/env python3
"""Manage the spoken reminders end to end from WSL.

reminders.json holds each reminder's time, spoken text, repeat rule and
optional lead time (a second ping N minutes early). This script edits that
file, renders any WAV whose text is new or changed (Kokoro), and then hands
over to dispatch.ps1 on the Windows side, which owns all the date maths and
the Scheduled Tasks. See ../../../reminders/README.md on the Windows drive.

Run with the tts venv python (Kokoro lives there):
  ~/.claude/scripts/tts/venv/bin/python3 ~/.claude/scripts/tts/reminder.py <cmd> ...
"""
import argparse
import calendar
import datetime
import json
import os
import re
import subprocess
import sys

def _run(*argv):
    # stderr is dropped on purpose: cmd.exe warns when the working directory is
    # a WSL-only path, but still answers correctly.
    return subprocess.run(argv, capture_output=True, text=True).stdout.strip()


def _reminders_dir():
    """WSL path of the reminders folder on the Windows side.

    Set CLAUDE_REMINDERS_DIR to override. Otherwise it is
    <Windows user profile>\\.claude\\reminders, found by asking cmd.exe.
    """
    env = os.environ.get("CLAUDE_REMINDERS_DIR")
    if env:
        return os.path.expanduser(env)
    profile = _run("cmd.exe", "/c", "echo %USERPROFILE%")
    if not profile or profile.startswith("%"):
        raise SystemExit("ERROR: cannot find the Windows user profile -- "
                         "set CLAUDE_REMINDERS_DIR to the reminders folder")
    return os.path.join(_run("wslpath", "-u", profile), ".claude", "reminders")


REMINDERS_DIR = _reminders_dir()
CONFIG_PATH = os.path.join(REMINDERS_DIR, "reminders.json")
WAV_DIR = os.path.join(REMINDERS_DIR, "wav")
STATE_PATH = os.path.join(REMINDERS_DIR, "state", "rendered.json")
DISPATCH_PS1 = _run("wslpath", "-w", os.path.join(REMINDERS_DIR, "dispatch.ps1"))
VOICE = os.environ.get("CLAUDE_TTS_VOICE", "af_nicole")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


# --- repeat rules ---------------------------------------------------------

REPEAT_HELP = (
    "repeat spec: 'daily' | a weekday like 'tue' | '<n>weeks@YYYY-MM-DD' "
    "(e.g. 2weeks@2026-09-01) | '<weekday>:<nths>' (e.g. fri:1,3,5) | "
    "'day:<n>' (e.g. day:15) | 'once@YYYY-MM-DD' | 'yearly@MM-DD'"
)


def parse_repeat(spec):
    s = spec.strip().lower()
    if s == "daily":
        return {"type": "daily"}
    if s in DAYS:
        return {"type": "weekly", "weekday": s}
    m = re.match(r"^(\d+)weeks?@(\d{4}-\d{2}-\d{2})$", s)
    if m:
        return {"type": "every_n_weeks", "n": int(m.group(1)), "start": m.group(2)}
    m = re.match(r"^(%s):([1-5](?:,[1-5])*)$" % "|".join(DAYS), s)
    if m:
        nths = sorted({int(x) for x in m.group(2).split(",")})
        return {"type": "nth_weekday", "weekday": m.group(1), "nth": nths}
    m = re.match(r"^day:(\d{1,2})$", s)
    if m and 1 <= int(m.group(1)) <= 31:
        return {"type": "monthly_day", "day": int(m.group(1))}
    m = re.match(r"^once@(\d{4}-\d{2}-\d{2})$", s)
    if m:
        try:
            datetime.date.fromisoformat(m.group(1))
        except ValueError:
            die(f"'{m.group(1)}' is not a real date")
        return {"type": "once", "date": m.group(1)}
    m = re.match(r"^yearly@(\d{1,2})-(\d{1,2})$", s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        # 2024 is a leap year, so 29 February validates here as it should
        try:
            datetime.date(2024, month, day)
        except ValueError:
            die(f"'{s}' is not a real month-day")
        return {"type": "yearly", "month": month, "day": day}
    die(f"bad repeat '{spec}'\n{REPEAT_HELP}")


def describe(rule):
    t = rule["type"]
    if t == "daily":
        return "every day"
    if t == "weekly":
        return f"every {rule['weekday']}"
    if t == "every_n_weeks":
        every = "every week" if rule["n"] == 1 else f"every {rule['n']} weeks"
        return f"{every} from {rule['start']}"
    if t == "nth_weekday":
        return "%s %s of the month" % (
            ", ".join(ORDINALS[n] for n in rule["nth"]), rule["weekday"])
    if t == "once":
        past = " (past)" if datetime.date.fromisoformat(rule["date"]) < datetime.date.today() else ""
        return f"once on {rule['date']}{past}"
    if t == "yearly":
        return f"every year on {rule['day']} {calendar.month_name[rule['month']]}"
    return f"day {rule['day']} of the month"


# --- config ---------------------------------------------------------------

def load():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save(reminders):
    with open(CONFIG_PATH, "w") as f:
        json.dump(reminders, f, indent=2)
        f.write("\n")


def find(reminders, name):
    for r in reminders:
        if r["name"] == name:
            return r
    return None


def lead_text(r):
    return f"In {r['lead']} minutes. {r['text']}"


def wanted_wavs():
    """{wav basename: text to speak} for every reminder."""
    out = {}
    for r in load():
        out[r["name"]] = r["text"]
        if r.get("lead", 0) > 0:
            out[f"{r['name']}-lead"] = lead_text(r)
    return out


# --- rendering + dispatch -------------------------------------------------

def render_all():
    """Synthesize any WAV that is missing or whose text changed."""
    os.makedirs(WAV_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    done = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            done = json.load(f)

    wanted = wanted_wavs()
    todo = [w for w, text in wanted.items()
            if done.get(w) != text or not os.path.exists(os.path.join(WAV_DIR, f"{w}.wav"))]

    if todo:
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np
        pipeline = KPipeline(lang_code="a")
        for w in todo:
            chunks = [audio for _, _, audio in pipeline(wanted[w], voice=VOICE)]
            if not chunks:
                die(f"no audio produced for '{w}'")
            sf.write(os.path.join(WAV_DIR, f"{w}.wav"), np.concatenate(chunks), 24000)
            done[w] = wanted[w]
            print(f'rendered voice for {w}: "{wanted[w]}"')

    for w in list(done):
        if w not in wanted:
            path = os.path.join(WAV_DIR, f"{w}.wav")
            if os.path.exists(path):
                os.remove(path)
            del done[w]
            print(f"removed voice file for {w}")

    with open(STATE_PATH, "w") as f:
        json.dump(done, f, indent=2)


def dispatch(*extra):
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", DISPATCH_PS1, *extra],
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        die(res.stderr.strip() or "dispatch.ps1 failed")
    return res.stdout


def sync():
    render_all()
    out = dispatch("-Force").strip()
    print(out if out else "scheduled tasks already up to date")


# --- commands -------------------------------------------------------------

HELP = """spoken reminders -- add, change and preview them

READ (no changes)
  reminder                       list every reminder
  reminder list                  same
  reminder next [days]           preview upcoming pings (default 14)
  reminder help                  this text

CHANGE
  reminder add <name> --at HH:MM --repeat <spec> [--lead <min>] --text <words...>
  reminder edit <name> [--at HH:MM] [--repeat <spec>] [--lead <min>] [--text <words...>]
  reminder delete <name>
  reminder sync                  re-render voices + rebuild tasks
                                 (only needed after hand-editing reminders.json)

REPEAT SPECS
  daily                          every day
  mon tue wed thu fri sat sun    every week on that day
  <n>weeks@YYYY-MM-DD            every n weeks, counting from that date
  <weekday>:<nths>               e.g. fri:1,3,5 -- 1st, 3rd and 5th Friday
  day:<n>                        e.g. day:15 -- the 15th of every month
  once@YYYY-MM-DD                a single date, then never again
  yearly@MM-DD                   e.g. yearly@03-30 -- every 30 March

OPTIONS
  --at HH:MM     when the thing happens, 24-hour clock
  --lead <min>   extra "in N minutes" ping before it. Default 30. Use 0 for none.
  --text ...     what the voice says. No quotes needed. Put it last.
  --repeat ...   see above

EXAMPLES
  reminder add tea --at 15:00 --repeat daily --lead 0 --text Time for tea
  reminder add rent --at 09:00 --repeat day:1 --text Pay the rent today
  reminder add poker --at 20:00 --repeat 2weeks@2026-09-04 --text Poker night
  reminder add dentist --at 09:15 --repeat once@2026-10-07 --text Dentist appointment
  reminder add bday-ada --at 08:00 --repeat yearly@12-10 --lead 0 --text Ada's birthday today
  reminder edit baker --at 08:10
  reminder edit baker --text The baker is here with fresh bread
  reminder delete tea

NOT SUPPORTED YET (these need a code change -- ask Claude in Claude Code)
  several weekdays in one entry (mon+wed+fri), every n days, an end date,
  different lead times for the same entry. A 'once' entry is not deleted
  automatically after it fires -- 'list' marks it (past).

Reminders keep working with WSL and Claude Code closed. Windows plays them.
Config: @@DIR@@/reminders.json
Docs:   @@DIR@@/README.md
"""


def cmd_help(args):
    print(HELP.rstrip().replace("@@DIR@@", REMINDERS_DIR))


def cmd_list(args):
    reminders = load()
    if not reminders:
        print("no reminders set")
        return
    w = max(len(r["name"]) for r in reminders)
    for r in sorted(reminders, key=lambda x: (x["time"], x["name"])):
        lead = f"  (+{r['lead']}min warning)" if r.get("lead", 0) else ""
        print(f'{r["time"]}  {r["name"]:<{w}}  {describe(r["repeat"]):<32} '
              f'"{r["text"]}"{lead}')


def cmd_next(args):
    out = dispatch("-Preview", str(args.days)).strip()
    print(out if out else f"nothing due in the next {args.days} days")


def cmd_add(args):
    name = args.name
    if not NAME_RE.match(name):
        die(f"bad name '{name}' -- use letters, digits, - and _ only")
    if not TIME_RE.match(args.at):
        die(f"bad time '{args.at}' -- use 24-hour HH:MM")
    reminders = load()
    if find(reminders, name):
        die(f"reminder '{name}' already exists -- use edit")
    r = {
        "name": name,
        "time": args.at,
        "text": " ".join(args.text),
        "lead": args.lead,
        "repeat": parse_repeat(args.repeat),
    }
    reminders.append(r)
    save(reminders)
    print(f'added {name}: {args.at}, {describe(r["repeat"])}, "{r["text"]}"')
    sync()


def cmd_edit(args):
    reminders = load()
    r = find(reminders, args.name)
    if not r:
        die(f"no reminder called '{args.name}'")
    if not any([args.at, args.repeat, args.text, args.lead is not None]):
        die("nothing to change -- pass --at, --repeat, --lead or --text")
    if args.at:
        if not TIME_RE.match(args.at):
            die(f"bad time '{args.at}' -- use 24-hour HH:MM")
        r["time"] = args.at
    if args.repeat:
        r["repeat"] = parse_repeat(args.repeat)
    if args.lead is not None:
        r["lead"] = args.lead
    if args.text:
        r["text"] = " ".join(args.text)
    save(reminders)
    print(f'edited {r["name"]}: {r["time"]}, {describe(r["repeat"])}, "{r["text"]}"')
    sync()


def cmd_delete(args):
    reminders = load()
    if not find(reminders, args.name):
        die(f"no reminder called '{args.name}'")
    save([r for r in reminders if r["name"] != args.name])
    print(f"deleted {args.name}")
    sync()


def cmd_sync(args):
    sync()


def main():
    p = argparse.ArgumentParser(prog="reminder.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("help", help="how to use this").set_defaults(fn=cmd_help)
    sub.add_parser("list", help="show all reminders").set_defaults(fn=cmd_list)
    sub.add_parser("sync", help="re-render voices and rebuild the scheduled tasks"
                   ).set_defaults(fn=cmd_sync)

    n = sub.add_parser("next", help="preview upcoming pings")
    n.add_argument("days", nargs="?", type=int, default=14)
    n.set_defaults(fn=cmd_next)

    a = sub.add_parser("add", help="add a reminder", epilog=REPEAT_HELP)
    a.add_argument("name")
    a.add_argument("--at", required=True, metavar="HH:MM")
    a.add_argument("--repeat", required=True, metavar="SPEC")
    a.add_argument("--lead", type=int, default=30, metavar="MIN",
                   help="minutes for the early warning ping (0 = none, default 30)")
    a.add_argument("--text", required=True, nargs="+")
    a.set_defaults(fn=cmd_add)

    e = sub.add_parser("edit", help="change a reminder", epilog=REPEAT_HELP)
    e.add_argument("name")
    e.add_argument("--at", metavar="HH:MM")
    e.add_argument("--repeat", metavar="SPEC")
    e.add_argument("--lead", type=int, metavar="MIN")
    e.add_argument("--text", nargs="+")
    e.set_defaults(fn=cmd_edit)

    d = sub.add_parser("delete", help="remove a reminder")
    d.add_argument("name")
    d.set_defaults(fn=cmd_delete)

    args = p.parse_args(sys.argv[1:] or ["list"])
    args.fn(args)


if __name__ == "__main__":
    main()
