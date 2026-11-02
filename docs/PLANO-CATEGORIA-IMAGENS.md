# Plano da categoria Imagens — ordem por risco e lógica

Método: **uma funcionalidade por entrega**, na ordem abaixo; só ao fechar a categoria roda a **prova de qualidade** (seção final). Critério de ordem: (1) dependência técnica, (2) risco de implementação, (3) valor para o estágio atual. Cada entrega segue a definição de pronto de `ARCHITECTURE.md`.

## Já entregue
Conversão PNG/JPEG/WebP/TIFF/BMP, Imagem→PDF (uma imagem por PDF), Recortar, Canvas, Fundo, Anotar (texto), Ocultar, Metadados (cópia limpa PNG), Ajustar, Comprimir JPEG, Colagem, **Remoção de fundo offline com U²-Net (0.9.25), EMF/WMF como entrada, só no Windows (0.9.24), Illustrator .ai moderno como entrada (0.9.23), OCR em texto e PDF pesquisável (0.9.22), HEIC como entrada e saída (0.9.21), AVIF como formato de saída (0.9.20), Vetores SVG/SVGZ como entrada (0.9.19), ICO e GIF estático como formatos de saída (0.9.18), Várias imagens → um PDF (0.9.17), Renomeação em lote (0.9.16), Formas (0.9.15), Níveis e auto-níveis (0.9.14), Nitidez e desfoque (0.9.13), Redimensionar (0.9.8), Girar e espelhar (0.9.9), sub-rodas/agrupamento (0.9.10), formato de saída nas ferramentas e cópia limpa em JPEG/WebP (0.9.11), marca d'água (0.9.12)**.

## Fila (próxima = a primeira não entregue)
| # | Funcionalidade | Risco | Depende de | Por que nesta posição |
|---|---|---|---|---|
| 1 | ~~Redimensionar~~ (0.9.8) | baixo | — | mais pedida, sem dependências novas |
| 2 | ~~Girar 90°/180°/270° e espelhar~~ (0.9.9) | baixo | — | completa as transformações geométricas |
| 2b | ~~Agrupar fatias da roda~~ (0.9.10) | médio | 2 | roda de 11 fatias no limite; agora 4–5 fatias + sub-rodas |
| 3 | ~~Formato de saída nas ferramentas~~ (0.9.11) | médio | 1–2 | PNG/JPEG/WebP/TIFF/BMP, qualidade, fundo opaco; base para vetores e novas ferramentas |
| 4 | ~~Cópia limpa em JPEG/WebP~~ (0.9.11, junto com o item 3) | baixo | 3 | usa a escolha de formato |
| 5 | ~~Marca d'água~~ (0.9.12) | médio | 3 | texto/logotipo, 9 posições + repetição, opacidade, prévia ao vivo |
| 6 | ~~Nitidez e desfoque~~ (0.9.13) | baixo | 3 | máscara de nitidez e gaussiano, raio proporcional, prévia ao vivo |
| 7 | ~~Níveis e auto-níveis~~ (0.9.14) | médio | 6 | histograma, pontos preto/branco, gama, automático por imagem. **Curvas** (editor de pontos) ficam como retoque futuro |
| 8 | ~~Anotação com formas~~ (0.9.15) | médio-alto | — | retângulo, elipse, linha e seta, até 50, prévia ao vivo; novo grupo «Desenhar». Texto múltiplo e edição/movimento de formas já adicionadas ficam como retoque |
| 9 | ~~Lote com renomeação~~ (0.9.16) | médio | 3 | padrão `{nome}`/`{n}`/`{sufixo}`/`{data}` em todas as saídas de imagem, numeração pela fila, nomes seguros, nunca sobrescreve |
| 10 | ~~Várias imagens → um PDF~~ (0.9.17) | médio | — | ordem da lista, página da imagem/A4/Carta, margem, qualidade JPEG; sem OCR |
| 11 | ~~ICO e GIF estático~~ (0.9.18) | baixo | — | saída em «Salvar como»; ICO 16–256 px quadrado, GIF 256 cores e transparência de 1 bit |
| 12 | ~~Vetores: SVG/SVGZ como entrada~~ (0.9.19) | médio-alto | — | resvg-py preferido, QtSvg de reserva; largura escolhida pelo usuário; saída em todos os formatos com a transparência preservada onde o formato permite |
| 12b | ~~HEIC e AVIF~~ (AVIF 0.9.20 com o Pillow; **HEIC 0.9.21** com `pillow-heif`, por decisão do usuário em 27/10/2026) | médio / alto | 3 | entrada e saída; wheel de 5,7 MB (≈ 23 MB descompactados) com libheif/libde265 (LGPL-3.0) e **x265 (GPL-2.0)**; HEVC tem patentes: **revisão jurídica antes de distribuir publicamente** |
| 13 | ~~**OCR (imagem → texto e PDF pesquisável)**~~ (**0.9.22**: grupo «Ler texto», Tesseract externo, `.txt` e PDF pesquisável, por/eng) | médio | 10 | Tesseract (Apache-2.0) como programa empacotado, pacotes de idioma `por`+`eng`; roda no worker, offline, testável no Linux; reaproveita «Várias imagens → um PDF» para a camada de texto |
| 14 | ~~**Adobe Illustrator (.ai) moderno**~~ (**0.9.23**: PDFium via `pypdfium2`, primeira página, 1 pt = 1 px, recusa `.ai` antigo) | médio | 12 | `.ai` com «compatibilidade com PDF» é um PDF: rasterizar com `pypdfium2` (BSD/Apache-2.0), sem Ghostscript; o mesmo rasterizador serve à categoria PDF; `.ai` antigo (PostScript) é recusado com mensagem clara |
| 15 | ~~**EPS**~~ (**descartado pelo usuário em 28/10/2026**; não será feito) | alto | 14 | só via Ghostscript **externo e opcional** instalado pelo usuário (AGPL: nunca embutido nem ligado ao app, apenas processo separado com `-dSAFER`, sem rede, limites do worker); sem Ghostscript, erro claro |
| 16 | ~~**Remoção de fundo**~~ (**0.9.25**) | alto | 13 | modelo local ONNX (onnxruntime MIT + pesos com licença verificada, ex.: U²-Net/BiRefNet; **evitar pesos de uso só não comercial**); modelo pequeno por padrão, grande opcional; nada baixado sem ação do usuário; saída com alfa; medir memória/tempo no worker |
| 17 | ~~**EMF/WMF**~~ (**0.9.24**, adiantado a pedido do usuário em 28/10/2026) | alto | 12 | só Windows (GDI, pelo desenhista do Pillow): fundo branco opaco, sem transparência; **desenho real ainda não executado no Windows**; recusado com mensagem clara fora dele |
| — | Retoques de interface (diálogo de recorte, arrastar para reordenar a colagem) | baixo | — | podem entrar entre as entregas |

