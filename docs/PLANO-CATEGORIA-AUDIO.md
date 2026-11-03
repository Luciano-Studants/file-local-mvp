# Plano da categoria Áudio — ordem por risco

Decisão (03/11/2026): Áudio é a próxima categoria. Motivos: é a Fase 4 do roteiro; abre a base do FFmpeg que o Vídeo reaproveita; dá para entregar com **build LGPL**, sem tocar na pendência jurídica de HEVC/x265 (que só pesa no Vídeo); usa a base de dependências, CI e diagnóstico recém-montada. Arquivos compactados (stdlib) ficam para a Fase 6.

## Regras da categoria
- FFmpeg/ffprobe como **programas externos**: sem shell, sem rede (`-protocol_whitelist file`), sem teclado, com tempo máximo e saída limitada; nunca opções livres do usuário (só valores validados montam a linha de comando).
- Pacote distribuído só com build **LGPL** (sem `--enable-gpl`/`--enable-nonfree`); `package.py` recusa outro. Build GPL serve para desenvolver e testar.
- Originais intactos; saída com nome novo; publicação atômica; nada parcial em erro (mesmas regras de Imagens e PDF).
- A extensão não decide o formato: sempre `ffprobe`.
- Roda: grupos com no máximo 8 fatias e rótulos ≤ 13 caracteres (`tests/test_wheel_layout.py`).

## Itens (do menor para o maior risco) — siga nesta ordem, um por «próximo passo»
| # | Funcionalidade | Estado |
|---|---|---|
| 1 | **Base de mídia:** localizar FFmpeg/ffprobe, licença do build, leitura segura | ✅ 0.9.43 |
| 2 | **Informações do áudio:** painel com duração, codec, taxa, canais, etiquetas, capa; vários arquivos; leitura no worker (`audio_info`) | ✅ 0.9.43 |
| 3 | **Converter:** MP3, M4A/AAC, FLAC, OGG/Vorbis, Opus, WAV, AIFF; qualidade (bitrate/VBR/nível FLAC); relatório de perdas; publicação atômica; limite próprio de tamanho | ⏳ próximo |
| 4 | **Metadados:** ver tudo; remover/editar só etiquetas permitidas; capa | |
| 5 | **Canais:** mono/estéreo, downmix explícito, aviso de clipping/fase | |
| 6 | **Cortar:** início/fim com onda visual; silêncio só nas pontas | |
| 7 | **Normalizar volume:** EBU R128 (loudnorm em duas passadas); recusa alvos que causam clipping | |
| 8 | **Comprimir:** bitrate-alvo, tamanho como melhor esforço | |
| 9 | **Bleep:** intervalos validados, tom sintético; cópia nova, não é anonimização criptográfica | |
| 10 | **Visualizador em MP4:** exige codificador de vídeo aprovado; por último | |

### Decisões de interface
- Enquanto a categoria tem poucas ferramentas, o Áudio usa **cartões** (ativos e «Planejado»). Ao entregar o item 3 passa a **roda em grupos**, respeitando o limite de 8 fatias: **Ler** (Informações, Metadados), **Converter** (Converter, Comprimir), **Ajustar** (Canais, Normalizar), **Editar** (Cortar, Bleep, Visualizador). Os grupos ficam em `tool_registry` (como `PDF_GROUPS`) e o `test_wheel_layout` passa a cobri-los.
- Ferramenta de leitura (`READONLY_TOOLS`): sem botão «Aplicar» nem «Abrir pasta do resultado».
- Soltar um áudio no app abre «Informações» direto (enquanto for a única ferramenta).

### Limites conhecidos
- O motor recusa arquivos acima de 100 MiB (`source_file`); para áudio longo sem perdas (FLAC/WAV) o item 3 define um limite próprio, validado.
- Só o primeiro fluxo de áudio é descrito; arquivos de vídeo com áudio são aceitos para leitura.

## Portões
- **Portão A (por entrega):** testes novos + `test_architecture` + `test_wheel_layout` + suíte completa + item no diagnóstico.
- **Portão B (fim da categoria):** corpus de áudio na `tools/quality_suite.py` (mono/estéreo/5.1, silêncio/fala/música, VBR, tags Unicode, arquivo truncado/corrompido, 4 h, taxas incomuns), medindo duração, amostras, picos e sincronismo; nota 0–100 por função.

## Pendências externas (não bloqueiam o desenvolvimento)
- Escolher e **fixar um build LGPL do FFmpeg para Windows** (versão, URL, SHA-256, flags e licenças registrados em `THIRD_PARTY_NOTICES.md`); copiar para `ffmpeg\` antes do `package.py`. O build do CI (choco/apt) é GPL e serve só para testes.
- Revisão jurídica: patentes de codecs (AAC/MP3) na distribuição.
