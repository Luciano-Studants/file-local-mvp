<#
 Gera o pacote do Arquivo Local para Windows: testes, suíte de qualidade, PyInstaller, verificação e (se o Inno Setup estiver instalado) o instalador.
 Uso (PowerShell, na pasta Desktop):   powershell -ExecutionPolicy Bypass -File instalador\build_windows.ps1
 Requisitos: Windows 10/11 64 bits, Python 3.12 64 bits (python.org), internet só para o pip. Opcional: Inno Setup 6 e a pasta «tesseract» ao lado do package.py.
 Este roteiro foi escrito no Linux e NUNCA foi executado no Windows: se algum passo falhar, o erro aparece e nada é publicado.
#>
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step 'Conferindo o Python'
$version = & python -c "import sys; print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], 64 if sys.maxsize > 2**32 else 32))"
if ($version -ne '3.12 64') { throw "É preciso Python 3.12 de 64 bits; encontrado: $version" }

Step 'Criando o ambiente .venv-build e instalando as dependências'
if (-not (Test-Path .venv-build)) { & python -m venv .venv-build }
$py = Join-Path (Get-Location) '.venv-build\Scripts\python.exe'
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'pip falhou' }

Step 'Rodando os testes automáticos'
& $py -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Há testes falhando; o pacote NÃO foi gerado.' }

Step 'Rodando a suíte de qualidade de imagem (rápida)'
& $py tools\quality_suite.py --fast --out dist\relatorio-qualidade
if ($LASTEXITCODE -ne 0) { throw 'A suíte de qualidade reprovou; veja dist\relatorio-qualidade\quality-report.md' }

Step 'Gerando o pacote com PyInstaller'
& $py package.py
if ($LASTEXITCODE -ne 0) { throw 'package.py falhou' }

Step 'Verificando o ZIP'
& $py verify_package.py
if ($LASTEXITCODE -ne 0) { throw 'verify_package.py falhou' }

Step 'Teste de fumaça do programa empacotado'
& $py smoke_package.py
if ($LASTEXITCODE -ne 0) { throw 'smoke_package.py falhou' }

Step 'Criando o instalador (Inno Setup), se existir'
$iscc = @("$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    $appVersion = (& $py -c "from engine import VERSION; print(VERSION)").Trim()
    & $iscc "/DAppVersion=$appVersion" instalador\ArquivoLocal.iss
    if ($LASTEXITCODE -ne 0) { throw 'ISCC falhou' }
} else {
    Write-Host 'Inno Setup 6 não encontrado: só o ZIP portátil foi gerado (dist\*.zip).' -ForegroundColor Yellow
}

Write-Host "`nPronto. Arquivos em dist\. Teste a instalação e a desinstalação num Windows limpo antes de distribuir." -ForegroundColor Green
