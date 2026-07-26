#ifndef Version
  #define Version "1.2.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\build\installer-payload"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{D20137F5-355D-4CC1-AD76-EC74C0FB4D4A}
AppName=HCQ
AppVerName=HCQ {#Version}
AppVersion={#Version}
AppPublisher=Taiyo1031
AppPublisherURL=https://github.com/Taiyo1031/HCQ
AppSupportURL=https://github.com/Taiyo1031/HCQ/issues
AppUpdatesURL=https://github.com/Taiyo1031/HCQ/releases
DefaultDirName={localappdata}\Programs\HCQ
DefaultGroupName=HCQ
DisableProgramGroupPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=HCQ-Setup-{#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayName=HCQ {#Version}
UsePreviousAppDir=yes
SetupLogging=yes
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "hcq-install.json"; Flags: dontcopy

[Icons]
Name: "{group}\HCQ Documentation"; Filename: "https://github.com/Taiyo1031/HCQ#main-workflows"
Name: "{group}\Uninstall HCQ"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  DetectedVersions: TStringList;
  RegisteredPackages: TStringList;
  SkippedPackages: TStringList;
  MigrationJournals: TStringList;
  RemoveUserData: Boolean;

function IsVersionCharacter(C: Char): Boolean;
begin
  Result := ((C >= '0') and (C <= '9')) or (C = '.');
end;

function NormalizeHoudiniVersion(Value: String): String;
var
  I, Dots: Integer;
  Candidate: String;
begin
  Candidate := '';
  Dots := 0;
  for I := 1 to Length(Value) do
  begin
    if IsVersionCharacter(Value[I]) then
    begin
      if Value[I] = '.' then
      begin
        Dots := Dots + 1;
        if Dots >= 2 then
          Break;
      end;
      Candidate := Candidate + Value[I];
    end
    else if Candidate <> '' then
      Break;
  end;
  if (Pos('21.', Candidate) = 1) and (Length(Candidate) >= 4) then
    Result := Candidate
  else
    Result := '';
end;

procedure AddVersion(Value: String);
var
  Version: String;
begin
  Version := NormalizeHoudiniVersion(Value);
  if (Version <> '') and (DetectedVersions.IndexOf(Version) < 0) then
    DetectedVersions.Add(Version);
end;

procedure DetectRegistryVersions(RootKey: Integer);
var
  Names: TArrayOfString;
  I: Integer;
begin
  if RegGetSubkeyNames(
    RootKey,
    'SOFTWARE\Side Effects Software',
    Names
  ) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if Pos('Houdini 21.', Names[I]) = 1 then
        AddVersion(Names[I]);
end;

procedure DetectDirectoryVersions(BasePath: String);
var
  FindRec: TFindRec;
begin
  if FindFirst(AddBackslash(BasePath) + 'houdini21.*', FindRec) then
  begin
    try
      repeat
        if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          AddVersion(FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function HCQUserDocs: String;
begin
  Result := ExpandConstant('{param:HCQUSERDOCS|{userdocs}}');
end;

function HCQUserProfile: String;
begin
  Result := ExpandConstant('{param:HCQUSERPROFILE|{userprofile}}');
end;

function HoudiniIsRunning: Boolean;
var
  ResultCode: Integer;
  OutputPath, Command: String;
  Output: AnsiString;
begin
  OutputPath := ExpandConstant('{tmp}\hcq-tasklist.txt');
  Command := '/C tasklist /FO CSV /NH > "' + OutputPath + '"';
  Result := False;
  if Exec(
    ExpandConstant('{cmd}'),
    Command,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  if LoadStringFromFile(OutputPath, Output) then
  begin
    Output := Lowercase(Output);
    Result :=
      (Pos('"houdini.exe"', Output) > 0) or
      (Pos('"houdinifx.exe"', Output) > 0) or
      (Pos('"houdinicore.exe"', Output) > 0) or
      (Pos('"hmaster.exe"', Output) > 0) or
      (Pos('"hmaster-ng.exe"', Output) > 0) or
      (Pos('"hindie.exe"', Output) > 0) or
      (Pos('"happrentice.exe"', Output) > 0) or
      (Pos('"hython.exe"', Output) > 0) or
      (Pos('"hython3.11.exe"', Output) > 0) or
      (Pos('"hbatch.exe"', Output) > 0);
  end;
  DeleteFile(OutputPath);
end;

function PackageCanBeReplaced(Target: String): Boolean;
var
  Existing: AnsiString;
begin
  if not FileExists(Target) then
  begin
    Result := True;
    Exit;
  end;
  if not LoadStringFromFile(Target, Existing) then
  begin
    Result := False;
    Exit;
  end;
  Result :=
    (Pos('$HOUDINI_PACKAGE_PATH/../HCQ', Existing) > 0) or
    (Pos('$LOCALAPPDATA/Programs/HCQ', Existing) > 0);
end;

procedure RegisterPackage(PrefRoot, PackageSource: String);
var
  PackageDir, Target: String;
begin
  PackageDir := AddBackslash(PrefRoot) + 'packages';
  Target := AddBackslash(PackageDir) + 'hcq.json';
  if not PackageCanBeReplaced(Target) then
  begin
    SkippedPackages.Add(Target);
    Exit;
  end;
  ForceDirectories(PackageDir);
  if FileExists(Target) then
    if not FileCopy(Target, Target + '.hcq-pre-1.2.0.bak', False) then
      RaiseException('Could not back up the existing HCQ package: ' + Target);
  if not FileCopy(PackageSource, Target, False) then
    RaiseException('Could not register HCQ with Houdini: ' + Target);
  RegisteredPackages.Add(Target);
end;

procedure RollbackRegisteredPackages;
var
  I: Integer;
  Target, Backup: String;
begin
  for I := RegisteredPackages.Count - 1 downto 0 do
  begin
    Target := RegisteredPackages[I];
    Backup := Target + '.hcq-pre-1.2.0.bak';
    if FileExists(Backup) then
    begin
      FileCopy(Backup, Target, False);
      DeleteFile(Backup);
    end
    else
      DeleteFile(Target);
  end;
  RegisteredPackages.Clear;
end;

procedure FinalizePackageBackups;
var
  I: Integer;
begin
  for I := 0 to RegisteredPackages.Count - 1 do
    DeleteFile(RegisteredPackages[I] + '.hcq-pre-1.2.0.bak');
end;

function FindHoudiniPythonInRoot(RootKey: Integer): String;
var
  Names: TArrayOfString;
  I: Integer;
  InstallPath, Candidate: String;
begin
  Result := '';
  if RegGetSubkeyNames(
    RootKey,
    'SOFTWARE\Side Effects Software',
    Names
  ) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if (Pos('Houdini 21.', Names[I]) = 1) and RegQueryStringValue(
        RootKey,
        'SOFTWARE\Side Effects Software\' + Names[I],
        'InstallPath',
        InstallPath
      ) then
      begin
        Candidate := AddBackslash(InstallPath) + 'python311\python.exe';
        if FileExists(Candidate) then
        begin
          Result := Candidate;
          Exit;
        end;
      end;
end;

function FindHoudiniPython: String;
begin
  Result := FindHoudiniPythonInRoot(HKLM64);
  if Result = '' then
    Result := FindHoudiniPythonInRoot(HKLM32);
  if Result = '' then
    Result := FindHoudiniPythonInRoot(HKCU);
end;

procedure MigrateLegacyRoot(PrefRoot, Python, Helper: String);
var
  LegacyRoot, BackupRoot, Journal, Parameters: String;
  ResultCode: Integer;
begin
  LegacyRoot := AddBackslash(PrefRoot) + 'HCQ';
  if not FileExists(AddBackslash(LegacyRoot) + 'HCQ_MANIFEST.json') then
    Exit;
  if Python = '' then
    RaiseException(
      'HCQ found a legacy installation but could not locate Houdini Python.'
    );
  BackupRoot := ExpandConstant('{localappdata}\HCQ\migration-backups');
  Journal := ExpandConstant('{tmp}\hcq-migration-') +
    IntToStr(MigrationJournals.Count) + '.json';
  Parameters :=
    '"' + Helper + '" migrate --preference-root "' + PrefRoot +
    '" --backup-root "' + BackupRoot + '" --journal "' + Journal + '"';
  if not Exec(
    Python,
    Parameters,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) or (ResultCode <> 0) then
    RaiseException('Could not migrate the legacy HCQ installation: ' + PrefRoot);
  if FileExists(Journal) then
    MigrationJournals.Add(Journal);
end;

procedure RollbackMigrations(Python, Helper: String);
var
  I, ResultCode: Integer;
  Parameters: String;
begin
  for I := MigrationJournals.Count - 1 downto 0 do
  begin
    Parameters :=
      '"' + Helper + '" rollback --journal "' +
      MigrationJournals[I] + '"';
    Exec(
      Python,
      Parameters,
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    );
  end;
  MigrationJournals.Clear;
end;

procedure InstallForDetectedVersions;
var
  I: Integer;
  Version, UserDocsPref, UserProfilePref, PackageSource: String;
  Python, Helper, ErrorMessage: String;
begin
  ExtractTemporaryFile('hcq-install.json');
  PackageSource := ExpandConstant('{tmp}\hcq-install.json');
  Python := FindHoudiniPython();
  Helper := ExpandConstant('{app}\install_tools\hcq_installer_helper.py');
  try
    for I := 0 to DetectedVersions.Count - 1 do
    begin
      Version := DetectedVersions[I];
      UserDocsPref := AddBackslash(HCQUserDocs) + 'houdini' + Version;
      UserProfilePref := AddBackslash(HCQUserProfile) + 'houdini' + Version;
      MigrateLegacyRoot(UserDocsPref, Python, Helper);
      if CompareText(UserProfilePref, UserDocsPref) <> 0 then
        MigrateLegacyRoot(UserProfilePref, Python, Helper);
      RegisterPackage(UserDocsPref, PackageSource);
      if CompareText(UserProfilePref, UserDocsPref) <> 0 then
        RegisterPackage(UserProfilePref, PackageSource);
    end;
    RegisteredPackages.SaveToFile(
      ExpandConstant('{app}\registered_packages.txt')
    );
  except
    ErrorMessage := GetExceptionMessage;
    RollbackRegisteredPackages;
    RollbackMigrations(Python, Helper);
    RaiseException(ErrorMessage);
  end;
  FinalizePackageBackups;
end;

procedure InitializeWizard;
begin
  DetectedVersions := TStringList.Create;
  RegisteredPackages := TStringList.Create;
  SkippedPackages := TStringList.Create;
  MigrationJournals := TStringList.Create;
  DetectRegistryVersions(HKLM64);
  DetectRegistryVersions(HKLM32);
  DetectRegistryVersions(HKCU);
  DetectDirectoryVersions(HCQUserDocs);
  DetectDirectoryVersions(HCQUserProfile);
  if DetectedVersions.Count = 0 then
    DetectedVersions.Add('21.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if HoudiniIsRunning then
    Result :=
      'Close Houdini, hython, and hbatch before installing HCQ. ' +
      'HCQ will not force-close a session because it may contain unsaved work.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  MessageText: String;
begin
  if CurStep = ssPostInstall then
  begin
    InstallForDetectedVersions;
    if SkippedPackages.Count > 0 then
    begin
      MessageText :=
        'HCQ kept custom package registrations unchanged:' + #13#10 +
        SkippedPackages.Text + #13#10 +
        'Update those files manually if they belong to a development checkout.';
      MsgBox(MessageText, mbInformation, MB_OK);
    end;
  end;
end;

function InitializeUninstall: Boolean;
begin
  RemoveUserData :=
    SuppressibleMsgBox(
      'Remove HCQ user data too?' + #13#10 +
      'Choose No to keep settings, queues, history, logs, and recovery data.',
      mbConfirmation,
      MB_YESNO,
      IDNO
    ) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Packages: TStringList;
  I: Integer;
  Target, PrefRoot, DataRoot: String;
  CurrentText, OwnedText: AnsiString;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Packages := TStringList.Create;
  try
    if FileExists(ExpandConstant('{app}\registered_packages.txt')) then
      Packages.LoadFromFile(ExpandConstant('{app}\registered_packages.txt'));
    if not LoadStringFromFile(
      ExpandConstant('{app}\install_tools\hcq-install.json'),
      OwnedText
    ) then
      OwnedText := '';
    for I := 0 to Packages.Count - 1 do
    begin
      Target := Packages[I];
      if FileExists(Target) and LoadStringFromFile(Target, CurrentText) and
        (CurrentText = OwnedText) then
        DeleteFile(Target);
      if RemoveUserData then
      begin
        PrefRoot := ExtractFileDir(ExtractFileDir(Target));
        DataRoot := AddBackslash(PrefRoot) + 'HCQ';
        DelTree(DataRoot, True, True, True);
      end;
    end;
    if RemoveUserData then
      DelTree(
        ExpandConstant('{localappdata}\HCQ\migration-backups'),
        True,
        True,
        True
      );
  finally
    Packages.Free;
  end;
end;
