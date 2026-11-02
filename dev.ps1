<#
 Atalhos de desenvolvimento no Windows (PowerShell, na pasta do repositório).
 Uso:  .\dev.ps1 setup | run | test | quality | smoke | build
 Se o PowerShell bloquear scripts:  powershell -ExecutionPolicy Bypass -File .\dev.ps1 test
#>
param([string]$Task = 'help')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Need-Venv { if (-not (Test-Path $py)) { throw 'Rode primeiro:  .\dev.ps1 setup' } }
switch ($Task) {
    'setup'   { & python -m venv .venv; & $py -m pip install --upgrade pip; & $py -m pip install -r requirements.txt }
    'run'     { Need-Venv; & $py app.py }
    'test'    { Need-Venv; $env:QT_QPA_PLATFORM = 'offscreen'; & $py -I -W ignore -m unittest discover -s tests -q }
    'quality' { Need-Venv; $env:QT_QPA_PLATFORM = 'offscreen'; & $py tools\quality_suite.py --only pdf --fast --out quality-report; Write-Host 'Relatório: quality-report\quality-report.md' }
    'smoke'   { Need-Venv; & $py app.py --smoke-test; Write-Host "código de saída: $LASTEXITCODE" }
    'build'   { & powershell -ExecutionPolicy Bypass -File instalador\build_windows.ps1 }
    default   { Write-Host 'uso: .\dev.ps1 setup | run | test | quality | smoke | build' }
}
