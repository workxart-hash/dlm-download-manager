; Inno Setup script for dlm (download manager).
; Per-user install (no admin / no UAC) so the Chrome native-messaging host is
; registered under the real user's HKCU hive. Bundles the --onedir PyInstaller
; build from ..\dist\dlm\.
;
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\dlm.iss
; Output: installer\Output\dlm-setup-<version>.exe

#define MyAppName "dlm download manager"
#define MyAppVersion "0.1.1"
#define MyAppPublisher "dlm"
#define MyAppExeName "dlm.exe"
#define HostName "com.dlm.native"
#define HostRegKey "Software\Google\Chrome\NativeMessagingHosts\com.dlm.native"

[Setup]
AppId={{B9D5E2A1-4C3F-4E6A-9F2D-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\dlm
DefaultGroupName=dlm
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=dlm-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
SetupIconFile=..\assets\dlm.ico
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "addtopath"; Description: "Add dlm to my PATH (for the command line)"

[Files]
Source: "..\dist\dlm\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\dlm"; Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"
Name: "{group}\Uninstall dlm"; Filename: "{uninstallexe}"
Name: "{autodesktop}\dlm"; Filename: "{app}\{#MyAppExeName}"; Parameters: "gui"; Tasks: desktopicon

[UninstallDelete]
Type: files; Name: "{app}\dlm_host.bat"
Type: files; Name: "{app}\{#HostName}.json"

[Code]
var
  ExtPage: TInputQueryWizardPage;

function HostBatPath: String;
begin
  Result := ExpandConstant('{app}\dlm_host.bat');
end;

function HostManifestPath: String;
begin
  Result := ExpandConstant('{app}\{#HostName}.json');
end;

procedure InitializeWizard;
begin
  ExtPage := CreateInputQueryPage(wpSelectTasks,
    'Chrome native host',
    'Register the native messaging host (optional)',
    'Enter the Extension ID from chrome://extensions (Developer mode > Load unpacked).' + #13#10 +
    'Leave blank to skip; you can register later with  dlm install-host <id>.');
  ExtPage.Add('Extension ID:', False);
end;

procedure RegisterHost(ExtId: String);
var
  Bat, Manifest, JsonBatPath: String;
begin
  Bat := '@echo off' + #13#10 +
         '"' + ExpandConstant('{app}\{#MyAppExeName}') + '" native-host %*' + #13#10;
  SaveStringToFile(HostBatPath, Bat, False);

  JsonBatPath := HostBatPath;
  StringChangeEx(JsonBatPath, '\', '\\', True);  { escape for JSON }

  Manifest :=
    '{' + #13#10 +
    '  "name": "{#HostName}",' + #13#10 +
    '  "description": "dlm download manager",' + #13#10 +
    '  "path": "' + JsonBatPath + '",' + #13#10 +
    '  "type": "stdio",' + #13#10 +
    '  "allowed_origins": [ "chrome-extension://' + ExtId + '/" ]' + #13#10 +
    '}' + #13#10;
  SaveStringToFile(HostManifestPath, Manifest, False);

  RegWriteStringValue(HKEY_CURRENT_USER, '{#HostRegKey}', '', HostManifestPath);
end;

{ --- optional PATH handling (per-user) --- }
function PathHasDir(const Dir: String): Boolean;
var
  Cur: String;
begin
  Result := False;
  if RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Cur) then
    Result := Pos(Uppercase(Dir), Uppercase(Cur)) > 0;
end;

procedure PathAdd(const Dir: String);
var
  Cur: String;
begin
  if PathHasDir(Dir) then
    Exit;
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Cur) then
    Cur := '';
  if (Cur <> '') and (Copy(Cur, Length(Cur), 1) <> ';') then
    Cur := Cur + ';';
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Cur + Dir);
end;

procedure PathRemove(const Dir: String);
var
  Cur: String;
begin
  if RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Cur) then
  begin
    StringChangeEx(Cur, ';' + Dir, '', True);
    StringChangeEx(Cur, Dir + ';', '', True);
    StringChangeEx(Cur, Dir, '', True);
    RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Cur);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExtId: String;
begin
  if CurStep = ssPostInstall then
  begin
    ExtId := Trim(ExtPage.Values[0]);
    if ExtId <> '' then
      RegisterHost(ExtId);
    if WizardIsTaskSelected('addtopath') then
      PathAdd(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegKeyExists(HKEY_CURRENT_USER, '{#HostRegKey}') then
      RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, '{#HostRegKey}');
    PathRemove(ExpandConstant('{app}'));
  end;
end;
