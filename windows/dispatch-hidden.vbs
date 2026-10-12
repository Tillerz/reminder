' Runs dispatch.ps1 with no window appearing at all. Registered as the action
' of the ClaudeReminder_Dispatch task:
'   wscript.exe //nologo //B "<this folder>\dispatch-hidden.vbs"
'
' Task Scheduler running powershell.exe directly makes Windows allocate a
' console window, which flashes on screen at every morning check, even with
' -WindowStyle Hidden. wscript.exe is a GUI-subsystem program, so it never gets
' a console, and Run(cmd, 0, True) keeps the PowerShell child hidden.
Option Explicit
Dim fso, sh, root, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & root & "\dispatch.ps1"""
Set sh = CreateObject("WScript.Shell")
WScript.Quit sh.Run(cmd, 0, True)
