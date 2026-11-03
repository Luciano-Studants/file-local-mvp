; Instalador do Arquivo Local (Inno Setup 6) — instala só para o usuário atual, SEM administrador.
; Compilar:  ISCC /DAppVersion=0.9.26 instalador\ArquivoLocal.iss   (build_windows.ps1 faz isso). Entrada: dist\ArquivoLocal (saída do package.py).
; NUNCA foi compilado nem executado no Windows real (feito no Linux): rode build_windows.ps1 e teste a instalação, o atalho e a desinstalação antes de distribuir.
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{6F1B2E1C-3D55-4C9E-9A57-5B1E7A0C42D1}
AppName=Arquivo Local
AppVersion={#AppVersion}
AppPublisher=Arquivo Local (projeto de código aberto, GPL-3.0)
DefaultDirName={autopf}\Arquivo Local
DefaultGroupName=Arquivo Local
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=Arquivo-Local-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Arquivo Local
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "startup"; Description: "Iniciar o Arquivo Local junto com o Windows (fica na bandeja, perto do relógio)"; GroupDescription: "Opções:"; Flags: unchecked
Name: "contextmenu"; Description: "Adicionar «Arquivo Local» ao menu de clique direito de imagens e PDFs (pode ser removido em Atalhos)"; GroupDescription: "Opções:"; Flags: unchecked

[Files]
Source: "..\dist\ArquivoLocal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Arquivo Local"; Filename: "{app}\ArquivoLocal.exe"
Name: "{group}\Desinstalar Arquivo Local"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ArquivoLocal"; ValueData: """{app}\ArquivoLocal.exe"""; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\image\shell\ArquivoLocal"; ValueType: string; ValueName: ""; ValueData: "Arquivo Local"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\image\shell\ArquivoLocal\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ArquivoLocal.exe"" --send-to ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\ArquivoLocal"; ValueType: string; ValueName: ""; ValueData: "Arquivo Local"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\ArquivoLocal\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ArquivoLocal.exe"" --send-to ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\ArquivoLocal.exe"; Description: "Abrir o Arquivo Local agora"; Flags: nowait postinstall skipifsilent

; Os arquivos que o aplicativo cria (configurações em %LOCALAPPDATA%) NÃO são apagados: a desinstalação mexe só na pasta do programa e nas chaves acima.
