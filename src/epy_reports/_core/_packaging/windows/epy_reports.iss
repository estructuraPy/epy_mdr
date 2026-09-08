; Inno Setup script for epy_reports
;
; Build from the project root AFTER running `python build.py`:
;   ISCC.exe src\epy_reports\_core\_packaging\windows\epy_reports.iss
;
; Output: dist\epy_reports-setup-<AppVersion>.exe
; NOTE: AppVersion below must match src/epy_reports/__init__.py __version__
; (single source); bump both together on release.
;
; Design decisions:
;   - PrivilegesRequired=lowest  -> per-user install; no UAC prompt.
;     This is intentional: the file-association backend (winreg_assoc.py)
;     writes to HKCU, which requires the *installing* user's context.
;     A per-user install keeps the app directory, the registry work, and
;     the user account all consistent.
;   - DefaultDirName={localappdata}\Programs\epy_reports  -> conventional
;     location for user-scoped apps on Windows 10/11.
;   - Windows 10/11 UserChoice limitation:
;     Microsoft signs the UserChoice key with an undocumented HMAC that
;     only Windows itself can produce.  No installer or third-party app
;     can silently set a file-type default since Windows 8.  The
;     --as-default flag in winreg_assoc.py writes the *legacy* handler
;     and the Capabilities tree so the app appears in "Settings > Default
;     apps".  The user must open that Settings page and click "Set as
;     default" (or use the "Open with > Always use this app" dialog) for
;     the change to take effect in the UserChoice.  The optional final
;     checkbox below launches "ms-settings:defaultapps" as a convenience.

#define AppName "epy_reports"
#define AppVersion "0.7.0"
#define AppPublisher "Ing. Angel Navarro-Mora M.Sc."
#define AppURL "https://github.com/estructuraPy/epy_reports"
#define AppId "{{D9B4E1C7-2A6F-4B83-9E5D-7C1A0F3B6E24}"
#define AppExeName "epy_reports.exe"
; Paths are relative to the location of this .iss file
; (src\epy_reports\_core\_packaging\windows\).
#define DistDir "..\..\..\..\..\dist\epy_reports"
#define IconFile "..\assets_build\epy_reports.ico"
#define OutputDir "..\..\..\..\..\dist"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir={#OutputDir}
OutputBaseFilename=epy_reports-setup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Do not write to HKLM — keep this install entirely per-user.
UsePreviousGroup=yes
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "opendefaults"; Description: "Open Windows Default Apps settings after install (to confirm epy_reports as default)"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
; Package the entire PyInstaller onedir output.
; The {#DistDir} path is relative to the location of this .iss file.
Source: "{#DistDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; auto* constants resolve to the per-user folders when PrivilegesRequired=lowest.
; Never use common* here: writing all-users shortcuts without elevation fails
; with IPersistFile::Save 0x80070005 (access denied).
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Register file associations in HKCU immediately after installation.
; --as-default writes the legacy default handler *and* the Capabilities
; tree so epy_reports appears in Settings > Default apps.
; runascurrentuser is the default for PrivilegesRequired=lowest, but
; listed explicitly for clarity.
Filename: "{app}\{#AppExeName}"; Parameters: "--register --as-default"; \
    Flags: runascurrentuser nowait postinstall skipifsilent; \
    Description: "Register epy_reports for .md / .markdown / .qmd files"

; Optional: open Windows Default Apps settings so the user can confirm
; epy_reports as the default handler.  Unchecked by default.
; NOTE: This is the ONLY reliable way to change the UserChoice default
; on Windows 10/11 — the user must click "Set as default" themselves.
Filename: "{app}\{#AppExeName}"; Parameters: "--set-default"; \
    Flags: runascurrentuser nowait postinstall skipifsilent unchecked; \
    Description: "Open Windows Default Apps settings (confirm epy_reports as default)"; \
    Tasks: opendefaults

[UninstallRun]
; Remove registry keys when the user uninstalls.
Filename: "{app}\{#AppExeName}"; Parameters: "--unregister"; \
    RunOnceId: "UnregisterFileAssoc"; \
    Flags: runascurrentuser nowait

[Code]
// Additional Inno Setup Pascal scripting can go here if needed.
// For example: detect existing installation, migrate settings, etc.
