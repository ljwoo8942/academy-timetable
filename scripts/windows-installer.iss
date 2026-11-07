#define AppName "학원 시간표"

[Setup]
AppId=AcademyTimetable
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AcademyTimetable
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
DisableDirPage=yes
DisableProgramGroupPage=yes
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=AcademyTimetable-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\AcademyTimetable.exe

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "..\dist\AcademyTimetable.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\AcademyTimetable.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\AcademyTimetable.exe"

[Run]
Filename: "{app}\AcademyTimetable.exe"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