## Ordem de inclusão dos itens restantes (definida em 27/10/2026)
Todos serão incluídos, um por entrega ("Próximo passo"), do menor para o maior risco e respeitando dependências: **~~13 OCR~~ (0.9.22) → ~~14 .ai moderno~~ (0.9.23) → ~~15 EPS~~ (descartado) → ~~16 remoção de fundo~~ (0.9.25) → ~~17 EMF/WMF~~ (0.9.24, adiantado a pedido do usuário)**. Justificativa: (a) OCR é o de maior valor e testável por completo no Linux, sem pesos de IA; (b) `.ai` moderno é PDF e prepara o rasterizador da categoria PDF; (c) EPS só depois, pois depende de programa externo AGPL e de endurecimento contra PostScript; (d) remoção de fundo pesa em tamanho, memória e licença dos pesos; (e) EMF/WMF só se valida no Windows, que ainda não reexecutou as versões 0.9.7+. Retoques de interface entram entre as entregas. Após o 17: Portão B, Portão C, portabilidade Linux. Pendência transversal: revisão jurídica (HEVC/x265) antes de qualquer distribuição pública.

## Vetores (SVG e outros): quando fazer
**Decisão: no fim da fila, logo depois do formato de saída (item 3), não agora.** Motivos:
1. **Depende do item 3.** O valor do recurso é converter o vetor para vários formatos e levar a transparência junto (PNG, WebP, TIFF; JPEG/BMP/PDF achatam com fundo escolhido). Sem a escolha de formato de saída nas ferramentas, só haveria «SVG → PNG».
2. **Segurança é o risco principal.** SVG é XML com referências externas, scripts, entidades (XXE, «billion laughs») e dimensões gigantes. Regras: nunca buscar recursos externos nem executar script, limite de tamanho do arquivo, limite de dimensão e de megapixels (os mesmos 40 MP), SVGZ com descompressão limitada, erro claro em português.
3. **Arquitetura:** o núcleo não pode importar Qt. A rasterização entra como **porta** (`Rasterizer`) com adaptadores: o `QtSvg` do PySide6 (sem dependência nova, saída RGBA com alfa; cobre SVG Tiny 1.2, não todo o SVG 1.1 — filtros e alguns recursos ficam de fora) ou, se a fidelidade medida for insuficiente, `resvg`. A escolha sai de uma comparação com um corpus de SVGs (a mesma prova de qualidade do Portão B).
4. **Transparência:** fundo transparente do vetor vira alfa no PNG/WebP/TIFF; para formatos sem alfa, usar a cor de fundo escolhida (padrão branco) e avisar no relatório de perdas.
5. **Tamanho de saída:** o vetor não tem pixels; a entrada precisa de largura/altura (ou escala/DPI) escolhida pelo usuário, com padrão igual ao tamanho declarado no arquivo.
Prova de qualidade específica: corpus de SVGs (formas, gradientes, texto, `viewBox` sem largura/altura, transparência, referências externas, XML malicioso), comparação contra renderização de referência (SSIM), tempo e memória.

