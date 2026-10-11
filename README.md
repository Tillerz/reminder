# reminder

Spoken daily reminders on Windows, with the same local voice as
[claude-audio-feedback](https://github.com/Tillerz/claude-audio-feedback) (requirement!). Each reminder is a
pre-rendered WAV played by a Windows Scheduled Task.

**Deliberately independent of WSL and Claude Code.** Nothing needs to be open at
the time a reminder speaks. WSL is only needed ahead of time, to render the audio
and to edit the list.

Built 2026-08-31 (v1, one task per reminder). Rewritten 2026-09-02 (v2, one
planner task). Last extended 2026-09-15 (one-off and yearly dates).

> **This folder is a copy, not the live install.** The running code lives in
> `~/.claude/scripts/tts/` (WSL) and `%USERPROFILE%\.claude\reminders\`
> (Windows). See [Keeping this copy in sync](#keeping-this-copy-in-sync).

## Example reminders

`windows/reminders.example.json` ships with one entry per repeat rule, so you
can see every shape and then replace them with your own. No personal data is
kept in this project.

| Time | Name | Repeat | Early ping |
|---|---|---|---|
| 08:00 | birthday-example | every year, 10 December | - |
| 09:00 | rent | day 1 of every month | - |
| 09:15 | dentist | once, on 2026-10-07 | 30 min |
| 09:30 | standup | every Monday | 5 min |
| 12:30 | lunch | every day | - |
| 18:00 | game-night | every 2 weeks from 2026-01-06 | 30 min |
| 19:00 | bin-day | 1st, 3rd and 5th Thursday | 30 min |

Run `reminder` to list whatever you actually have.

## How it works

```
reminders.json                 name, time, text, lead, repeat rule
      |
      |  reminder.py (WSL)     edits the list, then renders any WAV whose
      |                        text is new or changed, using the Kokoro venv
      |                        from claude-audio-feedback
      v
wav/<name>.wav                 spoken at the event time
wav/<name>-lead.wav            spoken `lead` minutes earlier
      |
      |  dispatch.ps1 (Windows)   owns ALL the date maths. Works out every ping
      |                           in the next 36 h, and registers one one-shot
      |                           task per ping:
      |                           ClaudeReminderRun_<wav>__<MMdd-HHmm>
      |                           Prunes tasks that are no longer wanted.
      v
wscript.exe play-hidden.vbs    plays the WAV with no window flashing up
                               (falls back to play.ps1 if that file is missing)
```

One planner task, `ClaudeReminder_Dispatch`, runs `dispatch.ps1`.

### Why the date rules are not in Task Scheduler

The v1 design used one daily Scheduled Task per reminder. It could not express
what was needed:

- **"5th Friday of the month" is impossible.** `schtasks /sc MONTHLY /MO` accepts
  only FIRST, SECOND, THIRD, FOURTH and LAST. LAST is *not* the 5th: in
  September 2026 the last Friday is the 4th one.
- Anchoring "every 2 weeks from date X" to a StartBoundary is fiddly and fails
  quietly.
- `New-ScheduledTaskTrigger` cannot build a monthly trigger at all.

So all rules live in `dispatch.ps1` instead, and Task Scheduler only ever gets
plain one-shot times.

### Why the planner runs in the morning

**This PC is switched off overnight.** A nightly planner would never run. The
planner therefore fires at logon, plus on a repeat during the morning. Each run
plans 36 hours ahead, so one morning run covers the rest of the day and the next
morning.

`state/plan.stamp` holds the plan it last applied. A run whose plan is unchanged
exits at once, so a frequent repeat costs almost nothing.

## Files

### WSL side (`wsl/`)

| File | Where it belongs | What it is |
|---|---|---|
| `reminder.py` | `~/.claude/scripts/tts/reminder.py` | The CLI. Edits `reminders.json`, renders changed WAVs, calls `dispatch.ps1`. |
| `reminder_hook.py` | `~/.claude/scripts/tts/reminder_hook.py` | `UserPromptExpansion` hook. Answers the read-only `/reminder` commands with no model call, so they cost no tokens. |
| `bin-reminder` | `~/bin/reminder` | Plain terminal wrapper. Hides the venv path and filters PyTorch warnings. |

### Claude Code side (`claude-code/`)

| File | Where it belongs |
|---|---|
| `reminder.md` | `~/.claude/commands/reminder.md` - the `/reminder` slash command |
| `settings.hook.json` | merge into `~/.claude/settings.json` - the `UserPromptExpansion` hook |

### Windows side (`windows/`)

| File | Where it belongs | What it is |
|---|---|---|
| `dispatch.ps1` | `%USERPROFILE%\.claude\reminders\dispatch.ps1` | The planner. All date maths. `-Preview <days>` prints upcoming pings without touching the scheduler. `-Force` rebuilds even if the plan is unchanged. |
| `install_dispatcher.ps1` | same folder | Run once. Registers `ClaudeReminder_Dispatch` and removes the old v1 per-reminder tasks. |
| `play.ps1` | same folder | Plays `wav\<Name>.wav`. Now only a fallback and a handy way to test by hand. |
| `reminders.example.json` | copy to `reminders.json` in the same folder | Starter list, one entry per repeat rule. |
| `scheduled-tasks/ClaudeReminder_Dispatch.template.xml` | - | The planner task definition, with your user, PC name and SID replaced by placeholders. Normally you do not need it: `install_dispatcher.ps1` builds the task correctly from scratch. |

**Generated data is deliberately not in this project:** `wav/*.wav`,
`state/rendered.json` and `state/plan.stamp`. They hold your own reminder text
as files and as audio. `reminder sync` rebuilds all of them from
`reminders.json` in about two minutes.

## WARNING: the live task differs from the installer

Checked 2026-10-11. Someone edited the planner task by hand in the Windows Task
Scheduler window after it was installed.

| | `install_dispatcher.ps1` says | Live task is |
|---|---|---|
| Start | 06:00 | **06:30** |
| Repeat every | 5 min | **30 min** |
| For | 3 hours | **2 hours** |

Both work. The hand-made values are recorded in the table above;
`scheduled-tasks/ClaudeReminder_Dispatch.template.xml` carries the same trigger
shape with the user, PC name and SID removed.

**Re-running `install_dispatcher.ps1` will overwrite the hand-made change.**
Decide which one you want and make them match.

This happened once before: on 2026-09-15 the task was found with its repeat
trigger disabled entirely, which stopped the pruning of finished tasks.

## Install from scratch

Needs [claude-audio-feedback](../claude-audio-feedback/) installed first. This
project uses two things from it:

- its venv and Kokoro model, to render the WAV files, and
- its `play-hidden.vbs`, so a reminder does not flash a console window when it
  speaks. Without that file `dispatch.ps1` falls back to `play.ps1`, which
  still works but flashes.

1. **Windows files:**
   ```bash
   W="$(wslpath -u "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")/.claude/reminders"
   mkdir -p "$W/wav" "$W/state"
   cp windows/dispatch.ps1 windows/install_dispatcher.ps1 windows/play.ps1 "$W/"
   cp windows/reminders.example.json "$W/reminders.json"
   ```
   Then edit `$W/reminders.json` and put your own reminders in it.

2. **WSL files:**
   ```bash
   cp wsl/reminder.py wsl/reminder_hook.py ~/.claude/scripts/tts/
   mkdir -p ~/bin && cp wsl/bin-reminder ~/bin/reminder && chmod +x ~/bin/reminder
   cp claude-code/reminder.md ~/.claude/commands/
   ```
   `~/.profile` already adds `~/bin` to PATH for login shells. For VS Code
   terminals, add this to `~/.bashrc`:
   ```bash
   case ":$PATH:" in *":$HOME/bin:"*) ;; *) PATH="$HOME/bin:$PATH" ;; esac
   ```

3. **Merge the hook** from `claude-code/settings.hook.json` into
   `~/.claude/settings.json`. Keep your other hooks.

4. **Register the planner task** (from WSL is fine):
   ```bash
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$W/install_dispatcher.ps1")"
   ```

5. **Render and plan:**
   ```bash
   reminder sync
   reminder next 14
   ```

## Settings

| Environment variable | Default | Meaning |
|---|---|---|
| `CLAUDE_REMINDERS_DIR` | `<Windows user profile>/.claude/reminders`, found by asking `cmd.exe` | Where `reminders.json`, `wav/` and `state/` live. |
| `CLAUDE_TTS_VOICE` | `af_nicole` | Kokoro voice used when rendering. |

Nothing in the code hardcodes a user name or a home folder.

## Usage

```
reminder                       list every reminder
reminder list                  same
reminder next [days]           preview upcoming pings (default 14)
reminder help                  full usage
reminder add <name> --at HH:MM --repeat <spec> [--lead <min>] --text <words...>
reminder edit <name> [--at HH:MM] [--repeat <spec>] [--lead <min>] [--text <words...>]
reminder delete <name>
reminder sync                  re-render voices and rebuild tasks
```

`/reminder ...` works the same inside Claude Code. The read-only commands
(`help`, `list`, `next`, no argument) are answered by the hook and cost no
tokens. `add`, `edit`, `delete` and `sync` go to Claude, so it can explain an
error.

### Repeat specs

| Spec | Meaning |
|---|---|
| `daily` | every day |
| `mon` … `sun` | every week on that day |
| `<n>weeks@YYYY-MM-DD` | every n weeks, counting from that date |
| `<weekday>:<nths>` | e.g. `fri:1,3,5` - 1st, 3rd and 5th Friday |
| `day:<n>` | e.g. `day:15` - the 15th of every month |
| `once@YYYY-MM-DD` | a single date, then never again |
| `yearly@MM-DD` | e.g. `yearly@03-30` - every 30 March |

`--lead <min>` adds a second ping that many minutes earlier, spoken as
"In N minutes. `<text>`". Default 30. `--lead 0` disables it.

### Not supported

Several weekdays in one entry (`mon+wed+fri`), every n days, an end date, and
different lead times for the same entry. These need a code change in both
`reminder.py` (the spec parser) and `dispatch.ps1` (`Test-Due`).

A `once` entry is not deleted after it fires. `list` marks it `(past)`.

## Behaviour worth knowing

- **Missed pings.** Each run task uses `-StartWhenAvailable` with an EndBoundary
  20 minutes after its time (`$graceMin` in `dispatch.ps1`). A ping missed
  because the PC slept still fires shortly after wake. An older one is skipped,
  not shouted hours late.
- **29 February** fires on 28 February in normal years.
- **`day:31`** never fires in short months. Pre-existing limit, not used.
- **Run-task names include the time** (`__MMdd-HHmm`). A daily reminder appears
  twice inside the 36 h window, and one name per WAV would let the later ping
  overwrite the sooner one.

## Gotchas already fixed

| Problem | Cause | Fix in the code |
|---|---|---|
| Every triggered run failed silently (`LastTaskResult = 1`) | A fresh non-interactive `powershell.exe` from Task Scheduler does not inherit a permissive execution policy | `-ExecutionPolicy Bypass` in every task action |
| `Register-ScheduledTask` returned "Access is denied" | An `AtLogOn` trigger without `-User` means "any user", which needs elevation | `New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"` |
| A repeating daily trigger could not be built | `New-ScheduledTaskTrigger` has no repetition parameter for `-Daily` | Borrow the `Repetition` block from a throwaway `-Once` trigger |
| `/reminder` with no argument errored out | argparse required a subcommand | `reminder.py` defaults to `list` |
| A console window flashed on every reminder | Task Scheduler launching `powershell.exe` gets a console before `-WindowStyle Hidden` can hide it | The run tasks call `wscript.exe` with `play-hidden.vbs`, which is GUI-subsystem and never gets a console |

## Testing

```powershell
# Play a WAV directly, no scheduler:
powershell.exe -NoProfile -File "%USERPROFILE%\.claude\reminders\play.ps1" -Name CinemaReminder

# Preview the date rules without touching the scheduler:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude\reminders\dispatch.ps1" -Preview 35

# Re-plan now, ignoring the stamp:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.claude\reminders\dispatch.ps1" -Force

# What is armed right now?
schtasks.exe /query /fo csv /nh | findstr ClaudeReminder

# Did the planner succeed?
Get-ScheduledTaskInfo -TaskName "ClaudeReminder_Dispatch" | Select LastRunTime, LastTaskResult
```

`LastTaskResult = 267011` means "has not run yet". That is normal for a future
one-shot task.

## Keeping this copy in sync

```bash
T=~/.claude/scripts/tts
W="$(wslpath -u "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")/.claude/reminders"
R=~/projects/reminder
cp $T/reminder.py $T/reminder_hook.py $R/wsl/
cp ~/bin/reminder $R/wsl/bin-reminder
cp ~/.claude/commands/reminder.md $R/claude-code/
jq '{hooks: {UserPromptExpansion: .hooks.UserPromptExpansion}}' ~/.claude/settings.json > $R/claude-code/settings.hook.json
cp "$W/dispatch.ps1" "$W/install_dispatcher.ps1" "$W/play.ps1" $R/windows/
```

**Code only, on purpose.** `reminders.json`, `wav/` and `state/` are your own
data and must stay out of here. The task template is already generic, so there
is nothing to re-export either.
