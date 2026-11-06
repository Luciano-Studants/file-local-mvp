# Testes: Git (CI) e laboratórios Linux e Windows

Três camadas, da mais barata para a mais cara. Cada uma pega coisas que as outras não pegam.

## 1. Git — CI automática (`.github/workflows/ci.yml`)
Roda em **todo PR** e em todo push para `main`, em duas máquinas: `ubuntu-latest` (Python 3.13, FFmpeg 6–8 do apt) e `windows-latest` (Python 3.12, FFmpeg e Tesseract via choco).

| Etapa | O que garante |
|---|---|
| Diagnóstico (`tools/doctor.py`) | versões de Python, FFmpeg, Tesseract, dependências |
| Testes automáticos (`unittest discover`) | ~1 350 testes; FFmpeg real nos de Áudio; log completo guardado como artefato |
| Teste de fumaça (`app.py --smoke-test`) | o app sobe, registra ferramentas e fecha com código 0 |
| Qualidade do PDF (`--only pdf --fast`) | nota 0–100 por função do PDF |
| **Qualidade do Áudio (`--only audio`)** | 104 verificações em 11 funções, com oráculo independente (o FFmpeg decodifica a saída e o numpy mede frequência, nível, amostras); inclui arquivo de 4 h pelo worker |
| Dependências (`dependencias`) | `pip check`, `pip-audit` (informativo), licenças (bloqueia AGPL) |

Relatórios: aba **Actions → run → Artifacts** (`quality-report-ubuntu-latest`, `quality-report-windows-latest`, `test-log-*`). Aprovado = nenhuma função abaixo de 80 e nenhuma falha bloqueante.
Ler o resultado sem abrir o navegador: `gh run list --branch <branch>` e `gh run view <id> --log-failed`.
**Fora do alcance da CI:** instalador (Inno Setup), app empacotado (PyInstaller; workflow manual «Build Windows»), áudio audível, players reais, antivírus, Explorer.

## 2. Laboratório Linux (máquina limpa ou contêiner)
```bash
git clone https://github.com/Luciano-Studants/file-local-mvp.git && cd file-local-mvp
git switch item-audio-10            # ou a branch do portão
sudo apt-get install -y ffmpeg tesseract-ocr libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 fonts-dejavu-core
./dev.sh setup
python tools/doctor.py
./dev.sh test                       # suíte completa (≈ 3 min)
./dev.sh smoke
python tools/quality_suite.py --only audio --out quality-audio     # completa, com 10 min e 4 h de áudio
python tools/quality_suite.py --only pdf --fast --out quality-pdf
```
Variar o FFmpeg: repetir com a versão do apt e com um build estático (BtbN/johnvansickle) — o FFmpeg 8 já mostrou comportamento diferente do 6 (threads/memória), por isso a suíte roda o visualizador sob `RLIMIT_AS` de 1 GiB.

## 3. Laboratório Windows (PC limpo, de preferência 10 e 11)
```powershell
winget install -e --id Git.Git; winget install -e --id Python.Python.3.12; winget install -e --id Gyan.FFmpeg
git clone https://github.com/Luciano-Studants/file-local-mvp.git; cd file-local-mvp; git switch item-audio-10
Set-ExecutionPolicy -Scope Process Bypass
.\dev.ps1 setup; python tools\doctor.py; .\dev.ps1 test; .\dev.ps1 smoke
python tools\quality_suite.py --only audio --out quality-audio
.\dev.ps1 run
```
**Checklist manual (o que a CI não vê) — marcar e anotar a versão do Windows e do FFmpeg (`ffmpeg -version`):**
- [ ] `doctor.py` mostra FFmpeg e ffprobe encontrados (PATH ou pasta do app); «Informações» abre um MP3, um FLAC e um MP4.
- [ ] Nomes com acento, espaço, `#`, parênteses e caminho longo (> 260 caracteres) em Converter, Etiquetas e Bleep; pasta em OneDrive e em disco de rede.
- [ ] **Ouvir** as saídas: Converter (MP3/M4A/Opus), Normalizar (volume parecido entre faixas), Bleep (tom e mudo caem onde marcado), Cortar (sem estalo no corte).
- [ ] **Visualizador:** o MP4 (MPEG-4 + AAC) abre em *Filmes e TV*, no VLC e no Windows Media Player; anotar onde não abre (esperado: sites que exigem H.264).
- [ ] Onda: arrastar alças (Cortar) e arrastar para marcar trechos (Bleep) com mouse e com caneta/touch; tela com escala 125 % e 150 %.
- [ ] Roda (Shift+F9 / menu radial): 4 fatias no Áudio, sub-rodas com 3 fatias; rótulos legíveis em 100 %, 125 % e 150 %.
- [ ] Arquivo aberto em outro programa (ex.: tocando no VLC): o app não corrompe o original e avisa se não conseguir ler.
- [ ] Windows Defender/antivírus não bloqueia o `ffmpeg.exe` nem apaga saídas; saída nunca sobrescreve o original.
- [ ] Cancelar um job longo (4 h): o `ffmpeg.exe` some do Gerenciador de Tarefas e não sobra arquivo parcial.
- [ ] `.\dev.ps1 build` (ou workflow «Build Windows»): o pacote portátil e o instalador abrem e convertem um áudio sem Python instalado.
Registrar resultado no Project («Registro de continuidade») e abrir issue para cada falha, com a versão do FFmpeg.

## Quando rodar o quê
- Cada PR: só a camada 1 (automática).
- Fim de categoria (Portão B): camadas 1 + 2 + 3, nas duas plataformas; os resultados de cada sistema valem separadamente.
- Antes de uma versão (tag `v*`): camada 3 completa + «Build Windows».
