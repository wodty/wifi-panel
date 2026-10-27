' wifi-panel Agent - silent launcher (no console window)
' Runs agent\start_agent.bat completely hidden.
' Use it via Task Scheduler (install_autostart.bat) or a shortcut in shell:startup.
' NOTE: keep this file ASCII-only; edit HUB/TOKEN/NAME in start_agent.bat instead.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
bat = """" & root & "\agent\start_agent.bat"" hidden"
sh.CurrentDirectory = root
sh.Run "cmd /c " & bat, 0, False