### Resultado da comparação de desenhistas (0.9.19)
Corpus de 16 recursos de SVG desenhados pelos dois adaptadores (planilha de contato conferida a olho; a comparação numérica SSIM contra uma referência fica no Portão B):
| Recurso | Qt SVG | resvg |
|---|---|---|
| gradiente linear e radial, padrão (`pattern`), máscara, marcador, CSS em `<style>`, `tspan`, sombra (`feOffset`+`feGaussianBlur`+`feMerge`), opacidade de grupo, `transform`, imagem `data:`, tracejado e junções | correto | correto |
| recorte `clipPath` | **ignorado** (desenha o retângulo inteiro) | correto |
| texto em caminho (`textPath`) | **não desenha** | correto |
| `<svg>` aninhado | **não desenha** | correto |
| `<symbol>` com `viewBox` em `<use width height>` | **não escala** (círculo pequeno) | correto |
Decisão: **resvg-py é o desenhista preferido** (MIT; 1,4 MB por wheel; wheels para Windows x64, Linux x86-64 e aarch64) e o **QtSvg fica de reserva** (sem dependência nova; o relatório de perdas avisa que ele não desenha esses recursos). 40 megapixels em ~7 s e ≤ 520 MiB no worker com o limite de 1,5 GiB.

PDF→imagem pertence à categoria PDF (precisa de rasterizador de PDF; escolher biblioteca com licença compatível com GPL-3.0).

## Portões
- **Portão A (por entrega):** testes novos + `test_architecture` + suíte completa em Linux + item no diagnóstico do Windows.
- **Portão B (fim da fila):** prova de qualidade abaixo, em Linux e em Windows.
- **Portão C:** decisão final de linguagem (ADR-0001) com os números do Portão B.

## Prova de qualidade da categoria (`tools/quality_suite.py`, a criar no Portão B)
1. **Corpus:** fotos com EXIF/GPS, PNG com alfa, 16 bits, CMYK, paleta, perfil ICC, 40 MP, nomes com Unicode, pasta somente leitura, arquivos truncados/corrompidos e "bombas de descompressão".
2. **Matriz ferramenta × corpus:** cada célula termina em *ok*, *erro controlado* (mensagem em português) ou *falha* (exceção/travamento). Meta: zero falhas.
3. **Invariantes de segurança:** hash do original intacto; nenhum arquivo parcial; nenhuma sobrescrita; limpeza do staging; nenhuma conexão de rede (soquete bloqueado no teste); metadados sensíveis ausentes nas cópias limpas e nas ocultações.
4. **Fidelidade:** saídas sem perda comparadas pixel a pixel; com perda por PSNR/SSIM contra a referência; dimensões exatas; diferença de cor ΔE após conversão de perfil; alfa sem halo.
5. **Desempenho:** tempo e pico de memória por megapixel; lote de 100 imagens; cancelamento sem resíduo.
6. **Robustez:** fuzz de opções (valores limite, tipos errados) pela lista branca e pelo motor.
7. **Relatório (JSON + Markdown):** nota por função de 0 a 100 — correção 40, fidelidade 25, segurança 20, desempenho 10, regressão 5. Aprovação: nenhuma função abaixo de 80, nenhuma falha crítica de segurança, e as mesmas medições repetidas no Windows.


## Fechamento da categoria Imagens (0.9.26, 29/10/2026)
Auditoria completa feita a pedido do usuário. **Corrigido:** WebP rápido ignorava a qualidade; arquivos truncados/falsos geravam erro técnico; botão principal escondido pela rolagem; controles da ferramenta abaixo dos comuns; chips cortados; lista da colagem apertada. **Incluído:** suíte de qualidade (`tools/quality_suite.py`, 70/70 no Linux), prévia da remoção de fundo, reordenar colagem arrastando, PDF único com OCR, Job Object (`winjob.py`), kit de instalação (`instalador/`), ZIP de arquivos de teste para a roda.
**Pendências conscientes:** editar/mover formas, várias anotações de texto, curvas, orientação no OCR, transparência EMF/WMF, `.pdf` como entrada (categoria PDF), cosméticos (abas ≤ 900 px, rótulo «TRANSFORMAR ›», «arquivo(s)»), assinatura de código, ícone `.ico`, revisão jurídica (HEVC/x265, DLLs do Tesseract, DUTS-TR). **Evidência:** só Linux; Windows rodou até a 0.9.6; instalador e Job Object nunca executados no Windows.

## 0.9.27 — Pasta numerada para várias imagens (29/10/2026)
Pedido do usuário: converter várias imagens de formatos diversos e receber uma pasta com as imagens numeradas na ordem. Feito (ver RELEASE.md). Verificado só no Linux.

## 0.9.28 — Retoques de interface (29/10/2026)
Editor de recorte (proporções, limpar, posição, botão principal), lista da colagem com estilo do sistema, plural da barra de status e correção do «Limpar seleção». Arrastar para reordenar a colagem já existia (0.9.26). Verificado só no Linux.
