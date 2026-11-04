# Arquivo Local 0.9.45-phase2-dev — Áudio: canais

## Novidades da 0.9.45 (categoria Áudio, item 5)
- Nova ferramenta Áudio › Ajustar › **Canais** (`Audio Channels`): mono (mistura), estéreo (surround vira estéreo; mono é duplicado), só o canal esquerdo ou só o direito. Recodifica no mesmo formato (MP3, M4A, FLAC, OGG, Opus, WAV, AIFF) mantendo etiquetas e, em MP3/M4A/FLAC, a capa. Saída `-mono`, `-estereo`, `-esquerdo` ou `-direito`.
- **Avisos medidos de verdade:** fase (o mono ficou mais de 6 dB abaixo do estéreo → aviso; quase mudo ou mudo → o app **recusa** e sugere esquerdo/direito) e clipping (mistura de surround acima de 0 dBFS → volume reduzido o mínimo e avisado). Os avisos aparecem no relatório do resultado.
- Os avisos voltam do worker (`notes`), sem mudar o formato das saídas; módulo novo `audiochannels.py`; `tests/test_audiochannels.py` (39 testes, FFmpeg real).
- Roda do Áudio com 3 grupos: Ler, Converter, Ajustar.

# Arquivo Local 0.9.44-phase2-dev — Áudio: metadados

## Novidades da 0.9.44 (categoria Áudio, item 4)
- Nova ferramenta Áudio › Ler › **Metadados** (`Audio Tags`): edita título, artista, álbum, artista do álbum, data, gênero, faixa, disco, compositor e comentário; remove a capa; ou limpa tudo (etiquetas, capa e capítulos). O áudio é **copiado sem recodificar** (o hash do áudio decodificado é igual ao original). Campos que o app não edita são mantidos.
- MP3, M4A, FLAC, OGG, Opus, WAV e AIFF; saída `-etiquetas`, sem sobrescrever. Conferência do resultado (codec, duração, campos, capa) antes de salvar; se o formato não guarda um campo (ex.: gênero no AIFF) nada é salvo e o app diz qual.
- Limite conhecido: OGG/Opus com capa embutida só podem ser reescritos removendo a capa (limitação do FFmpeg).
- A tela de **Informações** agora mostra também as outras etiquetas do arquivo e a capa de OGG/Opus.
- Módulo novo `audiotags.py`; `tests/test_audiotags.py` (39 testes, FFmpeg real).

# Arquivo Local 0.9.43-phase2-dev — Áudio: base, informações e conversão

## Novidades da 0.9.43 (categoria Áudio, itens 1 a 3)
- **Base de mídia** (`mediatools.py`): localiza FFmpeg/ffprobe, confere a licença do build (o pacote só embute build LGPL) e lê arquivos sem shell, com tempo e tamanho máximos. `python tools/doctor.py` mostra o estado.
- **Áudio › Ler › Informações**: duração, codec, taxa, canais, taxa de bits, etiquetas e capa; vários arquivos; leitura no worker.
- **Áudio › Converter › Converter** (`Convert Audio`): MP3, M4A (AAC), FLAC, OGG (Vorbis), Opus, WAV e AIFF; qualidade baixa/média/alta; manter ou remover etiquetas; áudio de vídeos; relatório de perdas; conferência do resultado (codec, duração) antes de salvar; saída `-convertido`, sem sobrescrever. Entrada de até 512 MiB.
- Segurança: `-protocol_whitelist file` e `-format_whitelist` (listas de reprodução não abrem outros arquivos); o mesmo vale para a leitura de informações.
- A categoria Áudio ganhou **roda em grupos** (Ler, Converter); a roda do PDF foi reorganizada em 5 grupos e há um teste que barra rodas com mais de 8 fatias ou rótulos com mais de 13 caracteres.
- Correção visual: o rótulo de fatia com seta («CONVERTER ›») era medido sem a seta e podia ficar cortado.
- Testes novos: `test_mediatools.py`, `test_audio_stage.py`, `test_audioconvert.py`, `test_wheel_layout.py`, `test_doctor.py`. **Testar no Windows** com um FFmpeg LGPL real (versão a fixar; ver THIRD_PARTY_NOTICES).

# Arquivo Local 0.9.42-phase2-dev — Portão B da categoria PDF

## Novidades da 0.9.42 (fim da categoria PDF)
- `tools/quality_suite.py` ganhou o **corpus de PDFs** (texto com marcadores/metadados/anexo, escaneado, formulário, com senha, truncado, corrompido, falso, 200 e 201 páginas, página gigante, JavaScript/anexos, rotação + CropBox, 50 páginas, e PDF gerado pelo LibreOffice quando há `soffice`) e 8 seções novas: invariantes (original intacto, sem parciais, sem rede), fidelidade (texto e SSIM antes/depois), redação (sem vazamento em bytes, fluxos, texto, metadados; OCR sobre o resultado), robustez, geometria (páginas giradas/CropBox), senha, OCR e desempenho (tempo por página e memória).
- Relatório com **nota 0–100 por função**; aprovação exige nenhuma abaixo de 80 e nenhuma falha bloqueante. Novos: `--only pdf|images|all`.
- Correção na suíte: `identical()` usava `getbbox()` em RGBA, que só olha o canal alfa, e dava «idêntico» a imagens opacas diferentes; agora compara todos os canais (as verificações de Imagens continuam passando).
- 7 testes novos (`tests/test_quality_pdf.py`), incluindo uma execução completa `--only pdf --fast`. Resultado no Linux: 117 verificações de qualidade passam, nenhuma função abaixo de 100. **Windows ainda por verificar.**

# Arquivo Local 0.9.41-phase2-dev — Preencher formulário e assinatura visual

## Novidades da 0.9.41 (categoria PDF, item 13)
- Nova ferramenta PDF › **Preencher e assinar** (`Fill PDF`): lista os campos AcroForm (texto, caixa, opção única, lista), preenche, opcionalmente **achata** (valores viram parte da página, campos removidos) e coloca uma **imagem de assinatura** em áreas marcadas, com transparência e páginas giradas. Aviso permanente: não é assinatura digital certificada.
- Conferência do resultado (páginas, valores gravados, campos removidos ao achatar, imagem presente). Saída `-preenchido`. Módulo novo `pdfform.py`; `inspect_pdf` passa a trazer `form_fields`. Sem dependências novas.
- 26 testes novos (`tests/test_pdf_form.py`, fixture em `tests/formfixture.py`). Só Linux; **testar no Windows** e com formulários reais (governo, bancos).

# Arquivo Local 0.9.40-phase2-dev — Tarjar conteúdo do PDF

## Novidades da 0.9.40 (categoria PDF, item 12)
- Nova ferramenta PDF › **Tarjar conteúdo** (`Redact PDF`): áreas marcadas na página, termos e padrões (CPF, CNPJ, e-mail, telefone). Páginas afetadas viram imagem com tarjas pintadas nos pixels (150/200/300 dpi); as demais são copiadas sem mudança.
- Segurança: o texto sob a tarja não existe mais no arquivo; marcadores, anexos, formulários e metadados são removidos; **conferência automática** (sem texto nas páginas tarjadas, tarja preta, sem o termo nas outras páginas, sem restos do documento) — se falhar, nada é salvo. Saída `-tarjado`.
- Módulo novo `pdfredact.py`; `PdfStage` ganhou modo de seleção de áreas. Tempo limite longo (como OCR e Comprimir). 25 testes novos (`tests/test_pdf_redact.py`). Só Linux; **testar no Windows**.

## Novidades da 0.9.39 (categoria PDF, item 11)
- Novas ferramentas PDF › **Proteger com senha** (`Protect PDF`, AES-256, restrições opcionais com senha de permissões) e **Remover senha** (`Unprotect PDF`, uma tentativa com a senha informada; restrições só com a senha de proprietário).
- Segurança: senha só no JSON de stdin do worker, fora de relatório/mensagens/histórico, campos mascarados e limpos ao iniciar; sem tentativa de adivinhar ou quebrar senha.
- Dependência nova: `cryptography` 50.0.2 (+ cffi, pycparser), licenças em `licenses/` e `THIRD_PARTY_NOTICES.md`; PyInstaller com `--hidden-import cryptography`.
- 12 testes novos (`tests/test_pdf_password.py`). Só Linux; **testar no Windows** (wheel do cryptography e empacotamento).

## Novidades da 0.9.38 (categoria PDF, item 10)
- Nova ferramenta PDF › **Numerar / carimbar** (`Stamp PDF`): numeração, texto de cabeçalho/rodapé e marca d'água, com `{n}` e `{total}`, intervalo de páginas, primeiro número, 9 posições, margem, cor, negrito, opacidade e marca diagonal.
- Texto vetorial Helvetica (sem embutir fonte): selecionável, arquivo quase não cresce; só alfabeto latino/cp1252. Correto em páginas giradas e com CropBox.
- Módulo novo `pdfstamp.py`. Conferência do resultado (páginas e texto). Saída `-numerado`, `-carimbado` ou `-marcadagua`.
- Limites: sem prévia do carimbo na página; a marca d'água fica por cima e é removível; assinaturas digitais ficam inválidas.
- 15 testes novos (`tests/test_pdf_stamp.py`). Só Linux.

## Novidades da 0.9.37 (categoria PDF, item 9)
- Nova ferramenta PDF › **Comprimir** (`Compress PDF`, opção `pdf_level` = `light`/`medium`/`strong`): reduz imagens pela resolução efetiva e recodifica em JPEG; saída `<nome>-comprimido.pdf`.
- Nunca aumenta: exige ganho de pelo menos 1 %; senão nada é salvo e a mensagem sugere outro nível.
- Módulo novo `pdfcompress.py` (núcleo sem Qt); tempo de job de 900 s para compressão e OCR de PDF.
- Limites: fotos perdem qualidade; assinaturas digitais ficam inválidas; imagens com máscara, CMYK, paleta ou em blocos internos não são tocadas.
- 12 testes novos (`tests/test_pdf_compress.py`). Só Linux.

## Novidades da 0.9.36 (categoria PDF, item 8)
- Nova ferramenta PDF › **Metadados** (`Clean PDF`): mostra Info, XMP, anexos, JavaScript e formulário; **cópia limpa** `<nome>-limpo.pdf` com remoção à escolha (`meta_info`, `meta_attach`, `meta_js`).
- Remoção em duas passadas e conferência do arquivo gerado; sem nada a remover, o erro explica e nada é salvo.
- Limites: EXIF dentro de imagens permanece; assinaturas digitais ficam inválidas; cálculos por script em formulários deixam de funcionar.
- 11 testes novos (`tests/test_pdf_clean.py`). Só Linux.

## Novidades da 0.9.35 (categoria PDF, item 7)
- PDF › **OCR → PDF pesquisável** e **OCR → texto**: páginas desenhadas a 300 dpi, reconhecidas pelo Tesseract (offline), com seleção de páginas, idioma e modo de página.
- Páginas que já têm texto são puladas por padrão (não contam no limite de 20 páginas por vez); desligue para reconhecer tudo.
- Resultado só com as páginas escolhidas: `<nome>-pesquisavel.pdf` (páginas reconhecidas viram imagem JPEG + texto invisível), `<nome>-ocr.txt` ou pasta «<nome> - texto».
- Erros claros: sem Tesseract/idioma, páginas já com texto, limite de páginas, nenhum texto reconhecido (nada é salvo).
- Tempo máximo do job de OCR de PDF: 900 s. 14 testes novos.
- Limites: marcadores, anexos, formulários e assinaturas não são preservados; verificado só no Linux.

