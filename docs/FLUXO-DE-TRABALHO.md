# Fluxo de trabalho com Git, CI e testes na sua máquina

## Uma vez só
1. `git clone https://github.com/Luciano-Studants/file-local-mvp.git` (ou use a pasta que já existe).
2. Windows: `python -m venv` exige Python 3.12 de 64 bits (python.org). Depois `.\dev.ps1 setup`.

## Testar na sua máquina
- Abrir o app: `.\dev.ps1 run`
- Testes: `.\dev.ps1 test` (2–3 min) · Qualidade do PDF: `.\dev.ps1 quality` (relatório em `quality-report\quality-report.md`)
- Instalador completo (precisa do Inno Setup 6 para o `.exe`): `.\dev.ps1 build` → arquivos em `dist\`

## Testar sem montar nada (CI)
- Todo push e todo PR roda **Actions › CI** no Linux e no Windows. Abra a aba *Actions* do repositório, clique na execução e veja os testes; o relatório de qualidade fica em *Artifacts*.
- **Actions › Build Windows › Run workflow** gera o ZIP portátil e o instalador; baixe em *Artifacts* → `arquivo-local-windows`.

## Cada entrega
`git switch -c item-NN-nome` → mudanças → commit → push → abrir PR → CI verde → merge na `main`.

## Windows verde
O job do Windows usa `continue-on-error` (aparece amarelo/vermelho sem bloquear). Quando ficar verde por alguns dias, remova essa linha de `.github/workflows/ci.yml` para ele passar a bloquear.
