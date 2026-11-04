# Dependências — matriz por categoria

Fonte única do que o projeto usa, do que já está instalado e do que cada categoria futura vai exigir. Verificação local: `python tools/doctor.py` (ou `.\dev.ps1 doctor`). No CI, o job «Dependências» roda `pip check`, `pip-audit` (informativo) e `pip-licenses` (bloqueia AGPL).

## Já instaladas (requirements.txt, versões fixadas)

| Pacote | Uso | Licença |
|---|---|---|
| Pillow, pillow-heif | Imagens, HEIC/HEIF | HPND, LGPL-3.0 (libheif) |
| pypdf, pypdfium2 | PDF (estrutura, renderização) | BSD-3, Apache-2.0/BSD-3 |
| cryptography (+cffi, pycparser) | Proteger/remover senha | Apache-2.0/BSD |
| resvg-py | SVG | MPL-2.0 |
| numpy, onnxruntime | Remoção de fundo (U²-Net-p) | BSD, MIT |
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
| Áudio | FFmpeg; Mutagen (opcional, GPL-2+) para tags | Mutagen só após confirmar compatibilidade com GPL-3.0-only |
| Vídeo | FFmpeg; opencv-python-headless (opcional) | Evitar builds com `--enable-nonfree` |
| Dados/Texto | (stdlib; markdown-it-py se Markdown) | — |

Regra: pacote novo só entra com versão fixada, licença conferida (compatível com GPL-3.0-only, sem AGPL), registro em `THIRD_PARTY_NOTICES.md` e teste.
