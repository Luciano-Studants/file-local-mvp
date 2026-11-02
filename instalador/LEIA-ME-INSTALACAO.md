# Arquivo Local — instalação no Windows

> Estado: **pacote experimental**. O instalador e o roteiro de build foram escritos no Linux e **ainda não foram executados no Windows**; a primeira execução real vai mostrar ajustes.

## Para quem vai usar
1. Baixe `Arquivo-Local-<versão>-Setup.exe` (instalador) **ou** o ZIP portátil `Arquivo-Local-<versão>-Windows-x64.zip` (descompacte onde quiser e abra `ArquivoLocal.exe`).
2. O instalador **não pede administrador**: instala na sua pasta de programas (`%LOCALAPPDATA%\Programs\Arquivo Local`). Opções (desligadas por padrão): iniciar com o Windows e item no menu de clique direito.
3. Como o programa ainda não é assinado digitalmente, o Windows SmartScreen pode avisar «O Windows protegeu seu PC». Confira o SHA-256 publicado junto com o arquivo e só então escolha «Mais informações → Executar assim mesmo».
4. Tudo funciona **offline**. O programa nunca envia arquivos; seus originais nunca são alterados nem sobrescritos.
5. Uso: selecione um arquivo no Explorer e **segure Shift** (conversões rápidas) ou aperte **Shift+F9** (ferramentas do arquivo). A bandeja perto do relógio abre o painel.
6. Para **ler texto de imagens (OCR)** é preciso o Tesseract: o pacote traz só os idiomas (português e inglês); o programa `tesseract.exe` precisa estar na pasta `tesseract` ao lado do aplicativo ou instalado no Windows (por exemplo, o instalador de UB Mannheim).
7. Para **remover fundo** com mais precisão, coloque `u2net.onnx` (176 MB, SHA-256 em `models\LEIA-ME.md`) na pasta `models`; o modelo leve já vem incluído.
8. Desinstalar: «Configurações → Aplicativos» (ou o atalho «Desinstalar» no Menu Iniciar). Suas configurações em `%LOCALAPPDATA%` ficam; apague a pasta se quiser.

## Para quem vai gerar o pacote
Python 3.12 64 bits, e na pasta `Desktop`:

    powershell -ExecutionPolicy Bypass -File instalador\build_windows.ps1

O roteiro cria um ambiente isolado, instala as dependências, roda os testes e a suíte de qualidade, gera o PyInstaller, confere o ZIP e, se o Inno Setup 6 estiver instalado, cria o instalador. **Pendências conhecidas:** assinatura de código, ícone `.ico`, licenças das DLLs do Tesseract para Windows e termos dos pesos do U²-Net (revisão jurídica antes de distribuir publicamente).