## Novidades da 0.9.34 (categoria PDF, item 6)
- **PDF → texto:** opções `text_mode` (`single`/`marks`/`pages`), `text_layout` (`simple`/`layout`) e `pdf_pages`; um arquivo por página vai para «<nome> - texto». **Mudanças de comportamento:** sem texto nas páginas escolhidas agora dá erro explicativo (antes salvava um arquivo vazio) e o nome padrão passou de `<nome>-converted.txt` para `<nome>-texto.txt`.
- **Imagens embutidas** (`Extract PDF Images`): PDFium (`get_objects` + `extract`) copia JPEG/JPEG 2000 sem recomprimir e converte o resto para PNG; deduplica por hash, ignora imagens menores que `img_min` (padrão 32 px), limites de 40 MP por imagem, 500 imagens e 512 MiB; pasta «<nome> - imagens».
- Painel: controles e avisos nas duas ferramentas; atalho «Imagens do PDF» na lista de ferramentas de PDF.
- 19 testes novos (`tests/test_pdf_extract.py`) e 3 antigos ajustados. Só Linux; Windows pendente desde a 0.9.6.

## 0.9.33 — Organizar páginas
### Novidades da 0.9.33 (categoria PDF, item 5)
- Nova operação **Organizar páginas** (`Organize PDF`): opção `organize_pages` = lista de `"página:giro"` (giro 0/90/180/270, 1 a 200 itens, na ordem final; página ausente = excluída; repetida = duplicada). Validada no motor e no controlador (um PDF por job).
- Widget novo `page_organizer.py` (`PageOrganizer`): miniaturas em lotes (a prévia do worker ganhou o parâmetro `first`), arrastar/girar/duplicar/excluir/mover/restaurar, estado = a própria lista de itens. Respostas de pedidos antigos são descartadas; threads guardadas até terminarem.
- Painel: nova área (`STAGE_ORGANIZE`), botões, resumo, botão de salvar bloqueado até haver mudança; trocar de ferramenta descarta as edições.
- Saída `<nome>-organizado.pdf`; relatório de perdas (marcadores, anexos, formulários, assinaturas; aviso de duplicadas).
- 15 testes novos (`tests/test_organize_pdf.py`). Só Linux; Windows pendente desde a 0.9.6.

## 0.9.32 — Dividir e extrair páginas
### Novidades da 0.9.32 (categoria PDF, item 4)
- **Dividir/extrair PDF** com modos `each`, `every` (N páginas), `ranges` (grupos `1-3; 4-6; 7-`) e `extract` (opções `split_mode`, `split_every`, `split_ranges`), validadas no motor e no controlador.
- Várias partes vão para «<nome> - partes» (`pagina-001`/`parte-001`); a extração gera `<nome>-extraido.pdf`. O runner publica a pasta só depois que o worker termina (mesmo mecanismo do PDF → imagens, agora genérico: `engine.output_group_suffix`/`publish_group`).
- Marcadores das páginas copiadas preservados; relatório de perdas por modo.
- Painel: modo, páginas por parte, intervalos e resultado (quantos PDFs saem); botão bloqueado com entrada inválida. A prévia do PDF único agora também avisa o painel (`infos_ready`).
- **Mudança de comportamento:** «Separar» passou a criar a pasta «- partes» (antes soltava `<nome>-page-N.pdf` ao lado do original).
- 15 testes novos (`tests/test_split_pdf.py`); suíte: 842 testes, 3 pulados. Só Linux; Windows pendente desde a 0.9.6.

## 0.9.31 — Unir PDFs melhorado
### Novidades da 0.9.31 (categoria PDF, item 3)
- **Unir PDFs** com ordem arrastável, intervalo de páginas por arquivo (opção `merge_ranges`, um texto por arquivo, validado no motor e no controlador), marcador por arquivo preservando os marcadores existentes, total de páginas e bloqueio do botão no painel, prévia do arquivo selecionado.
- Saída `unido.pdf` (antes `merged.pdf`); relatório de perdas atualizado (marcadores, intervalos, formulários/anexos/assinaturas).
- `PdfStage` ganhou `set_paths`/`select_path`/`hide_list` para reordenar sem reler os PDFs.
- 13 testes novos (`tests/test_merge_pdfs.py`); suíte completa verde. Verificado só no Linux; Windows segue pendente desde a 0.9.6.

## 0.9.30 — PDF → imagens
### Novidades da 0.9.30 (categoria PDF, item 2)
- Nova operação **PDF → imagens** (`PDF → Images`): resolução 72–600 dpi, intervalo de páginas (`1-3,7`, `5-`), formato de saída reaproveitado (PNG, JPEG, WebP, TIFF, BMP, GIF, AVIF, HEIC; ICO recusado), teto de 40 MP por página com mensagem em português que sugere o dpi máximo, até 200 páginas e 512 MiB de saída.
- Saída em pasta nova «<nome> - páginas» com `pagina-001…`; criada pelo runner só depois de todas as páginas prontas e desfeita se a publicação falhar.
- Painel: controles de resolução, páginas e tamanho em pixels; botão bloqueado com intervalo inválido ou página acima de 40 MP. Menu radial do PDF ganhou «Imagens». Novo ícone `image`.
- Opções novas na lista branca do controlador: `pdf_dpi` (inteiro) e `pdf_pages` (texto).
- 20 testes novos (`tests/test_pdf_images.py`); suíte: 814 testes, 3 pulados. Verificado só no Linux; Windows segue pendente desde a 0.9.6.

## 0.9.29 — Categoria PDF: base

### Novidades da 0.9.29 (categoria PDF, item 1: base)

- **Prévia dos PDFs no painel:** resumo do arquivo (páginas, papel, tamanho, versão, camada de texto, indícios de formulário/JavaScript/anexos), **página grande** e **faixa de miniaturas** (24 primeiras páginas; clicar abre a página maior). Com vários PDFs, lista com páginas/tamanho e total; clicar abre a prévia daquele arquivo. Aparece em todas as ferramentas de PDF (Extrair texto, Separar, Unir).
- **Leitura segura em módulo próprio** `pdfinfo.py` (núcleo, sem Qt): `inspect_pdf`, `open_reader`, `render_pages`, `run_op`. Limites: 100 MiB, 200 páginas, página até 14 400 pt, 12 milhões de pixels por página desenhada, 24 miniaturas por pedido. Cabeçalho `%PDF-` conferido (aceita lixo nos primeiros 1024 bytes), senha reconhecida e recusada, truncado/corrompido com mensagem em português. Formulários e anotações **não** são desenhados; JavaScript e anexos são só detectados (pela estrutura do documento, não por busca de texto), nunca executados.
- **A interface nunca abre o PDF:** o painel pede ao **worker descartável** (`runner.run_pdf_op`, op `pdf_info`/`pdf_preview`; mesma isolação, limites de memória/CPU e Job Object do Windows das conversões); as miniaturas voltam como PNG por uma pasta temporária privada que some ao fim. Respostas de pedidos antigos são ignoradas (troca de arquivo/página).
- **Unir, Separar e Extrair texto** passaram a usar as mesmas verificações (`engine.read_pdf` → `pdfinfo.open_reader`); o erro cita o nome do arquivo.
- Painel: nova área `pdf_stage.py` (`PdfStage`); categoria PDF descrita como «Ver páginas, extrair texto, separar e unir». Sem `pypdfium2` a prévia avisa e o resumo continua.
- **Sem pacote novo** (usa `pypdf` e `pypdfium2`, já no `requirements.txt`). O grupo da roda para PDF (Páginas, Converter, Proteger, Ler texto, Otimizar) entra quando cada grupo tiver ao menos duas ferramentas (itens 2 a 13 do plano).
- Testes novos: `tests/test_pdfinfo.py` (28) e `tests/test_pdf_stage.py` (12). Total: **794** (3 pulados). Verificado só no Linux (capturas de tela em modo offscreen); **não executado no Windows**.
- Armadilhas: PDF só com páginas brancas some no fundo da lista (miniaturas têm contorno); o Qt tingia de azul o ícone selecionado (cada modo de ícone recebe a mesma imagem); `QThread` ativo destruído derruba o programa (as threads ficam guardadas até acabar); conectar sinais a `lambda` que captura widgets evitado.

## Novidades da 0.9.28

- **Editor de recorte («Ampliar editor…»):** agora tem as **proporções** do painel (Livre, Original, 1:1, 4:3, 3:2, 16:9, 9:16), botão **Limpar seleção**, texto com tamanho **e posição** do recorte (ex.: «150 × 150 px, a partir de (85, 40) numa imagem de 480 × 320 px»), botão principal laranja «Aplicar recorte» e as mesmas cores do painel. As proporções ficam em `visual_tools.ASPECTS`, usadas pelo painel e pelo editor.
- **Lista da colagem:** linhas mais altas, item selecionado no laranja do sistema (antes, azul padrão do Qt), espaçamento entre itens e dica de arrastar; arrastar para reordenar já funcionava (0.9.26) e continua testado.
- **Estilo de listas** do painel agora é igual em todas as telas (seleção e passagem do mouse).
- **Barra de status:** «1 arquivo» / «N arquivos» (antes «arquivo(s)»).
- **Bug corrigido:** «Limpar seleção» no painel de recorte não zerava os campos (o `bool` do clique virava `emit=False`). Teste de regressão incluído.
- Testes novos: `tests/test_ui_polish.py` (6). Total: **754** (3 pulados). Verificado só no Linux (capturas de tela em modo offscreen).

## Novidades da 0.9.27 — Pasta numerada para várias imagens

## Novidades da 0.9.27

- **Várias imagens → uma pasta numerada.** Ao escolher 2 ou mais imagens (de formatos diferentes, se quiser) e converter, o resultado vai para uma **pasta nova** «Convertidas AAAA-MM-DD HH-MM-SS», criada ao lado do primeiro arquivo, com os nomes **001, 002, 003…** na **ordem da seleção** (ex.: `001.png`, `002.png`). Vale para as conversões das rodas (Shift e Shift+F9, quando há mais de um arquivo) e para as ferramentas do painel, onde a caixa «Salvar tudo numa pasta nova» vem marcada com 2+ arquivos e pode ser desmarcada. Com um padrão de nome próprio («viagem»), vira `viagem-001.png…` (o «-{n}» é acrescentado se faltar); «Primeiro nº» define o começo; os dígitos crescem sozinhos (mínimo 3).
- Nunca reaproveita pasta existente nem sobrescreve; os originais não mudam; se todas as conversões falharem ou forem canceladas, a pasta vazia é removida (pasta com resultados nunca é apagada). Colagem, PDF único e operações de PDF não usam isso (geram um arquivo só).
- Núcleo em `engine.py` (`create_batch_folder`, `batch_rename_options`, sem Qt); fila em `tray_app.py` (opção interna `to_folder`).
- Testes novos: `tests/test_batch_folder.py` (15). Total: **748** (3 pulados). Verificado só no Linux.

