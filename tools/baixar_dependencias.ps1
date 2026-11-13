<#
 Baixa os programas externos que o Arquivo Local usa e coloca nas pastas certas (nada disso vai para o Git).
 Uso:  powershell -ExecutionPolicy Bypass -File tools\baixar_dependencias.ps1 [-Somente ffmpeg|tesseract|todos] [-FFmpegUrl <zip>] [-FFmpegSha256 <hash>]
   ffmpeg    : baixa um build LGPL do FFmpeg (BtbN/FFmpeg-Builds, win64-lgpl) para a pasta «ffmpeg\», confere o SHA-256 e a licença.
   tesseract : instala o Tesseract (winget, UB-Mannheim) se faltar e copia para «tesseract\» (tools\stage_tesseract.ps1). Os dados eng/por já estão em tessdata\.
 Para fixar a versão (recomendado para release): preencha tools\dependencias.json (url e sha256 do FFmpeg). Sem isso, usa o build mais recente e só confere o checksum publicado junto.
 O que for baixado é registrado em ffmpeg\ORIGEM.txt (url, SHA-256, data, versão).
#>
param([ValidateSet('todos','ffmpeg','tesseract')][string]$Somente = 'todos', [string]$FFmpegUrl = '', [string]$FFmpegSha256 = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pin = Join-Path $PSScriptRoot 'dependencias.json'
$cfg = if (Test-Path $pin) { Get-Content $pin -Raw | ConvertFrom-Json } else { $null }
if (-not $FFmpegUrl -and $cfg -and $cfg.ffmpeg.url) { $FFmpegUrl = $cfg.ffmpeg.url }
if (-not $FFmpegSha256 -and $cfg -and $cfg.ffmpeg.sha256) { $FFmpegSha256 = $cfg.ffmpeg.sha256 }
$latest = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/'
function Get-Hash256($path) { (Get-FileHash $path -Algorithm SHA256).Hash.ToLower() }

function Install-FFmpeg {
    $dest = Join-Path $root 'ffmpeg'
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('arquivo-local-ffmpeg-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        $pinned = [bool]$FFmpegSha256
        $url = if ($FFmpegUrl) { $FFmpegUrl } else { $latest + 'ffmpeg-master-latest-win64-lgpl.zip' }
        if ($url -notmatch '^https://github\.com/') { throw 'Só aceito URL https://github.com/ para o FFmpeg.' }
        $zip = Join-Path $tmp 'ffmpeg.zip'
        Write-Host "Baixando $url ..."
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        $hash = Get-Hash256 $zip
        if ($pinned) {
            if ($hash -ne $FFmpegSha256.ToLower()) { throw "SHA-256 diferente do fixado (esperado $FFmpegSha256, obtido $hash). Nada foi instalado." }
            Write-Host 'SHA-256 confere com o valor fixado.'
        } else {
            $sums = Invoke-WebRequest -Uri ($url.Substring(0, $url.LastIndexOf('/') + 1) + 'checksums.sha256') -UseBasicParsing
            $line = ($sums.Content -split "`n") | Where-Object { $_ -match [regex]::Escape((Split-Path $url -Leaf)) } | Select-Object -First 1
            if (-not $line) { throw 'Não achei o checksum publicado para este arquivo; fixe o SHA-256 em tools\dependencias.json.' }
            if ($hash -ne ($line -split '\s+')[0].ToLower()) { throw 'SHA-256 não confere com o publicado. Nada foi instalado.' }
            Write-Host "AVISO: versão não fixada; SHA-256 $hash. Para release, copie-o para tools\dependencias.json."
        }
        $ext = Join-Path $tmp 'x'
        Expand-Archive $zip $ext
        $bin = Get-ChildItem $ext -Recurse -Filter ffmpeg.exe | Select-Object -First 1
        if (-not $bin) { throw 'ffmpeg.exe não está no zip.' }
        $src = Split-Path -Parent (Split-Path -Parent $bin.FullName)
        $banner = & $bin.FullName -hide_banner -version | Out-String
        if ($banner -match '--enable-(gpl|nonfree)') { throw 'Este FFmpeg é GPL/nonfree; o app só aceita build LGPL. Nada foi instalado.' }
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        New-Item -ItemType Directory $dest | Out-Null
        Copy-Item (Join-Path $src 'bin\*') $dest
        Get-ChildItem $src -File | Where-Object { $_.Name -match 'LICENSE|COPYING|README' } | Copy-Item -Destination $dest
        @("url: $url", "sha256: $hash", "data: $(Get-Date -Format s)", ($banner -split "`n")[0].Trim()) | Set-Content (Join-Path $dest 'ORIGEM.txt') -Encoding UTF8
        Write-Host "FFmpeg instalado em $dest"
    } finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}

function Install-Tesseract {
    $exe = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if (-not (Test-Path $exe)) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget não encontrado; instale o Tesseract (UB-Mannheim) à mão e rode de novo.' }
        winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
    }
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stage_tesseract.ps1')
}

if ($Somente -in 'todos','ffmpeg') { Install-FFmpeg }
if ($Somente -in 'todos','tesseract') { Install-Tesseract }
Write-Host 'Pronto. Confira com:  python tools\doctor.py'
