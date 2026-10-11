<#
Reminder dispatcher. Runs on Windows only -- no WSL, no Claude Code needed.

Reads reminders.json, works out which reminders fall inside the next ~36h,
and creates one short-lived Scheduled Task per ping ("ClaudeReminderRun_*")
that plays the pre-rendered WAV at the exact minute. Stale run-tasks from
earlier days are pruned.

Why not encode the recurrence in Task Scheduler directly? It cannot express
"5th Friday of the month" (/MO only knows FIRST..FOURTH, LAST), and its
week-interval anchoring is awkward. All the date rules therefore live here.

  -Preview <days>   print the upcoming firings instead of touching the
                    scheduler (used by reminder.py from WSL)
  -Force            rebuild the run-tasks even if the plan is unchanged
#>
param(
    [int]$Preview = 0,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root       = $PSScriptRoot
$configPath = Join-Path $root "reminders.json"
$stampPath  = Join-Path $root "state\plan.stamp"
$runPrefix  = "ClaudeReminderRun_"
$horizonH   = 36    # how far ahead pings are pre-scheduled
$graceMin   = 20    # how late a missed ping (asleep PC) may still fire

# Windowless player from the claude-audio-feedback setup. Launching
# powershell.exe from Task Scheduler makes Windows flash up a console window;
# wscript.exe is a GUI-subsystem program, so it never gets one. If the file is
# missing we fall back to play.ps1, which works but flashes.
$hiddenPlayer = Join-Path $env:USERPROFILE ".claude\tts\play-hidden.vbs"

$inv = [Globalization.CultureInfo]::InvariantCulture
$weekdays = @{ mon=1; tue=2; wed=3; thu=4; fri=5; sat=6; sun=0 }

function Test-Due($rule, [datetime]$date) {
    switch ($rule.type) {
        "daily"  { return $true }
        "weekly" { return [int]$date.DayOfWeek -eq $weekdays[$rule.weekday] }
        "every_n_weeks" {
            $start = [datetime]::ParseExact($rule.start, 'yyyy-MM-dd', $inv)
            if ($date.Date -lt $start.Date) { return $false }
            return (($date.Date - $start.Date).Days % (7 * [int]$rule.n)) -eq 0
        }
        "nth_weekday" {
            if ([int]$date.DayOfWeek -ne $weekdays[$rule.weekday]) { return $false }
            $nth = [math]::Floor(($date.Day - 1) / 7) + 1
            return ([int[]]$rule.nth) -contains $nth
        }
        "monthly_day" { return $date.Day -eq [int]$rule.day }
        "once" {
            return $date.Date -eq [datetime]::ParseExact($rule.date, 'yyyy-MM-dd', $inv).Date
        }
        "yearly" {
            $m = [int]$rule.month; $d = [int]$rule.day
            # 29 February only exists in leap years -- fall back to the 28th
            if ($m -eq 2 -and $d -eq 29 -and -not [datetime]::IsLeapYear($date.Year)) { $d = 28 }
            return ($date.Month -eq $m -and $date.Day -eq $d)
        }
    }
    throw "unknown repeat type '$($rule.type)'"
}

# Every ping (lead + on-time) falling in [$from, $from + $hours].
function Get-Pings([datetime]$from, [int]$hours) {
    $reminders = Get-Content $configPath -Raw | ConvertFrom-Json
    $until = $from.AddHours($hours)
    $pings = @()
    # look one day either side so a lead ping that crosses midnight is caught
    foreach ($offset in -1..([math]::Ceiling($hours / 24.0) + 1)) {
        $day = $from.Date.AddDays($offset)
        foreach ($r in $reminders) {
            if (-not (Test-Due $r.repeat $day)) { continue }
            $hm = [datetime]::ParseExact($r.time, 'HH:mm', $inv)
            $at = $day.AddHours($hm.Hour).AddMinutes($hm.Minute)
            $lead = 0
            if ($r.PSObject.Properties.Name -contains 'lead') { $lead = [int]$r.lead }
            $shots = @(@{ wav = $r.name; when = $at; kind = "at" })
            if ($lead -gt 0) {
                $shots += @{ wav = "$($r.name)-lead"; when = $at.AddMinutes(-$lead); kind = "lead" }
            }
            foreach ($s in $shots) {
                if ($s.when -ge $from -and $s.when -le $until) {
                    $pings += [pscustomobject]@{
                        Name = $r.name; Wav = $s.wav; Kind = $s.kind; When = $s.when
                    }
                }
            }
        }
    }
    return $pings | Sort-Object When
}

if ($Preview -gt 0) {
    foreach ($p in (Get-Pings ([datetime]::Now) ($Preview * 24))) {
        "{0:yyyy-MM-dd ddd HH:mm}  {1,-16} {2}" -f $p.When, $p.Name, $p.Kind
    }
    exit 0
}

$pings = Get-Pings ([datetime]::Now) $horizonH

# Skip the (slow) scheduler work when today's plan is already in place.
$plan = ($pings | ForEach-Object { "{0:s} {1}" -f $_.When, $_.Wav }) -join "`n"
New-Item -ItemType Directory -Force -Path (Split-Path $stampPath) | Out-Null
if (-not $Force -and (Test-Path $stampPath) -and (Get-Content $stampPath -Raw) -eq $plan) {
    exit 0
}

$wanted = @{}
foreach ($p in $pings) {
    # the firing time is part of the name: a daily reminder occurs twice
    # inside the horizon, and one name per WAV would let the later run
    # overwrite the sooner one.
    $taskName = "$runPrefix$($p.Wav)__$($p.When.ToString('MMdd-HHmm'))"
    $wanted[$taskName] = $true
    $wavPath = Join-Path $root "wav\$($p.Wav).wav"
    if (-not (Test-Path $wavPath)) {
        Write-Warning "no WAV for '$($p.Wav)' -- run reminder.py sync from WSL. Skipping."
        continue
    }
    if (Test-Path $hiddenPlayer) {
        $action = New-ScheduledTaskAction -Execute "wscript.exe" `
            -Argument "//nologo //B `"$hiddenPlayer`" `"$wavPath`""
    } else {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\play.ps1`" -Name $($p.Wav)"
    }
    $trigger = New-ScheduledTaskTrigger -Once -At $p.When
    # a ping missed while the PC slept may still fire, but only briefly
    $trigger.EndBoundary = $p.When.AddMinutes($graceMin).ToString("s")
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Claude reminder: $($p.Name) ($($p.Kind))" -Force | Out-Null
    Write-Output ("scheduled {0,-24} {1:yyyy-MM-dd HH:mm}" -f $p.Wav, $p.When)
}

foreach ($t in (Get-ScheduledTask -TaskName "$runPrefix*" -ErrorAction SilentlyContinue)) {
    if (-not $wanted.ContainsKey($t.TaskName)) {
        Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
        Write-Output "pruned $($t.TaskName)"
    }
}

Set-Content -Path $stampPath -Value $plan -NoNewline