## Novidades da 0.9.26 — Fechamento da categoria Imagens

Atualização experimental do código-fonte, sem certificação Windows nem release pública.

## Novidades da 0.9.26 (auditoria e fechamento de Imagens)

- **Erros reais achados pela nova suíte de qualidade e corrigidos:** (1) a conversão rápida para **WebP ignorava «qualidade»** (usava 80 sempre; agora respeita, e 100 é sem perdas); (2) arquivo de imagem **truncado, falso ou ilegível** gerava erro técnico em inglês; agora a mensagem é em português e cita o arquivo. Ambos têm teste de regressão (`tests/test_quality_regressions.py`).
- **Suíte de qualidade de imagem** (`tools/quality_suite.py`; 70 verificações; PSNR/SSIM, orientação, privacidade por estrutura do arquivo, geometria, ajustes, anotações, compressão, colagem/PDF, robustez, determinismo, SVG, remoção de fundo, OCR e desempenho em 12 MP). `--corpus PASTA` grava os arquivos de teste sintéticos; `--fast` pula a parte pesada. Resultado no Linux: 70/70.
- **Design do painel:** o botão principal fica **fixo** fora da rolagem; controles da ferramenta vêm antes dos comuns (formato, qualidade, nome); dica abaixo do formulário; chips longos quebram linha sem corte; lista da colagem maior e **reordenável arrastando**; **«Ver prévia do resultado»** na remoção de fundo (xadrez).
- **PDF único com texto pesquisável** (OCR; só com página «Do tamanho da imagem», até 20 imagens, 300 dpi; página sem texto fica só como imagem; A4/Carta + OCR é recusado com explicação).
- **Job Object do Windows** (`winjob.py`, ctypes): o worker fica limitado a 3 GiB por processo, 4 processos e 170 s de CPU, e morre junto com o painel. **Nunca executado no Windows.**
- **Kit de instalação** (`instalador/`): `build_windows.ps1` (testes → qualidade → PyInstaller → verificação → Inno Setup), `ArquivoLocal.iss` (por usuário, sem administrador, só HKCU, iniciar com o Windows e menu de clique direito desligados por padrão) e `LEIA-ME-INSTALACAO.md`. **Escrito no Linux; nunca compilado nem executado no Windows.**
- Diagnóstico do Windows: item novo `[0.9.26]`.
- Testes novos: `test_winjob` (7), `test_quality_regressions` (7), `test_drag_reorder` (3), `test_onepdf_ocr` (10), `test_installer_kit` (6).
- **Fora desta entrega (decisão consciente):** editar/mover formas já desenhadas, várias anotações de texto, curvas, correção de orientação no OCR, transparência EMF/WMF via GDI+, `.pdf` como entrada de imagem (pertence à categoria PDF), assinatura de código, ícone `.ico`. Cosméticos conhecidos: a fileira de abas rola e corta a última em janelas ≤ 900 px; o rótulo «TRANSFORMAR ›» usa fonte menor; a barra de status diz «1 arquivo(s)».
- **Evidência:** tudo verificado só no Linux. A última execução no Windows foi a da 0.9.6 (204/206). As versões 0.9.7–0.9.26 ainda precisam rodar no Windows.

## Novidades da 0.9.25

- **Remoção de fundo** (item 16 do plano; **o item 15, EPS/Ghostscript, foi descartado pelo usuário em 28/10/2026**): ferramenta «Sem fundo» (`Remove Background → PNG`) no grupo Ajustes. A imagem é reduzida a 320×320, a rede **U²-Net** devolve o mapa do objeto principal, que é ampliado e vira o canal alfa; a transparência que a imagem já tinha é mantida; as cores não mudam. Opções: modelo (`bg_model`: «Leve» `u2netp`, padrão; «Preciso» `u2net`) e «Borda suave» (`bg_feather`, 0–10 px, padrão 2). Aceita todas as entradas (inclusive SVG/.ai) e os formatos de saída das demais ferramentas; em JPEG/BMP o fundo transparente vira o «Fundo opaco».
- Núcleo `bgremove.py` (sem Qt, em `CORE_MODULES`; erros `BgError` → `ConversionError`): lista fechada de modelos com **SHA-256 e tamanho** conferidos **antes** de carregar (arquivo trocado é recusado), sessão do ONNX Runtime com 1 thread e sem arenas, importações preguiçosas, mensagem clara se faltar pacote ou modelo; **nada é baixado**. Modelo leve em `models/u2netp.onnx` (empacotado); `u2net.onnx` opcional na mesma pasta.
- **Licenças:** código e pesos do U²-Net são Apache-2.0; ONNX Runtime é MIT; NumPy é BSD-3. Pacotes novos: `numpy==2.5.3` e `onnxruntime==1.29.0` (wheels Windows x64 e Linux conferidos). **O IS-Net (`isnet-general-use`) foi excluído de propósito**: foi treinado no DIS5K, cujos termos permitem só uso não comercial e proíbem redistribuição (li o PDF dos termos). **Pendência jurídica:** os pesos do U²-Net foram treinados no DUTS-TR e seus termos não foram revistos.
- Resultado totalmente vazio (nenhum objeto) não é salvo; o relatório de perdas avisa que cabelos finos, vidro, sombras e imagens com vários objetos podem sair errados.
- Medidas (Linux, 1 thread, worker com limite de 1,5 GiB de memória virtual): `u2netp` 0,8 s em 640 px e 2,0 s em 32 MP (≤ 583 MiB); `u2net` 2,1 s em 640 px e 3,1 s em 35 MP (≤ 1 047 MiB). Com 40 MP o `u2net` fica perto do limite de memória do worker.
- Painel: modelo, borda suave e aviso quando falta modelo ou pacote (o botão fica desabilitado); `package.py` coleta `onnxruntime`/`numpy`, empacota `models/` e registra as versões.
- Testes: `tests/test_bgremove.py` (27 casos; os que rodam a rede pulam sem onnxruntime/modelo): tabela de modelos, hash, tamanho/conteúdo trocados, modelo/pacote ausente, opções, relatório, imagem real (objeto opaco, fundo transparente, cores intactas), alfa preexistente, paleta/cinza/1×1, PNG e JPEG, original intacto, nunca sobrescreve, resultado vazio, worker e foto de 40 MP no worker, painel. Total: **698** (3 pulados).
- Diagnóstico do Windows: item novo `[0.9.25]`.
- Fora desta entrega: EPS (descartado), modelos maiores/outros (BiRefNet), retoque manual da máscara, recorte automático ao objeto.

## Novidades da 0.9.24

- **Arquivos `.emf` e `.wmf` como entrada, só no Windows** (item 17 do plano, pedido pelo usuário antes dos itens 15 e 16): abrem em todas as ferramentas, conversões, colagem, PDF único e OCR, e na roda de atalhos. **Sem pacote novo:** o Pillow para Windows já traz o desenhista (`Image.core.drawwmf`, que chama o GDI); conferi no wheel `pillow-13.0.0 cp312 win_amd64` que ele existe (símbolos `drawwmf` e `PlayEnhMetaFile` no `_imaging`). Em Linux/macOS o Pillow só lê o cabeçalho: lá o arquivo é recusado com a mensagem «EMF e WMF só podem ser desenhados no Windows… nada foi simulado» e **nenhum arquivo é criado**.
- Núcleo `metafile.py` (sem Qt, em `CORE_MODULES`; erros `MetafileError` → `ConversionError`): `read_header` (valida EMF — assinatura ` EMF`, moldura com tamanho, ≥ 88 bytes — e WMF «placeable» — chave, cabeçalho padrão, escala ≠ 0, ≥ 40 bytes; WMF antigo sem cabeçalho de tamanho é recusado explicando; coordenadas absurdas recusadas), `describe_metafile`, `rasterize_metafile`. Tamanho padrão = o do cabeçalho (EMF: pixels do dispositivo de referência; WMF: 72 dpi); a «Largura do vetor» muda o **dpi** passado ao desenhar (`load(dpi=…)`), então o desenho é refeito no tamanho novo, não ampliado; limites iguais aos do SVG (`vector.target_size`: 8192 px/40 MP por padrão, 16384 px no máximo). O arquivo é aberto com `with` porque o Pillow não fecha o do metarquivo (no Windows travaria o arquivo).
- **Compatibilidade com o Pillow 12 e 13:** o 13 mudou onde o desenhista é guardado (de `WmfImagePlugin._handler` para `WmfStubImageFile._handler`); `current_handler()` procura nos dois lugares (testado). O 13 também recusa dpi negativo e confere bomba de descompressão em `load(dpi)`.
- **Limites (também no relatório de perdas):** o GDI desenha sobre **fundo branco opaco** — **sem transparência** (alfa 255), ao contrário de SVG e .ai —, sem suavização das bordas das formas, texto com as fontes instaladas, EMF+ só pelos registros de reserva do EMF. Transparência exigiria GDI+ via ctypes (ideia futura, não feita).
- **Segurança:** o GDI interpreta um arquivo não confiável dentro do worker (processo separado, pasta de trabalho privada). **No Windows o worker ainda não tem Job Object com limites de memória/CPU** (pendência antiga, agora mais relevante); nada é buscado na rede.
- **Evidência — leia com cuidado:** no Linux os testes (`tests/test_metafile.py`, 23 casos) conferem cabeçalhos EMF/WMF montados à mão, as contas de tamanho e dpi feitas pelo próprio código do Pillow, limites, mensagens de erro, a recusa fora do Windows (motor, relatório e worker) e a ligação com o motor usando um **desenhista falso** que devolve uma cor lisa. **Isso não prova que o GDI desenha o arquivo certo.** Dois testes só rodam no Windows (`WindowsRenderTests`): criam um EMF de verdade pelo `gdi32` (retângulo vermelho) e conferem o desenho real, a largura e o worker; são a primeira prova no Windows e podem falhar se algo na minha chamada do gdi32 estiver errado.
- Relatório de perdas do EMF/WMF: desenhado pelo GDI em N × M px, fundo branco opaco/sem transparência/fontes, redução de tamanho; SVG, .ai e EMF/WMF juntos geram os blocos de cada um.
- Diagnóstico do Windows: item novo `[0.9.24]` (o primeiro que de fato exercita o GDI).
- Fora desta entrega: transparência (GDI+), WMF sem cabeçalho de tamanho, EMF+ nativo, EMZ/WMZ comprimidos.

## Novidades da 0.9.23

