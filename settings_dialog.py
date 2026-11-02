"""Janela «Atalhos e integração»: atalho global, Shift + botão do meio e menu de contexto do Explorer."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import shell_integration
import theme
from global_hotkey import HOTKEY_PRESETS
from widgets import ChipGroup


class SettingsDialog(QDialog):
    """Mostra o estado real de cada integração e só altera algo quando o usuário aperta o botão correspondente."""

    def __init__(self, tray_app, parent=None, registry=None):
        super().__init__(parent)
        self.tray_app = tray_app
        self.registry = registry                      # injetável nos testes; None = winreg real (só Windows)
        self.setWindowTitle('Atalhos e integração')
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.panel_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel('Atalhos e integração'); title.setObjectName('PageTitle'); layout.addWidget(title)
        intro = QLabel('Segurar Shift abre a roda de conversões. O atalho abaixo abre a roda de ferramentas do arquivo selecionado. '
                       'Há também formas que não dependem do teclado.')
        intro.setObjectName('Muted'); intro.setWordWrap(True); layout.addWidget(intro)

        layout.addWidget(self._heading('Atalho global das ferramentas'))
        self.hotkey_chips = ChipGroup(HOTKEY_PRESETS, per_row=3)
        current = tray_app.settings.hotkey
        if current in HOTKEY_PRESETS:
            self.hotkey_chips.setCurrentIndex(HOTKEY_PRESETS.index(current))
        else:
            self.hotkey_chips.addItem(current); self.hotkey_chips.setCurrentIndex(self.hotkey_chips.count() - 1)
        layout.addWidget(self.hotkey_chips)
        self.hotkey_status = QLabel(); self.hotkey_status.setWordWrap(True); self.hotkey_status.setObjectName('Caption')
        layout.addWidget(self.hotkey_status)

        self.middle_check = QCheckBox('Shift + botão do meio do mouse abre as ferramentas')
        self.middle_check.setChecked(tray_app.settings.middle_click)
        layout.addWidget(self.middle_check)

        layout.addWidget(self._heading('Menu de contexto do Explorer'))
        self.context_status = QLabel(); self.context_status.setWordWrap(True); self.context_status.setObjectName('Muted')
        layout.addWidget(self.context_status)
        context_row = QHBoxLayout()
        self.context_button = QPushButton()
        self.context_button.clicked.connect(self.toggle_context_menu)
        context_row.addWidget(self.context_button); context_row.addStretch(1)
        layout.addLayout(context_row)

        layout.addWidget(self._heading('Arrastar e soltar'))
        drag = QLabel('Solte arquivos sobre uma fatia da roda (ou sobre a janela do painel) para aplicar a ação a eles.')
        drag.setObjectName('Muted'); drag.setWordWrap(True); layout.addWidget(drag)

        self.message = QLabel(''); self.message.setWordWrap(True); layout.addWidget(self.message)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        close = QPushButton('Fechar'); close.clicked.connect(self.reject)
        self.apply_button = QPushButton('Salvar preferências'); self.apply_button.setObjectName('Primary')
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(close); buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.refresh()
        self.setMinimumHeight(layout.totalHeightForWidth(560) + 8)
        self.resize(560, self.minimumHeight())

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text); label.setStyleSheet('font-weight:600;font-size:14px;padding-top:6px'); return label

    def refresh(self) -> None:
        registered = self.tray_app.hotkey_registered
        name = self.tray_app.global_hotkey.hotkey
        self.hotkey_status.setText(f'Atalho atual: {name} — ' + ('registrado.' if registered else
                                   'não registrado (outro aplicativo pode estar usando; escolha outro).' if os.name == 'nt' else
                                   'o registro só acontece no Windows.'))
        if os.name != 'nt' and self.registry is None:
            self.context_status.setText('Disponível somente no Windows.')
            self.context_button.setText('Indisponível neste sistema'); self.context_button.setEnabled(False)
            return
        installed = shell_integration.is_installed(self.registry)
        self.context_status.setText(('O item «Arquivo Local» está no menu de contexto de imagens e PDFs (no Windows 11, em «Mostrar mais opções»). '
                                     'Até 15 arquivos por vez.') if installed else
                                    'Adiciona «Arquivo Local» ao clicar com o botão direito em imagens e PDFs. Grava só chaves próprias do usuário atual, sem administrador.')
        self.context_button.setText('Remover do menu de contexto' if installed else 'Adicionar ao menu de contexto')
        self.context_button.setEnabled(True)

    def toggle_context_menu(self) -> None:
        installed = shell_integration.is_installed(self.registry)
        ok = shell_integration.uninstall(self.registry) if installed else shell_integration.install(registry=self.registry)
        self.message.setText(('Menu de contexto removido.' if installed else 'Menu de contexto adicionado.') if ok else 'Não foi possível alterar o menu de contexto.')
        self.refresh()

    def apply(self) -> None:
        ok, message = self.tray_app.apply_settings(self.hotkey_chips.currentText(), self.middle_check.isChecked())
        self.message.setText(message)
        self.message.setStyleSheet('' if ok else f'color:{theme.ACCENT_HOVER}')
        self.refresh()
