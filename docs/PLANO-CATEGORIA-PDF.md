# Plano da categoria PDF — ordem por risco e lógica

Mesmo método da categoria Imagens: **uma funcionalidade por entrega** (comando "Próximo passo"), na ordem abaixo; só ao fechar a categoria roda a **prova de qualidade** (Portão B) com corpus de PDFs. Cada entrega segue a definição de pronto de `ARCHITECTURE.md`. Versões a partir da 0.9.29.

## Por que PDF é a próxima categoria (e não Vídeo, que vem logo depois na lista original)
1. **Base já pronta:** `pypdf` (texto, unir, dividir), `pypdfium2` (rasterizador, entrou na 0.9.23), OCR com Tesseract, «Imagens → um PDF», prévia, worker com limites, Job Object. Quase nenhuma dependência nova.
2. **Público forte do app (administrativo):** unir, dividir, comprimir, proteger e extrair PDF são o trabalho diário desse público.
3. **Risco baixo/médio:** tudo roda offline, testável por completo no Linux, sem política de codec/patente (Vídeo e Áudio exigem decidir FFmpeg: distribuição, licença LGPL/GPL, patentes).
4. **Fecha lacunas deixadas em Imagens:** PDF→imagem e PDF digitalizado→PDF pesquisável.

Ordem das categorias seguintes (a confirmar): **Áudio → Vídeo** (precisam de ADR do FFmpeg), depois Documentos, Slides, Planilhas, EPUB, Legendas e Arquivos.

## Já existe (herdado da Fase 1/2)
PDF→texto, unir PDF, dividir PDF (motor), «Imagens → um PDF» (com OCR opcional), OCR→PDF pesquisável de imagem, rasterizador `pypdfium2`. Limites atuais: 200 páginas, 100 MiB. A categoria PDF no painel hoje é só uma tela simples; **não há prévia de páginas nem miniaturas**.

## Requisitos transversais (valem para todos os itens)
- Original intacto; saída em staging privado, publicação atômica com nome novo, nunca sobrescreve; sufixos em português (`-unido`, `-paginas`, `-comprimido`…).
- 100% offline; sem JavaScript, sem executar ações do PDF, sem abrir anexos/links; `may_draw_forms=False` e anotações desligadas na prévia.
- PDF é entrada hostil: tudo no worker (com Job Object no Windows), limites de arquivo, páginas, dimensão de página e megapixels por página; senha, truncado e corrompido recusados com mensagem clara em português.
- PDF criptografado: pedir senha só quando a ferramenta precisar; senha nunca gravada em log, histórico ou relatório.
- Relatório de perdas por ferramenta (ex.: «formulários achatados», «marcadores removidos», «texto virou imagem»).
- Licenças: **evitar PyMuPDF/MuPDF (AGPL)** e Ghostscript embutido; manter `pypdf` (BSD), `pypdfium2` (Apache/BSD). Dependência nova só com licença conferida e registrada em `THIRD_PARTY_NOTICES.md`/`licenses/SOURCES.md`.
- Roda radial: topo ≤ 7 fatias + «Voltar»; ferramentas agrupadas (sugestão: **Páginas, Converter, Proteger, Ler texto, Otimizar**); rótulos ≤ 10 caracteres; seleção múltipla de PDFs abre «Unir».
- Cada ferramenta nova: `ToolSpec` → função no motor → `loss_report` → controles/dica/prévia no painel → ícone → testes → `test_architecture` verde → item no diagnóstico do Windows → RELEASE/registro atualizados.

## Fila ordenada

