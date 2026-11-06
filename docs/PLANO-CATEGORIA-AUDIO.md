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
| 3 | **Converter:** MP3, M4A/AAC, FLAC, OGG/Vorbis, Opus, WAV, AIFF; qualidade (bitrate/VBR/nível FLAC); relatório de perdas; publicação atômica; limite próprio de tamanho | ✅ 0.9.43 |
| 4 | **Metadados:** ver tudo; remover/editar só etiquetas permitidas; capa | ✅ 0.9.44 |
| 5 | **Canais:** mono/estéreo, downmix explícito, aviso de clipping/fase | ✅ 0.9.45 |
| 6 | **Cortar:** início/fim com onda visual; silêncio só nas pontas | ✅ 0.9.46 |
| 7 | **Normalizar volume:** EBU R128 (loudnorm em duas passadas); recusa alvos que causam clipping | ✅ 0.9.47 |
| 8 | **Comprimir:** bitrate-alvo, tamanho como melhor esforço | ✅ 0.9.48 |
| 9 | **Bleep:** intervalos validados, tom sintético; cópia nova, não é anonimização criptográfica | |
| 10 | **Visualizador em MP4:** exige codificador de vídeo aprovado; por último | |

### Decisões de interface
- Desde o item 3 o Áudio usa a **roda em grupos** (`tool_registry.AUDIO_GROUPS`, `radial_menu.audio_tool_actions`), respeitando o limite de 8 fatias. Hoje só entram operações já entregues (**Ler › Informações**, **Converter › Converter**); o desenho final é: **Ler** (Informações, Metadados), **Converter** (Converter, Comprimir), **Ajustar** (Canais, Normalizar), **Editar** (Cortar, Bleep, Visualizador). Os grupos ficam em `tool_registry` (como `PDF_GROUPS`) e o `test_wheel_layout` passa a cobri-los.
- Ferramenta de leitura (`READONLY_TOOLS`): sem botão «Aplicar» nem «Abrir pasta do resultado».
- Soltar um áudio no app abre «Informações» direto; «Converter» fica a um clique na roda e já usa os arquivos abertos.

### Limites conhecidos
- Áudio e vídeo de entrada: até **512 MiB** (`engine.AUDIO_MAX_BYTES`; o FFmpeg lê em fluxo). Demais categorias seguem em 100 MiB.
- Saída: até 512 MiB (limite do worker). WAV/AIFF/FLAC têm o tamanho **estimado antes** (duração × taxa × canais × 2 bytes) e a conversão é recusada se passar de ~95 % do limite; sem duração conhecida só os formatos comprimidos são aceitos. O FFmpeg também roda com `-fs` como segunda trava.
- Tempo: 800 s por arquivo (alvo «longo» do runner, 900 s). O limite de CPU do worker (160 s) vale só para o Python; o FFmpeg é processo filho.
- Só o primeiro fluxo de áudio é descrito; arquivos de vídeo com áudio são aceitos para leitura.

## Portões
- **Portão A (por entrega):** testes novos + `test_architecture` + `test_wheel_layout` + suíte completa + item no diagnóstico.
- **Portão B (fim da categoria):** corpus de áudio na `tools/quality_suite.py` (mono/estéreo/5.1, silêncio/fala/música, VBR, tags Unicode, arquivo truncado/corrompido, 4 h, taxas incomuns), medindo duração, amostras, picos e sincronismo; nota 0–100 por função.

