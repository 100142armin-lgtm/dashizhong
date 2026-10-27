; Clock/Alarm - Windows installer (Inno Setup 6)
; MyAppVersion and MyAppURL are supplied by the release workflow.

#define MyAppName "Clock/Alarm"
#define MyAppSafeName "Clock-Alarm"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.20"
#endif
#ifndef MyAppURL
  #define MyAppURL ""
#endif
#define MyAppPublisher "Clock/Alarm"
#define MyAppExeName "Clock-Alarm.exe"
#define MySourceDir "..\dist\Clock-Alarm"

[Setup]
AppId={{A8C3E2F1-4B7D-4E9A-9C2F-ClockAlarm}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\ClockAlarm
DefaultGroupName={#MyAppSafeName}
DisableProgramGroupPage=yes
OutputDir=..\dist\release
OutputBaseFilename=Clock-Alarm-{#MyAppVersion}-windows-setup
SetupIconFile=..\logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppSafeName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppSafeName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppSafeName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; The application creates this value only after explicit consent in Settings.
; The installer only removes it on uninstall; it never enables autostart.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: none; ValueName: "ClockAlarm"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
