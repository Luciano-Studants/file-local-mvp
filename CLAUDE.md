# Arquivo Local — guia para o Claude (e para quem desenvolve)

Conversor/ferramentas de arquivos **offline** para Windows 10/11 (também roda em Linux). Python 3.12/3.13 + PySide6 + Pillow + pypdf + pypdfium2 + cryptography. Licença GPL-3.0-only. **Interface, mensagens e documentação em português do Brasil.**

## Regras que não mudam
- Originais **nunca** são alterados nem sobrescritos; saída sempre com nome novo (`-2`, `-3`…); nada de arquivo parcial em caso de erro.
- 100% offline: nenhuma chamada de rede em código de conversão.
- Licenças: **não** usar PyMuPDF nem Ghostscript (AGPL). Dependência nova → `requirements.txt` com versão fixa, texto da licença em `licenses/`, linha em `THIRD_PARTY_NOTICES.md` e `licenses/SOURCES.md`.
- Senhas nunca vão para relatório, histórico, mensagem de erro nem linha de comando.
- Uma funcionalidade por entrega (branch/PR por item). Falou «próximo passo» → próximo item do plano em `docs/PLANO-CATEGORIA-*.md`.

## Arquitetura (resumo; detalhes em `docs/ARCHITECTURE.md`)
- Núcleo **sem Qt**: `engine.py`, `tool_registry.py`, `runner.py`, `pdfinfo.py`, `pdfcompress.py`, `pdfstamp.py`, `pdfredact.py`, `pdfform.py`, `ocr.py`, `vector.py`, … (lista `CORE_MODULES` em `tests/test_architecture.py`; módulo novo do núcleo entra lá).
- `runner.py`: cada job roda num worker (subprocesso), JSON por stdin, saída publicada atomicamente.
- Interface: `workspace_panel.py` (painel e ferramentas), `pdf_stage.py`, `page_organizer.py`, `visual_tools.py`, `radial_menu.py`, `tray_app.py` (controlador `JobController`: valida tipos e chaves de opções).
- Ferramenta nova de PDF toca: `engine.py` (constante, `OPERATIONS`, função, ramo em `_convert`, `loss_report`), `tool_registry.py` (opções str/int/lista/caminho), `tray_app.py` (rótulo e validação de listas), `workspace_panel.py` (TOOLS, roda, painel, estado, `run_selected`), testes, `package.py` (`--hidden-import`), `verify_package.py`, docs e `windows_acceptance_check.py`.

## Comandos
- Windows: `.\dev.ps1 setup` · `.\dev.ps1 run` · `.\dev.ps1 test` · `.\dev.ps1 quality` · `.\dev.ps1 build`
- Linux: `./dev.sh setup|run|test|quality|smoke`
- Testes à mão: `QT_QPA_PLATFORM=offscreen python -I -W ignore -m unittest discover -s tests -q` (≈2–3 min). **Chamadas de ferramenta têm limite de 120 s: rode em segundo plano, gravando num log, e espere.** Um arquivo só: `-p test_pdf_form.py`.
- Smoke: `python app.py --smoke-test` (sem `-I`; sai com 0).
- Qualidade: `python tools/quality_suite.py --only pdf --fast` (nota 0–100 por função; aprovado = nenhuma abaixo de 80 e nenhuma falha bloqueante).

## Convenções de teste
- Testes **não** iniciam QThread real: `mock.patch.object(JobController, '_start_next')`; `PdfStage` usa `loader=lambda job: runner.run_pdf_op(job)` e `addCleanup(stage.shutdown)`.
- Fixtures de PDF à mão: `tests/formfixture.py` (formulário), `tests/test_illustrator.py::make_pdf`, `tools/quality_suite.py::text_pdf_bytes`.
- Quirks do pypdf: `PdfWriter(clone_from=…)` mantém objetos órfãos → clonar duas vezes (via BytesIO) para limpar; `writer._info=None` tira o /Info; AES exige `cryptography`.

## Estado
- Categorias ativas: **Imagens** e **PDF** (13/13 itens, Portão B aprovado no Linux). Próximas: Vídeo, Áudio, Documentos… (ver `docs/`).
- **Windows ainda não verificado desde a 0.9.6** (suíte, instalador, PyInstaller). O CI roda Windows com `continue-on-error` até ficar verde; o checklist manual está em `windows_acceptance_check.py`.
- Pendências legais: HEVC/x265, DLLs do Tesseract, pesos U²-Net/DUTS-TR.

## Fluxo de trabalho
1. `git switch -c item-NN-nome` → implementar → `./dev.sh test` ou `.\dev.ps1 test` → PR → CI verde → merge.
2. Atualizar: README (uma linha), RELEASE (cabeçalho novo), `docs/ARCHITECTURE.md` (item numerado), plano da categoria, checklist do Windows. Registro de continuidade no Project do Claude.
