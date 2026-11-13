# Roadmap de implementação — Arquivo Local para Windows 10 Pro 22H2

**Documento vivo de planejamento e execução.** Itens marcados como concluídos foram somente editados/testados no ambiente indicado; isso não significa release. A meta de produto registrada pelo usuário é publicar futuramente online um aplicativo gratuito para usuários de Windows 10. O projeto não promete compatibilidade com toda build do sistema: a matriz mínima será definida e validada antes de distribuir. A meta está registrada também em `PROJECT_GOALS.md`.

## 1. Objetivo e contrato do produto

O Arquivo Local será um aplicativo **local, Windows-only**, cuja primeira matriz-alvo é Windows 10 Pro 22H2 x64, operado principalmente pela seleção atual do Windows Explorer/Área de Trabalho e por um menu radial. Outras versões de Windows só serão adicionadas após testes explícitos. A distribuição online gratuita é uma meta futura, não o estado atual do protótipo.

### 1.1 Experiência radial obrigatória

- **Shift pressionado:** operações rápidas e frequentes, escolhidas conforme o tipo de arquivo selecionado. Exemplos: conversão simples, exportação, extração de texto, snapshot, conversão de legenda ou compressão.
- **Shift+F9:** ferramentas e ações secundárias, globais ou menos frequentes. Exemplos: inspeção de metadados, organização, redaction, merge/split, ações de clipboard, shelf, Move, Copy Path e Terminal.
- A ação deve aparecer somente quando o tipo de entrada e as capacidades locais necessárias forem confirmados. Ausência de codec, programa, engine, traineddata ou formato compatível deve produzir estado **indisponível e explicável**, nunca fallback silencioso.
- Seleção múltipla deve abrir um painel apropriado quando a operação não puder ser representada com segurança no radial de arquivo único.
- A UI deve indicar perda potencial, modo de qualidade, destino, sobrescrita, flatten/rasterização e dependências antes da confirmação.
- A bandeja abre a escolha de categoria: Imagens, Vídeo, Áudio, PDF, Documentos, Slides, Planilhas, EPUB, Legendas e Arquivos. Somente verticais com motor e gates aprovados podem executar ações; categorias futuras informam o estado sem simular conversão.
- Shift+F9 é a roda de ferramentas contextual ao arquivo. Hover destaca a ação e mostra rótulo legível; operações geométricas como Crop/Trim devem permitir preview e ajuste visual, sem coordenadas como fluxo principal.
- Ferramentas usam workspaces contextuais: esconder controles irrelevantes, manter texto em português sem clipping e testar tamanho mínimo/escala DPI.
- O fluxo deve manter fila, cancelamento, progresso, histórico local de sessão e abertura da pasta de saída pelo Explorer, sem depender de aplicativos Apple.

### 1.2 Regras de processamento

1. Validar caminho absoluto local, arquivo/pasta regular, identidade do item, reparse points, tamanho, assinatura/conteúdo real, contagem de frames/páginas/streams e limites de recursos antes de decodificar ou extrair.
2. Nunca confiar apenas na extensão.
3. Preservar o original por padrão. Toda transformação gera nova saída em diretório de **staging local confinado** e publica somente após validação.
4. Publicar atomicamente, sem sobrescrever resultados anteriores; colisões recebem nome novo determinístico e seguro.
5. Usar worker descartável por tarefa, timeout, cancelamento e limpeza de staging. No Windows, evoluir para **Job Object** para limitar e encerrar a árvore de processos.
6. Subprocessos externos usam caminho absoluto permitido, `shell=False`, lista fixa de argumentos, ambiente controlado, sem comandos derivados de arquivos, sem rede e sem elevação de privilégio.
7. O produto não é sandbox forense. Arquivos não confiáveis devem ser rejeitados, limitados ou tratados como fora da garantia quando excederem o threat model.
8. Toda saída deve ser reaberta ou inspecionada com o backend correspondente antes da publicação.
9. Relatar bytes antes/depois, codec, encoder, qualidade, perda, campos não preservados e motivo de falha.
10. Nenhuma operação de remoção de metadados será descrita como anonimização certificada; nenhuma blur/redaction por inferência será descrita como irreversível.

## 2. Política Windows-only e equivalentes interoperáveis

| Ideia ou dependência Apple/macOS | Alternativa Windows aberta/interoperável | Limite declarado |
|---|---|---|
| Finder, seleção e abrir pasta | Windows Explorer/Área de Trabalho via Shell/COM/`SelectedItems`; `QDesktopServices` para abrir pasta | Somente caminhos locais regulares; rejeitar UNC, itens virtuais, atalhos, symlinks/junctions e reparse points conforme a política do produto. |
| Finder/clipboard de arquivos | `QClipboard`/`QMimeData`, `QUrl.fromLocalFile` e CF_HDROP | Copia referências de arquivos/pastas, não bytes; o clipboard é global e pode ser substituído por outro processo. |
| iTerm2/Terminal macOS | Windows Terminal (`wt.exe`) e fallback PowerShell com diretório inicial | Não usar `-Command` com texto do caminho, `cmd.exe` concatenado ou shell arbitrário. |
| Pages | DOCX/OOXML, ODT opcional, PDF, HTML sanitizado, Markdown, EPUB, TXT | Não ler/gravar `.pages`, RTFD, text clippings ou pacotes iWork; não prometer fidelidade de layout/editabilidade. |
| Keynote | PPTX/PDF; LibreOffice Impress opcional para conversão | Não ler/gravar `.key`; PPTX visual ou reconstruído não é equivalente semântico a Keynote. |
| Numbers | XLSX/ODS/CSV/TSV e PDF | Não ler/gravar `.numbers`; não copiar semântica de fórmulas/objetos proprietários. |
| Quick Look/Preview/Photos | Preview Qt, `QImageReader`, PDFium/pypdfium2, Pillow, painel local | Não usar Quick Look, Preview.app, iOS Photos, iCloud ou APIs Apple. |
| NSImage, ImageIO, Core Image, Vision | Pillow/PySide6/QPainter; OpenCV local; Tesseract local opcional | Qualidade e cobertura não são equivalentes às APIs Apple; capacidades devem ser condicionadas a testes Windows. |
| AVFoundation, VideoToolbox, CoreAudio, Audio Units | FFmpeg/ffprobe, WASAPI/Media Foundation e QtMultimedia aprovado | Não usar SDK Apple; codecs dependem da build FFmpeg e das licenças/patentes aplicáveis. |
| Apple Books | EPUB 3.3 local, leitores Windows e HTML/XHTML | DRM/LCP, scripts e recursos externos ficam fora. |
| Finder Services/AppleScript | Ações do radial, Shell/COM e APIs Win32 documentadas | Não instalar, emular ou automatizar aplicativos Apple. |

**Regra de substituição:** quando houver equivalente aberto/interoperável, usar o formato e o backend Windows correspondente. Quando não houver equivalente confiável, o item permanece explicitamente fora do escopo, sem mock de comportamento Apple.

## 3. Estado de execução e critérios de promoção

A base contém um motor local com worker, staging, publicação não destrutiva, limites iniciais e ponte de seleção Windows. A maioria das verticais fora da Fase 1 continua planejada. Cada item declara ambiente e testes; o roadmap não transforma código em release automaticamente.

### Estado registrado em 2026-10-22