| # | Funcionalidade | Risco | Depende de | O que entrega |
|---|---|---|---|---|
| 1 | ~~**Base da categoria PDF**~~ (**0.9.29**) | médio | — | `.pdf` como entrada; leitura segura (`pdfinfo`: páginas, tamanho, senha, versão, metadados); prévia de página e **faixa de miniaturas** via `pypdfium2` no worker; painel PDF no mesmo padrão visual de Imagens; grupos da roda; limites configurados |
| 2 | ~~**PDF → imagens**~~ (**0.9.30**) | baixo | 1 | PNG/JPEG/WebP/TIFF… (reaproveita «formato de saída»), DPI 72–600 com teto de 40 MP por página, intervalo de páginas (`1-3,7`), pasta numerada `pagina-001…`, transparência/fundo branco |
| 3 | ~~**Unir (melhorado)**~~ (**0.9.31**) | baixo | 1 | miniaturas, reordenar arrastando, escolher intervalo por arquivo, preservar marcadores quando possível, relatório do que se perdeu |
| 4 | ~~**Dividir e extrair páginas**~~ (**0.9.32**) | baixo | 1 | por intervalos, a cada N páginas, uma por arquivo, extrair seleção marcada nas miniaturas; saída em pasta numerada |
| 5 | ~~**Organizar páginas**~~ (**0.9.33**) | médio | 1, 4 | girar, excluir, duplicar e reordenar páginas com miniaturas; salva em PDF novo (nunca edita o original) |
| 6 | ~~**Extrair texto (melhorado) e imagens embutidas**~~ (**0.9.34**) | baixo | 1 | texto por página/único (`.txt`), aviso quando o PDF não tem camada de texto (sugerir OCR); extrair imagens originais sem recomprimir |
| 7 | ~~**OCR de PDF digitalizado → PDF pesquisável / texto**~~ (**0.9.35**) | médio | 1, 2 | páginas rasterizadas (pypdfium2) → Tesseract → camada de texto invisível; idioma `por+eng`; limite de páginas e tempo por página; fecha a lacuna da 0.9.22 |
| 8 | ~~**Metadados do PDF**~~ (**0.9.36**) | baixo | 1 | ver autor, programa, datas, XMP; **cópia limpa** (remover metadados, anexos, JavaScript) — alto valor administrativo/jurídico |
| 9 | ~~**Comprimir PDF**~~ (**0.9.37**) | médio-alto | 1, 2 | níveis (leve/médio/forte), recompressão de imagens (JPEG) e redução de DPI; relatório de tamanho antes/depois; nunca aumentar (se não reduzir, avisar e não salvar); sem Ghostscript |
| 10 | ~~**Numerar páginas, cabeçalho/rodapé e marca d'água**~~ (**0.9.38**) | médio | 1 | texto/numeração (`Página {n} de {total}`), 9 posições, opacidade, intervalo de páginas; sobreposição gerada com Pillow + `pypdf` (fonte livre empacotada, p.ex. DejaVu) |
| 11 | ~~**Proteger e desproteger (senha)**~~ (**0.9.39**) | médio | 1 | definir senha de abertura/permissões com AES-256 e **remover senha informada pelo usuário** (nunca quebrar senha); provável dependência `cryptography` (Apache/BSD) a conferir |
| 12 | ~~**Tarjar/ocultar conteúdo (redação segura)**~~ (**0.9.40**) | alto | 1, 2 | marcar áreas na página e **rasterizar as páginas afetadas** (único jeito honesto de remover o texto por baixo); aviso claro de que o resultado perde a camada de texto; verificação automática de que o texto tarjado sumiu |
| 13 | ~~**Preencher formulários (AcroForm) e assinatura visual**~~ (**0.9.41**) | alto | 1 | listar campos, preencher, achatar; inserir imagem de assinatura (não é assinatura digital certificada — dizer isso na tela) |
| — | Retoques (arrastar páginas entre arquivos, favoritos de intervalo, atalho «Comprimir para e-mail») | baixo | — | podem entrar entre as entregas |

## Fora do escopo desta categoria (decisão para evitar promessa falsa)
- **PDF → Word/Excel/PowerPoint:** pertence às categorias Documentos/Planilhas/Slides.
- **PDF/A e PDF/UA certificados**, assinatura digital com certificado, comparação de PDFs, edição livre de texto existente: não serão simulados; só entram se pedidos, com ADR próprio.
- **Ghostscript, PyMuPDF:** não embutidos (licença AGPL).

