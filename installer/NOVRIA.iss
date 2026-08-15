#define MyAppName "NOVRIA AI Music Studio"
#define MyAppVersion "0.3.2"
#define MyAppExeName "NOVRIA-AI-Music-Studio.exe"

[Setup]
AppId={{A53F12F1-55B4-4B74-A67C-6A28C243A1CE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\NOVRIA AI Music Studio
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=NOVRIA_AI_Music_Studio_v0.3.2_Setup_x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist\NOVRIA-AI-Music-Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