- **Fase 0, documental:** contrato de produto e segurança atualizado; meta de distribuição gratuita registrada em `PROJECT_GOALS.md`; matriz Windows 10 ainda deve ser formalizada e validada.
- **Fase 1, implementação de código:** subfases 1.1–1.6 registradas acima; além das ações, inclui probe de capabilities Pillow/pypdf/pywin32/Terminal e gate explicável no radial e painel. Código ainda não validado em Windows real.
- **Fase 2, incremento inicial de Image Core:** Crop→PNG, canvas, anotação e compressão JPEG. A UX atual (0.9.6) inclui home de categorias, navegação pelas dez verticais (somente Imagens/PDF ativos), radiais de fatias com hover e rótulo central, página Imagens com as duas rodas (Shift e Shift+F9), recorte com alças/mover, prévias visuais de anotação (posição, texto, cor, tamanho) e canvas, e mensagens em português. Testes Qt de geometria, teclado e coordenadas passam no Sandbox; recorte com proporções fixas e prévia de rotação/tamanho de saída; predefinições de compressão com estimativa e prévia do resultado; fixtures golden de EXIF/alpha/ICC/limites (0.8.5, com preservação/conversão de perfil ICC); cinza de 16 bits e CMYK tratados na 0.8.6; colagem de 2–12 imagens (0.8.7); relatório de perdas textual (0.8.8); design system quente, ferramenta Fundo e atalhos alternativos — hotkeys configuráveis, Shift+botão do meio, soltar na roda, menu de contexto do Explorer (0.9.0, sem validação Windows); ferramenta Ocultar com tarja/pixelização (0.9.1); ferramenta Metadados com inspeção e cópia PNG limpa (0.9.2); ferramenta Ajustar com brilho, contraste, saturação e espelhar (0.9.3); colagem com miniaturas e reordenação (0.9.4); prévia do efeito na Ocultar (0.9.5); primeira suíte em Windows real e correções de caminho/IPC/atalho (0.9.6, ainda sem o gate Windows completo); 204/206 na segunda suíte Windows e correção das 2 falhas de teste, com checklist ampliado (0.9.7); ferramenta Redimensionar, registro de ferramentas e arquitetura em camadas (0.9.8; plano em docs/PLANO-CATEGORIA-IMAGENS.md); ferramenta Girar sem perda (0.9.9); sub-rodas com grupos de ferramentas (0.9.10); formato de saída PNG/JPEG/WebP/TIFF/BMP nas ferramentas, com qualidade e fundo opaco (0.9.11); marca d'água com texto ou logotipo, posições e repetição (0.9.12); gate Windows ainda pendente. Os recursos permanecem experimentais.
- **Shelf experimental adicionada:** janela flutuante de sessão, até 100 caminhos; add/remover/limpar e `QDrag`/`QMimeData` com `CopyAction`. Nenhum conteúdo é copiado pelo app e a lista não persiste. Integração de drop real com Explorer/terceiros aguarda Windows.
- **Fila experimental adicionada:** até 100 tarefas sequenciais, indicador indeterminado sem estimativa inventada, cancelamento do job ativo e limpeza de pendentes. Saídas do worker ficam em staging privado e só são promovidas após sucesso; teste de cancelamento comprovou que staging gerado não aparece no destino. Integração e timing ainda não validados no Windows 10.
- **Regressão de UX corrigida:** Shift+F9 não dispara o radial rápido pelo Shift compartilhado; o radial global troca o rápido visível sem empilhar, e ambos fecham via Esc/clique fora no código. A lógica passa teste automatizado; clique fora no sistema real ainda aguarda teste em Windows.
- **Proteção contra processos duplicados:** inicialização normal usa `QLockFile` por usuário; segunda cópia é recusada com aviso. Teste automatizado do lock passou no Sandbox; checagem de comportamento e pasta de dados segue pendente no Windows.
- **Próximo passo de validação preparado:** `Desktop/windows_acceptance_check.py` verifica dependências, registro da hotkey e seleção no Windows; depois pode abrir o app real e exibir checklist para prateleira, fila/cancelamento, radiais, Unicode e monitores. O checklist restante é autorrelato manual; o gate segue pendente até testes reais no Windows 10 22H2.
- **Fora do escopo desta Fase 1:** Move via IFileOperation, Job Object/limites rígidos de recursos, instalador/autostart, assinatura, pipeline de release pública; percentual real de progresso também não está disponível.
- **Gates pendentes:** Windows 10 Pro 22H2 real, conflitos de hotkey, Explorer/Desktop, clipboard CF_HDROP, caminhos locais/reparse points, terminal sem injeção, PyInstaller, Defender/SmartScreen e distribuição gratuita revisada.

Uma ação só pode sair de **planejada** para **candidata a release** quando cumprir todos os gates:

- matriz de fixtures válida e inválida executada em Windows 10 Pro 22H2 x64;
- validação por assinatura/conteúdo antes do decode;
- original verificado byte a byte após a operação;
- output reaberto e validado pelo backend apropriado;
- cancelamento, timeout, disco cheio, colisão e falha deixam zero output parcial;
- limites de bytes, pixels, páginas, frames, streams, membros, tempo e memória definidos;
- execução sem rede e sem privilégio administrativo;
- SBOM, hashes, versões, origem de binários e NOTICE atualizados;
- mensagens de perda e dependência ausente revisadas em português;
- integração real do Explorer, radial, tray, DPI, Unicode e caminhos locais validada no Windows;
- a capacidade continua desligada quando o codec/programa/licença não está aprovado.

## 4. Ordem geral das fases

### Fase 0 — contrato, threat model e licenças

**Objetivo:** congelar regras comuns antes de adicionar verticais.

Entregáveis de planejamento:

- contrato Windows 10 Pro 22H2 x64, sem Apple, sem rede e sem execução elevada;
- validador comum de caminhos, identidade, arquivos regulares, pastas permitidas, reparse points, UNC, dispositivos e colisões;
- política de staging, publicação atômica e preservação do original;
- limites iniciais e limites específicos por vertical;
- DTOs tipados para jobs, sem filtergraph, flags ou comandos arbitrários vindos da UI/arquivo;
- Job Object ou desenho equivalente para worker e descendentes;
- matriz de dependências, SBOM, hashes, origem, avisos e compatibilidade de licença;
- corpus de fixtures válidos, corrompidos, truncados, malformados, grandes e com caminhos Unicode;
- classificação de mensagens: suportado, indisponível, perda prevista, falha segura, revisão necessária.

**Gate:** threat model revisado, política de limites aprovada, licenças identificadas e testes de segurança do validador executados em Windows real.

### Fase 1 — fundação da experiência Windows e radial

- manter Shift como radial de ações rápidas por extensão/tipo;
- implementar Shift+F9 com `RegisterHotKey(MOD_SHIFT, VK_F9)` e `WM_HOTKEY`, sem hook/keylogger;
- reportar conflito de hotkey sem tomar o atalho de outro programa;
- capturar novamente a seleção do Explorer/Desktop na abertura e revalidar antes da execução;
- painel para seleção múltipla, capability probe e dependências ausentes;
- Copy Path e clipboard CF_HDROP/file URLs não destrutivos;
- Terminal via `wt.exe` opcional e fallback PowerShell, sem comandos arbitrários;
- base da shelf: QWidget sem moldura, referências de caminhos, QDrag/QMimeData com CopyAction;
- fila, progresso, cancelamento e histórico local de sessão.

#### Subfases de implementação

- **1.1 — Gestos, seleção e radial:** Shift, Shift+F9 por `RegisterHotKey`, consulta da seleção Shell, prevenção de menus duplicados e fechamento por Esc/clique externo. Código e testes de lógica prontos; validação Win32 pendente.
- **1.2 — Capability probe:** probe local/offline para Pillow, pypdf, pywin32/Shell e Terminal; radiais e painel desabilitam ou explicam ações sem backend; o controller recusa jobs sem capability. Testes sintéticos prontos; ausência real de dependências deve ser validada em Windows.
- **1.3 — Painel e ações seguras:** seleção múltipla, Copy Path, clipboard de referências CF_HDROP/file URLs, abrir Terminal/PowerShell e acesso à saída. Código e testes de lógica prontos; integração Explorer/clipboard/terminal pendente no Windows.
- **1.4 — Prateleira:** referências locais limitadas à sessão, deduplicação, remoção/limpeza e drag Copy-only. Código e testes Qt prontos; arraste real para Explorer pendente.
- **1.5 — Fila de jobs:** até 100 tarefas sequenciais, lote expandido por arquivo, Merge como job conjunto, estado/progresso indeterminado, cancelar atual, limpar pendentes e histórico local. Staging privado só é publicado após sucesso. Código e testes de worker/UI prontos; cancelamento e timing reais pendentes no Windows.
- **1.6 — Empacotamento e aceite:** instruções reproduzíveis, ZIP-fonte com hash, diagnóstico Windows e checklist manual preparados. Artefato-fonte verificável; build PyInstaller/Defender e checklist de aceitação ainda pendentes no Windows.

