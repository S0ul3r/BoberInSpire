; BoberInSpire installer - Inno Setup script
; Prerequisite: run build.bat first so dist\BoberInSpire exists.

#define MyAppName "BoberInSpire"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "BoberInSpire"
#define MyAppURL "https://github.com/your-repo/BoberInSpire"
#define MyAppExeName "run_overlay.bat"

[Setup]
AppId={{BoberInSpire-2025-STS2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=BoberInSpire_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "installmod"; Description: "Copy mod to Slay the Spire 2 (requires game path below)"; GroupDescription: "Mod installation:"; Flags: unchecked

[Files]
; Overlay app (Python sources + data) - must exist after build.bat
Source: "dist\BoberInSpire\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Launcher
Source: "run_overlay.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\BoberInSpire Overlay"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BoberInSpire Overlay"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  STS2PathPage: TInputDirWizardPage;
  STS2ModPath: String;

procedure InitializeWizard;
begin
  STS2PathPage := CreateInputDirPage(wpSelectTasks,
    'Slay the Spire 2 path', 'Where is STS2 installed?',
    'Select the Slay the Spire 2 game folder (e.g. Steam\steamapps\common\Slay the Spire 2).',
    False, '');
  STS2PathPage.Add('');
  STS2PathPage.Values[0] := ExpandConstant('{pf32}\Steam\steamapps\common\Slay the Spire 2');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if PageID = STS2PathPage.ID then
    Result := not WizardIsTaskSelected('installmod')
  else
    Result := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // STS2 v0.99+: mod files live directly in <game>\mods\ (BoberInSpire.dll / .pck / .json)
  if CurPageID = STS2PathPage.ID then
    STS2ModPath := AddBackslash(STS2PathPage.Values[0]) + 'mods\';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppMod: String;
begin
  if CurStep = ssPostInstall then
    if WizardIsTaskSelected('installmod') and (STS2ModPath <> '') then
    begin
      AppMod := ExpandConstant('{app}\Mod\');
      if DirExists(AppMod) then
      begin
        ForceDirectories(STS2ModPath);
        CopyFile(AppMod + 'BoberInSpire.dll', STS2ModPath + 'BoberInSpire.dll', False);
        CopyFile(AppMod + 'BoberInSpire.pck', STS2ModPath + 'BoberInSpire.pck', False);
        if FileExists(AppMod + 'BoberInSpire.json') then
          CopyFile(AppMod + 'BoberInSpire.json', STS2ModPath + 'BoberInSpire.json', False);
      end;
    end;
end;

[UninstallDelete]
Type: dirifempty; Name: "{app}"