- **Arquivos `.ai` do Illustrator como entrada** (`.ai` moderno = PDF por dentro): abrem em todas as ferramentas, conversões, colagem, PDF único e OCR, e na roda de atalhos. Desenho pelo **PDFium** (pacote novo `pypdfium2==5.13.0`, Apache-2.0 ou BSD-3-Clause; o wheel embute o PDFium e bibliotecas permissivas: FreeType, lcms2, libjpeg-turbo, OpenJPEG, libpng, libtiff, zlib, ICU, abseil; wheels para Windows x64, Linux x86-64 e aarch64, sem dependências). Licenças em `licenses/pypdfium2-5.13.0-LICENSE.txt` e `licenses/pypdfium2_5.13.0-LICENSES_bundled.txt`; `package.py` coleta `pypdfium2`/`pypdfium2_raw` e registra a versão.
- Núcleo `illustrator.py` (sem Qt, em `CORE_MODULES`): `describe_ai` e `rasterize_ai`. Só a **primeira página** (prancheta); tamanho padrão = página em pontos com **1 pt = 1 px**, com a mesma regra do SVG (`vector.target_size`: reduz acima de 8192 px/40 MP; «Largura do vetor» 1–16384 mantém a proporção); fundo **transparente**; anotações e formulários não são desenhados, não há JavaScript, nada vai à rede, anexos são ignorados.
- **Recusados com mensagem em português, sem criar arquivo:** `.ai` antigo em PostScript ou sem parte de PDF (explica «Criar arquivo compatível com PDF»), arquivo salvo sem conteúdo PDF (página-aviso do Illustrator), protegido por senha, PDF danificado/truncado, página inválida ou gigante (> 200 000 pt), arquivo vazio ou > 100 MiB, pacote ausente.
- A linha do painel passou de «Largura SVG» para **«Largura do vetor»** (SVG e .ai); a dica explica as duas regras. `.ai` entra nas listas de arquivos do painel, da roda e nos diálogos de abrir.
- Relatório de perdas do `.ai`: desenhado pelo PDFium em N × M px, só a primeira página, aviso de mais de uma página, redução de tamanho, fundo transparente, cores possivelmente diferentes do Illustrator (CMYK→RGB simples, sem sobreposição/tintas especiais), fontes não incorporadas trocadas; SVG e .ai juntos geram os dois blocos de notas.
- Medida (Linux, worker): página de 8000 × 5000 pt (40 MP) quase vazia, 1,4 s e ≤ 330 MiB; **página cheia de imagens/transparências pesadas não foi medida** (depende do conteúdo; o worker limita 1,5 GiB e 160 s de CPU).
- Testes: `tests/test_illustrator.py` (32 casos; os que desenham pulam sem `pypdfium2`): cores, posição e transparência, largura, redução e limites, várias páginas, cabeçalho deslocado, `.ai` antigo/outros/vazio/corrompido/truncado/com senha/sem conteúdo PDF, JavaScript, pacote ausente, ferramentas e formatos (PNG, WebP, JPEG com fundo, TIFF, girar, nitidez, comprimir, limpar), colagem e PDF único, OCR sobre `.ai`, original intacto, falhas sem arquivos, worker (também 40 MP), relatório e painel. Total: 648 (1 pulado).
- Diagnóstico do Windows: item novo `[0.9.23]`.
- Fora desta entrega: `.pdf` como entrada de imagem (pertence à categoria PDF; o mesmo rasterizador já está pronto), todas as pranchetas/páginas, perfis ICC/CMYK fiéis, `.ai` PostScript antigo, `.eps` (item 15).

## Novidades da 0.9.22

- **Grupo «Ler texto» na roda de ferramentas (Shift+F9):** duas ferramentas novas. **OCR → texto** salva um `.txt` (UTF-8, sufixo `-texto`); **OCR → PDF** salva um PDF de uma página com a imagem e o texto invisível por baixo, que dá para buscar e copiar (sufixo `-pesquisavel`). Idioma: Português + Inglês (padrão), Português ou Inglês. Modo de página: Automático, Bloco único, Uma linha ou Texto esparso. Funciona com todas as entradas de imagem (PNG, JPEG, WebP, TIFF, BMP, AVIF, SVG/SVGZ, HEIC/HEIF) e com a renomeação em lote; nunca sobrescreve.
- **Tesseract como programa externo (Apache-2.0):** `ocr.py` (núcleo, sem Qt) o chama como processo separado, sem shell, sem rede, com `TESSDATA_PREFIX` descartado, uma thread (`OMP_THREAD_LIMIT=1`), tempo máximo de 120 s e a imagem num arquivo temporário privado. Procura `tesseract/` ao lado do aplicativo, depois o PATH (e, no Windows, a pasta do instalador). **Não é dependência do `requirements.txt`**: sem o programa, o painel mostra a mensagem em português, desabilita o botão e o motor recusa sem criar nada. Linux: `apt install tesseract-ocr`.
- **Dados de idioma incluídos** em `tessdata/`: `por` e `eng` (tessdata_fast, Apache-2.0, ~6 MB) e `pdf.ttf`; o PDF pesquisável usa `-c tessedit_create_pdf=1`, então não precisa da pasta `configs/`.
- **Preparação da imagem:** transparência → fundo branco; modos estranhos → RGB; lado maior que 12 000 px é reduzido; no texto, imagens com os dois lados abaixo de 1000 px são ampliadas 2×; 300 dpi assumidos. **Nada é salvo** se o OCR não encontrar texto (mensagem própria) e, no PDF, o texto é conferido com o pypdf antes de publicar.
- **Roda reorganizada:** a roda de primeiro nível já estava no limite de 8 fatias; «Comprimir» agora fica no grupo «Transformar» (5 itens) e «Ler texto» ocupa a fatia que sobrou. A ordem do registro continua a ordem da roda.
- Relatório de perdas do OCR: aproximado (conferir números, acentos, tabelas, manuscrito), idioma usado, imagens de cabeça para baixo/inclinadas não corrigidas, transparência, redução/ampliação, e um aviso se o Tesseract não está instalado.
- Medidas (Linux, worker): página A4 de 300 dpi com 50 linhas de texto sintético, texto 2,9 s e PDF 3,3 s (≤ 180 MiB); imagem de 40 MP com essa página ao centro, 5,7 s e 6,5 s (≤ 670 MiB). Texto sintético limpo (DejaVu) saiu 100 % igual ao original; **isso não mede qualidade em fotos, manuscrito ou escaneamentos ruins** (fica para o Portão B). Uma página de 40 MP cheia de texto deve demorar bem mais (não medido).
- Testes: `tests/test_ocr.py` (29 casos; os que usam o Tesseract pulam sem ele): núcleo (listas, limpeza, ausência de programa e de idiomas, timeout, comando sem shell), opções e registro, preparação da imagem, relatório, falhas sem criar arquivos, texto e PDF reais, idiomas, modos de página, transparente/paleta/pequena, imagem em branco, não sobrescrita e renomeação, JPEG e SVG, worker com limites, painel e fila. Total: 616 (1 pulado).
- **Pendência de empacotamento no Windows:** `package.py` inclui `tessdata/` e, se existir, `tesseract/` (tesseract.exe + DLLs) ao lado de `package.py`; sem ela o pacote sai sem OCR (com aviso). As licenças das DLLs do Tesseract para Windows (Leptonica etc.) precisam ser conferidas e copiadas antes de distribuir; PyInstaller com os arquivos novos não foi testado.
- Diagnóstico do Windows: item novo `[0.9.22]`.
- Fora desta entrega: PDF digitalizado como entrada (precisa do rasterizador de PDF, item 14), várias imagens → um PDF pesquisável, correção automática de orientação (OSD), mais idiomas, tabelas e manuscrito.

## Novidades da 0.9.21

- **HEIC/HEIF como entrada:** `.heic`, `.heif` e `.hif` abrem em todas as ferramentas e conversões de imagem e na roda de atalhos (Shift / Shift+F9), como qualquer outra imagem. HEIC de iPhone: a orientação é aplicada, EXIF/GPS não vão para o resultado e HEIC de mais de 8 bits (HDR) é reduzido para 8 bits, com aviso no relatório. Arquivos com várias imagens (sequências, rajadas) continuam recusados, como GIF animado. O limite de 40 megapixels vale antes de decodificar.
- **Salvar como HEIC** em todas as ferramentas que têm o «Salvar como» (incluindo Colagem): nono botão, com o controle «Qualidade» (1–100). HEIC tem perda; **em 100 o codificador entra no modo sem perda**, mas a conversão de cor ainda pode mudar um nível por canal (medido: diferença máxima 1–2), então o relatório não promete bit a bit. A partir de 95 as cores não são reduzidas (4:4:4); abaixo disso, 4:2:0. A transparência é mantida e o perfil de cor ICC é preservado; EXIF/GPS não são copiados.
- **Pacote novo em `requirements.txt`: `pillow-heif==1.8.1`** (BSD-3-Clause; wheels para Windows x64 cp312, Linux x86-64 e aarch64). Os wheels embutem **libheif 1.23.6 e libde265 1.1.3 (LGPL-3.0)** e o codificador **x265 4.3 (GPL-2.0)**, além do runtime MinGW-w64 no Windows; licenças e endereços do código-fonte estão em `licenses/pillow_heif-1.8.1-LICENSES_bundled.txt` e em `THIRD_PARTY_NOTICES.md`. O pacote é **opcional em tempo de execução**: sem ele, abrir HEIC e escolher HEIC como saída dão mensagens claras («instale o pacote pillow-heif») e nada é criado; o relatório de perdas continua funcionando. `package.py` inclui `pillow_heif` (coleta completa) e copia as licenças.
- **Pendência jurídica (não resolvida aqui):** o HEVC tem patentes de terceiros e o x265 é GPL; a combinação com a GPL-3.0 do projeto precisa de confirmação (os wheels se declaram GPLv2; a compatibilidade depende de o x265 permitir «versão 2 ou posterior», o que não foi verificado nesta sessão). **Revisão jurídica antes de qualquer distribuição pública.**
- Relatório de perdas: nota própria do HEIC (qualidade, perda, modo sem perda em 100, 4:4:4 em ≥ 95, transparência mantida, patentes HEVC e extensões HEIF/HEVC da Microsoft Store que o Windows pode exigir para abrir) e aviso de «origem já tinha perda» ao recomprimir HEIC/AVIF.
- Correção: imagens com mais do que o dobro do limite de megapixels davam a mensagem em inglês do Pillow; agora a mensagem é «A imagem excede 40 megapixels.» para qualquer formato.
- Medidas no Linux (worker com limites de 1,5 GiB e 160 s de CPU): 12 MP HEIC gravado em ~10 s (18 s de CPU, ~315 MiB); **40 MP em ~31 s (58 s de CPU, ~950 MiB)** — em computador bem mais lento o limite de CPU do worker pode ser alcançado e a conversão falha com mensagem; decodificar 12 MP leva ~3 s.
- Testes: `tests/test_heic.py` (22 casos; os que precisam do pacote pulam sem ele): registro, opções, mensagens sem o pacote, arquivo, transparência, qualidade e modo sem perda, todas as ferramentas e colagem, modos e tamanhos estranhos, ICC/EXIF, as três extensões, HEIC com alfa, orientação, limite de megapixels, arquivo corrompido, relatório, worker real e painel. A matriz de `test_output_format` cobre 9 formatos (pula HEIC sem o pacote). Total: 587 testes no Linux (1 skip).
- Diagnóstico do Windows: item novo `[0.9.21]`.
- Fora desta entrega: HEIC com várias imagens, imagens auxiliares (profundidade, mapa de ganho) e HEIC animado.

## Novidades da 0.9.20