**Status geral da Fase 1:** o escopo de código previsto está implementado no Sandbox; a fase não está certificada para uso Windows até passar o gate abaixo. O progresso indeterminado é deliberado: ainda não há percentual de conversão confiável.

**Gate:** hotkey, seleção, clipboard, ações de pasta, Unicode, múltiplos monitores/DPI, usuário padrão, cancelamento e regressão da UI validados no Windows 10 22H2.

### Fase 2 — Image core e operações de alta frequência

- conversão PNG/JPEG/WebP/BMP e PDF raster simples;
- preview reduzido, orientação, crop, resize/rotação e exportação;
- canvas/fundo, anotações achatadas e collage;
- compressão com presets e métricas;
- primeira política de metadados e relatórios de perda.

**Implementado experimentalmente no Sandbox:** recorte visual por arraste no preview orientado por EXIF, convertido para coordenadas da imagem; engine rejeita limites inválidos; canvas PNG centralizado e limitado a 40 MP; anotação local achatada; compressão JPEG qualidade 1–100 com bytes antes/depois. A interface tem home category-first e dez categorias visíveis; só Imagens/PDF executam ações. Testes sintéticos de drag/coord e navegação passam no Sandbox. Ainda faltam collage, golden fixtures de orientação/ICC/alpha, teste em DPI/Windows e gate Windows. Não tratar como pronto para release.

**Gate:** golden fixtures, equivalência preview/export, alpha/ICC/orientação, limites de pixels/bytes, original intacto e saída reaberta.

### Fase 3 — codecs e Image avançado

- TIFF single-frame e variantes aprovadas;
- AVIF e HEIC condicionais a wheels/codecs/licenças auditados;
- ExifTool opcional por caminho absoluto e timeout;
- OpenCV para sugestões faciais e Tesseract para texto, ambos locais e opt-in;
- redaction sólida como cobertura forte, blur apenas com aviso.

**Gate:** codec probe, matriz de bit depth/transparência/metadados, ausência de fallback, validação de pixels e revisão humana de todas as sugestões.

### Fase 4 — Video, Audio e motores externos

- FFmpeg/ffprobe pinados, capability probe, licença e build flags registradas;
- conversão, probe, mute, snapshots, crop, velocidade, split e trim de vídeo;
- compressão, loudnorm, trim, silêncio, canais, bleep e visualizer de áudio;
- redaction temporal de vídeo inicialmente com retângulos fixos e números validados;
- quotas específicas para duração, frames, resolução, streams, CPU, memória e saída.

**Gate:** fixtures CBR/VFR, sincronismo, PTS, codecs, streams, ausência de shell/rede, encerramento da árvore e validação em players Windows.

### Fase 5 — PDF, Documentos, Slides, Spreadsheets e EPUB

- PDF core, renderização, metadados, merge/split/organização e exportações raster;
- TXT/Markdown/HTML sanitizado e DOCX content-first;
- EPUB seguro e reflow/fixed-layout conforme limitações;
- PPT/PPTX via LibreOffice opcional e PDF→PPTX visual;
- XLSX/ODS/CSV/TSV e PDF→Excel com revisão;
- OCR Tesseract somente como dependência explícita e opcional.

**Gate:** pacotes ZIP/XML confinados, PDFs digitais/scans, comparação visual, licenças, macros/scripts bloqueados e avisos de reconstrução.

### Fase 6 — Archives e ações globais completas

- ZIP/TAR/GZIP com preflight e extração manual;
- RAR import-only via backend aprovado, sem criação RAR;
- Move por IFileOperation em COM STA, com confirmação e relatório de falha parcial;
- shelf interoperável com Explorer e aplicativos que aceitem CF_HDROP;
- hardening de reparse points, links, archive bombs e Job Object.

**Gate:** corpus de archives hostis, nomes Windows, links, colisões, volumes RAR, cancelamento, ausência de output parcial e aceitação do comportamento destrutivo de Move.

### Fase 7 — release Windows e validação de produto

- build PyInstaller criada em Windows, não no Sandbox Linux;
- máquina limpa sem dependências opcionais para verificar mensagens de indisponibilidade;
- Defender/SmartScreen, usuário não administrador, caminhos Unicode, DPI, múltiplos monitores, Explorer e tray;
- regressão de todas as verticais e ações radiais;
- SBOM, THIRD_PARTY_NOTICES, licenças, hashes, changelog de limitações e documentação de suporte;
- nenhuma ação marcada como pronta antes dos gates de release.

## 5. Matriz consolidada por vertical e subitem

As linhas abaixo são **itens planejados**. “Alta/média/baixa” é viabilidade preliminar, não estado de implementação.

### 5.1 Image

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Conversão | PNG, WebP, HEIC, TIFF, AVIF, BMP, PDF e JPEG apenas quando codec e teste passarem; cópia em staging, nome novo, publicação atômica | Pillow; pillow-heif/libheif somente para HEIC/AVIF | Validar assinatura, arquivo regular, frames e limites antes de decodificar; codec ausente não gera fallback | Golden fixtures por formato; dimensões, modo, alpha, orientação e tolerância de pixel; output reaberto |
| Compressão | Presets lossless, qualidade, target-size e percentual como objetivo iterativo; JPEG/WebP/AVIF por qualidade/subsampling; PNG por optimize/compress_level | Pillow/libwebp/libjpeg; encoder AVIF/HEIC condicionado | Tamanho-alvo aproximado; original preservado; PDF só por rasterização controlada ou reempacotamento limitado; pypdf não recompõe imagens | Bytes antes/depois, hash do original, PSNR/SSIM ou revisão visual; abortar se qualidade mínima falhar; PDF explicita rasterização |
| Metadados | Inspeção de EXIF/GPS/orientação, IPTC, XMP, ICC, JFIF, comentários, thumbnails e campos específicos; remoção gera nova cópia | Pillow; ExifTool opcional para cobertura independente; pypdf para Info/XMP PDF | Remoção não é anonimização certificada; pixels, esteganografia, thumbnails e dados de container podem sobreviver | Fixtures com EXIF/GPS/IPTC/XMP/ICC/thumbnail; comparar Pillow e ExifTool antes/depois; preserve vs strip |
| Preview/edição | Preview limitado por pixels; exposição, contraste, saturação, temperatura, sombras/highlights, nitidez, clarity, grain, noise reduction e dehaze | Pillow/QPainter; filtros determinísticos primeiro | Dehaze/clarity profissional não devem ser vendidos como editor profissional; preview e full-resolution devem ser determinísticos | Qt offscreen, responsividade, cancelamento, undo/redo e igualdade matemática entre preview/export |
| Anotações | Camada não destrutiva com seta, linha, texto, retângulo, círculo, callout, marcador, rótulo, magnifier e imagem; flatten explícito | QPainter/Pillow, fontes Windows escolhidas | Original preservado; rasterização não mantém camadas; registrar cor, espessura e opacidade | Zoom/rotação/coordenadas normalizadas, move/resize, undo/redo, flatten e reabertura visual |
| Fundo/canvas | Largura/altura/padding, cor/gradiente, imagem, blur, cantos, sombra, composição RGBA | Pillow/QPainter | Limites globais antes de alocar; JPEG/BMP/PDF achatam transparência e devem avisar | Alpha, dimensões, memória, saída perto do limite e transparência validada |
| Crop | Handles, zoom, proporções preset/custom, pixels exatos e expansão de canvas | Pillow/Qt | Converter EXIF orientation uma única vez; rejeitar retângulo negativo/fora da imagem | Fixtures rotacionadas, alpha, aspect ratio, pixels exatos e determinismo preview/export |
| Redact local | Sugestões faciais OpenCV e caixas OCR Tesseract; áreas sólidas ou blur, feather/tamanho, múltiplas áreas, revisão manual, flatten | opencv-python-headless; Tesseract+pytesseract opcional; modelos/cascades com hash | Sem promessa de detecção perfeita; blur reversível por inferência; preenchimento sólido + revisão é a única cobertura forte | Rostos pequenos/perfil/oclusão/rotação; pt/en/baixa resolução; boxes/confiança, overrides e verificação de pixels opacos |
| Collage | 2–100 imagens, miniaturas reordenáveis, grid/row/column/featured, dimensões, spacing, corners, background, fit/crop | Pillow/QPainter | Limites de contagem, pixels, memória e output; seleção do Explorer é ordem inicial | Layout determinístico, 40 MP/512 MiB perto do limite, reordenação, flatten e codecs aprovados |