## Portões
- **Portão A (por entrega):** testes novos + `test_architecture` + suíte completa em Linux + item no diagnóstico do Windows.
- **Portão B (fim da categoria):** estender `tools/quality_suite.py` com **corpus de PDFs**: texto simples, escaneado, formulário, com senha, truncado, corrompido, 200 páginas, página gigante, com JavaScript/anexos, fontes não incorporadas, rotação/CropBox, PDF produzido por Word/LibreOffice/impressora virtual. Medir: invariantes de segurança (original intacto, sem parciais, sem rede), fidelidade (SSIM da página renderizada antes/depois, texto extraído igual onde deveria), tempo e memória por página, taxa de acerto do OCR, redação sem vazamento. Nota por função 0–100; aprovação = nenhuma abaixo de 80.
- **Evidência Windows:** continua pendente desde a 0.9.6; antes de distribuir, reexecutar suíte e percorrer os itens do diagnóstico (incluindo `WindowsRenderTests`, Job Object e instalador).

## Entregas
- **0.9.29 — item 1, base da categoria PDF (30/10/2026):** `pdfinfo.py` (leitura segura, limites, informações, desenho de páginas), operações `pdf_info`/`pdf_preview` no worker, `pdf_stage.py` (resumo, página grande, miniaturas, lista de vários PDFs), Unir/Separar/Texto com as mesmas verificações. 40 testes novos. Os **grupos da roda** para PDF ficam para quando houver ao menos duas ferramentas por grupo (item 2 em diante). Verificado só no Linux.
- **0.9.30 — item 2, PDF → imagens (31/10/2026):** alvo `PDF → Images`, `pdfinfo.parse_page_range/render_dpi/page_pixels_ok`, painel com dpi/páginas/tamanho, ação radial «Imagens», pasta «<nome> - páginas». 20 testes novos (814 no total). Verificado só no Linux.
- **0.9.31 — item 3, Unir (melhorado) (31/10/2026):** lista arrastável, intervalo por arquivo (`merge_ranges`), marcador por arquivo + marcadores preservados, total de páginas, saída `unido.pdf`. 13 testes novos. Reordenar na prévia com miniaturas das páginas (não só dos arquivos) fica como retoque. Verificado só no Linux.
- **0.9.32 — item 4, Dividir e extrair páginas (31/10/2026):** modos uma por página / a cada N / por intervalos / extrair, pasta «- partes», marcadores preservados, painel com resultado e bloqueio. 15 testes novos (842 no total). Extrair clicando nas miniaturas fica como retoque. Verificado só no Linux.
- **0.9.33 — item 5, Organizar páginas (31/10/2026):** miniaturas arrastáveis, girar/duplicar/excluir/mover/restaurar, `organize_pages`, saída `-organizado.pdf`. 15 testes novos. Marcadores não são preservados (reordenar torna o mapeamento ambíguo); anotar isso na tela foi feito. Verificado só no Linux.
- **0.9.34 — item 6, Extrair texto (melhorado) e imagens embutidas (31/10/2026):** texto por páginas/modos/layout com erro claro em PDF digitalizado; imagens embutidas sem recomprimir JPEG, deduplicadas, pasta «- imagens». 19 testes novos. Verificado só no Linux.
- **0.9.35 — item 7, OCR de PDF digitalizado (31/10/2026):** alvos `PDF OCR → PDF` (`<nome>-pesquisavel.pdf`) e `PDF OCR → Text` (`<nome>-ocr.txt` ou pasta «- texto»); 300 dpi, páginas escolhidas, pula páginas que já têm texto, limite de 20 páginas com OCR, tempo do job 900 s. 14 testes novos (Tesseract eng). Verificado só no Linux; pt exige tessdata `por` no pacote.
- **0.9.36 — item 8, Metadados do PDF (01/11/2026):** alvo `Clean PDF` (`<nome>-limpo.pdf`); painel mostra Info, XMP, anexos, JavaScript e formulário; remove metadados/anexos/JavaScript à escolha com conferência do resultado e duas passadas (sem restos no arquivo). 11 testes novos. Não remove EXIF dentro de imagens; assinaturas digitais ficam inválidas. Verificado só no Linux.
- **0.9.37 — item 9, Comprimir PDF (01/11/2026):** alvo `Compress PDF` (`<nome>-comprimido.pdf`), níveis Leve/Médio/Forte (300/150/96 dpi; JPEG q88/72/55), resolução efetiva pela matriz `cm`, fotos sem perda viram JPEG em Médio/Forte, imagens com máscara/CMYK/paleta/em formulários internos intactas, nunca aumenta (exige ≥1 % de ganho), antes → depois no status. Módulo novo `pdfcompress.py`. 12 testes novos. Sem Ghostscript. Verificado só no Linux.
- **0.9.38 — item 10, Numerar páginas, cabeçalho/rodapé e marca d'água (01/11/2026):** alvo `Stamp PDF` (`-numerado`/`-carimbado`/`-marcadagua`), texto vetorial Helvetica (WinAnsi, sem embutir fonte), `{n}`/`{total}`, primeiro número, intervalo de páginas, 9 posições, margem, cor, negrito, opacidade, marca diagonal centrada, páginas com /Rotate e CropBox. Módulo novo `pdfstamp.py`. 15 testes novos. Sem prévia do carimbo na página (retoque). Verificado só no Linux.
- **0.9.39 — item 11, Proteger e desproteger (senha) (01/11/2026):** alvos `Protect PDF` (`-protegido`, AES-256, senha de abertura ≥4, restrições imprimir/copiar/editar só com senha de permissões diferente, conferência do resultado) e `Unprotect PDF` (`-desprotegido`, uma tentativa com a senha informada, restrições só saem com a senha de proprietário); dependência nova `cryptography` 50.0.2 (Apache-2.0 OU BSD-3) + cffi + pycparser, licenças registradas. Senha nunca em mensagens, relatório, histórico nem argv; campos limpos ao iniciar. 12 testes novos. Verificado só no Linux.
- **0.9.40 — item 12, Tarjar/ocultar conteúdo (02/11/2026):** alvo `Redact PDF` (`<nome>-tarjado.pdf`); áreas marcadas na página (milésimos), termos e padrões CPF/CNPJ/e-mail/telefone; páginas afetadas rasterizadas (150/200/300 dpi) com tarjas pintadas nos pixels; remove marcadores, anexos, formulários e metadados; conferência automática (sem texto sob a tarja, tarja preta, sem termo nas demais, sem restos) — falhou, nada é salvo. Nada achado e sem área → erro, nada salvo. 25 testes novos. Limites: termos só em PDF com texto; rotação 90/270 testada; assinatura digital perdida.
- **0.9.41 — item 13, Preencher formulários e assinatura visual (02/11/2026):** alvo `Fill PDF` (`<nome>-preenchido.pdf`); lista campos AcroForm, preenche texto/caixa/opção/lista, achata (aparências na página, campos e XFA removidos), imagem de assinatura (PNG com transparência, várias áreas, páginas giradas) com aviso de que não é assinatura digital certificada; conferência do resultado. 26 testes novos. Limites: sem desenhar/ditar assinatura à mão no app; sem campos de data/número com máscara JavaScript; formulários XFA puros ficam sem campos.
- **0.9.42 — Portão B (02/11/2026):** corpus de PDFs e 8 seções de qualidade em `tools/quality_suite.py` (invariantes, fidelidade, redação sem vazamento, robustez, geometria, senha, OCR, desempenho); nota 0–100 por função e aprovação com nenhuma abaixo de 80. Linux: 117 verificações passam. Corrigido `identical()` (olhava só o alfa). 7 testes novos.
- **Categoria PDF concluída (13/13) e Portão B aprovado no Linux.** **Próxima:** reexecução no Windows (suíte, diagnóstico, `quality_suite`, PyInstaller com cryptography e os módulos novos) e pendências legais.
