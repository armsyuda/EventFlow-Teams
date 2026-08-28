; Per-user installer: no administrator account is required and user work data is never removed.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "EventFlow Teams"
#define AppExeName "EventFlowTeams.exe"

[Setup]
AppId={{C3C7E4B3-A2A8-4C89-B7F2-3DAA9589F48D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=EventFlow
DefaultDirName={localappdata}\Programs\EventFlow Teams
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release\installer
OutputBaseFilename=EventFlowTeams-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "..\release\EventFlowTeams\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "EventFlow Teams 실행"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\.eventflow-teams-installed"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\.eventflow-teams-installed'), 'EventFlow Teams installed application', False);
end;