**Formatos Image:** PNG mantém alpha e lossless; WebP oferece lossy/lossless e transparência; BMP é interoperável porém grande e normalmente achata alpha; JPEG é lossy, RGB e sem alpha; TIFF deve começar single-frame com limites de 16-bit/BigTIFF/multipágina; AVIF deve começar em 8-bit salvo e não prometer HDR/10-bit/sequences; HEIC depende de libheif e codecs HEVC/AV1, com patentes e possíveis perdas de bit depth; PDF é saída raster, não editor PDF, PDF/A ou redator certificado.

### 5.2 Video

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Probe/conversão | Entrada local identificada por ffprobe; MP4, MKV, WebM, AVI, WMV, GIF e MP3 conforme combinação real de streams/codecs | ffmpeg.exe/ffprobe.exe pinados, caminho absoluto, capability probe | Não confiar em extensão; sem protocolos de rede, concat arbitrário, UNC ou shell | JSON de container/streams/codec/duração/fps/timebase/capítulos; saída reaberta por ffprobe |
| Compressão | CRF/qualidade recomendado; bitrate/tamanho como melhor esforço; remux apenas quando compatível | FFmpeg com encoders/muxers aprovados | Lossy perde qualidade; 100 MiB/512 MiB e 180 s atuais não podem ser aplicados cegamente a vídeo | Originais, bytes, sincronismo, tolerância de tamanho, falha sem output parcial |
| Remover áudio | `-map` explícito apenas vídeo; copy quando possível, reencode quando necessário | FFmpeg | Informar duração e alteração de vídeo; rejeitar entrada somente áudio | ffprobe sem stream de áudio, duração aceitável e vídeo decodificável |
| Trim preciso | Timecode [início,fim), preview quadro a quadro, PTS real, reencode para precisão | FFmpeg trim/atrim e reset de timestamps | `-ss` por stream-copy é keyframe-limited; VFR/B-frames podem aproximar fronteira | Slates, CBR/VFR, tom/samples, primeiro/último PTS, ausência de drift |
| Crop | x/y/largura/altura, presets e exact=1; áudio por map separado | Filtro crop e encoder | Rejeitar fora do quadro, zero e combinações de subsampling; não arredondar silenciosamente | Dimensões ffprobe, áudio preservado e casos de subsampling |
| Velocidade | 0,25x–4x, setpts e atempo encadeado; pitch preservado por padrão | Filtros FFmpeg | Artefatos, duração efetiva e atempo >2; vídeo silencioso permitido | 0,5x/1x/2x/3x, duração, pitch e sincronismo |
| Snapshots | Timestamp/índice para PNG full-resolution, nomes sem colisão | FFmpeg/Pillow para validar PNG | VFR mostra timestamp solicitado e timestamp do frame real | Slates CBR/VFR, vários snapshots, tamanho, conflito de nomes |
| Split | Pontos ordenados ou partes iguais; publicar somente após todas válidas | FFmpeg; reencode para precisão | Copy rápido deve ser rótulo keyframe-limited; rejeitar duplicados/fora da duração | Nenhuma lacuna/sobreposição, A/V sincronizado e falha sem conjunto parcial |
| Redaction temporal | Retângulos sólidos ou blur com início/fim e números validados; reencode de todos os frames | drawbox/boxblur; filtergraph interno | Sem OCR/face detection nesta fase; blur não é anonimização; amostrar fronteiras | Movimento, múltiplos retângulos, fronteiras e frames aleatórios; nenhum filtergraph livre |
| Integração | Ações no radial/painel somente após capability probe | Worker descartável, quotas específicas e Job Object | Nada deste vertical depende de Apple ou LibreOffice | Shift/radial, filas, cancelamento, codec ausente e players Windows |

**Formatos Video:** MP4 prioriza H.264/AAC quando disponíveis; MKV mantém múltiplas trilhas quando explicitamente selecionadas; WebM somente VP8/VP9 + Vorbis/Opus; AVI e WMV são legados e condicionais; GIF tem paleta limitada e pode ficar maior; MP3 é extração de áudio, não vídeo.

### 5.3 Audio

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Conversão | MP3, M4A/AAC/ALAC, WAV, FLAC, OGG/Vorbis, Opus, AIFF e WMA conforme codec real | FFmpeg/ffprobe pinados; Mutagen opcional para tags | M4A/OGG são containers; WMA depende de perfil; não inferir codec pelo sufixo | Probe, round-trip, sample rate/format/layout, duração e decodificação |
| Compressão | Bitrate/VBR, FLAC compression level, PCM para WAV/AIFF, tamanho como melhor esforço | FFmpeg | VBR, tags e padding impedem tamanho exato; lossless só em FLAC/PCM | Conteúdo silêncio/fala/música, bytes, amostras e sem clipping inesperado |
| Normalização | EBU R128/loudnorm, alvo de integrated loudness, LRA e true peak; análise/double-pass | Filtro loudnorm; relatório local | Não é simples ganho; alvo extremo/clipping deve ser rejeitado | Mono/dual-mono/stereo/multicanal, IL/LRA/true peak e clipping |
| Trim/silêncio | Waveform, início/fim em segundos/amostras; remover silêncio apenas nas extremidades com limiar, duração, janela e any/all por canal | FFmpeg atrim/silenceremove; preview PCM | Pode cortar transientes/fala; não faz sincronização com vídeo | Amostras conhecidas, ruído, canais assimétricos, bordas e preview |
| Canais | Mono/stereo, ganho L/R, isolamento e downmix explícito | pan/channelsplit; Qt preview opcional | Downmix pode causar clipping, fase e mudança de panorama | Mono↔stereo, 5.1, layout desconhecido, peak/fase |
| Visualizer MP4 | showwaves/showspectrum, landscape/portrait/square, imagem local opcional, duração | FFmpeg + encoder de vídeo aprovado | Sempre reencode; patentes/compatibilidade do codec; sem QuickTime | MP4 reaberto, áudio/sincronismo/fps/pixel format/orientação |
| Bleep | Intervalos, mover/ajustar, tom sintético limitado, crossfade e todos os canais | FFmpeg sine/filters; DTO numérico | Não é anonimização criptográfica; cópia nova | Intervalos sobrepostos/bordas/fracionários, comparação e ausência de vazamento |
| Metadados | JSON por arquivo/stream/chapter/program; allowlist de edição/remoção, artwork/capítulos quando suportados | ffprobe/FFmpeg; Mutagen opcional GPL-2-or-later | Remover tags não é sanitização certificada; muxer pode recriar dados | ID3, MP4 atoms, Vorbis, FLAC, AIFF/WAV, ASF, artwork e Unicode |
| UI | Tipo Audio no radial/painel após motor e capability probe | Worker recebe somente DTO validado | Não aceitar flags/filtergraphs arbitrários | Shift/Shift+F9, múltiplos, cancelamento e regressão Image/PDF |

