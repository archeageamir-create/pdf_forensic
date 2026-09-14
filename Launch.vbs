Option Explicit
Dim shell, fs, root, python
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not fs.FileExists(python) Then
    MsgBox "Run setup.ps1 once to prepare Python. Then open Launch.vbs again.", 48, "Document Forensic Inspector"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " -m app.main", 0, False
