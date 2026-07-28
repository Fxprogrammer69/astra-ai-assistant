' Fully detached ASTRA launcher (survives parent shell exit)
Option Explicit
Dim sh, root, electron, bat
Set sh = CreateObject("WScript.Shell")
root = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
electron = root & "\node_modules\electron\dist\electron.exe"
If CreateObject("Scripting.FileSystemObject").FileExists(electron) Then
  sh.Run """" & electron & """ .", 1, False
Else
  sh.Run "cmd /c npm start", 1, False
End If
