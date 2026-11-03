<#
 Copia o Tesseract instalado (Windows) para a pasta «tesseract» ao lado do package.py, para entrar no pacote.
 Uso:  powershell -ExecutionPolicy Bypass -File tools\stage_tesseract.ps1 [-Source "C:\Program Files\Tesseract-OCR"]
 Copia só o executável, as DLLs e as licenças; os dados de idioma do app ficam em tessdata\ (eng, por, pdf.ttf).
 Registra a lista de arquivos em tesseract\COPIADOS.txt (revisão jurídica das DLLs: ver docs\DEPENDENCIAS.md).
#>
param([string]$Source = 'C:\Program Files\Tesseract-OCR')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root 'tesseract'
if (-not (Test-Path (Join-Path $Source 'tesseract.exe'))) { throw "tesseract.exe não encontrado em $Source" }
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory $dest | Out-Null
Get-ChildItem $Source -File | Where-Object { $_.Extension -in '.exe', '.dll', '.txt', '.md' } | Where-Object { $_.Name -notmatch '^(unins|tesseract-uninst)' } | Copy-Item -Destination $dest
Get-ChildItem $dest -File | Sort-Object Name | ForEach-Object { '{0}  {1}' -f $_.Name, (Get-FileHash $_.FullName -Algorithm SHA256).Hash } | Set-Content (Join-Path $dest 'COPIADOS.txt') -Encoding utf8
& (Join-Path $dest 'tesseract.exe') --version
Write-Host "Tesseract preparado em $dest ($((Get-ChildItem $dest -File).Count) arquivos)"
