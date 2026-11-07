# Dependências — matriz por categoria

Fonte única do que o projeto usa, do que já está instalado e do que cada categoria futura vai exigir. Verificação local: `python tools/doctor.py` (ou `.\dev.ps1 doctor`). No CI, o job «Dependências» roda `pip check`, `pip-audit` (informativo) e `pip-licenses` (bloqueia AGPL).

## Já instaladas (requirements.txt, versões fixadas)

| Pacote | Uso | Licença |
|---|---|---|
| Pillow, pillow-heif | Imagens, HEIC/HEIF | HPND, LGPL-3.0 (libheif) |
| pypdf, pypdfium2 | PDF (estrutura, renderização) | BSD-3, Apache-2.0/BSD-3 |
| cryptography (+cffi, pycparser) | Proteger/remover senha | Apache-2.0/BSD |
| resvg-py | SVG | MPL-2.0 |
| numpy, onnxruntime | Remoção de fundo (U²-Net-p); numpy também confere o Bleep do Áudio | BSD, MIT |
| PySide6-Essentials, shiboken6 | Interface | LGPL-3.0 |
| pywin32 (só Windows) | Integração com o shell | PSF |

Ferramentas de desenvolvimento (requirements-dev.txt): PyInstaller (empacotamento), pip-audit, pip-licenses.

## Programas externos

| Programa | Estado | Onde entra |
|---|---|---|
| Tesseract (OCR) | CI instala (apt / choco); o build do Windows copia para `tesseract\` via `tools\stage_tesseract.ps1`; dados de idioma `eng` e `por` vêm em `tessdata\` | PDF › OCR; revisar licenças das DLLs copiadas (`tesseract\COPIADOS.txt`) |
| Inno Setup 6 | CI instala por choco | Instalador do Windows |
| FFmpeg/ffprobe | **Em uso (0.9.43)**: `mediatools.py` localiza, confere a licença do build e lê arquivos; `audioconvert.py` converte (item 3: MP3, M4A, FLAC, OGG, Opus, WAV, AIFF; precisa dos codificadores libmp3lame/aac/flac/libvorbis/libopus no build). CI instala (apt / choco, build GPL só para testes). O pacote só aceita build **LGPL** na pasta `ffmpeg\` | Áudio agora, Vídeo depois; HEVC/x265 depende de decisão jurídica |
| LibreOffice | Opcional, ainda não usado | Documentos (fallback); `soffice` já está na lista de permitidos |

## Planejadas por categoria (ainda NÃO instaladas — instalar quando a categoria começar)

| Categoria | Pacotes | Observação |
|---|---|---|
| Documentos | python-docx, python-pptx, openpyxl, odfpy, defusedxml, markdown-it-py | defusedxml obrigatório para qualquer XML de entrada |
| Áudio — fechada (0.9.50) | só o FFmpeg; Mutagen **não** é usado (as etiquetas passam pelo FFmpeg/ffprobe) | ver «Requisitos do build do FFmpeg» abaixo |
| Vídeo | FFmpeg; opencv-python-headless (opcional) | Evitar builds com `--enable-nonfree` |
| Dados/Texto | (stdlib; markdown-it-py se Markdown) | — |

## Requisitos do build do FFmpeg (checklist para fixar o build LGPL do Windows)

O app confere isto sozinho (`mediatools.build_info`, `python tools/doctor.py`); um build que não atende recusa só a ferramenta afetada, com explicação.
- **Licença:** sem `--enable-gpl`, sem `--enable-nonfree` (o `package.py` recusa). Sem `libx264`/`libx265`.
- **Codificadores de áudio:** `libmp3lame`, `aac`, `flac`, `libvorbis`, `libopus`, `pcm_s16le` (WAV/AIFF).
- **Codificador de vídeo:** `mpeg4` (nativo; usado só pelo Visualizador). H.264/HEVC dependem de decisão jurídica.
- **Filtros:** `aformat`, `aresample`, `astats`, `pan`, `volume`, `silencedetect`, `loudnorm`, `aeval`, `showwaves`, `showspectrum`, `fps`, `format`.
- **Formatos de entrada/saída:** mp3, mov/mp4/m4a, flac, ogg, opus, wav, aiff, matroska/webm (entrada); muxers `mp4`, `ipod`/`ogg`/`opus` conforme o formato.
- **Registrar** em `THIRD_PARTY_NOTICES.md`: versão, origem, SHA-256 do arquivo baixado e licenças das bibliotecas embutidas (lame, opus, vorbis, ogg).

## Vulnerabilidades (pip-audit)
Rodar `pip-audit -r requirements.txt` a cada atualização de dependência (a CI faz de forma informativa). 06/11/2026: pypdf 6.21.1 tinha 10 avisos, corrigidos em **6.21.4** (atualizado). A 7.0.0 existe, mas é versão principal nova: avaliar só com uma rodada completa de testes do PDF.

Regra: pacote novo só entra com versão fixada, licença conferida (compatível com GPL-3.0-only, sem AGPL), registro em `THIRD_PARTY_NOTICES.md` e teste.
