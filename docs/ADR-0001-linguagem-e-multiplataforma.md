# ADR-0001 — Linguagem e multiplataforma (Windows 10/11 + Linux)

**Estado:** aceita em 25/10/2026, a ser reavaliada no **Portão C** (fim da categoria Imagens).

## Contexto
O app será publicado como software de desktop para Windows 10, Windows 11 e Linux. A base atual é Python 3.12 + PySide6 + Pillow + pypdf (≈5,3 mil linhas, 237 testes). Pergunta: trocar de linguagem (por exemplo Go) agora, no fim, ou não?

## Decisão
**Manter Python + PySide6 agora. Não migrar antes do Portão C.** Preparar a portabilidade por arquitetura (núcleo puro e adaptadores de plataforma), não por reescrita.

## Por quê
- **Qt já é multiplataforma.** O custo real do Linux não está na linguagem; está nos adaptadores: atalho global, leitura da seleção do gerenciador de arquivos, menu de contexto e o radial sob o cursor.
- **Go não resolve esses pontos e piora outros.** Não há GUI nativa madura em Go (as opções usam webview ou desenho próprio, sem o nível de widgets do Qt), e faltam equivalentes prontos de Pillow para ICC/EXIF/vários formatos sem cgo. Seria reescrever motor, interface e 237 testes sem ganho funcional.
- **Reescrever agora congelaria as funcionalidades** que o plano de Imagens ainda vai entregar e adiaria a medição de qualidade.
- **Risco de adiar:** baixo, porque o núcleo é separado da interface (testado em `test_architecture`). Se a decisão mudar, o motor pode virar uma biblioteca/CLI (Go ou Rust) chamada pelo mesmo contrato de job, sem refazer a interface.

## Riscos reais do Linux (a tratar no plano de portabilidade)
| Tema | Windows hoje | Linux |
|---|---|---|
| Atalho global | `RegisterHotKey` | X11: `XGrabKey`; **Wayland**: sem API livre, só portal `GlobalShortcuts` (nem todo ambiente tem) |
| Seleção do gerenciador de arquivos | COM do Explorer | não há padrão; Nautilus/Dolphin/Thunar diferem → usar menu de contexto/"enviar para" com os caminhos como argumento |
| Menu de contexto | chaves em HKCU | `.desktop`/service menus (Dolphin), scripts (Nautilus) |
| Radial sob o cursor | posição global do cursor | **Wayland não expõe a posição global**; plano: abrir centralizado na janela ativa ou no último ponto conhecido |
| Empacotamento | PyInstaller + instalador (Inno Setup) + assinatura de código | AppImage e Flatpak (o sandbox limita atalhos globais), `.deb` opcional |

## Critérios para reavaliar no Portão C
Tempo de abertura, tamanho do instalador, memória em lote de 100 imagens, facilidade de empacotar nos três sistemas e custo dos adaptadores Linux. Só se algum critério falhar de forma clara a migração do motor será proposta, com este ADR atualizado.