**Formatos Audio:** AIFF e M4A são tratados como formatos interoperáveis via FFmpeg no Windows, sem CoreAudio/QuickTime; WMA só deve aparecer para perfis cobertos por fixture; WAV/FLAC/AIFF lossless devem comparar amostras quando a operação não muda sample rate/layout.

### 5.4 PDF

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Core/merge/split/organização | Merge, split, duplicar, remover, girar e reordenar páginas com confirmação | pypdf; pypdfium2 para thumbnails | Preparar tudo antes de publicar; criptografado/protegido pode ser rejeitado; assinaturas podem invalidar | Contagem, ordem, rotação, falha parcial, cancelamento e originais |
| PDF→JPG/PNG | Renderizar cada página a 300 DPI, uma por arquivo, nomes determinísticos | pypdfium2, Pillow | 300 DPI não garante nitidez; pixels/memória podem explodir; JPG é lossy | 612×792 pt → 2550×3300 px, DPI metadata, páginas grandes e streaming |
| PDF→TXT/Markdown | Extração nativa; headings/listas/tabelas heurísticos; fallback simples | pypdf, pdfminer.six/pdfplumber | PDF não tem semântica confiável; scans precisam OCR | Corpus de colunas, tabelas, rotação, ligaturas, ordem de leitura |
| PDF→DOCX/PPTX/XLSX | Reconstrução best-effort; PPTX image-backed; XLSX somente tabelas detectáveis | python-docx/python-pptx/openpyxl; OCR opcional | Não prometer layout, objetos editáveis ou semântica perfeita | Comparação visual/estrutural e relatório de perda |
| PDF→EPUB | Reflow para PDF digital; fixed-layout por página rasterizada | writer EPUB seguro, pypdfium2, Tesseract opcional | Reflow é heurístico; fixed perde seleção/acessibilidade | EPUBCheck, ordem, spine/nav, pixels e tamanho |
| Compressão | Lossless com content streams/deduplicação/rewrite; visual com downsample opt-in | pypdf/pikepdf/qpdf após revisão | Lossless pode aumentar; downsample altera imagens; não é PDF/A | qpdf check quando disponível, texto/objetos e avisos |
| Metadados | Info/XMP, título/autor/assunto/keywords/datas; remoção seletiva | pypdf; pikepdf/qpdf opcional | Não cobre automaticamente JS, anexos, thumbnails, IDs, revisões ocultas | Antes/depois, anexos/JS/links preservados ou removidos conforme contrato |
| OCR | Renderizar temporários e chamar Tesseract com argumentos fixos | Tesseract + traineddata configurado | CER/WER e revisão humana; sem rede/admin | Idiomas, rotação, baixa resolução, engine/traineddata ausente |

**Limites PDF:** entrada inicial até 100 MiB, 1–200 páginas, saída até 512 MiB e limites adicionais por content stream/pixels/memória. A documentação do pypdf alerta que streams descompactados podem consumir RAM muito acima do tamanho do arquivo; o worker Windows não deve ser tratado como sandbox rígido.

### 5.5 Documentos

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| TXT | UTF-8, BOM UTF-8/UTF-16 explícito; exportar para MD/HTML/DOCX/EPUB | Biblioteca padrão | Codificação ambígua deve ser sinalizada; sem formatação inventada | CRLF/LF, NUL, pt-BR, RTL, arquivo grande e linha final ausente |
| Markdown | CommonMark configurado; MD↔HTML/TXT/EPUB/DOCX | markdown-it-py; sanitização | HTML, plugins e GFM não são assumidos; não executar links/scripts | Corpus CommonMark, HTML perigoso, tabelas/extensões e golden files |
| HTML | HTML/XHTML estático, parser inerte, allowlist de elementos/atributos | markdown-it-py/defusedxml ou parser aprovado | Remover script, eventos, `javascript:`, `file:`, `data:` perigoso e recursos remotos | XSS, SVG ativo, iframe, CSS externo, entidades e HTML malformado |
| DOCX | Conteúdo estruturado: headings, parágrafos, listas, tabelas, imagens, hyperlinks | python-docx, lxml/typing_extensions | DOCM/macros/OLE/ActiveX fora; layout, campos, revisão, comentários e caixas podem perder | Round-trip estrutural, OOXML malicioso, imagens, Unicode e macros rejeitadas |
| EPUB | Ler/exportar package, manifest, spine, nav, capa e metadados; DOCX/HTML/TXT/MD | zipfile + defusedxml; writer próprio preferido | EPUB reflowable; DRM, scripts, mídia, recursos externos e CSS complexo ficam fora | EPUBCheck, package inválido, ZIP bomb, links externos e referências quebradas |
| PDF | Texto/merge/split/metadados; PDF→DOCX apenas best-effort | pypdf/pypdfium2; Tesseract opcional | pypdf não renderiza; PDF escaneado não tem texto sem OCR | PDF digital/scan/protegido, render, limites e aviso de reconstrução |
| Imagens | Capas/embutidos/imagem→PDF em formatos aprovados | Pillow; HEIC opcional condicionado | Engine atual de planejamento rejeita animação/multipágina; metadados podem perder | Alpha/ICC/EXIF, 40 MP, decompression bomb e multipágina |
| LibreOffice opt-in | DOCX/ODT/HTML/RTF/PDF de maior fidelidade quando escolhido | `soffice` allowlisted, perfil temporário, timeout | Nunca requisito do núcleo; não chamar macros/rede/admin | Versão ausente, filtro, timeout, processo órfão e diff visual |

**Pages permanece fora:** pedir ao usuário DOCX, ODT, PDF, HTML, EPUB, Markdown ou TXT exportado de fonte sob controle dele; não instalar ou emular Pages.

### 5.6 Slides

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| PPT/PPTX→PDF | Todos os slides por padrão; opções futuras para notas, ocultos e intervalo | LibreOffice Impress headless no Windows, filtro fixo | Fontes, temas, SmartArt, gráficos, transições, áudio/vídeo, macros e OLE podem variar | Contagem, ordem, orientação, fontes e diff visual |
| PPT/PPTX→JPG/PNG | PDF intermediário e rasterização por página; nomes `stem-slide-001` | LibreOffice + pypdfium2 + Pillow | Limites DPI/pixels; PNG preserva melhor texto, JPG perde | 96/150/300 DPI, streaming, memória e saída por slide |
| PDF→PPTX visual | Um slide por página, imagem full-bleed, proporção preservada | python-pptx + pypdfium2 | Não é texto/objeto editável, sem notas/transições/acessibilidade semântica | Renderizar novamente e comparar cada slide ao PDF |
| PPT legado | Importação delegada ao LibreOffice e exportação em staging | Filtros PowerPoint 97–2003 e 2007–365 | Fidelidade menor e somente entrada; nunca salvar `.ppt` original | Corpus real, fontes/objetos/gráficos e classificação aprovado/advertido/rejeitado |
| Radial | Shift para conversão rápida; Shift+F9 para opções, intervalo, notas e inspeção | Capability probe de LibreOffice | `.key`/Keynote ficam indisponíveis | Hotkey, painel, dependência ausente e seleção múltipla |

