#define MyAppName "Document Forensic Inspector"
#include "version.iss"
#define MyAppPublisher "ТОО «АНСЭ»"
#define MyAppExeName "DocumentForensicInspector.exe"
#ifndef MyAppId
#define MyAppId "{{3DA10599-74CB-4A61-97FC-A7759120AB62}"
#endif

[Setup]
AppId={#MyAppId}
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
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Исследование файлов и метаданных — АНСЭ
VersionInfoCopyright=© 2026 ТОО «АНСЭ». Права защищены в пределах применимых лицензий.
VersionInfoProductName={#MyAppName}
LicenseFile=USER_AGREEMENT_RU.txt
SetupIconFile=..\app\resources\icons\anse.ico
WizardImageFile=..\app\resources\branding\wizard.bmp
WizardSmallImageFile=..\app\resources\branding\wizard-small.bmp
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
AppPublisherURL=https://github.com/archeageamir-create/pdf_forensic
AppSupportURL=https://github.com/archeageamir-create/pdf_forensic/issues
UninstallDisplayName={#MyAppName} {#MyAppVersion} — АНСЭ

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce

[InstallDelete]
; Only replace directories owned by an existing installation of this product.
; Research databases and working copies live outside {app} and are never removed.
Type: filesandordirs; Name: "{app}\_internal"; Check: IsManagedInstall
Type: filesandordirs; Name: "{app}\licenses"; Check: IsManagedInstall
Type: filesandordirs; Name: "{app}\compliance"; Check: IsManagedInstall
Type: filesandordirs; Name: "{app}\certificates"; Check: IsManagedInstall

[Files]
Source: "..\dist\DocumentForensicInspector\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\SBOM.spdx.json"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\SOURCE_OFFER.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\docs\LGPL_COMPLIANCE.md"; DestDir: "{app}\compliance"; Flags: ignoreversion
; Full supplier recipes and patches are in the separate source delivery. Their
; deep upstream paths are not required at runtime and can exceed MAX_PATH.
Source: "..\compliance\*"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\app\resources\AUTHORSHIP.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\release-resources\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

Source: "USER_AGREEMENT_RU.txt"; DestDir: "{app}\compliance"; Flags: ignoreversion
Source: "..\docs\release\*.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

Name: "{group}\Руководство пользователя"; Filename: "{app}\_internal\docs\user-guide\DocumentForensicInspector-User-Guide-RU.pdf"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := PageID = wpSelectTasks;
end;

function IsManagedInstall: Boolean;
var
  InstalledVersion: String;
begin
  Result := FileExists(ExpandConstant('{app}\unins000.dat')) and
    GetVersionNumbersString(ExpandConstant('{app}\{#MyAppExeName}'), InstalledVersion);
end;
