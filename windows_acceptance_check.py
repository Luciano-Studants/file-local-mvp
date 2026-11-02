"""Interactive Windows acceptance check for Shift+F9 and Shell selection.

Run on the target Windows PC. It does not modify files; selected path names are
shown only in this local diagnostic window and are not persisted or transmitted.
"""
from __future__ import annotations
import os
import subprocess
import struct
import sys
from pathlib import Path

if os.name != 'nt':
    raise SystemExit('Este diagnóstico precisa ser executado no Windows.')

try:
    from PySide6.QtCore import Qt
except ModuleNotFoundError:
    raise SystemExit('PySide6 não encontrado neste Python. Execute com o Python do ambiente do projeto: .\\.venv\\Scripts\\python.exe windows_acceptance_check.py')
from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget

from file_actions import validate_selection
from global_hotkey import ShiftF9Hotkey
from windows_bridge import selected_paths_from_explorer


class AcceptanceWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.setWindowTitle('Arquivo Local — diagnóstico Windows')
        self.resize(700, 720)
        self.app = app
        self.checks = []
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel('Verificação de integração • Shift+F9'))
        self.system_label = QLabel(self.system_summary())
        self.system_label.setWordWrap(True)
        layout.addWidget(self.system_label)
        self.status = QLabel('Clique em “Iniciar teste”. Depois selecione um arquivo local no Explorer ou na Área de Trabalho e pressione Shift+F9.')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.start_button = QPushButton('Iniciar teste da hotkey')
        self.start_button.clicked.connect(self.start_hotkey_test)
        layout.addWidget(self.start_button)
        self.launch_button = QPushButton('Abrir o app real para testar a Fase 1 e o Image Core')
        self.launch_button.setEnabled(False)
        self.launch_button.clicked.connect(self.launch_application)
        layout.addWidget(self.launch_button)
        group = QGroupBox('Checklist manual — marque somente depois de testar no Windows')
        checklist_layout = QVBoxLayout(group)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setMinimumHeight(260)
        self.checks = []
        items = [
            'Ao abrir o app pela bandeja, a home aparece; navego pelas dez categorias, nenhuma aba fica cortada e as verticais planejadas não executam operações. Em Imagens vejo duas rodas; hover deixa a fatia laranja e mostra o nome; clicar abre a ferramenta.',
            'Shift no Desktop e Explorer abre apenas um radial; Esc e clique fora fecham.',
            'Shift+F9 não duplica o radial; ferramentas correspondem à extensão e hover mostra o nome da ação no centro.',
            'Recortar: marco uma região, testo as proporções (1:1, 16:9), redimensiono pelas alças, movo pelo interior, aplico e confiro o PNG sem alterar o original; Ampliar editor também funciona.',
            'Copy Path e Copy Files funcionam com arquivos de teste e os originais continuam intactos.',
            'Prateleira adiciona/remove itens e arrasta para o Explorer como cópia; originais intactos.',
            'Converter: a prévia gira conforme a rotação e o tamanho aproximado confere com o arquivo gerado.',
            'Fila executa várias imagens/PDFs em sequência; limpar pendentes não cancela a tarefa ativa.',
            'Cancelar tarefa atual não deixa saída parcial visível; tarefa já concluída permanece intacta.',
            'Com cópias, valide canvas (prévia e cor), anotação (clicar na imagem posiciona; tamanho e cor) e compressão JPEG (predefinições, estimativa e prévia); confira dimensões, métricas, se o tamanho estimado confere com o arquivo gerado e o original intacto.',
            'Testei caminho Unicode, usuário padrão e, se disponível, segundo monitor/DPI diferente.',
            '[0.9] Fundo: escolho degradê, cor sólida e cor própria; margem, cantos, sombra e proporção; o PNG gerado confere com a prévia e o original fica intacto.',
            '[0.9] Ocultar: marco duas áreas, uso tarja e pixelização; a prévia confere com o PNG; ao ampliar o PNG o conteúdo coberto não aparece; o original fica intacto.',
            '[0.9] Metadados: com foto de celular vejo câmera, data e GPS; a cópia "-sem-metadados" não mostra GPS/câmera em Propriedades > Detalhes do Explorer.',
            '[0.9] Ajustar: brilho, contraste, saturação e espelhar mudam a prévia; o PNG gerado confere; "Redefinir ajustes" volta ao neutro.',
            '[0.9] Colagem: selecionei 2 a 12 imagens no Explorer + atalho; as miniaturas aparecem; Subir/Descer/Tirar mudam a ordem; o PNG respeita a ordem; "Tirar" não apaga o arquivo.',
            '[0.9] Atalhos: a janela "Atalhos" abre; trocar o atalho global funciona (ou avisa que está ocupado e mantém o anterior); Shift + botão do meio abre as ferramentas do arquivo selecionado.',
            '[0.9] Menu de contexto do Explorer: instalar (sem pedir administrador), clicar com o botão direito num arquivo abre a roda; remover apaga a entrada.',
            '[0.9] Arrastar arquivos do Explorer sobre uma fatia da roda e sobre a janela do painel aplica a ação ou adiciona o arquivo.',
            '[0.9.8] Tamanho: nos três modos (porcentagem, caber em, medida exata) o texto "Resultado" confere com as dimensões do PNG gerado em Propriedades; ampliar mostra aviso; o original fica intacto.',
            '[0.9.9] Girar: 90° à direita/esquerda, 180° e espelhar (horizontal, vertical, ambos): a prévia confere com o PNG gerado e as dimensões trocam em 90°; o original fica intacto.',
            '[0.9.29] Prévia de PDF: abra um PDF de várias páginas em PDF › Extrair texto (ou Unir/Separar): aparecem o resumo (páginas, papel, tamanho, «com texto» ou «sem camada de texto»), a página 1 grande e as miniaturas; clicar numa miniatura mostra aquela página; com 2 ou 3 PDFs a lista mostra páginas/tamanho e o total, e clicar troca a prévia; um PDF com senha mostra «protegido por senha» e não trava; um arquivo .pdf falso/truncado mostra mensagem em português; um PDF de 100+ páginas mostra as 24 primeiras miniaturas; no Gerenciador de Tarefas o «worker» aparece e some sozinho; os testes tests/test_pdfinfo.py e tests/test_pdf_stage.py passam na suíte (sem pulados).',
            '[0.9.30] PDF → imagens: em PDF › Páginas em imagens, abra um PDF de várias páginas; com 150 dpi o painel mostra o tamanho em pixels; digite «2-3» em Páginas e salve em PNG: aparece a pasta «<nome> - páginas» ao lado do PDF com pagina-002.png e pagina-003.png nítidas sobre fundo branco; repita e surge «… (2)» sem sobrescrever; escolha JPEG e confira que abre; digite «99» e o botão fica bloqueado com mensagem em português; 600 dpi num PDF de página enorme é recusado com o dpi máximo sugerido; ICO é recusado; o PDF original não muda; o teste tests/test_pdf_images.py passa sem pulados.',
            '[0.9.31] Unir PDFs: abra 3 PDFs em PDF › Unir PDFs; arraste um item da lista para outra posição (a numeração acompanha) e use Subir/Descer/Tirar; clicar num item mostra a prévia daquele arquivo; escreva «1-2» em «Páginas do arquivo» e o total «N páginas no PDF unido» diminui; «99» bloqueia o botão com mensagem em português; união que passaria de 200 páginas bloqueia; salve e abra o unido.pdf no leitor de PDF: ordem e páginas certas e painel de marcadores com um item por arquivo (com os marcadores originais dentro); rodar de novo cria unido-2.pdf sem sobrescrever; os originais não mudam; o teste tests/test_merge_pdfs.py passa sem pulados.',
            '[0.9.32] Dividir/extrair: abra um PDF de 9 páginas em PDF › Dividir; «Uma por página» cria a pasta «<nome> - partes» com pagina-001…009.pdf; «A cada N» com 4 cria 3 partes (4+4+1); «Por intervalos» com «1-3; 4-6; 7-» cria 3 PDFs de 3 páginas; «Extrair páginas» com «2,5» cria <nome>-extraido.pdf com 2 páginas; «99» bloqueia o botão com mensagem em português; abra as partes no leitor de PDF e confira páginas e marcadores; rodar de novo cria «… (2)» sem sobrescrever; o original não muda; o teste tests/test_split_pdf.py passa sem pulados.',
            '[0.9.33] Organizar páginas: abra um PDF de 8+ páginas em PDF › Organizar páginas; todas as miniaturas aparecem (conte 8+ e, com 30+ páginas, veja o carregamento em lotes); arraste a página 3 para o começo; selecione a 2 e a 5 (Ctrl) e use ↻ Girar; Duplicar a 4; Excluir a 6; o resumo diz quantas páginas terá o PDF novo; «Restaurar tudo» volta ao início; salve e abra <nome>-organizado.pdf no leitor de PDF: ordem, giros, cópias e exclusões conferem; o original não muda; rodar de novo cria -organizado-2.pdf; o teste tests/test_organize_pdf.py passa sem pulados.',
            '[0.9.34] Texto e imagens: num PDF com texto, PDF › Extrair texto salva <nome>-texto.txt; «Com marcas de página» insere «--- Página N ---»; «Um por página» cria «<nome> - texto» com pagina-001.txt…; «Manter o layout» conserva colunas por espaços; num PDF digitalizado o painel avisa e o botão resulta em mensagem «não há texto» sem salvar nada; em PDF › Imagens do PDF, num PDF com fotos, a pasta «<nome> - imagens» traz JPEG idênticos aos embutidos (compare o tamanho) e PNG para as demais, sem repetir a mesma imagem e sem ícones pequenos (ponha 0 para trazer tudo); os testes tests/test_pdf_extract.py passam sem pulados.',
            '[0.9.35] OCR de PDF: com Tesseract e idiomas empacotados, em PDF › «OCR → PDF pesquisável» num PDF digitalizado, o botão gera <nome>-pesquisavel.pdf com o mesmo número de páginas; no leitor de PDF a busca (Ctrl+F) acha palavras do documento e dá para selecionar o texto; «OCR → texto» salva <nome>-ocr.txt (e, em «Um por página», a pasta «<nome> - texto»); páginas que já têm texto são puladas; com mais de 20 páginas o painel pede um intervalo menor; sem os dados de idioma o painel explica e bloqueia o botão; os testes tests/test_pdf_ocr.py passam sem pulados.',
            '[0.9.36] Metadados: em PDF › «Metadados», num PDF com autor, anexo e JavaScript (por exemplo, exportado do Word com anexos), o painel lista autor, programa, datas, anexos e JavaScript; «Gerar cópia limpa» salva <nome>-limpo.pdf que abre normalmente no leitor, com as mesmas páginas e sem Propriedades › autor/programa; num PDF já limpo a mensagem diz que não há o que remover; os testes tests/test_pdf_clean.py passam sem pulados.',
            '[0.9.37] Comprimir PDF: com um PDF de fotos grandes (por exemplo, digitalizado ou exportado com imagens em alta resolução), PDF › «Comprimir» no nível Médio gera <nome>-comprimido.pdf bem menor que o original, que abre normalmente no leitor com as mesmas páginas; o status mostra «antes → depois»; o nível Forte fica menor e mais borrado que o Médio; num PDF só de texto a mensagem diz que não reduziu e nada é salvo; os testes tests/test_pdf_compress.py passam sem pulados.',
            '[0.9.38] Carimbo: em PDF › «Numerar / carimbar», «Numeração» gera <nome>-numerado.pdf com «Página 1 de N» centralizado no rodapé de todas as páginas (texto selecionável no leitor); «2-» pula a capa; «Marca d\'água» (CONFIDENCIAL, diagonal) aparece clara no centro; numa página girada o carimbo fica na posição escolhida como a página é vista; os testes tests/test_pdf_stamp.py passam sem pulados.',
            '[0.9.39] Senha de PDF: em PDF › «Proteger com senha» num PDF comum, defina uma senha e gere <nome>-protegido.pdf: ao abri-lo no leitor (Edge, Chrome ou Adobe) a senha é pedida e o conteúdo aparece igual; «Remover senha» com a senha errada diz que não abriu e não salva nada; com a senha certa gera <nome>-desprotegido.pdf que abre sem senha; num PDF com impressão bloqueada, a senha de abertura sozinha não remove a proteção (pede a senha de permissões); os campos de senha ficam vazios após iniciar a tarefa; os testes tests/test_pdf_password.py passam sem pulados e o pacote do PyInstaller inclui cryptography.',
            '[0.9.40] Tarjar PDF: em PDF › «Tarjar conteúdo» num PDF com texto, marque uma área sobre uma linha, informe também um termo e o padrão CPF e gere <nome>-tarjado.pdf: no leitor, a área, o termo e os CPFs aparecem cobertos por tarja preta; selecionar/copiar (Ctrl+A, Ctrl+C) nas páginas tarjadas não devolve texto algum e a busca pelo termo não acha nada; as páginas sem tarja continuam com texto selecionável; marcadores, anexos e propriedades do documento sumiram; num PDF girado a tarja cobre o texto certo; com termo inexistente e sem área nada é salvo e a mensagem explica; os testes tests/test_pdf_redact.py passam sem pulados.',
            '[0.9.41] Preencher e assinar: em PDF › «Preencher e assinar» abra um formulário real (por exemplo de órgão público ou banco): os campos aparecem na lista; altere texto, caixa e lista, gere <nome>-preenchido.pdf e confira no leitor (Edge, Chrome, Adobe) que os valores aparecem e ainda dá para editar; repita com «Achatar»: os valores aparecem e os campos somem; coloque uma assinatura PNG com fundo transparente numa área (também numa página girada) e confira posição e proporção; a tela avisa que não é assinatura digital certificada; PDF sem campos só aceita a assinatura; os testes tests/test_pdf_form.py passam sem pulados.',
            '[0.9.28] Retoques: em Recortar, «Ampliar editor…» mostra as proporções, «Limpar seleção» e o botão laranja «Aplicar recorte»; escolher 1:1 deixa a área quadrada; «Limpar seleção» no painel zera Área/medidas; na Colagem a linha selecionada fica laranja, arrastar um item muda a ordem e a numeração na prévia; a barra de status diz «1 arquivo» com um arquivo.',
            '[0.9.27] Pasta numerada: selecione 5 imagens de formatos diferentes (PNG, JPG, WebP, BMP, TIFF), segure Shift (ou Shift+F9) e escolha PNG: aparece uma pasta «Convertidas AAAA-MM-DD HH-MM-SS» ao lado do primeiro arquivo com 001.png a 005.png na ordem da seleção, sem arquivos temporários; os originais não mudam; no painel, desmarcar «Salvar tudo numa pasta nova» devolve o comportamento antigo (nomes ao lado dos originais); com arquivos que não são imagem, a pasta vazia some.',
            '[0.9.26] Fechamento de Imagens: (1) abra qualquer ferramenta em janela pequena: o botão principal fica sempre visível e o formulário rola; (2) em Colagem arraste uma imagem na lista para outra posição e confira a ordem na saída; (3) em Sem fundo use «Ver prévia do resultado» (xadrez) antes de salvar; (4) em Várias imagens → PDF único escolha «Texto pesquisável» (OCR, página do tamanho da imagem, até 20 imagens) e busque uma palavra no PDF; (5) um arquivo de imagem truncado ou falso mostra mensagem em português com o nome do arquivo, sem travar; (6) WebP rápido com qualidade 100 sai sem perdas; (7) Job Object: converta uma foto grande e confira no Gerenciador de Tarefas que o processo «worker» termina sozinho e some ao fechar o painel no meio da conversão; (8) use os arquivos do ZIP «arquivos-de-teste» conforme o LEIA-ME dele.',
            '[0.9.25] Remover fundo: após «pip install -r requirements.txt» (instala numpy e onnxruntime), abra uma foto de um objeto ou pessoa sobre fundo liso em Ajustes › Sem fundo; o botão fica habilitado (modelo leve incluído); salve: o PNG tem o objeto com o fundo transparente (confira sobre um fundo colorido), a borda não fica serrilhada com «Borda suave» 2 px e o original não muda; com o arquivo u2net.onnx na pasta «models» o modelo «Preciso» funciona; um arquivo .onnx trocado ou adulterado é recusado; uma foto grande (30 a 40 MP) termina sem travar o computador.',
            '[0.9.24] EMF/WMF (primeira prova do GDI): abra um .emf e um .wmf (ex.: figura copiada do Word/Visio/Inkscape «Salvar como EMF»): a prévia aparece em fundo branco; «Largura do vetor» redesenha maior sem borrar; salve em PNG e JPEG. Rode também «python -I -m unittest discover -s tests -p test_metafile.py»: os testes WindowsRenderTests (EMF criado pelo gdi32) devem passar e não ficar pulados.',
            '[0.9.23] Illustrator: após «pip install -r requirements.txt» (instala o pypdfium2), abra um .ai moderno (salvo com «Criar arquivo compatível com PDF»): a prévia mostra a arte com fundo transparente; «Largura do vetor» muda o tamanho; salve em PNG/WebP e em JPEG; um .ai antigo ou salvo sem parte de PDF mostra mensagem clara e não cria arquivo.',
            '[0.9.22] OCR: instale o Tesseract (ou coloque a pasta «tesseract» ao lado do app); com uma imagem com texto em português abra Ler texto › Texto e › PDF texto; o .txt confere com a imagem e, no PDF pesquisável, Ctrl+F no leitor de PDF acha uma palavra; sem o Tesseract o botão fica desabilitado com aviso; uma imagem em branco não cria arquivo.',
            '[0.9.21] HEIC: após «pip install -r requirements.txt» (instala o pillow-heif), abra uma foto .heic de iPhone: a prévia sai na orientação certa; converta para JPEG/PNG; salve uma imagem em HEIC com qualidade 90 e 30 (a de 30 é menor) e uma transparente (a transparência continua); o .heic gerado abre no Windows (pode pedir as extensões HEIF e HEVC da Microsoft Store); sem o pacote (pip uninstall pillow-heif) o app avisa claramente; o original não muda.',
            '[0.9.20] AVIF: numa ferramenta (ex.: Tamanho) salve em AVIF com qualidade 90 e 30 (o menor arquivo é o de 30); o resultado abre no Edge/Chrome atuais (o Visualizador de Fotos pode exigir a extensão AV1 da Microsoft Store); com uma imagem transparente a transparência continua; abra um .avif como entrada e converta para PNG; o original não muda.',
            '[0.9.19] SVG: após «pip install -r requirements.txt» (instala o resvg-py), abra um SVG com texto, gradiente, recorte (clipPath) e fundo transparente; a prévia confere com o navegador, a «Largura SVG» redesenha nítido (ex.: 2000 px) e o texto usa as fontes do Windows; salve em PNG (transparente), WebP, GIF, ICO e JPEG (fundo branco/«Fundo opaco»); abra também um .svgz; o relatório diz «resvg»; um SVG com <image href="arquivo-vizinho.png"> não mostra o arquivo vizinho; sem o resvg-py (pip uninstall resvg-py) o app ainda abre SVG pelo Qt e o relatório avisa que é a alternativa; o original não muda.',
            '[0.9.18] GIF e ICO: numa ferramenta (ex.: Tamanho) salve em ICO e em GIF; o .ico aparece com o ícone da imagem no Explorer e em Propriedades › Detalhes mostra os tamanhos; com uma imagem não quadrada o ícone vem centralizado e transparente; o GIF abre no navegador/visualizador com a transparência (bordas serrilhadas são esperadas) e não anima; o original não muda e nada é sobrescrito.',
            '[0.9.17] PDF único: com 3 a 4 imagens de formatos diferentes (retrato, paisagem, PNG transparente) crie o PDF em «Do tamanho da imagem», A4 e Carta; as páginas seguem a ordem da lista (Subir/Descer/Tirar), a orientação acompanha cada imagem, a margem aparece e a prévia confere; o PDF abre no leitor; a transparência vira branco; o original não muda; o nome segue o campo «Nome» e não sobrescreve.',
            '[0.9.16] Renomeação em lote: com 3 imagens e o padrão «viagem-{n}-{nome}» (primeiro nº 10, 3 dígitos) os arquivos saem como viagem-010-…, viagem-011-…, viagem-012-… na ordem da seleção; o exemplo do painel confere; padrões com \\ : * ? " < > | são recusados; repetir a conversão gera -2, -3 sem sobrescrever; o original não é renomeado.',
            '[0.9.15] Formas: com uma imagem, desenhe retângulo, elipse, linha e seta (as quatro direções), em cores e espessuras diferentes; a prévia confere com o arquivo gerado; Desfazer última remove a mais recente; a forma não confirmada entra ao salvar; com várias imagens a ferramenta pede uma só; o original não muda; os rótulos da roda rápida (9 fatias) aparecem inteiros.',
            '[0.9.14] Níveis: o histograma aparece com uma imagem; Preto, Branco e Tons médios mudam a prévia e as marcas; Automático mostra os pontos calculados e em lote cada imagem usa os seus; o botão só habilita após um ajuste; PNG transparente mantém a transparência; o original não muda.',
            '[0.9.13] Nitidez e desfoque: em uma foto, Nitidez realça bordas e Desfoque suaviza; a prévia confere com o arquivo gerado, também em foto grande; PNG transparente não ganha halo escuro no desfoque; em lote, o mesmo efeito vale para todas; o original não muda.',
            '[0.9.12] Marca d\'água: texto (em Arial) e logotipo PNG transparente nas nove posições e repetida; a prévia confere com o arquivo gerado; a opacidade muda; em lote a mesma marca vai em todos; o original e o logotipo ficam intactos.',
            '[0.9.11] Salvar como: numa ferramenta (ex.: Tamanho) salvo em PNG, JPEG, WebP, TIFF e BMP; a extensão e o tipo conferem em Propriedades; com uma imagem transparente, JPEG/BMP usam o «Fundo opaco» e PNG/WebP/TIFF mantêm a transparência; WebP 100 % abre sem diferença visível; Metadados em JPEG não mostra GPS/câmera nos Detalhes do Explorer.',
            '[0.9.10] Sub-rodas: na roda de ferramentas, Transformar, Ajustes, Desenhar e Proteger abrem uma sub-roda; Voltar, Esc e Backspace retornam; clicar numa ferramenta dentro do grupo abre o painel dela; soltar um arquivo sobre uma ferramenta do grupo funciona.',
            '[0.9] As rodas ficam legíveis (rótulos sem corte) em 100%, 125% e 150% de escala do Windows; "O que mudou" aparece após cada resultado.',
        ]
        for text in items:
            row = QWidget(group)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            check = QCheckBox(row)
            label = QLabel(text, row)
            label.setWordWrap(True)
            row_layout.addWidget(check)
            row_layout.addWidget(label, 1)
            check.stateChanged.connect(self.update_checklist_status)
            self.checks.append(check)
            checklist_layout.addWidget(row)
        scroll.setWidget(group)
        layout.addWidget(scroll, 1)
        self.checklist_status = QLabel(f'Checklist: 0 de {len(self.checks)} itens confirmados. As caixas são autorrelato manual, não resultados automáticos.')
        self.checklist_status.setWordWrap(True)
        layout.addWidget(self.checklist_status)
        self.close_button = QPushButton('Fechar')
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.hotkey = ShiftF9Hotkey(self.app, self.on_hotkey)

    @staticmethod
    def system_summary() -> str:
        version = sys.getwindowsversion()
        return (f'Windows {version.major}.{version.minor}, build {version.build}; '
                f'Python {sys.version_info.major}.{sys.version_info.minor} '
                f'{struct.calcsize("P") * 8}-bit.')

    def start_hotkey_test(self):
        try:
            import pythoncom  # noqa: F401
            import win32com.client  # noqa: F401
            import win32gui  # noqa: F401
            import PySide6  # noqa: F401
            import PIL  # noqa: F401
            import pypdf  # noqa: F401
        except Exception as error:
            self.status.setText(f'FALHA: dependência ausente ou quebrada: {type(error).__name__}: {error}')
            return
        if not self.hotkey.start():
            self.status.setText(f'FALHA: RegisterHotKey não foi registrado. Código Win32: {self.hotkey.last_error}. Pode haver conflito de atalho.')
            return
        self.start_button.setEnabled(False)
        self.status.setText('Hotkey registrada. Agora selecione um arquivo local no Explorer ou na Área de Trabalho e pressione Shift+F9. Nenhum arquivo será alterado.')

    def on_hotkey(self):
        try:
            paths = validate_selection(selected_paths_from_explorer())
        except Exception as error:
            self.status.setText(f'Hotkey recebida, mas seleção indisponível/recusada: {type(error).__name__}: {error}. Tente novamente com um arquivo local comum selecionado.')
            return
        names = '\n'.join(f'• {os.path.basename(path)}' for path in paths[:8])
        more = f'\n… e mais {len(paths) - 8}' if len(paths) > 8 else ''
        self.status.setText(f'PASSOU: Shift+F9 recebido; {len(paths)} item(ns) local(is) validado(s):\n{names}{more}\n\nNenhum conteúdo foi aberto ou modificado. A hotkey de teste foi liberada; clique no botão abaixo para iniciar o app real e percorrer o checklist manual.')
        self.hotkey.stop()
        self.launch_button.setEnabled(True)

    def launch_application(self):
        desktop = Path(__file__).resolve().parent
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        executable = pythonw if pythonw.is_file() else Path(sys.executable)
        try:
            kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
                      'cwd': str(desktop), 'close_fds': True}
            if executable.name.lower() == 'python.exe':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen([str(executable), str(desktop / 'app.py')], **kwargs)
            self.launch_button.setEnabled(False)
            self.status.setText('App iniciado. Faça os testes do checklist usando cópias de arquivos; volte a esta janela para marcar os resultados.')
        except Exception as error:
            self.status.setText(f'Falha ao iniciar o app: {type(error).__name__}: {error}')

    def update_checklist_status(self):
        passed = sum(check.isChecked() for check in self.checks)
        self.checklist_status.setText(
            f'Checklist: {passed} de {len(self.checks)} itens confirmados. '
            'Autorrelato manual; os testes Win32 e a interação visual não são automatizados por este formulário.'
        )

    def closeEvent(self, event):
        self.hotkey.stop()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = AcceptanceWindow(app)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
