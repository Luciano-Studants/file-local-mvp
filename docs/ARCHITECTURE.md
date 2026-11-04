# Arquitetura — Arquivo Local

Objetivo do produto: aplicativo de desktop **publicável e instalável** em Windows 10, Windows 11 e Linux, 100% offline, que preserva o original e nunca sobrescreve em silêncio (licença GPL-3.0-only; interface e textos em português do Brasil).

## Estilo adotado: núcleo puro + registro de ferramentas + adaptadores de plataforma

```
┌──────────────────────────── Interface (PySide6) ───────────────────────────┐
│ workspace_panel · radial_menu · visual_tools · widgets · theme · icons      │
│ tray_app (bandeja, JobController: fila, lista branca de opções)             │
└───────────────▲──────────────────────────────────────▲─────────────────────┘
                │ lê tabelas derivadas                   │ chama portas
┌───────────────┴────────────┐              ┌───────────┴───────────────────┐
│ tool_registry.py           │              │ Adaptadores de plataforma     │
│ ToolSpec: nome, sufixo,    │              │ windows_bridge (seleção do    │
│ formato, opções, rótulos,  │              │ Explorer) · global_hotkey ·   │
│ ícone, risco               │              │ shell_integration · ipc       │
└───────────────▲────────────┘              │ (Linux: a criar, ver ADR-0001)│
                │                           └───────────────────────────────┘
┌───────────────┴──────────────────────────────────────────────────────────┐
│ Núcleo (sem Qt, sem API do sistema): engine.py · package.py · runner.py   │
│ Contrato: job {paths, target, options} → arquivos novos + relatório       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Regras (verificadas por `tests/test_architecture.py`)
1. **O núcleo não importa Qt, interface nem módulos de Windows.** Isso mantém a lógica de conversão testável em qualquer sistema e permite trocar a interface ou o motor no futuro.
2. **APIs exclusivas do Windows (`win32*`, `pythoncom`, `winreg`) só aparecem nos módulos de plataforma.** Todo suporte a Linux entra como novos adaptadores, sem tocar no núcleo.
3. **`tool_registry.py` é a fonte única de cada ferramenta.** Motor, bandeja, painel e roda derivam suas tabelas dele (sufixos, formatos, lista branca de opções, rótulos, ícones). Registrar sem ligar uma camada derruba o teste de arquitetura.
4. **O job é um contrato.** Opções são lista branca por tipo (inteiro, texto, lista); o motor valida de novo tudo o que recebe.
5. **Rasterizadores como portas (implementado na 0.9.19):** `vector.py` (núcleo, sem Qt) lê e limpa o SVG, calcula o tamanho e entrega o texto limpo a um adaptador que devolve uma imagem RGBA. Adaptadores fora do núcleo, em ordem de preferência: `vector_resvg.py` (pacote `resvg-py`) e `vector_qt.py` (QtSvg, alternativa). O núcleo os carrega por nome (`importlib`) na hora de desenhar, então trocar ou acrescentar um desenhista não mexe no motor.
6. **PDF como entrada hostil (0.9.29):** `pdfinfo.py` (núcleo, sem Qt) lê, limita e desenha páginas; a interface **nunca** abre um PDF: pede ao worker descartável (`runner.run_pdf_op` → `pdfinfo.run_op`) e recebe PNGs por uma pasta temporária privada. `pdf_stage.py` só exibe o que o worker devolveu, ignorando respostas de pedidos antigos.
7. **Segurança de arquivos:** saída em área privada → publicação atômica com nome novo; original intocado; sem rede; sem execução de shell.

## Definição de pronto de uma ferramenta (checklist)
1. `ToolSpec` em `tool_registry.py` (inclui risco e opções).
2. Função pura no motor + validação + nota no relatório de perdas (`loss_report`).
3. Controles, dica, texto do botão e prévia no painel; entrada na roda (ícone em `icons.py`).
4. Testes: tamanho/valores, entradas inválidas, original intacto, sem sobrescrever, alfa/EXIF/ICC quando couber, painel, lista branca.
5. `test_architecture` verde; suíte completa verde em Linux; item novo no diagnóstico do Windows.
6. Registro de continuidade e RELEASE atualizados.
7. **Roda:** a ferramenta está num grupo da roda (`PDF_GROUPS`/`AUDIO_GROUPS`/`GROUPS`), com rótulo ≤ 13 caracteres e descrição; `tests/test_wheel_layout.py` passa (≤ 8 fatias por roda) e a roda foi conferida visualmente.

## Camadas de teste
| Camada | Onde | Mede |
|---|---|---|
| Unidade do núcleo | `test_engine`, `test_resize`, … | correção por função |
| Contrato/arquitetura | `test_architecture` | ligações entre camadas e fronteiras |
| Fixtures douradas | `test_fixtures`… | EXIF, ICC, alfa, 16 bits, CMYK, limites |
| Interface offscreen | `test_ui`, `test_design`… | painel, roda, foco, arrasto |
| Windows real | suíte no PC + `windows_acceptance_check.py` | integração e diferenças de SO |
| **Prova de qualidade por categoria** | ver `docs/PLANO-CATEGORIA-IMAGENS.md` | fidelidade, segurança, desempenho, robustez (feita só ao fechar a categoria) |

## Decisões
Registradas em `docs/ADR-*.md`. A decisão sobre linguagem e multiplataforma está em `docs/ADR-0001-linguagem-e-multiplataforma.md`.

7. **PDF → imagens (0.9.30):** `pdfinfo.render_dpi` desenha uma página por vez (40 MP/página, fundo branco, sem formulários/anotações); `engine.pdf_to_images` valida o intervalo e todos os tamanhos antes de desenhar e só publica no fim. Dentro do runner as páginas ficam soltas na pasta privada do job e `runner.run_job` as publica na pasta «<nome> - páginas» (única forma compatível com a regra «saída só na pasta privada»).

8. **Unir PDFs (0.9.31):** `merge_ranges` (lista de textos, um por arquivo, na ordem de `paths`) é a única opção de lista fora das ferramentas de imagem (`tool_registry.BASE_LIST_OPTIONS`); o motor valida cada intervalo com `pdfinfo.parse_page_range` e usa `PdfWriter.append(..., pages=[...], outline_item=nome)` do pypdf, que mantém só os marcadores das páginas incluídas.

9. **Saídas em grupo (0.9.32):** ferramentas que geram vários arquivos de uma vez (PDF → imagens, Dividir) devolvem arquivos soltos na pasta privada do job; `engine.output_group_suffix(job)` diz o sufixo da pasta dedicada e o `runner.run_job` a cria e publica depois que o worker termina. Fora do runner (`convert()` direto), `engine.publish_group` faz o mesmo e desfaz a pasta se algo falhar.

10. **Organizar páginas (0.9.33):** a interface guarda o plano como lista de itens (`page_organizer.PageOrganizer`) e envia só `organize_pages` (`"página:giro"`); o motor reconstrói o PDF com `PdfWriter.append(pages=[n])` por entrada (uma cópia independente a cada vez) e `rotate`. As miniaturas vêm do worker em lotes (`pdf_preview` com `first`), nunca do processo da interface.

16. **Senha de PDF (0.9.39):** `engine.pdf_protect` clona o PDF e chama `PdfWriter.encrypt(..., algorithm='AES-256')` (revisão 6; exige o pacote `cryptography`), conferindo `/AESV3`, que a senha abre e que a senha vazia não abre. `engine.pdf_unprotect` usa `pdfinfo.open_protected` (UMA tentativa; tipo 0/1/2 = sem senha/abertura/proprietário) e recusa remover restrições de uso (`pdfinfo.has_restrictions`) sem a senha de proprietário. A senha viaja só no JSON de stdin do worker (nunca em argv), não entra em `loss_report`, mensagens de erro nem histórico, e o painel limpa os campos ao iniciar a tarefa, trocar de ferramenta ou de arquivo. As demais ferramentas de PDF continuam recusando PDFs com senha, apontando para «Remover senha».
15. **Carimbo (0.9.38):** `pdfstamp.py` (núcleo puro) gera um fluxo de conteúdo com `BT … Tj ET` em Helvetica/WinAnsi (uma das 14 fontes padrão: sem embutir, texto selecionável) sobre uma página-sobreposição com os recursos de fonte e `ExtGState` (`ca`/`CA`) e `engine.pdf_stamp` a mescla com `merge_page` numa cópia clonada (marcadores, anexos e formulários seguem). A geometria é a da página como aparece: CropBox, `/Rotate` (0/90/180/270) e giro do texto; larguras vêm de `pypdf._codecs.core_font_metrics` (se o módulo interno sumir, usa 556/1000 por caractere). O resultado é conferido (páginas e texto da primeira página carimbada).
14. **Comprimir PDF (0.9.37):** `pdfcompress.py` (núcleo puro) calcula a resolução efetiva de cada imagem pelo tamanho em que ela é desenhada (matriz `cm` do fluxo de conteúdo, maior uso vence) e recodifica no próprio objeto: JPEG → JPEG (LANCZOS), foto em Flate → JPEG (níveis Médio/Forte), arte chapada em Flate → Flate reduzido com BOX; só fica o que for menor. `engine.pdf_compress` usa as duas passadas (clonar de novo descarta órfãos) e recusa se o ganho for menor que 1 %. Jobs longos (`PDF_LONG_TARGETS`) ganham 900 s.
13. **Cópia limpa (0.9.36):** `pdfinfo.clean_scan` lê o que há (Info, `/Metadata`, `/PieceInfo`, anexos, JavaScript em nomes, abertura, páginas, anotações e campos) e `clean_apply` remove; `engine.pdf_clean` clona o PDF (`PdfWriter(clone_from=…)`), remove, grava em memória e **clona de novo** o resultado, porque o pypdf mantém objetos órfãos na primeira passada. Depois reabre o arquivo e confere que nada marcado sobrou. `writer._info = None` (atributo interno do pypdf) tira o Info; a conferência pega qualquer mudança futura.
12. **OCR de PDF (0.9.35):** `engine.pdf_ocr` rasteriza cada página escolhida com `pdfinfo.render_dpi` a 300 dpi, passa por `ocr_prepare` e chama `ocr.recognize` (Tesseract como processo externo). O PDF pesquisável usa as páginas de uma página do Tesseract (JPEG q85) na ordem escolhida e copia as páginas puladas (já com texto) do original; o texto reaproveita `write_text_chunks`. `runner.run_job` amplia o tempo para `PDF_OCR_TIMEOUT` (900 s).
11. **Texto e imagens embutidas (0.9.34):** `pypdf` extrai texto (`extraction_mode` simples ou `layout`); as imagens vêm do PDFium (`PdfPage.get_objects` filtrando imagens, `PdfImage.extract`), porque ele entrega JPEG/JPEG 2000 sem recodificar e decodifica o resto com segurança dentro do worker. O tamanho em pixels é conferido antes de extrair. `engine.output_group_suffix` ganhou ` - texto` e ` - imagens`.
17. **Tarjar conteúdo (0.9.40):** `pdfredact.py` (núcleo sem Qt) valida áreas («página:x0,y0,x1,y1» em milésimos da página como aparece), termos (2–60 caracteres, ≤20) e padrões prontos (CPF, CNPJ, e-mail, telefone), acha trechos no texto do pdfium e converte as caixas dos caracteres (espaço do PDF sem rotação, CropBox) em pixels da página já girada. `engine.pdf_redact` desenha só as páginas afetadas com `pdfinfo.render_dpi`, pinta retângulos pretos nos pixels, regrava essas páginas como imagem (PDF de uma página via Pillow) e copia as demais com pypdf (`import_outline=False`, `_info=None`); `redact_verify` reabre o arquivo gerado e exige: mesmo número de páginas, sem marcadores/anexos/formulário/XMP/Info, sem texto nas páginas rasterizadas, sem os termos nas demais e tarjas realmente pretas na renderização; qualquer falha descarta o resultado. A interface reaproveita `PdfStage(selectable=True)` (CropView) e guarda as áreas em milésimos da página, por página. Limite honesto: termos só existem em PDF com texto; páginas digitalizadas exigem área marcada.
18. **Formulários e assinatura visual (0.9.41):** `pdfform.py` (núcleo sem Qt) percorre os widgets das páginas (`/Annots` com `/Subtype /Widget`), monta o nome qualificado pela cadeia `/Parent` e herda `/FT`, `/Ff`, `/V`, `/Opt`, `/MaxLen`; tipos: texto, caixa, opção única (estado «ligado» lido de `/AP /N`), lista; assinatura digital, botão e somente leitura não são preenchíveis. `fill` grava texto via `PdfWriter.update_page_form_field_values` (aparência do pypdf), caixas/opções trocando `/V` e `/AS`, e listas com aparência própria (o pypdf desenharia todas as opções). `flatten` desenha o XObject de aparência de cada widget visível na página pela matriz BBox→Rect (como manda a especificação), remove widgets e `/AcroForm` (a parte `/XFA` é sempre descartada). A assinatura é um XObject de imagem com `/SMask` (transparência) posicionado por matriz calculada com `pdfstamp._to_user`, o que cobre rotação e CropBox; é só imagem, nunca assinatura digital. `engine.pdf_form` confere o arquivo gerado (páginas, valores, ausência de campos ao achatar, imagem na página) antes de publicar. A interface usa `PdfStage(selectable=True)` com realce (não preenchimento) da área; as informações dos campos chegam em `info['form_fields']` pelo mesmo worker de leitura.
19. **Portão B do PDF (0.9.42):** `tools/quality_suite.py` monta o corpus de PDFs em código (`write_pdf_corpus`: PDF de texto escrito à mão sem biblioteca, escaneado, formulário de `tests/formfixture.py`, senha, truncado/corrompido/falso, 200/201 páginas, página gigante, JS/anexos, rotação+CropBox, e PDF do LibreOffice se houver `soffice`) e mede por função: invariantes (hash do original, sobras `.part/.tmp`, `NoNetwork` conta tentativas de conexão), fidelidade (texto extraído e SSIM das páginas renderizadas), redação (`pdf_blob` junta bytes, fluxos descomprimidos, objetos e texto para procurar os segredos; OCR sobre o resultado), robustez (entradas defeituosas só podem gerar `ConversionError`), geometria, senha, OCR e desempenho. Nota = aprovadas ÷ (aprovadas + falhas bloqueantes) × 100; reprova com qualquer falha bloqueante ou função abaixo de 80.
20. **Áudio (0.9.43):** `mediatools.py` (base: localiza FFmpeg/ffprobe, licença do build, `audio_info`) e `audioconvert.py` (conversão; argumentos validados, `-protocol_whitelist file` + `-format_whitelist`, estimativa de tamanho, conferência com ffprobe) são núcleo sem Qt. `engine.AUDIO_CONVERT` usa o limite de entrada `AUDIO_MAX_BYTES` (512 MiB) e o tempo longo do runner; o FFmpeg é processo filho do worker (cancelar mata a árvore). A interface usa `audio_stage.py` (informações, leitura no worker) e a roda `AUDIO_GROUPS`.
