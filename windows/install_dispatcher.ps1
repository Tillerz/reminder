<#
Registers the single "ClaudeReminder_Dispatch" scheduled task that keeps the
per-ping run-tasks up to date, and removes the old one-task-per-reminder
"ClaudeReminder_<name>" tasks that the pre-2026-09-02 design used.

Triggers: at logon (the PC is off overnight, so a nightly trigger is useless)
and every 5 minutes between 06:00 and 09:00 as a safety net. dispatch.ps1
exits immediately when the day's plan is already in place, so the frequent
runs are nearly free.

Run once (and again only if these triggers should change):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\reminders\install_dispatcher.ps1"
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$taskName = "ClaudeReminder_Dispatch"

# Launch through wscript.exe when possible: Task Scheduler starting
# powershell.exe directly gets a console window, which flashes on screen at
# every morning check even with -WindowStyle Hidden.
$hidden = Join-Path $root "dispatch-hidden.vbs"
if (Test-Path $hidden) {
    $action = New-ScheduledTaskAction -Execute "wscript.exe" `
        -Argument "//nologo //B `"$hidden`""
} else {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\dispatch.ps1`""
}

# -User matters: an AtLogOn trigger without it means "any user", which
# Task Scheduler only lets an elevated process register.
$me = "$env:USERDOMAIN\$env:USERNAME"
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $me

# New-ScheduledTaskTrigger can't build a repeating *daily* trigger directly;
# borrow the Repetition block off a throwaway -Once trigger.
$daily = New-ScheduledTaskTrigger -Daily -At "06:00"
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At "06:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Hours 3)).Repetition

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($atLogon, $daily) -Settings $settings `
    -Description "Claude reminders: plans the day's spoken reminders" -Force | Out-Null
Write-Output "registered $taskName (at logon + every 5 min, 06:00-09:00)"

# Retire the old per-reminder daily tasks (superseded by ClaudeReminderRun_*).
foreach ($t in (Get-ScheduledTask -TaskName "ClaudeReminder_*" -ErrorAction SilentlyContinue)) {
    if ($t.TaskName -eq $taskName -or $t.TaskName -like "ClaudeReminderRun_*") { continue }
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
    Write-Output "removed obsolete task $($t.TaskName)"
}
