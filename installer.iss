; BoberInSpire installer - Inno Setup script
; Prerequisite: run build.bat first so dist\BoberInSpire exists.

#define MyAppName "BoberInSpire"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "BoberInSpire"
#define MyAppURL "https://github.com/S0ul3r/BoberInSpire"
#define MyAppExeName "BoberInSpire.exe"

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
Name: "installmod"; Description: "Copy mod to Slay the Spire 2"; GroupDescription: "Mod installation:"; Flags: checked

[Files]
; Overlay exe + runtime (PyInstaller output)
Source: "dist\BoberInSpire\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BoberInSpire Overlay"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BoberInSpire Overlay"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  STS2PathPage: TInputDirWizardPage;
  STS2ModPath: String;

{ ── Auto-detect STS2 install by parsing Steam libraryfolders.vdf ── }
function FindSTS2GameDir: String;
var
  SteamRoot, VdfPath, VdfText, LibPath, Candidate: String;
  Lines: TArrayOfString;
  I, P: Integer;
begin
  Result := '';
  SteamRoot := ExpandConstant('{pf32}\Steam');
  VdfPath := SteamRoot + '\steamapps\libraryfolders.vdf';

  { Check default Steam location first }
  Candidate := SteamRoot + '\steamapps\common\Slay the Spire 2';
  if DirExists(Candidate) then begin
    Result := Candidate;
    Exit;
  end;

  { Parse VDF for additional library folders }
  if not FileExists(VdfPath) then Exit;
  if not LoadStringsFromFile(VdfPath, Lines) then Exit;

  for I := 0 to GetArrayLength(Lines) - 1 do begin
    P := Pos('"path"', Lines[I]);
    if P > 0 then begin
      { Extract path value between quotes: "path"		"C:\SteamLibrary" }
      LibPath := Lines[I];
      { Find the second pair of quotes }
      Delete(LibPath, 1, P + 5);  { remove everything up to and including "path" }
      P := Pos('"', LibPath);
      if P > 0 then begin
        Delete(LibPath, 1, P);  { remove up to opening quote }
        P := Pos('"', LibPath);
        if P > 0 then begin
          LibPath := Copy(LibPath, 1, P - 1);
          Candidate := LibPath + '\steamapps\common\Slay the Spire 2';
          if DirExists(Candidate) then begin
            Result := Candidate;
            Exit;
          end;
        end;
      end;
    end;
  end;
end;

procedure InitializeWizard;
var
  DetectedPath: String;
begin
  STS2PathPage := CreateInputDirPage(wpSelectTasks,
    'Slay the Spire 2 path', 'Where is STS2 installed?',
    'The game folder was auto-detected. Change it only if the path below is wrong.',
    False, '');
  STS2PathPage.Add('');

  { Auto-detect game path }
  DetectedPath := FindSTS2GameDir;
  if DetectedPath <> '' then
    STS2PathPage.Values[0] := DetectedPath
  else
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
  if CurPageID = STS2PathPage.ID then
    STS2ModPath := AddBackslash(STS2PathPage.Values[0]) + 'mods\';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  { Validate game path when user clicks Next on the STS2 path page }
  if CurPageID = STS2PathPage.ID then begin
    if not FileExists(AddBackslash(STS2PathPage.Values[0]) + 'SlayTheSpire2.pck') then begin
      if MsgBox('SlayTheSpire2.pck not found in the selected folder.' + #13#10 +
                'This does not look like a valid Slay the Spire 2 installation.' + #13#10#13#10 +
                'Continue anyway?', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppMod: String;
begin
  if CurStep = ssPostInstall then
    if WizardIsTaskSelected('installmod') and (STS2ModPath <> '') then begin
      AppMod := ExpandConstant('{app}\Mod\');
      if DirExists(AppMod) then begin
        ForceDirectories(STS2ModPath);
        FileCopy(AppMod + 'BoberInSpire.dll', STS2ModPath + 'BoberInSpire.dll', False);
        FileCopy(AppMod + 'BoberInSpire.pck', STS2ModPath + 'BoberInSpire.pck', False);
        if FileExists(AppMod + 'BoberInSpire.json') then
          FileCopy(AppMod + 'BoberInSpire.json', STS2ModPath + 'BoberInSpire.json', False);
      end;
    end;
end;

[UninstallDelete]
Type: dirifempty; Name: "{app}"
