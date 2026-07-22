#define MyAppName "Document Forensic Inspector"
#define MyAppVersion "0.4.2"
#define MyAppPublisher "Amirkhan Smagulov"
#define MyAppExeName "DocumentForensicInspector.exe"

[Setup]
AppId={{3DA10599-74CB-4A61-97FC-A7759120AB62}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\DocumentForensicInspector
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DocumentForensicInspector-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Единая оболочка для экспертного исследования PDF и PPTX
VersionInfoCopyright=Оболочка и интеграция © 2026 Amirkhan Smagulov; сторонние компоненты сохраняют свои лицензии
VersionInfoProductName={#MyAppName}
InfoBeforeFile=..\app\resources\AUTHORSHIP.txt

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce

[Files]
Source: "..\dist\DocumentForensicInspector\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\SBOM.spdx.json"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\SOURCE_OFFER.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\docs\LGPL_COMPLIANCE.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\compliance\*"; DestDir: "{app}\compliance"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\app\resources\AUTHORSHIP.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\signing\Amirkhan-Smagulov-Code-Signing.cer"; DestDir: "{app}\certificates"; Flags: ignoreversion
Source: "..\signing\README-RU.txt"; DestDir: "{app}\certificates"; Flags: ignoreversion
Source: "..\app\resources\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