### 5.7 Spreadsheets

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| XLSX↔ODS | Workbook estruturado, múltiplas planilhas, escolha explícita para CSV | openpyxl + odfpy em licença aprovada | Fórmulas não são recalculadas; estilos/objetos/pivots/macros podem perder | Round-trip, fórmulas, datas, estilos, merges, imagens, shapes e relatório de perdas |
| CSV/TSV | Delimitador, quoting, encoding, seleção de uma planilha ou um arquivo por planilha | `csv` da stdlib | Não há folhas/estilos/tipos confiáveis; sem achatamento silencioso | Multilinha, Unicode, BOM, CRLF, delimitadores, zeros à esquerda |
| XLS legado | Importar BIFF histórico para XLSX/ODS/CSV/TSV | xlrd 2.x BSD; sem saída XLS | Sem senha; objetos, macros, gráficos e formatação podem ser ignorados | BIFF8 real, senha/corrupção, Unicode e perdas explícitas |
| XLSX/ODS→PDF | Página, área, escala, orientação e planilhas selecionadas | LibreOffice Calc opt-in | Depende de fontes, versão e paginação; não é requisito de execução | Página, quebras, folhas ocultas, fonte ausente e diff visual |
| PDF→Excel | Tabelas digitais por alinhamento/linhas; uma planilha por tabela/página | pdfplumber/pdfminer.six; Camelot opcional | PDF não tem semântica; scans exigem OCR e revisão | Linhas/sem linhas, mescladas, rotação, duas colunas e tabela ausente |
| CSV seguro | Neutralizar início `=`, `+`, `-`, `@` quando destino puder abrir no Excel | Regra própria, sem avaliação de fórmula | Deve informar alteração e manter original | Fixtures de formula injection e comparação de conteúdo normalizado |

**`.numbers` permanece fora.** A alternativa é exportar para XLSX, ODS, CSV, TSV ou PDF usando uma aplicação interoperável sob controle do usuário.

### 5.8 EPUB

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Leitor seguro | Validar `mimetype`, `META-INF/container.xml`, OPF, manifest, spine, nav/NCX e referências internas | zipfile, pathlib, defusedxml, parser próprio | Não usar `extractall`; rejeitar traversal, symlink-like, DRM, cifragem e links externos | EPUB2/3 válidos, XML inválido, ZIP bomb, duplicatas e referências quebradas |
| EPUB→TXT | Concatenar spine em ordem, títulos e separadores, UTF-8 | Parser próprio | Perde estilo, imagens, layout e interatividade | Ordem, Unicode, cues, tabelas e ausência de output parcial |
| EPUB→Markdown | XHTML para headings/ênfase/listas/código/links/imagens/tabelas simples | CommonMark/markdown-it-py | CSS e layout perdidos; dialeto declarado | Golden files, sanitização e links internos |
| EPUB→HTML | HTML standalone ou pacote de assets, TOC/spine e metadados | Parser/serializer seguro | Não executar JS; assets remotos rejeitados | HTML sanitizado, assets confinados e navegação |
| EPUB→DOCX | DOCX novo com capítulos, headings, parágrafos, listas, imagens e tabelas simples | python-docx | Não preservar CSS/paginação complexa | OOXML válido, imagens, links, sem macros e diff estrutural |
| EPUB→PDF | Renderização local de XHTML/CSS, JS/rede bloqueados | Qt WebEngine controlado ou backend futuro | Fontes/CSS/quebras variam; WebEngine não está na base Essentials | Sem rede/JS, timeout, páginas, fontes e output reaberto |
| PDF→EPUB reflow | Texto digital, parágrafos/capítulos inferidos, OPF/nav | pypdf/pdfminer; Tesseract opt-in para scan | Ordem de leitura heurística; revisão necessária | Colunas, tabelas, ligaturas, RTL, CJK e PDF sem texto |
| PDF→EPUB fixed | Uma página raster por XHTML, rendition pre-paginated | pypdfium2 | Preserva aparência, não editabilidade/seleção/acessibilidade; pode ser grande | Número de páginas, viewport, pixels, EPUBCheck e 512 MiB |

### 5.9 Subtitles

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| SRT→VTT | Converter timestamps para milissegundos inteiros e VTT com três casas | Biblioteca padrão; pysubs2 opcional MIT | Não inventar cue settings/estilos | Round-trip da tupla `(início_ms, fim_ms, payload)` |
| VTT→SRT | Preservar timing/payload/ordem suportados e avisar perda de ID/settings/NOTE/STYLE/REGION | Parser WebVTT estrito | SRT não representa todos os recursos VTT | Fixture normativa, avisos determinísticos e ausência de arredondamento |
| SRT/VTT→TXT | Remover cabeçalho, índices e timing; manter Unicode, ordem e linhas internas | Biblioteca padrão | Perde toda temporalidade; markup é dado literal, não executável | Cue multiline, IDs, tags e texto puro |
| UI | Extensões no filtro e ações no radial/painel; múltiplos no painel | Worker e publicação comuns | Não OCRiza, transcreve, sincroniza ou muxa vídeo | Shift, Shift+F9, seleção, encoding, cancelamento e PyInstaller |

**Contrato temporal:** VTT exige UTF-8 e header `WEBVTT`; SRT possui variantes reais. Aceitar apenas variantes documentadas, rejeitar fim menor/igual ao início, timestamps inválidos e bytes ambíguos. A garantia é semântica até 1 ms, não byte a byte.

### 5.10 Archives

| Subitem | Entrada/saída e proposta | Dependências/capability gate | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|---|
| Preflight | Inspecionar manifesto, nomes normalizados, duplicatas, CRC, bytes comprimidos/declarados e orçamento antes de escrever | `zipfile`, `tarfile`, `gzip`, pathlib, tempfile | Rejeitar absoluto, UNC, drive-relative, `..`, NUL/controles, ADS, nomes reservados, trailing space/ponto | Corpus de traversal, colisão case-insensitive, nomes longos e archive corrompido |
| ZIP | Extrair manualmente para staging; criar ZIP de arquivos/pastas regulares | stdlib; ZIP64 somente sob política | Sem `extractall`; não seguir symlink/reparse; excluir destino da entrada | ZIP bomb, duplicatas, CRC, colisões, criação determinística e ausência de output parcial |
| TAR/GZIP | `tarfile` com filtro seguro e política adicional que rejeita todos links/especiais; `.tar.gz` em duas etapas | stdlib | `data_filter` não elimina todo DoS; contar stream e limitar expansão | Links, devices, FIFO, altas expansões, truncamento e espaço insuficiente |
| RAR import-only | Listar/extrair RAR3/RAR5 e repacotar membros aprovados em ZIP | rarfile ISC + 7-Zip/backend aprovado e verificado | Não criar RAR; volumes, solid, senha e RAR5 condicionais | Backend ausente/errado, volumes, senha, CRC, arquivo incompleto e hash |
| UI/worker | Archives como arquivos opacos; extração somente por ação explícita em Shift+F9 | Job Object, timeout e staging | Não executar membros, não abrir comandos, não rede | Cancelamento, kill da árvore, limpeza e SmartScreen/Defender |

**Orçamento inicial a calibrar na Fase 0:** até 100 MiB de entrada conforme limite comum, até 512 MiB expandidos conforme saída comum, até 10.000 membros, limite menor por membro, profundidade de archive aninhado zero ou um, razão de expansão limitada e verificação de espaço livre antes da extração. Falhar fechado quando o orçamento não puder ser calculado.

### 5.11 File-actions globais