- **Salvar como AVIF** em todas as ferramentas de imagem que têm o «Salvar como» (incluindo Colagem), como oitavo botão ao lado de PNG, JPEG, WebP, TIFF, BMP, GIF e ICO. Usa o suporte nativo do Pillow (libavif embutida no wheel): **nenhuma dependência nova**. Tem o controle «Qualidade» (1–100, padrão 90 do painel); AVIF **sempre tem perda**, mesmo na qualidade máxima. A **transparência é mantida** (não há «Fundo opaco») e o **perfil de cor ICC** é preservado; EXIF/GPS não são copiados. Em qualidade 95 ou mais as cores não são reduzidas (subamostragem 4:4:4); abaixo disso usa 4:2:0. Velocidade de codificação fixa em 6.
- **Entrada AVIF:** `.avif` já era aceito; agora é coberto por testes (leitura, ferramentas, conversão). AVIF animado continua recusado (imagens com vários quadros não são suportadas).
- **Disponibilidade:** se o Pillow instalado não tiver AVIF, escolher esse formato dá uma mensagem clara e nada é criado; o relatório de perdas continua funcionando.
- Relatório de perdas: nota própria do AVIF (qualidade, perda sempre presente, transparência mantida, abrir só em programas recentes), aviso de «origem já tinha perda» ao recomprimir JPEG/WebP/AVIF e a cópia limpa avisa que os pixels mudaram.
- Medidas no Linux (worker com limite de 1,5 GiB): 12 MP em ~3,6 s (~340 MiB); **40 MP em ~11 s e ~1050 MiB**, ainda dentro do limite mas perto dele — se algum computador estourar, a conversão falha com mensagem e nada é criado.
- Testes: `tests/test_avif.py` (13 casos) e a matriz de `test_output_format` passa a cobrir 8 formatos. Total: 565 testes no Linux (1 skip).
- Diagnóstico do Windows: item novo `[0.9.20]`.
- **HEIC/HEIF (entrada) não entrou, por decisão de produto pendente:** exigiria o pacote `pillow-heif` (wheel de 5,7 MB, ~23 MB descompactados, que embute libheif, libde265 e **libx265, sob GPL**) e HEVC tem patentes. O pacote licencia-se de forma compatível com a GPL-3.0 do projeto, mas o custo em tamanho e o risco de patentes são do produto.

## Novidades da 0.9.19

- **SVG e SVGZ abrem em todas as ferramentas de imagem e conversões** (Tamanho, Recortar, Girar, Ajustar, Níveis, Nitidez, Formas, Marca, Anotar, Ocultar, Metadados, Fundo, Canvas, Colagem, PDF único, Imagem → PDF, PNG/JPEG/WebP/TIFF/BMP…) e na roda de atalhos (Shift / Shift+F9). O vetor é **desenhado em pixels** ao abrir, com **fundo transparente**; a transparência segue em PNG, WebP, TIFF, GIF e ICO, e JPEG, BMP e PDF a substituem pelo branco (ou pelo «Fundo opaco», nas ferramentas). O resultado é uma imagem de pixels: não volta a ser vetor.
- **Campo «Largura SVG»** (aparece só quando há SVG na seleção): 0 = «Do arquivo» (tamanho declarado em `width`/`height` ou, sem eles, o `viewBox`; unidades px, pt, pc, mm, cm, in), ou uma largura de 1 a 16384 px com a altura na mesma proporção. O vetor é **desenhado de novo** nessa largura (nítido, não é ampliação de pixels). A prévia usa a mesma largura do resultado; mudar a largura recomeça a ferramenta (posições marcadas dependem do tamanho). Sem largura, tamanhos acima de 8192 px por lado ou 40 megapixels são reduzidos na mesma proporção, com aviso no relatório. SVG sem `width`/`height`/`viewBox` é recusado com mensagem clara.
- **Desenhista:** **resvg-py** (novo pacote em `requirements.txt`, MIT; wheels para Windows x64 e Linux; motor resvg em Rust com dependências permissivas, lista em `licenses/`) é o preferido; o **QtSvg** do PySide6 é a reserva automática quando o pacote não está instalado. Medido num corpus de 16 recursos (plano, «Resultado da comparação»): o Qt SVG não desenha `clipPath`, texto em caminho, `<svg>` aninhado nem a escala de `<symbol>`; o resvg desenha todos. O relatório de perdas diz qual desenhista foi usado e, no caso do Qt, o que ele não cobre.
- **Segurança** (módulo `vector.py`, no núcleo, sem Qt): o SVG é lido como XML sem entidades (DOCTYPE com `ENTITY` é recusado: XXE e «billion laughs»; DTD externa nunca é buscada), com limites de 16 MiB (SVGZ: 50 MiB depois de descompactar), 200 mil elementos, profundidade 128, 2 milhões de elementos depois de expandir `<use>` e recusa de referências circulares. Tudo que sai do arquivo é removido antes de desenhar: `href` e `url()` que não apontem para `#id` do próprio arquivo, `@import`, `@font-face`, `<script>`, `foreignObject`, `iframe`, atributos `on*` e metadados de editores (Inkscape, Sodipodi); só imagens `data:` PNG/JPEG/GIF/WebP embutidas entram. O SVG limpo vai como texto ao desenhista: não há rede nem acesso a arquivos vizinhos. Um arquivo vizinho referenciado por `href` nunca é desenhado (teste).
- Relatório de perdas: tamanho de desenho, tamanho declarado, desenhista, o que foi ignorado (referências externas, scripts) e o aviso de que o resultado não volta a ser vetor.
- Empacotamento: `package.py` inclui `vector_resvg`, `vector_qt`, `resvg_py` e `PySide6.QtSvg` e copia a licença e a lista de componentes do resvg-py para `licenses/`.
- Testes novos (`tests/test_vector.py`, 63 casos, cada caso de desenho rodado nos dois adaptadores): tamanho e unidades, limites, entidades, bombas de `<use>`, referências circulares, SVGZ, limpeza de referências externas, transparência e alfa parcial, gradiente, texto, filtro, `clipPath`/texto em caminho/aninhado/`symbol` (só resvg), escolha e queda do adaptador, todos os formatos de saída, ferramentas, colagem e PDF único, relatório, painel e um worker real com `vector_width`. Total: 531 testes no Linux (1 skip).
- Diagnóstico do Windows: item novo `[0.9.19]` (instalar `resvg-py`, SVG com texto, `clipPath`, transparência, SVGZ).
- Medidas no Linux (worker com limite de 1,5 GiB): SVG de 40 megapixels em ~7 s e ≤ 520 MiB de memória.
- **Fora desta entrega:** EPS/AI/EMF/WMF (item 12c), animação SVG (desenha só o quadro inicial), fontes embutidas em `@font-face` (ignoradas; o texto usa as fontes instaladas) e a comparação numérica contra uma referência (SSIM), que fica no Portão B.

## Novidades da 0.9.18

- **Salvar como GIF e ICO** em todas as ferramentas de imagem que já ofereciam o «Salvar como» (Recortar, Tamanho, Girar, Ajustar, Níveis, Nitidez, Formas, Marca, Anotar, Ocultar, Metadados, Fundo, Canvas, Colagem…): dois botões novos ao lado de PNG, JPEG, WebP, TIFF e BMP. Sem dependência nova (Pillow). O botão de execução e o exemplo do campo «Nome» já mostram a extensão escolhida.
- **GIF estático (sem animação):** paleta de até 256 cores (MEDIANCUT com pontilhado Floyd–Steinberg). A transparência do GIF é de **1 bit**: pixels com alfa abaixo de 128 viram transparentes e os demais ficam opacos (meio transparentes **não** são preservados); com transparência, 255 cores + 1 índice reservado. Fotos e degradês perdem qualidade; o relatório avisa.
- **ICO:** ícone **quadrado** com os tamanhos padrão **16, 32, 48, 64, 128 e 256 px que cabem na imagem**. Imagens maiores que 256 px são reduzidas, menores que 16 px são ampliadas e as não quadradas são **centralizadas em fundo transparente** (nada é cortado nem esticado). A transparência (8 bits) é mantida. Sem camada de ícone por tamanho: todos os tamanhos vêm da mesma imagem.
- Sem «Qualidade» nem «Fundo opaco» para GIF/ICO (não se aplicam). GIF e ICO não guardam perfil de cor (a cor segue em sRGB) nem EXIF.
- Relatório de perdas: notas próprias para GIF (cores e 1 bit) e ICO (tamanhos, redução, centralização); a cópia limpa avisa que os pixels mudaram.
- Testes: `tests/test_gif_ico.py` (24 casos) e a matriz de `test_output_format` passa a cobrir 7 formatos. Total: 489 testes no Linux (1 skip).
- Diagnóstico do Windows: item novo para GIF/ICO (ícone aparece no Explorer, GIF abre com transparência).
- Não faz parte desta entrega: ler GIF animado/ICO com várias camadas (continua lendo só o primeiro quadro) e entradas vetoriais (SVG), que são o próximo bloco do plano.

## Novidades da 0.9.17

- **PDF único** (fatia «PDF único», `Images → One PDF`, uma fatia solta na roda de ferramentas, ao lado de Colagem): junta de 2 a 200 imagens em **um** PDF, uma por página, **na ordem da lista** (Subir, Descer e Tirar, como na colagem). Também aparece no Shift+F9 quando há duas ou mais imagens selecionadas. «Imagem → PDF» (um PDF por imagem) continua existindo nas conversões.
- **Página:** «Do tamanho da imagem» (cada página tem o tamanho da própria imagem a 150 dpi), **A4** ou **Carta**. Em A4/Carta a orientação acompanha cada imagem (paisagem se for mais larga que alta; quadrada = retrato), há **margem** de 0 a 50 mm e a imagem é ajustada à área útil, centralizada, mantendo a proporção — **pode ser ampliada** para preencher a página.
- **Qualidade JPEG** das páginas (padrão 88). As páginas são imagens gravadas a 150 dpi e compactadas em JPEG: há perda de qualidade e o texto das imagens **não** fica selecionável (sem OCR). Transparência vira fundo branco; as cores vão para sRGB; EXIF/GPS não entram no PDF. A orientação do EXIF é aplicada.
- **Memória baixa:** uma imagem por vez — cada página vira um PDF de uma página em memória e depois são unidas (pypdf); limite de 512 MiB na saída.
- **Prévia:** folhas na ordem da lista, com a geometria do motor (tamanho, orientação, margem e ajuste), numeradas, com miniaturas.
- **Nome:** usa o campo «Nome» da 0.9.16 com {nome} = «imagens» (padrão sem campo: `images.pdf`); nunca sobrescreve (`images-2.pdf`).
- Fila: um único job com todos os arquivos (como colagem e unir PDFs), mínimo 2 imagens. Relatório: páginas, tamanho, margem, perda e ausência de OCR.
- Motor: `onepdf_options_from`, `pdf_page_pixels`, `pdf_page_image`, `build_onepdf`; interface: `pdf_pages_pixmap`. Opções novas no registro: `pdf_page` (texto), `pdf_margin` (inteiro).
- Testes novos (`tests/test_onepdf.py`, 29 casos): opções, geometria A4/Carta, ordem das páginas, tamanhos lidos do PDF gerado, transparência, EXIF, qualidade × tamanho, nomes, fila, lista branca, painel (ordem, mensagens, opções), Shift+F9 e prévia. Testes antigos ajustados à nova fatia.
- Diagnóstico do Windows: item novo para o PDF único.

## Novidades da 0.9.16

