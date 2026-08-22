#define MyAppName "橘味儿音乐"
#define MyAppVersion "3.5.0"
#define MyAppExeName "Juweier-Music.exe"

[Setup]
AppId={{A53F12F1-55B4-4B74-A67C-6A28C243A1CE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Juweier Music
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=Juweier_Music_v3.5.0_Setup_x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\assets\novria_app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
AppPublisher=橘味儿音乐
AppPublisherURL=https://db0888.com
AppSupportURL=https://db0888.com
VersionInfoVersion=3.5.0.0
VersionInfoCompany=橘味儿音乐
VersionInfoDescription=橘味儿音乐多轨演奏工作站
VersionInfoProductName=橘味儿音乐
VersionInfoProductVersion=3.5.0

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; PyTorch ships thousands of duplicate third-party licence copies in very deep
; metadata paths. Those exceed the classic Windows path limit during Inno
; compilation. Keep the package's primary licences and omit only that duplicate
; subtree; runtime binaries and the portable ZIP remain unchanged.
Source: "..\dist\Juweier-Music\*"; DestDir: "{app}"; Excludes: "_internal\torch-*.dist-info\licenses\third_party\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
