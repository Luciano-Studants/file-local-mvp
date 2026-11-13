<#
 Atalhos de desenvolvimento no Windows (PowerShell, na pasta do repositório).
 Uso:  .\dev.ps1 setup | deps | doctor | run | test | quality | smoke | build
 Se o PowerShell bloquear scripts:  powershell -ExecutionPolicy Bypass -File .\dev.ps1 test
#>
param([string]$Task = 'help')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Need-Venv { if (-not (Test-Path $py)) { throw 'Rode primeiro:  .\dev.ps1 setup' } }
switch ($Task) {
    'setup'   { if (-not (Test-Path $py)) { & python -m venv .venv }; & $py -m pip install --upgrade pip; & $py -m pip install -r requirements.txt -r requirements-dev.txt; & $py tools\doctor.py }
    'deps'    { & powershell -ExecutionPolicy Bypass -File tools\baixar_dependencias.ps1 }
    'doctor'  { Need-Venv; & $py tools\doctor.py }
    'run'     { Need-Venv; & $py app.py }
    'test'    { Need-Venv; $env:QT_QPA_PLATFORM = 'offscreen'; & $py -I -W ignore -m unittest discover -s tests -q }
    'quality' { Need-Venv; $env:QT_QPA_PLATFORM = 'offscreen'; & $py tools\quality_suite.py --only pdf --fast --out quality-report; & $py tools\quality_suite.py --only audio --fast --out quality-report-audio; Write-Host 'Relatórios: quality-report\quality-report.md e quality-report-audio\quality-report.md' }
    'smoke'   { Need-Venv; & $py app.py --smoke-test; Write-Host "código de saída: $LASTEXITCODE" }
    'build'   { & powershell -ExecutionPolicy Bypass -File instalador\build_windows.ps1 }
    default   { Write-Host 'uso: .\dev.ps1 setup | deps | doctor | run | test | quality | smoke | build' }
}