- **Campo «Nome»** em todas as ferramentas de imagem e nas conversões (PNG, JPEG, WebP, TIFF, BMP, Imagem → PDF, Comprimir, Colagem): um padrão com os marcadores **{nome}** (nome original sem extensão), **{n}** (número), **{sufixo}** (o da ferramenta, ex.: «redimensionada») e **{data}** (AAAA-MM-DD). Vazio = comportamento de sempre (`{nome}-{sufixo}`). A extensão continua sendo a da ferramenta/formato escolhido.
- **Numeração em lote:** com {n} aparecem «Primeiro nº» (0–999999) e «Dígitos» (1–6, zeros à esquerda). A fila numera os arquivos na ordem da seleção (primeiro, primeiro+1, …). A colagem é um único arquivo e usa {nome} = «colagem».
- **Exemplo ao vivo:** o painel mostra os dois primeiros nomes reais já com a extensão (ex.: `viagem-010-praia.webp · viagem-011-montanha.webp …`), avisa «Padrão inválido: …» e, quando há vários arquivos sem {n} nem {nome}, avisa que nomes repetidos ganham -2, -3…. O campo volta ao vazio ao reabrir a ferramenta.
- **Segurança de nomes:** o padrão não aceita `/ \ : * ? " < > |` nem caracteres de controle, marcadores desconhecidos nem chaves desbalanceadas (recusa em vez de trocar em silêncio); até 120 caracteres. O resultado nunca fica vazio nem termina em ponto/espaço; nomes reservados do Windows (CON, NUL…) ganham `file-`; {nome} longo é encurtado para o total caber em 100 caracteres sem perder o {n}. **Nada é sobrescrito:** nome já existente vira -2, -3… (inclusive se o padrão reproduzir o nome do original). O original não é renomeado nem movido.
- Relatório: acrescenta o padrão usado e a regra de nunca sobrescrever.
- Motor: `rename_options_from`, `rename_stem`, `RENAMEABLE_TARGETS`. Fila: `start_job` grava `rename_n` em cada job. Novas opções comuns no registro: `rename_pattern` (texto ≤ 200), `rename_start`, `rename_digits`, `rename_n` (inteiros).
- Testes novos (`tests/test_rename.py`, 32 casos): validação, marcadores, zeros, limite de tamanho, nomes vazios/hostis/reservados, colisão sem sobrescrever, extensão sempre da ferramenta, PDF/JPEG/colagem, numeração da fila, lista branca e painel. Testes antigos que listavam as linhas visíveis ignoram as linhas do nome.
- Diagnóstico do Windows: item novo para renomeação em lote.

## Novidades da 0.9.15

