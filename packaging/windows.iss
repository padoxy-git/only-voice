#ifndef AppVersion
#define AppVersion "0.2.0"
#endif
[Setup]
AppId={{C4413A62-72BE-4E34-A4F4-E302DD914DA6}
AppName=Only Voice
AppVersion={#AppVersion}
AppPublisher=Pablo Dorado
AppPublisherURL=https://github.com/padoxy-git/only-voice
DefaultDirName={localappdata}\Programs\Only Voice
DefaultGroupName=Only Voice
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=OnlyVoice-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\OnlyVoice.exe
CloseApplications=yes
[Files]
Source: "..\dist\OnlyVoice\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Only Voice"; Filename: "{app}\OnlyVoice.exe"
[Run]
Filename: "{app}\OnlyVoice.exe"; Description: "Iniciar Only Voice en la bandeja"; Flags: nowait postinstall skipifsilent