| Subitem | Proposta Windows | Limitações e segurança | Testes e critério de promoção |
|---|---|---|---|
| Shift+F9 | `RegisterHotKey` + `WM_HOTKEY`; segundo radial com Shelf, Copy, Move, Copy Path e Terminal | Não usar hook/keylogger; conflito deve ser reportado | Shift/F9 isolados, repetição, conflito, unregister e foco fora do Explorer |
| Shelf | QWidget sem moldura, always-on-top opcional, QSettings para posição e somente referências de caminhos; QDrag/QMimeData com CopyAction | Apps podem rejeitar MIME; não usar MoveAction nem copiar conteúdo | Explorer→shelf→Explorer/Paint/editores, stale paths, pinagem, DPI e múltiplos monitores |
| Copy | QClipboard com CF_HDROP/file URLs para arquivos/pastas | Não é cópia de bytes; clipboard global | Colar no Explorer, Unicode, múltiplos itens, sem leitura do conteúdo |
| Copy Path | Texto Unicode, um caminho absoluto por linha, sem aspas, ordem recebida e deduplicação case-insensitive | Não abre arquivos; formato separado do clipboard de arquivos | Notepad/PowerShell, pastas, Unicode, newline Windows e duplicatas |
| Move… | Pasta existente via QFileDialog; IFileOperation em COM STA, confirmação e progresso | Destrutivo; não prometer preservação do original; sem overwrite silencioso; falha parcial detalhada | Mesmo diretório/subpasta/volume, ACL, arquivo bloqueado, cancelamento, conflito e reparse |
| Terminal | `wt.exe` com diretório inicial; fallback PowerShell por working directory | Caminho nunca vira comando; sem `-Command`, shell ou admin | Arquivo/pasta, espaços, Unicode, wt ausente e injeção |
| Validador comum | Arquivos/pastas locais existentes, revalidar identidade entre seleção e ação | Rejeitar UNC, remoto, itens virtuais, atalhos, symlink/junction/reparse e devices | Explorer/Desktop, seleção zero/uma/múltipla, item trocado e volume removível |

## 6. Dependências, licença e distribuição

### 6.1 Base Python/Qt

- Python 3.12 x64 no Windows.
- Pillow 13.0.0 — licença MIT-CMU/PIL; codecs efetivos devem ser verificados na wheel.
- pypdf 6.21.4 — BSD-3-Clause.
- PySide6-Essentials/shiboken6 6.12.0 — licença Qt aplicável; revisar módulos adicionais antes de incluir QtWebEngine/QtMultimedia.
- pywin32 — usar somente componentes/arquivos necessários; conferir licença e avisos distribuídos pelo projeto.
- PyInstaller — ferramenta de empacotamento, build Windows obrigatória; não é dependência que o usuário final deva instalar.

### 6.2 Dependências opcionais por vertical

| Dependência | Uso | Condição de habilitação | Licença/risco |
|---|---|---|---|
| pillow-heif + libheif | HEIC/AVIF | Wheel x64, DLLs, encoder/decoder e fixtures aprovados | pillow-heif BSD-3-Clause; libheif LGPL; codecs HEVC/AV1 e patentes precisam de revisão |
| OpenCV headless | Detecção facial local | Cascades/modelos com hash, sem GUI/câmera | OpenCV Apache-2.0, scripts MIT e terceiros no wheel; auditar NOTICE |
| Tesseract + traineddata | OCR | Executável/dados instalados ou empacotados de forma auditada; sem download automático | Apache-2.0 no engine; traineddata/idiomas devem ser inventariados |
| ExifTool | Metadados Image abrangentes | Executável absoluto, checksum, timeout e licença aprovada | Programa Perl/CLI externo; revisar redistribuição e avisos |
| FFmpeg/ffprobe | Video/Audio | Binários Windows pinados, capability probe, hash/build flags | LGPL com componentes GPL opcionais; escolher build coerente com distribuição e avaliar patentes |
| python-docx | DOCX | Conteúdo estruturado e pacote OOXML aprovado | MIT; lxml/typing_extensions também devem constar no SBOM |
| markdown-it-py | Markdown/CommonMark | Configuração sem HTML perigoso/plugins arbitrários | MIT; sanitização obrigatória |
| defusedxml | XML OOXML/EPUB | Parser XML seguro | Python Software Foundation License 2 |
| pypdfium2 | Render PDF | Wheel/DLLs e licenças PDFium verificadas | Apache-2.0/BSD-3-Clause e avisos PDFium |
| pdfminer.six/pdfplumber | Texto/tabelas PDF | PDF digital; revisão heurística | MIT |
| python-pptx | Criar PPTX visual | PDF→PPTX por imagem | MIT; não renderiza slides |
| openpyxl | XLSX | Planilhas; `defusedxml` para XML | MIT/Expat; não calcula fórmulas, shapes podem perder |
| odfpy | ODS | Escolher alternativa de licença aprovada | GPL-2-or-later ou Apache-2.0; selecionar/documentar Apache quando possível |
| xlrd 2.x | XLS legado | Importação somente | BSD; não grava XLS, não lê XLSX |
| Camelot | PDF→Excel opcional | Somente PDF baseado em texto e corpus aprovado | MIT; dependências extras |
| Mutagen | Metadados Audio | Se fidelidade de tags justificar | GPL-2.0-or-later; revisar compatibilidade com app GPL-3.0-only |
| QtMultimedia | Preview Audio | PySide6-Addons/backend aprovado | Licenças Qt e backend; não presumir presença em Essentials |
| LibreOffice | Documentos/Slides/Spreadsheets | Instalação configurada pelo usuário ou cópia auditada futura | MPL-2.0 e componentes; não instalar silenciosamente |
| rarfile + 7-Zip | RAR import-only | Backend absoluto, hash e licença aprovados | rarfile ISC; 7-Zip LGPL/BSD e restrições do componente unRAR |
| EbookLib | EPUB | Preferencialmente não usar no núcleo | AGPL-3.0; revisão legal obrigatória, writer próprio preferido |
| Pandoc/Calibre/WeasyPrint | Backends opcionais futuros | Apenas após threat model e empacotamento | GPL e dependências nativas; não são requisitos do primeiro release |

### 6.3 Regras de release e licenciamento

- Manter SBOM com pacote, versão, hash, origem, DLLs, encoders, build flags e licença.
- Atualizar `THIRD_PARTY_NOTICES` e diretório de licenças para qualquer wheel, binário, fonte, traineddata, PDFium ou codec distribuído.
- Não adicionar ImageMagick ou PyMuPDF/fitz por padrão sem revisão específica de superfície de comandos, licença AGPL/comercial e distribuição.
- Não usar `pi-heif` descontinuado/vulnerável.
- Não instalar FFmpeg, LibreOffice, Tesseract, 7-Zip ou componentes Apple automaticamente durante o job.
- Não assumir que uma build “gratuita” é legalmente adequada: H.264, AAC, MP3, HEVC, AV1, WMA e outros codecs podem envolver patentes/licenças por jurisdição.
- Para FFmpeg, escolher deliberadamente uma build LGPL ou GPL compatível com a licença do produto, documentar configuração e fornecer os avisos/fontes correspondentes quando necessário.
- Para programas externos, o produto deve aceitar caminho configurado e verificar versão/hash; ausência torna a ação indisponível, não substituída por outro backend não testado.

## 7. Limites, qualidade e mensagens de perda

### 7.1 Limites globais a preservar/revisar

- Entrada comum inicial: até 100 MiB.
- Saída comum inicial: até 512 MiB.
- Imagem inicial: até 40 megapixels.
- PDF inicial: 1–200 páginas.
- Legendas: até 100 MiB, 100 itens de seleção e limite adicional de cues/payload.
- Archives: limites separados de membros, bytes comprimidos, bytes expandidos, profundidade e razão de expansão.
- Video/Audio: quotas próprias de duração, frames, streams, resolução, sample count, CPU, memória e tempo; não aplicar limites de imagem cegamente.
- Canvas/collage: limites de largura, altura, pixels, camadas, imagens e memória antes de alocar.
- XML/OOXML/EPUB: profundidade, entidades, membros, bytes expandidos, relações externas e tempo.

### 7.2 Mensagens obrigatórias

- “Codec não disponível neste pacote; nenhuma conversão alternativa foi executada.”
- “O tamanho-alvo é uma tentativa aproximada, não uma garantia.”
- “A saída foi rasterizada; texto, vetores, camadas ou elementos editáveis não foram preservados.”
- “A operação pode perder metadados, perfil ICC, HDR, orientação, capítulos, anexos, fórmulas, macros, fontes ou tags; revise a lista antes de confirmar.”
- “Remover metadados não certifica anonimização; pixels, dados ocultos, thumbnails, anexos ou informações de container podem permanecer.”
- “Blur é reversível por inferência; para cobertura forte, use preenchimento opaco e revise todos os frames/áreas.”
- “Resultado OCR/reconstruído é best-effort e requer revisão humana.”
- “Move é destrutivo e não segue a garantia de preservação do original das conversões.”