- **Formas** (fatia «Formas», `Shapes → PNG`, sufixo `-com-formas`, risco médio, uma imagem por vez): **retângulo**, **elipse**, **linha** e **seta**, quantas precisar (até 50). Arraste sobre a imagem, escolha **cor** (#RRGGBB), **espessura** (1–200 px; o padrão acompanha o tamanho da imagem), **contorno ou cheio** (retângulo/elipse) ou **direção** ↘ ↙ ↗ ↖ (linha/seta, com a ponta no canto de chegada) e clique em «Adicionar forma». «Desfazer última» remove a mais recente; a forma ainda não confirmada entra ao salvar. A prévia mostra as formas já desenhadas e a atual com o estilo atual, usando o mesmo código do arquivo final.
- Desenho com suavização (região ampliada até 4× e reduzida por média de área, com limite de 16 MP para imagens grandes), contorno desenhado para dentro da caixa, seta com cabeça proporcional à espessura, caixa muito achatada (≤ 8 % do lado maior) vira reta horizontal/vertical. Formas posteriores cobrem as anteriores; a transparência da imagem fora das formas é mantida. As coordenadas valem para a imagem já orientada (EXIF).
- **Novo grupo «Desenhar»** na roda: Anotar, Formas, Marca. O grupo «Aparência» virou **«Ajustes»** (Ajustar, Níveis, Nitidez, Fundo), porque o rótulo antigo era cortado na roda rápida (agora com 9 fatias; o piso de largura dos rótulos vale a partir de 9). A roda de ferramentas do arquivo tem seis fatias: Transformar, Ajustes, Desenhar, Proteger, Comprimir, Colagem.
- Segurança: a lista `shape_items` tem validação própria na lista branca do app (até 50 itens, só chaves conhecidas, inteiros de verdade, cor de 7 caracteres) e de novo no motor (tipo, cor, espessura, caixa dentro da imagem).
- Relatório: quantidade de formas por tipo, aviso de que ficam gravadas nos pixels e não podem ser editadas no arquivo novo, e de que as posições valem só para esta imagem.
- Motor: `shape_items_from`, `shape_endpoints`, `draw_shape`, `shapes_image`. Testes novos (`tests/test_shapes.py`, 35 casos): validação, direções e achatamento, contorno/preenchimento/espessura medidos, suavização, seta (cabeça e ponta), ordem, alfa, borda da imagem, imagem grande, EXIF, formatos, relatório, painel e lista branca.
- Diagnóstico do Windows: item novo para as formas; o item das sub-rodas cita os novos grupos.

## Novidades da 0.9.14

- **Níveis** (fatia «Níveis» no grupo Aparência, `Levels → PNG`, sufixo `-com-niveis`, risco médio): **ponto preto** (0–254), **ponto branco** (1–255) e **tons médios** (gama 0,10–5,00) sobre um **histograma de luminosidade** com as marcas dos pontos, ou modo **Automático**, que calcula preto e branco de cada imagem descartando 0,5 % dos pixels de cada ponta (vale também para vários arquivos, cada um com os seus pontos).
- A mesma curva vale para R, G e B (a cor não desvia); o canal alfa não muda; imagem lisa ou já com a faixa inteira não é alterada pelo automático. O botão só habilita depois de mover um controle (ou no automático).
- **Curvas ficam de fora desta entrega:** exigem um editor de curva de pontos arrastáveis e estão registradas como retoque futuro no plano; os níveis cobrem o ajuste de sombras, realces e tons médios.
- Relatório: pontos usados (ou «calculados para cada imagem»), gama, aviso de que tons fora dos pontos viram preto/branco puro e perdem detalhe.
- Motor: `levels_options_from`, `luminance_histogram`, `levels_auto_points`, `levels_resolve`, `levels_image`. Interface: `HistogramView` e `SliderRow(formatter=…)` em `widgets.py`. Grupo Aparência: Ajustar, Níveis, Fundo, Anotar, Marca, Nitidez (6 + Voltar).
- Testes novos (`tests/test_levels.py`, 31 casos): validação, identidade exata, pontos e gama medidos, curva igual nos canais, alfa, histograma, automático (faixa, por imagem, lisa/transparente), job e formatos, relatório, painel (bloqueio do botão, preto×branco, reset, histograma) e lista branca.
- Diagnóstico do Windows: item novo para níveis.

## Novidades da 0.9.13

- **Nitidez e desfoque** (fatia «Nitidez» no grupo Aparência, `Sharpen → PNG`, sufixo `-com-efeito`, risco baixo): efeito **Nitidez** (máscara de nitidez no RGB, força 1–100 %) ou **Desfoque** (gaussiano). O **raio** (1–100) é proporcional ao menor lado da imagem (milésimos), então a prévia ao vivo, calculada numa cópia de 900 px, mostra o mesmo efeito do arquivo final, de qualquer tamanho.
- Transparência: a nitidez não mexe no canal alfa; o desfoque usa alfa pré-multiplicado, sem halo escuro nas bordas transparentes. Imagem plana não muda.
- Relatório: raio em pixels da primeira imagem; aviso de que o efeito fica gravado nos pixels, de que a nitidez pode criar halos e realçar ruído e de que o desfoque não se desfaz.
- Motor: `sharpen_options_from`, `sharpen_radius_px`, `sharpen_image`. Funciona com o seletor «Salvar como» da 0.9.11. A sub-roda Aparência agora tem Ajustar, Fundo, Anotar, Marca e Nitidez (5 fatias + Voltar).
- Testes novos (`tests/test_sharpen.py`, 24 casos): validação, raio proporcional, efeito medido (largura de borda, halo, força), área plana, alfa, halo no desfoque, prévia × final em outra escala, job, formatos, relatório, painel e lista branca.
- Diagnóstico do Windows: item novo para nitidez e desfoque.

## Novidades da 0.9.12

- **Marca d'água** (fatia «Marca» no grupo Aparência, `Watermark → PNG`, sufixo `-com-marca`): **texto** (até 100 caracteres, cor à escolha, negrito) ou **imagem/logotipo** (PNG com transparência recomendado), com **tamanho** (1–100 % da largura), **opacidade** (1–100 %), **posição** (3 × 3: cantos, bordas e centro) ou **repetida na diagonal**, e **margem** (0–25 % do menor lado). O tamanho é relativo à imagem, então a **prévia ao vivo** coincide com o resultado final; a marca nunca passa dos limites da imagem. Funciona em lote (a mesma marca em várias imagens; a prévia aparece com uma imagem) e com o **formato de saída** da 0.9.11 (PNG, JPEG, WebP, TIFF, BMP).
- Segurança: o arquivo do logotipo passa pelas mesmas verificações de qualquer entrada (caminho local absoluto, nada de links, pastas ou dispositivos, limite de tamanho e de megapixels); só é lido e nunca alterado. O caminho do logotipo aceita até 1024 caracteres na lista branca; as demais opções de texto continuam limitadas a 200.
- Relatório: posição, opacidade, tamanho, aviso de que a marca fica gravada nos pixels e não pode ser removida, e que o logotipo não foi alterado.
- Motor: `load_font` (Arial no Windows; DejaVu/Liberation no Linux; fonte embutida como último recurso) agora é compartilhada com Anotar; `watermark_options_from`, `watermark_mark`, `watermark_image`.
- Testes novos (`tests/test_watermark.py`): validação, largura do texto × tamanho, nove posições, margem, opacidade e alfa, repetição, logotipo (escala e transparência), marca maior que a imagem, independência de escala (prévia × final), job de texto e de imagem em vários formatos, entradas inválidas sem resíduo, logotipo inválido ou link simbólico, painel, lista branca. 314 testes no Linux.
- Diagnóstico do Windows: item novo para a marca d'água (texto, logotipo, repetição, fontes).

## Anterior — 0.9.11

- **Salvar como…** em todas as ferramentas que geram imagem (Recortar, Tamanho, Girar, Canvas, Ajustar, Fundo, Anotar, Ocultar, Metadados e Colagem): **PNG** (padrão, igual ao de antes), **JPEG**, **WebP**, **TIFF** ou **BMP**. O botão passa a dizer o formato («Recortar e salvar WebP») e o arquivo sai com a extensão certa (`foto-girada.jpg`).
- **Qualidade** (1–100) para JPEG e WebP; **WebP em 100 % é sem perda**. **Fundo opaco** (#RRGGBB) para JPEG e BMP: como esses formatos não têm transparência, o que era transparente recebe essa cor (padrão branco); PNG, WebP e TIFF mantêm a transparência.
- **Cópia limpa em JPEG/WebP** (item 4 do plano) vem junto: a ferramenta Metadados salva sem EXIF/GPS/XMP no formato escolhido; o relatório diz quando os pixels deixam de ser idênticos (JPEG ou WebP com perda). Em Ocultar com formato com perda, o relatório explica que as áreas foram gravadas antes da compactação. O perfil de cor é mantido em JPEG, WebP e TIFF e convertido para sRGB em BMP.
- Relatório do que mudou ampliado (formato, qualidade, perda, transparência substituída, origem já comprimida). Opções validadas no motor e na lista branca (`out_format`, `out_quality`, `out_flatten`).
- Testes novos (`tests/test_output_format.py`): matriz **ferramenta × formato** (10 × 5), transparência, WebP sem perda, qualidade e tamanho, EXIF/GPS ausentes, ICC, relatório, controles e botão do painel, bloqueio de ferramentas que exigem escolha, lista branca. 288 testes no Linux.
- Diagnóstico do Windows: item novo para o formato de saída.

## Anterior — 0.9.10

- **Sub-rodas:** as ferramentas de imagem foram agrupadas — **Transformar** (Recortar, Tamanho, Girar, Canvas), **Aparência** (Ajustar, Fundo, Anotar) e **Proteger** (Ocultar, Metadados) — mais Comprimir (e Colagem, só para várias imagens) como fatias soltas. Um clique no grupo abre a sub-roda; «Voltar», Esc ou Backspace retornam; o centro mostra o nome do grupo. A roda da tecla Shift+F9 passou de 10 para 4 fatias e a do painel de 11 para 5, com rótulos legíveis. Grupos e «Voltar» não recebem arquivos arrastados; arrastar sobre uma ferramenta dentro do grupo funciona; sem Pillow os grupos ficam desativados.
- **Arquitetura:** `tool_registry.GROUPS`/`ToolSpec.group` definem os grupos; `radial_menu.image_tool_actions` monta as rodas a partir do registro. `test_architecture` agora exige grupos coerentes (rótulo curto, ícone, ao menos 2 ferramentas) e no máximo 8 fatias por nível, para a roda não voltar ao limite.
- Plano: acrescentado o item **vetores (SVG/SVGZ)** com a análise de quando fazer; ver `docs/PLANO-CATEGORIA-IMAGENS.md`.
- Diagnóstico do Windows: item novo para as sub-rodas.

## Anterior — 0.9.9

- **Girar** (fatia «Girar», `Rotate → PNG`, sufixo `-girada`): 90° à direita, 180° ou 90° à esquerda, com espelhamento horizontal, vertical ou nos dois eixos aplicado **depois** do giro. Os pixels só trocam de lugar (sem reamostragem), então o resultado não perde nada; alfa e modos de cor são preservados; a orientação do EXIF é aplicada antes. Prévia imediata, texto «Resultado» com as dimensões e botão bloqueado até haver uma escolha. Original intacto, nunca sobrescreve.
- A roda de ferramentas do painel passou a 11 fatias (10 na roda de um arquivo); o piso de largura dos rótulos subiu para 68 px a partir de 10 fatias. **A roda chegou ao limite de legibilidade: a próxima ferramenta exige agrupar fatias** (item do plano).
- Diagnóstico do Windows: +1 item (Girar).

## Anterior — 0.9.8

- **Redimensionar** (fatia «Tamanho» da roda, `Resize → PNG`): três modos — porcentagem (1–1000 %), «Caber em» largura × altura mantendo a proporção (um eixo pode ficar sem limite) e medida exata (avisa quando a proporção muda). Lanczos com alfa pré-multiplicado, orientação do EXIF aplicada antes, limite de 10 000 px por lado e 40 megapixels, resultado mostrado antes de salvar, relatório com tamanhos e avisos de ampliação. Saída `-redimensionada.png`; original intacto.
- **Arquitetura:** novo `tool_registry.py` (fonte única de cada ferramenta de imagem; motor, bandeja, painel e roda derivam dele) e `ARCHITECTURE.md`. `tests/test_architecture.py` falha se uma ferramenta registrada não estiver ligada a todas as camadas e confere que o núcleo não importa Qt nem APIs do Windows.
- **Planejamento:** `docs/PLANO-CATEGORIA-IMAGENS.md` (ordem por risco, portões e prova de qualidade do fim da categoria) e `docs/ADR-0001-linguagem-e-multiplataforma.md` (manter Python/PySide6 agora; reavaliar no fim da categoria; riscos do Linux).
- Correção de teste: um teste que iniciava uma thread real e causava aborto intermitente foi isolado.

## Novidades da 0.9.7

Segunda execução da suíte em Windows 10 (build 19045, Python 3.12): 206 testes, 204 passaram, 2 falharam e 4 foram pulados (links simbólicos sem privilégio). As duas falhas eram dos próprios testes, não do app:

- **Arraste na roda:** o teste esperava `/tmp/a.png`; o app entrega o formato nativo do Windows. O teste agora compara com `QDir.toNativeSeparators`.
- **Lote de caminhos (IPC):** iniciar um processo leva mais de 350 ms no Windows, então dois envios viram dois lotes. O teste confere a entrega entre processos sem exigir lote único, e o agrupamento/remoção de duplicatas passou a ser testado diretamente com `server.feed`.
- **Diagnóstico Windows:** o checklist manual ganhou 9 itens (Fundo, Ocultar, Metadados, Ajustar, colagem, atalhos, menu de contexto, arrastar e soltar, roda de 9 fatias em 100/125/150%), rola dentro da janela e o contador acompanha o total. As caixas continuam sendo autorrelato.

Os 11 itens anteriores foram marcados manualmente pelo usuário; isso não substitui o gate Windows completo.

## Anterior — 0.9.6

Primeira execução da suíte em Windows real (Python 3.12, PySide6, plataforma offscreen): 205 testes, 5 falhas e 4 pulados (links simbólicos sem privilégio). Nenhuma falha era de conversão de arquivos; todas eram diferenças entre Linux e Windows:

- **Caminhos soltos com "/":** o Qt devolve `C:/pasta/a.png` ao arrastar arquivos no Windows. O app agora converte para o formato nativo (`C:\pasta\a.png`) ao soltar sobre a roda ou a janela, para que a mesma pessoa não acabe com o mesmo arquivo duplicado na lista com duas grafias. O teste de arraste da prateleira passou a comparar caminhos normalizados.
- **Troca de atalho global:** a lógica foi isolada em `TrayApplication._switch_hotkey`. O teste não registra mais atalhos no sistema; a falha de registro (combinação já usada por outro programa) tem teste próprio, que confere a mensagem e que o atalho anterior continua valendo. A falha observada foi no preset **Ctrl+Alt+Espaço**, provavelmente já ocupado por outro programa (o app do Claude para desktop usa essa combinação por padrão); se acontecer, escolha outro preset na janela "Atalhos".
- **IPC do menu de contexto:** os testes mandavam o caminho a partir da mesma thread do servidor; no Windows o canal nomeado exige que o servidor leia em paralelo. Agora o envio parte de **outro processo**, como faz o Explorer, e o servidor continua em segundo plano no teste.
- `windows_acceptance_check.py` avisa quando for executado com um Python sem PySide6 (use `.\.venv\Scripts\python.exe`).
- 206 testes no Sandbox Linux (1 skip).
- **Pendente:** reexecutar a suíte no Windows para confirmar que as 5 falhas sumiram (as correções foram escritas e verificadas só no Linux); os testes de IPC e do atalho global continuam dependendo do comportamento real do sistema.

## Novidades da 0.9.5

- **Prévia real na ferramenta Ocultar:** ao marcar uma área (e ao confirmá-la, trocar o modo ou mexer no tamanho do bloco) a tela já mostra a tarja preta ou a pixelização aplicada, em vez de uma caixa escura. A prévia usa o mesmo código do motor (`engine.redact_apply`) sobre uma cópia reduzida a 1000 px, com o bloco reduzido na mesma proporção; por isso é uma aproximação do arquivo final, que é calculado na resolução original.
- A imagem deixa de ser escurecida fora da seleção na Ocultar (o escurecimento continua no Recorte), para o efeito ser visível. A seleção atual também aparece com o efeito antes de ser confirmada.
- O motor continua exigindo bloco de 4 a 200 px e todas as validações da 0.9.1; só a prévia usa blocos menores.
- 4 novos testes (205 no total, 1 skip específico de Windows).
- **Limites:** a prévia é aproximada (arredondamentos da redução); a ocultação e a pixelização só valem no PNG novo. Sem validação em Windows real.

## Novidades da 0.9.4

- **Miniaturas na prévia da colagem:** cada célula mostra a imagem de verdade (EXIF aplicado), inteira, centralizada e sem ampliar além do tamanho original — como faz o motor — com o número da ordem num selo laranja. Imagem ilegível volta a aparecer só com número e nome. As miniaturas ficam em cache (até 48).
- **Reordenar a colagem:** nova lista "Ordem" com os botões **Subir**, **Descer** e **Tirar**. A ordem da lista é a ordem enviada ao job e a da prévia; "Tirar" só retira da sessão (o arquivo no disco não é tocado) e permite reduzir uma seleção de mais de 12 imagens. Com menos de 2 imagens a ferramenta avisa e não executa.
- 7 novos testes (201 no total, 1 skip específico de Windows). A colagem em si (motor, limites, sufixo) não mudou.
- **Limites:** reordenação por botões (sem arrastar dentro da lista); células continuam quadradas; a prévia é uma aproximação do resultado. Sem validação em Windows real.

## Novidades da 0.9.3

- **Nova ferramenta "Ajustar" (`Adjust → PNG`):** brilho, contraste e saturação (−100 a 100 cada) e espelhamento (nenhum, horizontal, vertical, ambos), com prévia ao vivo na tela (calculada com o mesmo código do motor sobre uma cópia reduzida). "Redefinir ajustes" volta tudo a zero; sem nenhum ajuste escolhido o botão fica desligado e o motor recusa o job.
- Os ajustes são gravados nos pixels de um PNG novo `-ajustada`; o original não muda. O canal alfa (transparência) não é alterado pelos ajustes de cor, e é espelhado junto com a imagem. Com várias imagens os mesmos ajustes valem para todas (a prévia mostra a primeira).
- Ordem de aplicação: espelhar, brilho, contraste, saturação. Cada valor vira um fator de 0 a 2 (0 = −100, 1 = neutro, 2 = +100).
- Entra na roda Shift+F9 (painel e flutuante, 2ª fatia, ícone novo) e no relatório de perdas ("Ajustes gravados nos pixels… realces e sombras fortes podem perder detalhe").
- Roda do painel agora tem 9 fatias; o diâmetro máximo subiu para 360 px e rótulos longos (Comprimir, Metadados) encolhem um pouco para caber.
- 10 novos testes (194 no total, 1 skip específico de Windows).
- **Limites:** sem curvas, níveis, nitidez nem temperatura de cor; ajustes não são reversíveis no arquivo novo. Sem validação em Windows real.

## Novidades da 0.9.2

- **Nova ferramenta "Metadados" (`Clean → PNG`):** ao abrir, lista em português o que a imagem guarda além dos pixels: formato e tamanho, fabricante e modelo da câmera, software, autor, direitos, descrição, data e hora, número de série do corpo, **localização GPS** (coordenadas), XMP, comentários, textos do PNG, Photoshop/IPTC e perfil ICC. Destaca o que costuma identificar pessoa, lugar ou aparelho. Com vários arquivos mostra uma linha por arquivo (até 12).
- "Salvar cópia sem metadados" cria um PNG novo `-sem-metadados`: os pixels ficam idênticos (só a orientação do EXIF é aplicada), o perfil de cor é mantido e EXIF, GPS, XMP e comentários não são copiados. O original não muda. Funciona com vários arquivos, um PNG por arquivo.
- `engine.inspect_metadata(path)` lê só o cabeçalho e nunca levanta erro (arquivo ilegível devolve mensagem); textos são limpos de caracteres de controle e limitados a 80 caracteres.
- Entra na roda Shift+F9 (painel e flutuante, ícone novo) e no relatório de perdas.
- 9 novos testes (184 no total, 1 skip específico de Windows).
- **Limites:** a cópia é sempre PNG (JPEG→PNG aumenta o arquivo; limpar sem recomprimir JPEG não é feito); não é anonimização certificada; miniaturas embutidas e metadados não reconhecidos pelo Pillow podem não aparecer na lista. Sem validação em Windows real. Edit/Ajustes continua não implementado.

## Novidades da 0.9.1

- **Nova ferramenta "Ocultar" (`Redact → PNG`):** marque uma ou mais áreas (até 50) sobre a imagem, confirme cada uma com "Adicionar área" (ou salve com a última ainda marcada) e escolha **Tarja preta** ou **Pixelar** (bloco de 4 a 200 px). A ocultação é gravada nos pixels de um PNG novo; o original não muda. Dentro das áreas o resultado é sempre opaco (a transparência não vaza), a pixelização usa a média de cada bloco, e EXIF/XMP/comentários não são copiados.
- As coordenadas valem para a imagem já orientada pelo EXIF; áreas fora da imagem, vazias, em excesso ou com modo/bloco inválido são recusadas sem criar saída. Funciona com uma imagem por vez.
- Aparece na roda Shift+F9 (painel e flutuante, ícone novo), com sufixo `-ocultada` e frase própria no relatório de perdas ("Não é anonimização certificada: confira o resultado").
- A prévia mostra as áreas confirmadas em escuro (tanto para tarja quanto para pixelização; a pixelização só é aplicada ao salvar).
- 12 novos testes (175 no total, 1 skip específico de Windows).
- **Limites:** não é anonimização certificada nem OCR; conteúdo fora das áreas marcadas permanece. Sem validação em Windows real. Edit/Ajustes e Metadata continuam não implementados.

## Novidades da 0.9.0

- **Design system aplicado (a partir do vídeo de referência):** rodas em vidro pêssego com fatias em pétala, fatia ativa laranja-avermelhada, hub central com rótulo (tamanho/ação sob o mouse), ícones só nas fatias de ferramenta, chips segmentados, controles deslizantes e amostras de cor. Os fluxos já existentes foram mantidos.
- **Nova ferramenta "Fundo" (Backdrop → PNG):** coloca a imagem sobre degradê ou cor sólida (ou hex personalizado) com margem 0–600 px, cantos 0–300 px, sombra 0–100 e proporção Auto/1:1/16:9/4:5. Saída limitada a 10000 px por lado e 40 MP; respeita ICC (convertido para sRGB), EXIF e alpha; prévia aproxima a sombra.
- **Nomes de saída em português por ferramenta** (ex.: sufixos descritivos); conversões continuam `-converted`; colisões numeram (-2) sem sobrescrever.
- **Atalhos alternativos ao Shift+F9** (janela "Atalhos"): predefinições de atalho global (Shift+F9, Ctrl+Shift+F9, Ctrl+Alt+F9, Ctrl+Alt+Espaço, Ctrl+Shift+Espaço; Alt+Espaço rejeitado; MOD_NOREPEAT), Shift + botão do meio, soltar arquivos sobre uma fatia ou sobre a janela, e verbo no menu de contexto do Explorer (HKCU, sem admin) via `--send-to "%1"` com IPC local (lote de 350 ms; limite de 15 arquivos pelo Explorer).
- 163 testes (1 skip específico de Windows).
- **Limites:** nada disso foi validado em Windows real (RegisterHotKey, polling do botão do meio, arraste do Explorer, registro). Redact, Edit e Metadata continuam não implementados.

## Novidades da 0.8.8

- **Relatório de perdas ("O que mudou"):** após cada resultado o painel lista, em português, o que a conversão alterou ou perdeu: JPEG/WebP com perda e a qualidade usada, recompressão que acumula perda, transparência trocada por fundo branco (ou pela cor da colagem), redução de tamanho (com o tamanho já orientado), metadados não copiados, orientação EXIF aplicada, perfil de cor preservado/convertido para sRGB/descartado, cinza de 16 bits e CMYK, recorte, anotação gravada nos pixels, colagem, e avisos de PDF (sem OCR; marcadores/anexos/formulários podem não ser preservados). Sem nada a relatar, diz "Nenhuma perda adicional conhecida". Também aparece na dica do histórico.
- `engine.loss_report(paths, target, options)` só lê o cabeçalho das origens e nunca levanta erro; os testes conferem as frases contra as saídas reais (alpha preservado em PNG/TIFF/WebP, EXIF removido, redução de tamanho etc.).
- A coluna de ajustes agora rola, para o relatório e os campos caberem em janelas baixas.
- 8 novos testes (133 no total).

## Novidades da 0.8.7

- **Colagem de imagens (`Collage → PNG`):** de 2 a 12 imagens em um único PNG novo (`collage.png`, sem sobrescrever). Opções: colunas (automático ou 1–6), célula quadrada de 64–2000 px, espaço de 0–200 px e cor de fundo `#RRGGBB`. Cada imagem entra inteira, centralizada na célula e sem ampliar; orientação EXIF aplicada, perfil ICC convertido para sRGB, transparência sobre o fundo; a última linha incompleta é centralizada. Limite de 10000 px por lado e 40 megapixels (erro claro, sem saída). As imagens são abertas uma por vez, para não somar a memória de todas.
- **Onde aparece:** roda Shift+F9 da página Imagens (5ª fatia, "Colagem"), e radial global Shift+F9 quando há de 2 a 12 imagens selecionadas. É um único job na fila (como Unir PDFs), com validação de 2–12 arquivos.
- **Prévia:** layout numerado na ordem da lista, calculado por `engine.collage_layout` (a mesma função do motor); não decodifica as imagens, então é instantâneo. O tamanho final e o aviso de "grande demais" aparecem antes de salvar, e o botão fica desabilitado nesse caso.
- 11 novos testes (125 no total); testes antigos ajustados para a nova operação e para o radial com várias imagens.

## Novidades da 0.8.6

- **Cinza de 16 bits (I;16 / I):** antes saía branco puro; agora é reduzido para 8 bits proporcionalmente (0→0, 32768→128, 65535→255) em PNG, JPEG, PDF etc. Vale também para prévia e estimativa, que usam o mesmo `open_image`.
- **CMYK:** convertido para sRGB pelo perfil embutido quando ele é um perfil CMYK válido; sem perfil (ou com perfil incompatível) usa a conversão simples do Pillow, que é aproximada. Não há fixture com perfil CMYK real; só os caminhos sem perfil e com perfil incompatível são testados.
- 3 novos testes (114 no total). RGB de 16 bits já era reduzido pelo Pillow ao abrir.

## Novidades da 0.8.5

- **Perfil de cor ICC:** preservado em PNG, JPEG, WEBP e TIFF quando é válido e compatível com o modo (RGB/cinza); em BMP e Image → PDF, que não guardam perfil, os pixels são convertidos para sRGB. Perfil inválido ou incompatível é descartado sem erro. A estimativa da compressão passou a incluir o perfil e continua idêntica ao tamanho real.
- **Limite de 40 MP:** imagens grandes agora falham com a mensagem em português (antes podia vazar o aviso interno do Pillow).
- **Fixtures sintéticas de fidelidade (`tests/test_fixtures.py`, 20 testes; 111 no total):** as 8 orientações EXIF (saída em pé, EXIF removido, coordenadas de Crop na imagem orientada, prévia igual à exportação), alpha (PNG/TIFF/WebP preservam; BMP/JPEG/Compress/PDF achatam sobre branco; paleta e cinza+alpha), ICC (preservado, convertido, inválido), limites (40 MP, 100 MiB, truncado, falso, animado), original com SHA-256 intacto e saída reaberta/verificada.

## Novidades da 0.8.4

- **Predefinições de compressão JPEG:** Leve (95), Equilibrado (88, o padrão anterior), Pequeno (70), Mínimo (50) e Personalizado; mexer na qualidade seleciona a predefinição correspondente.
- **Estimativa antes de salvar:** tamanho original, tamanho estimado e variação em %, com a imagem já comprimida na prévia. Usa `engine.jpeg_bytes`, a mesma codificação do motor (teste confirma que o tamanho estimado é idêntico ao do arquivo gerado). Limitada a imagens de até 12 megapixels, para não travar a interface; acima disso a tela avisa que o tamanho real só aparece depois. Avisa quando o JPEG ficaria maior que o original.
- 3 novos testes (91 no total).

## Validação e limitações

- Verificado só no Sandbox Linux (Qt offscreen): `py_compile`, 133 testes (1 skip específico de Windows), smoke test e captura renderizada. Nada substitui o gate Windows 10 Pro 22H2 (mouse real, DPI, tray, Explorer/COM, hotkey, PyInstaller, Defender, SmartScreen).
- A estimativa roda na interface (imagem já validada pelo motor), não no worker; o arquivo final continua sendo gerado pelo worker com staging.
- Limites: CMYK sem perfil é aproximado; ponto flutuante (modo F) não tem tratamento específico; WebP/JPEG são com perda por natureza. O relatório de perdas é textual: não mede diferença de pixels (PSNR/SSIM) nem tamanho de arquivo (a compressão já mostra bytes). A prévia da colagem mostra o layout, não as miniaturas; o ajuste de ordem é feito pela ordem da lista de arquivos. O worker não é sandbox e ainda não usa Job Object.

## Histórico

- `0.8.7-phase2-dev`: colagem de 2 a 12 imagens.
- `0.8.6-phase2-dev`: cinza de 16 bits e CMYK tratados.
- `0.8.5-phase2-dev`: fixtures de fidelidade (EXIF, alpha, ICC, limites) e perfil ICC preservado/convertido.
- `0.8.4-phase2-dev`: predefinições de compressão com estimativa e prévia do resultado.
- `0.8.3-phase2-dev`: proporções fixas no recorte e prévia de rotação/tamanho na conversão.
- `0.8.2-phase2-dev`: identidade clara, rodas de fatias, recorte com alças, prévias de anotar e canvas, tamanho da anotação, mensagens em português.
- `0.8.1-phase2-dev`: UX por categorias, preview/seleção de Crop no workspace, radial secundário contextual.
- `0.8.0-phase2-dev`: primeira entrega do Image Core (crop numérico, canvas, anotação, compressão) antes da mudança de UX.
- `0.7.0-phase1-dev`: radiais, Shift+F9, clipboard, shell, prateleira, fila, staging, capability probe e lock de instância única; Windows gate pendente.
