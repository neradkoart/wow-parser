#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{B75A9F49-2E03-4F09-B6F2-4F7E4A2B8B89}
AppName=Wow Parser
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Wow Parser
DefaultGroupName=Wow Parser
OutputDir=dist
OutputBaseFilename=wow-parser-windows-installer-v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\Wow Parser\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Wow Parser"; Filename: "{app}\Wow Parser.exe"
Name: "{autodesktop}\Wow Parser"; Filename: "{app}\Wow Parser.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные задачи:"

[Run]
Filename: "{app}\Wow Parser.exe"; Description: "Запустить Wow Parser"; Flags: nowait postinstall skipifsilent