## 8. Plano de testes transversal

### 8.1 Segurança de caminhos e execução

- Extensão divergente da assinatura, vazio, truncado, corrupto, conteúdo inesperado e múltiplos frames/streams.
- Caminhos Unicode, espaços, aspas, `&`, `%`, `;`, newline, nomes reservados, ponto/espaço final e caminhos longos conforme suporte do Windows.
- UNC, unidade remota/mapeada, URI, device path, symlink, hard link, junction, mount point, qualquer reparse point, item virtual e atalho.
- Troca da fonte entre probe e execução, colisões concorrentes, arquivo bloqueado, permissão insuficiente, disco cheio e saída já existente.
- Confirmar `shell=False`, lista de argumentos, caminho absoluto permitido, sem shell/PowerShell gerado, sem macro, sem rede e sem administrador.
- Cancelamento/timeout mata worker e descendentes, limpa somente o staging próprio e não publica saída parcial.
- Diagnóstico não expõe comandos internos, dados sensíveis ou caminhos de terceiros além do necessário.

### 8.2 Integridade e publicação

- Hash e bytes do original antes/depois.
- Publicação exclusiva/atômica e recuperação de colisões.
- Reexecução não sobrescreve resultados anteriores.
- Falha de um item não publica resultado dos outros quando a operação exige atomicidade de conjunto.
- Output reaberto e validado pelo backend: imagem, ffprobe, pypdf/qpdf check, XML/OOXML, EPUBCheck, parser de legenda ou manifest de archive.

### 8.3 Windows real

- Windows 10 Pro 22H2 x64 não administrativo, máquina limpa e máquina com dependências opcionais ausentes.
- Explorer e Desktop, seleção única/múltipla, tray, Shift, Shift+F9, foco em outros aplicativos, hotkey em conflito.
- Clipboard CF_HDROP, drag-and-drop, shelf, IFileOperation, Terminal, QClipboard e QFileDialog.
- DPI alto, múltiplos monitores, Unicode, volumes locais, arquivo grande, Defender/SmartScreen e PyInstaller.
- Codec HEIC/AVIF com e sem extensões Microsoft; essas extensões são opcionais para o app e não substituem libheif auditado.
- Qt offscreen/Linux pode cobrir lógica e layout, mas **não é aceite** para Shell COM, bandeja, hotkey global, OLE, codecs Windows, PyInstaller, Defender ou SmartScreen.

### 8.4 Regressão por vertical

- Image: PNG/JPEG/WebP/TIFF/BMP/AVIF/HEIC, alpha, ICC, orientação, metadados, 40 MP, decompression bombs.
- Video: CBR/VFR, áudio ausente/múltiplo, B-frames, PTS não zero, crop, trim, velocidade, split, redaction e players.
- Audio: PCM bit-exato, loudnorm, sample boundaries, silêncio, canais, clipping, visualizer e bleep.
- PDF: digital/scan/protegido, colunas, tabelas, fontes, rotação, content streams grandes, anexos/JS e render 300 DPI.
- Documents: CommonMark, HTML ativo, OOXML malicioso, DOCX/EPUB ZIP bombs, UTF-16, macro/OLE e LibreOffice opt-in.
- Slides: PPT legado, PPTX, fontes, proporção, transparência, PDF intermediário e diff visual.
- Spreadsheets: CSV injection, fórmulas, XLS legado, ODS/XLSX, paginação e PDF→Excel.
- EPUB: container/OPF/spine/nav, links, CSS, scripts, fixed-layout, OCR e EPUBCheck.
- Subtitles: timestamps 1 ms, VTT settings, perdas SRT, encoding, cues inválidas e round-trip semântico.
- Archives: traversal, links, devices, ZIP/TAR/GZIP bombs, duplicatas, RAR3/RAR5/volumes/senha e extração confinada.
- File-actions: hotkey, clipboard, path, shelf, Move, Terminal, reparse, ACL e conflitos.

## 9. Critérios de saída da roadmap

O roadmap pode ser considerado pronto para uma release somente quando:

1. cada ação estiver explicitamente vinculada a uma fase e capability gate;
2. a matriz de formatos declarar entradas, saídas, codecs e combinações realmente testadas;
3. nenhuma funcionalidade Apple for dependência, atalho de implementação ou fallback oculto;
4. Shift e Shift+F9 forem distintos e consistentes em todas as verticais;
5. originais permanecerem intactos em todas as conversões e operações não destrutivas;
6. Move for claramente separado, confirmado e documentado como destrutivo;
7. limites Windows de memória/CPU/processos forem aplicados ou a ação for desabilitada por falta de isolamento;
8. licenças, patentes, binários, wheels, traineddata, codecs e avisos estiverem auditados;
9. a suíte Windows 10 Pro 22H2 passar em máquina real, além dos testes Linux auxiliares;
10. documentação de perdas, revisão humana, OCR, redaction, metadados e best-effort estiver visível antes da confirmação;
11. não existir item classificado como pronto apenas porque funciona no Sandbox Linux ou porque um backend externo aceita o arquivo;
12. nenhum recurso for promovido sem teste de falha, cancelamento, timeout, colisão, disco cheio e dependência ausente.

## 10. Referências e materiais de partida

- Feature spec: `/home/ubuntu/upload/LEVANTAMENTODEFUNCIONALIDADESISTEM.md`.
- Código e documentação consultados como contexto: `/home/ubuntu/local-file-toolkit-mvp/Desktop/engine.py`, `runner.py`, `radial_menu.py`, `tray_app.py`, `windows_bridge.py`, `requirements.txt`, `README.md`, `RELEASE.md`, `THIRD_PARTY_NOTICES.md`, `tests/`.
- Pillow: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
- pillow-heif/libheif: https://github.com/bigcat88/pillow_heif e https://github.com/strukturag/libheif
- pypdf: https://pypdf.readthedocs.io/
- ExifTool: https://exiftool.org/
- OpenCV/Tesseract: https://docs.opencv.org/4.x/db/d28/tutorial_cascade_classifier.html e https://tesseract-ocr.github.io/tessdoc/Installation.html
- FFmpeg/ffprobe/legal: https://ffmpeg.org/ffmpeg.html, https://ffmpeg.org/ffprobe-all.html e https://ffmpeg.org/legal.html
- WebM: https://www.webmproject.org/docs/container/
- Python subprocess/tempfile/zipfile/tarfile: https://docs.python.org/3/library/subprocess.html, https://docs.python.org/3/library/tempfile.html, https://docs.python.org/3/library/zipfile.html e https://docs.python.org/3/library/tarfile.html
- Windows Shell/clipboard/hotkey/IFileOperation/Job Objects: documentação Microsoft em https://learn.microsoft.com/en-us/windows/win32/shell, https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey e https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Qt drag/clipboard/preview: https://doc.qt.io/qt-6/qmimedata.html, https://doc.qt.io/qt-6/qclipboard.html, https://doc.qt.io/qt-6/dnd.html e https://doc.qt.io/qt-6/qimagereader.html
- python-docx/python-pptx/openpyxl/pdfplumber/pypdfium2: documentação e repositórios oficiais dos projetos; licenças devem ser conferidas na versão pinada antes da distribuição.
- EPUB 3.3: https://www.w3.org/TR/epub-33/
- WebVTT: https://www.w3.org/TR/webvtt1/
- LibreOffice filtros e licenças: https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html e https://www.libreoffice.org/licenses/
- 7-Zip e rarfile: https://www.7-zip.org/ e https://github.com/markokr/rarfile