## Pendências externas (não bloqueiam o desenvolvimento)
- Escolher e **fixar um build LGPL do FFmpeg para Windows** (versão, URL, SHA-256, flags e licenças registrados em `THIRD_PARTY_NOTICES.md`); copiar para `ffmpeg\` antes do `package.py`. O build do CI (choco/apt) é GPL e serve só para testes.
- Revisão jurídica: patentes de codecs (AAC/MP3) na distribuição.

### Item 3 — Converter (0.9.43)
- Núcleo `audioconvert.py` (sem Qt): `options_from` (`audio_format` mp3/m4a/flac/ogg/opus/wav/aiff, `audio_quality` low/medium/high, `audio_tags` keep/drop), `build_args`, `estimate_bytes`, `loss_notes`, `convert`.
- Qualidade (só formatos com perda): MP3 128/192/320 kbps · M4A 96/160/256 kbps · Opus 64/96/160 kbps · OGG `-q:a` 3/5/8. FLAC/WAV/AIFF ignoram a qualidade (WAV/AIFF gravam 16 bits).
- Segurança do FFmpeg: sem shell, `-nostdin`, `-protocol_whitelist file`, `-format_whitelist` (só demuxers de áudio/vídeo conhecidos: uma lista `.m3u8` não consegue puxar outro arquivo), entrada `file:<caminho absoluto>`, `-n` (nunca sobrescreve), `-fs`, `-fflags +bitexact`, tempo máximo. A extensão não decide o formato. O mesmo `-format_whitelist` vale agora para o `ffprobe` das informações.
- Só a primeira faixa de áudio é convertida (`-map 0:a:0 -vn -sn -dn`); capa e capítulos não vão; MP3 com mais de 2 canais é mixado para estéreo.
- Conferência antes de publicar: codec esperado, 1 fluxo de áudio, sem vídeo, duração dentro de 2 % (ou 1 s). Falhou → nada é salvo. Publicação por `engine.publish` (nome `<nome>-convertido.<ext>`, nunca sobrescreve).
- Relatório de perdas (`engine.loss_report`) lê o arquivo real e avisa: formato com perda, 24 bits → 16 bits, vídeo descartado, faixas extras, downmix, capa/capítulos, mesmo formato de origem, etiquetas.

### Item 4 — Metadados (0.9.44)
- Núcleo `audiotags.py` (sem Qt): `options_from` (`tag_mode` edit/clear, `tag_cover` keep/drop, um `tag_<campo>` por campo editável), `kind_of`, `build_args`, `notes`, `apply`. O áudio é **copiado** (`-c copy`): nada é recodificado (os testes comparam o hash do PCM decodificado antes e depois).
- Campos editáveis: título, artista, álbum, artista do álbum, data (AAAA, AAAA-MM, AAAA-MM-DD), gênero, faixa e disco («n» ou «n/total»), compositor e comentário; até 200 caracteres, sem caracteres de controle. Só os campos **presentes no pedido** mudam; valor vazio remove o campo; os outros campos do arquivo (inclusive os que o app não edita) são mantidos.
- «Ver tudo»: a tela de informações agora lista também as «Outras» etiquetas (até 40) e reconhece capa de OGG/Opus.
- Formatos: MP3, M4A (AAC/ALAC), FLAC, OGG (Vorbis), Opus, WAV, AIFF — decididos pelo `ffprobe`, nunca pela extensão. Vídeo, várias faixas de áudio e outros formatos são recusados (a cópia não pode perder nada). Saída `<nome>-etiquetas.<ext>`.
- Capa: MP3, M4A e FLAC mantêm ou removem. **OGG/Opus com capa** só podem ser reescritos removendo a capa (o FFmpeg lê a capa mas não a regrava); a mensagem diz isso. WAV/AIFF não têm capa.
- «Limpar tudo» remove todas as etiquetas, a capa e os capítulos. Com vários arquivos só «Limpar tudo» e «Remover capa» valem (campos de texto exigem um arquivo).
- Conferência antes de publicar: mesmo codec e duração, campos pedidos gravados, campos removidos ausentes, campos não editados preservados, capa conforme pedido. WAV/AIFF guardam poucos campos: se o formato não aceita um campo (ex.: gênero no AIFF), nada é salvo e a mensagem diz qual.

### Item 5 — Canais (0.9.45)
- Núcleo `audiochannels.py` (sem Qt): `options_from` (`chan_mode` mono/stereo/left/right + `audio_quality`), `plan` (valida o modo contra os canais do arquivo e escolhe o filtro), `measure` (passadas só de decodificação com `astats`), `build_args`, `notes`, `apply`.
- Modos: **Mono** (estéreo: `pan=mono|c0=0.5*c0+0.5*c1`; surround: `aresample=ochl=mono`), **Estéreo** (surround → `aresample=ochl=stereo`; mono → duplicado, sem ganho real), **Só esquerdo / Só direito** (só em estéreo). Pedidos sem sentido (mono → mono, estéreo → estéreo, esquerdo em surround) são recusados com mensagem.
- **Recodifica** no mesmo formato do arquivo (decidido pelo ffprobe: MP3, M4A, FLAC, OGG, Opus, WAV, AIFF); qualidade pelos mesmos níveis da conversão; etiquetas mantidas; capa copiada em MP3/M4A/FLAC (OGG/Opus: limite do FFmpeg, avisado); capítulos não vão. Saída `<nome>-mono|-estereo|-esquerdo|-direito.<ext>`.
- **Fase (estéreo → mono):** mede o RMS do estéreo e do mono. Mono > 6 dB abaixo → **aviso**; > 15 dB abaixo ou mudo (oposição de fase) → **recusa**, sugerindo «Só esquerdo/Só direito». Fonte silenciosa não é problema de fase.
- **Clipping (surround → mono/estéreo):** mede o pico da mistura; se passar de −0,3 dBFS reduz o volume o mínimo necessário (`volume=-X dB`) e avisa; excesso absurdo (> 24 dB) é recusado.
- **Avisos medidos voltam do worker:** `engine.RUN_NOTES` → campo opcional `notes` na resposta do worker → `runner.LAST_NOTES`/`take_notes()` → `JobController.last_report` (os avisos vêm antes do relatório estático). O formato `outputs` não mudou, e as leituras de interface (`audio_info`) não tocam nas notas.
- Roda: novo grupo **Ajustar › Canais** (`AUDIO_GROUPS['adjust']`); a roda de primeiro nível passou a ter 3 fatias (Ler, Converter, Ajustar).
