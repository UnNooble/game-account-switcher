; Inno Setup script: turns dist\ValorantSwitcher\ into one GameAccountSwitcher-Setup-x.y.z.exe
; Built automatically by Build-Installer.cmd (or the GitHub workflow). Don't run by hand unless you want to.

#ifndef AppVersion
  #define AppVersion "3.9.2"
#endif
#define AppName "Game Account Switcher"
#define AppExe "ValorantSwitcher.exe"

[Setup]
AppId={{8C1B2E7A-4F7D-4C1E-9A55-3B0E5C2D9F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=UnNooble (unofficial; not made or endorsed by Riot Games)
; Installs for the current Windows user only: no administrator prompt.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Game Account Switcher
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
DisableWelcomePage=no
DisableFinishedPage=no
OutputDir=..\dist
OutputBaseFilename=GameAccountSwitcher-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Shows the terms and asks the user to accept before installing.
LicenseFile=..\TERMS.txt
; Closes a running copy of the app before updating or uninstalling.
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\ValorantSwitcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\TERMS.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Older versions were named "Valorant Account Switcher": remove their shortcuts so updates don't leave duplicates.
Type: files; Name: "{autodesktop}\Valorant Account Switcher.lnk"
Type: files; Name: "{autoprograms}\Valorant Account Switcher.lnk"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[Code]
// On uninstall, ask whether saved accounts should be removed too. Default: keep them,
// so reinstalling or updating never loses anyone's accounts.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if (CurUninstallStep = usUninstall) and not UninstallSilent then
    if MsgBox('Also delete your saved accounts, logins and passwords from this PC?' + #13#10 + #13#10 +
              'Choose No if you plan to reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      Exec(ExpandConstant('{app}\{#AppExe}'), '--forget-everything', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;
