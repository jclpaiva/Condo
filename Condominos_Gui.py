"""
Condominos_Gui.py - Widget de gestão de condóminos (Interface Gráfica)
Funcionalidades:
- Adicionar condóminos manualmente (tecla Insert)
- Editar condóminos existentes (duplo clique)
- Apagar condóminos selecionados (tecla Delete com confirmação)
- Mostrar foto ao hover sobre o nome
- Tooltip no EMAIL baseado no valor de CHECK
- Tooltip no ANDAR para ver pagamentos
- Validações de campos
- Guardar alterações
- ComboBox na coluna FRAÇÃO (chave canónica); ANDAR e PERMILAGEM são derivados
- Clique esquerdo na coluna ANDAR: consultar pagamentos de quotas / imprimir
- Checkbox para campo CHECK (verde quando ativa, vermelha quando inativa)
- Diálogo de pagamentos: administrador só para visualização (impressão de recibo)
- Clique direito no nome na grelha: definir administrador em funções
"""

import sys
from pathlib import Path
import re
import shutil
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableView, QHeaderView, QMessageBox, QStatusBar,
    QLabel, QApplication, QItemDelegate, QComboBox, QStyledItemDelegate, QMenu, QDialog, QTableWidget,
    QTableWidgetItem, QFrame, QGridLayout, QGraphicsOpacityEffect, QFileDialog,
    QLineEdit, QFormLayout, QDialogButtonBox, QStyle,
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize, QEvent, QPoint, QPropertyAnimation, QSequentialAnimationGroup, QEasingCurve, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QColor, QBrush, QIcon, QPixmap, QCursor, QPen, QPainter

# Constantes / utilitários
from Commons import (
    BASE_DIR, ICONS_DIR, PASTA_CORRENTE, PASTA_HISTORICO,
    FOTOS_DIR, clean_numeric, format_currency,
)
try:
    from Commons import pasta_e_corrente
except ImportError:
    # Fallback se Commons ainda não tiver a função (versão antiga)
    def pasta_e_corrente(pasta_dados=None) -> bool:
        if pasta_dados is None or str(pasta_dados).strip() in ("", "corrente"):
            return True
        s = str(pasta_dados).replace("\\", "/").strip().lower()
        return "historico" not in s.split("/") and (
            s == "corrente" or s.endswith("/corrente")
        )

# Importar módulo de impressão de recibos
from Imprimir_Recibo import gerar_recibo_pdf, obter_iniciais

# Importar geração de recibos em lote
from Imprimir_Recibos import gerar_recibos_para_todos_condominos

# Importar lógica de negócio
from Condominos import (
    carregar_condominos_db,
    guardar_condominos_db,
    validar_condominos,
    atualizar_quotas_regras,
    obter_pagamentos_condomino,
    criar_novo_condomino,
    obter_lista_administradores,
    definir_administrador,
    obter_fracoes,
    eh_admin_atual,
    validar_e_normalizar_campo,
    sincronizar_por_fracao,
    construir_mapas_fracoes,
    reconciliar_com_fracoes,
    calcular_meses_quotas,
    calcular_estado_atraso,
    condominos_ativos_na_fracao,
    MORADA_FIXA,
    CPOSTAL_FIXO,
    CIDADE_FIXA,
)

# Importar módulo WhatsApp
from WhatsApp import (
    enviar_whatsapp_a_todos_atrasados,
    enviar_whatsapp_a_condomino,
    abrir_whatsapp,
    montar_mensagem_atraso,
    formatar_numero_wa,
)


# ====================================================================
# DELEGATE PARA ALINHAMENTO À DIREITA
# ====================================================================
class RightAlignDelegate(QStyledItemDelegate):
    """Delegate que força alinhamento à direita para valores monetários"""
    
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


# ====================================================================
# DELEGATE PARA CHECKBOX
# ====================================================================
class CheckBoxDelegate(QStyledItemDelegate):
    """Delegate que mostra caixinha verde/vermelha para campo lógico"""
    
    def paint(self, painter, option, index):
        """Desenha a caixinha com cor baseada no valor"""
        from PyQt6.QtWidgets import QStyle
        
        # Obter valor do modelo
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        is_checked = value in (True, 'T', '.T.', 't')
        
        # Definir cor de fundo da caixinha
        if is_checked:
            box_color = QColor("#28a745")  # Verde
        else:
            box_color = QColor("#fb0000")  # Vermelho
        
        # CORRIGIDO: Respeitar cor de seleção da linha
        if option.state & QStyle.StateFlag.State_Selected:
            # Linha selecionada - usar cor de highlight (azul)
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            # Manter o destaque amarelo das linhas com alterações por gravar.
            fundo = index.data(Qt.ItemDataRole.BackgroundRole)
            painter.fillRect(option.rect, fundo if fundo else option.palette.base())
        
        # Desenhar caixinha quadrada no centro
        box_size = 16
        rect = option.rect
        box_rect = rect.adjusted(
            (rect.width() - box_size) // 2,
            (rect.height() - box_size) // 2,
            -(rect.width() - box_size) // 2,
            -(rect.height() - box_size) // 2
        )
        
        # Preencher caixinha com cor (verde ou vermelho)
        painter.fillRect(box_rect, box_color)
        
        # Desenhar contorno preto
        painter.setPen(QPen(QColor("#000000"), 2))
        painter.drawRect(box_rect)
    
    def editorEvent(self, event, model, option, index):
        """Permite clicar para alternar o estado da checkbox"""
        if event.type() == QEvent.Type.MouseButtonRelease:
            # Obter valor atual
            current_value = model.data(index, Qt.ItemDataRole.EditRole)
            is_checked = current_value in (True, 'T', '.T.', 't')
            
            # Alternar valor
            new_value = '.F.' if is_checked else '.T.'
            model.setData(index, new_value, Qt.ItemDataRole.EditRole)
            return True
        
        return super().editorEvent(event, model, option, index)
    
    def sizeHint(self, option, index):
        """Define tamanho da célula"""
        return QSize(30, 30)


# ====================================================================
# DELEGATE PARA COLUNA NOME COM ÍCONE DE ADMINISTRADOR
# ====================================================================
class NomeComAdminDelegate(QStyledItemDelegate):
    """
    Delegate que mostra nome com ícone de admin ao lado se ADMIN == 1.

    NOTA: O ícone é apenas VISUAL. Para alterar o administrador em funções,
    clique com o botão direito sobre o nome na grelha.
    """
            
    def __init__(self, parent=None):
        super().__init__(parent)
        # Carregar o ícone uma vez no construtor
        icon_path = ICONS_DIR / "admin-icon.png"
        self.admin_pixmap = None
        
        try:
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                if not pixmap.isNull():
                    self.admin_pixmap = pixmap.scaled(
                        30, 30, 
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    print(f"✓ Ícone de administrador carregado: {icon_path}")
                else:
                    print(f"⚠ AVISO: Pixmap nulo para {icon_path}")
            else:
                print(f"⚠ AVISO: Ícone admin não encontrado em {icon_path}")
                print(f"   Por favor, copie admin-icon.png para a pasta icons/")
        except Exception as e:
            print(f"✗ ERRO ao carregar ícone admin: {e}")
            self.admin_pixmap = None
    
    def paint(self, painter, option, index):
        """Desenha o nome e o ícone de admin ao lado se aplicável"""
        try:
            # Obter valor do campo ADMIN do modelo
            model = index.model()
            row = index.row()
            font = painter.font()
            font.setBold(bool(option.state & QStyle.StateFlag.State_Selected))
            painter.setFont(font)
            
            # Verificar se é administrador atual (admin == 1; -1 = cessante)
            is_admin = False
            try:
                if hasattr(model, "_data") and row < len(model._data):
                    admin_value = model._data[row].get("ADMIN", 0)
                    is_admin = eh_admin_atual(admin_value)
            except (IndexError, AttributeError, KeyError, TypeError):
                is_admin = False

            # Verificar se o condómino está com quotas em atraso
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            em_atraso = False
            try:
                if hasattr(model, "esta_em_atraso"):
                    em_atraso = model.esta_em_atraso(row)
            except (IndexError, AttributeError, KeyError, TypeError):
                em_atraso = False

            # Preencher fundo da célula
            if is_selected:
                painter.fillRect(option.rect, option.palette.highlight())
            else:
                fundo = index.data(Qt.ItemDataRole.BackgroundRole)
                painter.fillRect(option.rect, fundo if fundo else option.palette.base())
            
            # Obter o texto do nome
            nome = str(model.data(index, Qt.ItemDataRole.DisplayRole))
            
            # Configurar a cor do texto:
            # - selecionado: cor de destaque normal (sem piscar, para não conflituar
            #   com o realce azul da seleção)
            # - em atraso: vermelho
            # - normal: azul
            if is_selected:
                painter.setPen(option.palette.highlightedText().color())
            elif em_atraso:
                painter.setPen(QColor("#d32f2f"))
            else:
                painter.setPen(QColor("#1976d2"))
            
            # Calcular espaço disponível para o texto
            text_rect = option.rect.adjusted(5, 0, -40 if (is_admin and self.admin_pixmap) else -5, 0)
            
            # Desenhar o texto do nome — exceto no "tick" de piscar em que o nome
            # fica temporariamente oculto (efeito de intermitência), quando em atraso
            # e a linha não está selecionada.
            blink_visible = getattr(model, "_blink_visible", True)
            if not (em_atraso and not is_selected and not blink_visible):
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nome)
            
            # Se for admin e tiver ícone, desenhar no lado direito
            if is_admin and self.admin_pixmap and not self.admin_pixmap.isNull():
                icon_x = option.rect.right() - 35
                icon_y = option.rect.y() + (option.rect.height() - 26) // 2
                painter.drawPixmap(icon_x, icon_y, self.admin_pixmap)
        
        except Exception as e:
            # Em caso de erro, fazer o paint básico
            print(f"ERRO no NomeComAdminDelegate.paint: {e}")
            super().paint(painter, option, index)
    
    def createEditor(self, parent, option, index):
        """Criar editor apenas para a área do texto"""
        return super().createEditor(parent, option, index)
    
    def sizeHint(self, option, index):
        """Define tamanho da célula"""
        return QSize(option.rect.width(), 40)


# ====================================================================
# DELEGATE PARA COMBOBOX DA FRAÇÃO (chave canónica)
# ====================================================================
class FracaoComboDelegate(QStyledItemDelegate):
    """ComboBox para o campo FRACAO.

    Os valores vêm exclusivamente da tabela `fracoes` (sem fallbacks
    inventados). Abre com **um clique** e expande a lista de imediato.
    Se o valor actual do modelo não estiver na lista (dados legados), é
    mostrado temporariamente para não forçar outra fração por engano.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []  # preenchido por set_items a partir de `fracoes`

    def set_items(self, items):
        """Actualiza a lista de frações (letras) vindas da tabela `fracoes`."""
        self.items = [str(x).strip().upper() for x in (items or []) if str(x).strip()]

    def createEditor(self, parent, option, index):
        from PyQt6.QtCore import QTimer

        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for item in self.items:
            combo.addItem(item)
        # Commit imediato ao escolher um item da lista
        combo.activated.connect(lambda _i, c=combo: self._commit_and_close(c))
        # Expandir a lista assim que o editor estiver no ecrã
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def _commit_and_close(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)

    def setEditorData(self, editor, index):
        value = str(index.model().data(index, Qt.ItemDataRole.EditRole) or '').strip().upper()
        # Valor legado fora da lista: mostrar sem substituir por outro
        if value and editor.findText(value) < 0:
            editor.insertItem(0, value)
        if value:
            editor.setCurrentText(value)
        else:
            editor.setCurrentIndex(-1)  # obrigar escolha explícita

    def setModelData(self, editor, model, index):
        value = editor.currentText().strip().upper()
        if value:
            model.setData(index, value, Qt.ItemDataRole.EditRole)

    def editorEvent(self, event, model, option, index):
        """Abre o editor no primeiro clique (sem precisar de seleccionar antes)."""
        if (event.type() == QEvent.Type.MouseButtonPress and
                event.button() == Qt.MouseButton.LeftButton):
            view = self.parent()
            if isinstance(view, QTableView):
                view.setCurrentIndex(index)
                view.edit(index)
                return True
        return super().editorEvent(event, model, option, index)


# ====================================================================
# DELEGATE PARA COLORIR EMAIL BASEADO NO CHECK
# ====================================================================
class EmailColorDelegate(QStyledItemDelegate):
    """Delegate que muda a cor do texto do EMAIL baseado no valor do campo CHECK"""
    
    def initStyleOption(self, option, index):
        """Modifica as opções de estilo antes de pintar"""
        super().initStyleOption(option, index)
        
        # Obter o modelo e a linha
        model = index.model()
        row = index.row()
        
        # Encontrar a coluna CHECK
        check_value = None
        for col, field_name in enumerate(model._fields):
            if field_name == 'CHECK':
                check_index = model.index(row, col)
                check_value = model.data(check_index, Qt.ItemDataRole.EditRole)
                break
        
        # Determinar se está checked
        is_checked = check_value in (True, 'T', '.T.', 't')
        
        # Definir cor do texto
        if is_checked:
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#28a745"))  # Verde
        else:
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#fb0000"))  # Vermelho


# ====================================================================
# DIALOG DE PAGAMENTOS DE QUOTAS
# ====================================================================
class PagamentosQuotasDialog(QDialog):
    """Dialog para exibir pagamentos de quotas do condómino"""
    
    def __init__(self, nome, andar, fracao, quota_normal, quota_extra, 
                 dados_pagamentos, pasta_dados=None, telemovel="",
                 outros_na_fracao=None, parent=None):
        super().__init__(parent)
        
        self.nome = nome
        self.andar = andar
        self.fracao = fracao
        self.quota_normal = quota_normal
        self.quota_extra = quota_extra
        self.dados = dados_pagamentos
        self.pasta_dados = pasta_dados
        self.telemovel = str(telemovel or "").strip()
        # Outros condóminos ATIVOS que partilham o mesmo ANDAR (normalmente
        # vazio; só preenchido numa situação de transição, ex. venda a meio
        # do ano — ver condominos_ativos_na_fracao). Os valores de pagamento
        # são calculados por ANDAR, por isso o atraso pode estar agregado.
        self.outros_na_fracao = outros_na_fracao or []
        
        self.setup_ui()
    
    def setup_ui(self):
        self.setWindowTitle(f"Pagamentos de Quotas - {self.nome}")
        self.setMinimumSize(900, 700)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # HEADER: Informações do condómino
        header = self.criar_header()
        layout.addWidget(header)
        
        # TABELA: Pagamentos mensais
        self.table = self.criar_tabela()
        layout.addWidget(self.table)
        
        # ESPAÇAMENTO antes do footer para evitar sobreposição
        layout.addSpacing(12)
        
        # FOOTER: Totais e Saldo
        footer = self.criar_footer()
        layout.addWidget(footer)
        
        # ====================================================================
        # LAYOUT HORIZONTAL: Administrador (só leitura) + Botões
        # ====================================================================
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        
        # ESQUERDA: Administrador em funções (não editável neste ecrã)
        lbl_admin = QLabel("Administrador:")
        lbl_admin.setStyleSheet("font-size: 12px; font-weight: bold;")
        bottom_layout.addWidget(lbl_admin)

        self.administrador_nome = self._obter_nome_administrador_atual()
        texto_admin = (
            f"👑 {self.administrador_nome}"
            if self.administrador_nome else
            "— (não definido)"
        )
        self.lbl_administrador = QLabel(texto_admin)
        self.lbl_administrador.setStyleSheet("""
            QLabel {
                padding: 6px 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 11px;
                background-color: #f5f5f5;
                min-width: 220px;
            }
        """)
        self.lbl_administrador.setToolTip(
            "Administrador em funções (só leitura).\n"
            "Para alterar: na grelha de Condóminos, clique com o botão direito sobre o nome."
        )
        bottom_layout.addWidget(self.lbl_administrador)
        
        # ESPAÇO NO MEIO
        bottom_layout.addStretch()
        
        # DIREITA: Botões encostados
        self.btn_imprimir = QPushButton("🖨️ Imprimir Recibo Ano")
        self.btn_imprimir.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
                min-width: 200px;
            }
            QPushButton:hover {
                background-color: #1b5e20;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        self.btn_imprimir.clicked.connect(self.imprimir_recibo)
        bottom_layout.addWidget(self.btn_imprimir)
        
        btn_fechar = QPushButton("✓ Fechar")
        btn_fechar.setStyleSheet("""
            QPushButton {
                background-color: #1976d2;
                color: white;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
                min-width: 200px;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        btn_fechar.clicked.connect(self.close)
        bottom_layout.addWidget(btn_fechar)
        
        layout.addLayout(bottom_layout)
        
        # Validar botão imprimir
        self.atualizar_estado_botao_imprimir()
    
    def criar_header(self):
        """Cria frame com informações do condómino"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #395C8D;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(frame)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 8, 10, 8)
        
        # Nome
        lbl_nome = QLabel(f"<b>{self.nome}</b>")
        lbl_nome.setStyleSheet("color: white; font-size: 14px;")
        layout.addWidget(lbl_nome)
        
        # Fração e Andar
        info_layout = QHBoxLayout()
        info_layout.setSpacing(5)
        
        lbl_fracao = QLabel(f"Fração: {self.fracao}")
        lbl_fracao.setStyleSheet("color: white; font-size: 11px;")
        info_layout.addWidget(lbl_fracao)
        
        info_layout.addSpacing(20)
        
        lbl_andar = QLabel(f"Andar: {self.andar}")
        lbl_andar.setStyleSheet("color: white; font-size: 11px;")
        info_layout.addWidget(lbl_andar)
        
        info_layout.addStretch()
        
        # Quotas esperadas
        lbl_quota_n = QLabel(f"Quota Normal: {format_currency(self.quota_normal)}")
        lbl_quota_n.setStyleSheet("color: #FFD700; font-size: 11px; font-weight: bold;")
        info_layout.addWidget(lbl_quota_n)
        
        info_layout.addSpacing(15)
        
        lbl_quota_e = QLabel(f"Quota Extra: {format_currency(self.quota_extra)}")
        lbl_quota_e.setStyleSheet("color: #FFD700; font-size: 11px; font-weight: bold;")
        info_layout.addWidget(lbl_quota_e)
        
        layout.addLayout(info_layout)
        
        return frame
    
    def criar_tabela(self):
        """Cria tabela com pagamentos mensais"""
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(['Mês', 'Quota Normal', 'Quota Extra', 'Total Mês'])
        table.setRowCount(12)
        
        # Aplicar stylesheet FORTE
        table.setStyleSheet("""
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #2F5597;
                color: white;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #1F4587;
            }
        """)
        
        # Criar delegate para alinhamento à direita
        right_delegate = RightAlignDelegate(table)
        
        # Configurar scroll vertical sempre visível
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Configurar altura das linhas e scroll
        table.verticalHeader().setDefaultSectionSize(32)
        table.verticalHeader().setVisible(False)
        
        # Configurar scroll por item completo
        table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerItem)
        
        # Preencher dados
        for i, dados_mes in enumerate(self.dados['dados_mensais']):
            # Mês - CENTRALIZADO
            item_mes = QTableWidgetItem(dados_mes['mes'])
            item_mes.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 0, item_mes)
            
            # Quota Normal - DIREITA COM COR VERDE
            valor_normal = format_currency(dados_mes['normal'])
            item_normal = QTableWidgetItem(valor_normal)
            item_normal.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_normal.setBackground(QBrush(QColor("#d4edda")))
            item_normal.setToolTip("Quota Normal mensal")
            item_normal.setFlags(item_normal.flags())
            table.setItem(i, 1, item_normal)
            
            # Quota Extra - DIREITA COM COR AMARELA
            valor_extra = format_currency(dados_mes['extra'])
            item_extra = QTableWidgetItem(valor_extra)
            item_extra.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_extra.setBackground(QBrush(QColor("#fff3cd")))
            item_extra.setToolTip("Quota Extra mensal")
            item_extra.setFlags(item_extra.flags())
            table.setItem(i, 2, item_extra)
            
            # Total - DIREITA COM COR AZUL
            valor_total = format_currency(dados_mes['total'])
            item_total = QTableWidgetItem(valor_total)
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_total.setBackground(QBrush(QColor("#cfe2ff")))
            item_total.setToolTip("Total do mês")
            item_total.setFlags(item_total.flags())
            table.setItem(i, 3, item_total)
        
        # Aplicar delegate às colunas de valores - FORÇA O ALINHAMENTO
        table.setItemDelegateForColumn(1, right_delegate)
        table.setItemDelegateForColumn(2, right_delegate)
        table.setItemDelegateForColumn(3, right_delegate)
        
        # Ajustar colunas
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 70)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        # REMOVER alternância de cores
        table.setAlternatingRowColors(False)
        
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        
        # Habilitar navegação com teclado
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Altura calculada para mostrar EXATAMENTE as setas + conteúdo
        table.setMinimumHeight(314)
        table.setMaximumHeight(340)
        
        return table
    
    def criar_footer(self):
        """Cria frame com totais e saldo"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        layout = QGridLayout(frame)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 8, 10, 8)
        
        # Totais
        lbl_total_normal_desc = QLabel("<b>Total Quotas Normais:</b>")
        lbl_total_normal_desc.setStyleSheet("font-size: 11px;")
        layout.addWidget(lbl_total_normal_desc, 0, 0)
        
        lbl_total_normal = QLabel(format_currency(self.dados['total_normal']))
        lbl_total_normal.setStyleSheet("font-size: 11px; color: #28a745; font-weight: bold;")
        lbl_total_normal.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_total_normal, 0, 1)
        
        lbl_total_extra_desc = QLabel("<b>Total Quotas Extras:</b>")
        lbl_total_extra_desc.setStyleSheet("font-size: 11px;")
        layout.addWidget(lbl_total_extra_desc, 0, 2)
        
        lbl_total_extra = QLabel(format_currency(self.dados['total_extra']))
        lbl_total_extra.setStyleSheet("font-size: 11px; color: #ffc107; font-weight: bold;")
        lbl_total_extra.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_total_extra, 0, 3)
        
        # Linha separadora (mais fina)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #dee2e6;")
        line.setMaximumHeight(1)
        layout.addWidget(line, 1, 0, 1, 4)
        
        # Total Pago
        lbl_total_pago_desc = QLabel("<b>Total Pago no Ano:</b>")
        lbl_total_pago_desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(lbl_total_pago_desc, 2, 0)
        
        lbl_total = QLabel(format_currency(self.dados['total_geral']))
        lbl_total.setStyleSheet("font-size: 12px; font-weight: bold; color: #1976d2;")
        lbl_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_total, 2, 1)
        
        # Calcular esperado anual e saldo de controlo (visão do ano completo,
        # inclui meses futuros ainda não vencidos — útil para passagem de
        # saldos no final do ano, mas NÃO indica atraso real)
        esperado_anual = (self.quota_normal * 12) + (self.quota_extra * 12)
        saldo = self.dados['total_geral'] - esperado_anual

        lbl_esperado_desc = QLabel("<b>Esperado Anual:</b>")
        lbl_esperado_desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(lbl_esperado_desc, 2, 2)
        
        lbl_esperado = QLabel(format_currency(esperado_anual))
        lbl_esperado.setStyleSheet("font-size: 12px; font-weight: bold; color: #6c757d;")
        lbl_esperado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_esperado, 2, 3)
        
        # Saldo (controlo anual — mantém-se como está, inclui meses futuros)
        lbl_saldo_desc = QLabel("<b>Saldo (ano completo):</b>")
        lbl_saldo_desc.setStyleSheet("font-size: 13px;")
        layout.addWidget(lbl_saldo_desc, 3, 0)

        lbl_saldo = QLabel(format_currency(saldo))
        if saldo < -0.01:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #6c757d;")
        elif saldo > 0.01:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #28a745;")
        else:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #28a745;")
        lbl_saldo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_saldo, 3, 1)

        # --- Estado à data de hoje (atraso REAL) + ícone WhatsApp ---
        # Em vez de usar o saldo anual (que inclui meses futuros ainda não
        # vencidos), comparamos o pago com o esperado até ao mês actual.
        # NOTA: assume-se que o ano de quotas corre Jan-Dez, alinhado com o
        # mês corrente do calendário. Ajustar aqui se o condomínio usar um
        # ano de quotas com início diferente.
        estado = calcular_estado_atraso(
            self.dados['total_geral'], self.quota_normal, self.quota_extra,
            divida_anterior=self.dados.get('divida_anterior_liquidada', 0.0),
        )
        em_atraso = estado["em_atraso"]

        # Linha horizontal: status + ícone WA (só se atraso)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.setContentsMargins(0, 0, 0, 0)

        lbl_status = QLabel(f"<b>{estado['status_msg']}</b>")
        lbl_status.setStyleSheet(f"font-size: 12px; color: {estado['status_color']};")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(lbl_status)

        # Ícone WhatsApp — só no exercício corrente, com atraso e telefone
        telefone_cond = self.telemovel
        wa_permitido = pasta_e_corrente(self.pasta_dados)

        if em_atraso and formatar_numero_wa(telefone_cond) and wa_permitido:
            self.btn_wa = QPushButton()
            wa_icon_path = ICONS_DIR / "whatsapp-icon.png"
            if wa_icon_path.exists():
                self.btn_wa.setIcon(QIcon(str(wa_icon_path)))
            self.btn_wa.setIconSize(QSize(48, 48))
            self.btn_wa.setFixedSize(48, 48)
            self.btn_wa.setFlat(True)
            self.btn_wa.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tooltip_wa = (
                f"Enviar mensagem por WhatsApp a {self.nome}\n"
                f"({estado['meses_atraso']} quota(s) em atraso)"
            )
            if self.outros_na_fracao:
                tooltip_wa += (
                    f"\n⚠️ Fração partilhada com: {', '.join(self.outros_na_fracao)}"
                    f" — valores agregados, confirme antes de enviar"
                )
            self.btn_wa.setToolTip(tooltip_wa)
            self.btn_wa.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    padding: 0;
                    margin: 0;
                }
                QPushButton:hover {
                    background: transparent;
                }
                QPushButton:pressed {
                    background: transparent;
                }
            """)
            self.btn_wa.clicked.connect(
                lambda: self._enviar_whatsapp_condomino(telefone_cond, estado)
            )
            status_row.addWidget(self.btn_wa)

        status_row.addStretch()
        # Coloca o row horizontal nas células (3,2) a (3,3) do grid
        layout.addLayout(status_row, 3, 2, 1, 2)

        # Aviso: ANDAR partilhado com outro(s) condómino(s) ativo(s) —
        # os valores pagos/atraso são calculados por ANDAR, por isso ficam
        # agregados e não podem ser atribuídos com confiança a um só.
        if self.outros_na_fracao:
            lbl_aviso = QLabel(
                f"⚠️ Fração partilhada com: {', '.join(self.outros_na_fracao)} "
                f"— valores agregados, confirme manualmente"
            )
            lbl_aviso.setStyleSheet(
                "font-size: 10px; color: #b36b00; font-style: italic;"
            )
            lbl_aviso.setWordWrap(True)
            lbl_aviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl_aviso, 4, 0, 1, 4)

        # Se estiver REALMENTE em atraso (até ao mês actual), piscar
        if em_atraso:
            from PyQt6.QtCore import QPropertyAnimation, QSequentialAnimationGroup, QEasingCurve
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            
            # Criar efeito de opacidade
            self.opacity_effect = QGraphicsOpacityEffect()
            lbl_status.setGraphicsEffect(self.opacity_effect)
            
            # Criar animação de fade out
            self.fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
            self.fade_out.setDuration(800)  # 800ms para desaparecer
            self.fade_out.setStartValue(1.0)
            self.fade_out.setEndValue(0.3)
            self.fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
            
            # Criar animação de fade in
            self.fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
            self.fade_in.setDuration(800)  # 800ms para aparecer
            self.fade_in.setStartValue(0.3)
            self.fade_in.setEndValue(1.0)
            self.fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
            
            # Criar grupo sequencial
            self.blink_animation = QSequentialAnimationGroup()
            self.blink_animation.addAnimation(self.fade_out)
            self.blink_animation.addAnimation(self.fade_in)
            self.blink_animation.setLoopCount(-1)  # Loop infinito
            self.blink_animation.start()
        
        return frame

    def _enviar_whatsapp_condomino(self, telefone: str, estado: dict):
        """Abre o WhatsApp para este condómino com mensagem de atraso."""
        if not pasta_e_corrente(self.pasta_dados):
            QMessageBox.information(
                self,
                "Exercício histórico",
                "O envio de mensagens WhatsApp só está disponível no exercício corrente.",
            )
            return
        msg = montar_mensagem_atraso(
            nome=self.nome,
            meses_atraso=estado["meses_atraso"],
            deficit=estado["deficit"],
            fracao=self.fracao,
            andar=self.andar,
        )
        if not abrir_whatsapp(telefone, msg):
            QMessageBox.warning(
                self, "Aviso",
                "Não foi possível abrir o WhatsApp.\n\nVerifique o número de telefone."
            )

    def _obter_nome_administrador_atual(self) -> str:
        """Devolve o nome do administrador em funções (admin == 1), ou ''."""
        if not self.pasta_dados:
            return ""
        try:
            for nome, is_admin in obter_lista_administradores(self.pasta_dados):
                if is_admin:
                    return nome
        except Exception as e:
            print(f"Erro ao obter administrador: {e}")
        return ""

    def atualizar_estado_botao_imprimir(self):
        """Ativa/desativa botão de impressão baseado no valor total pago"""
        total_pago = self.dados.get('total_geral', 0.0)
        
        if total_pago > 0:
            self.btn_imprimir.setEnabled(True)
            self.btn_imprimir.setToolTip("Imprimir recibo anual de quotas pagas")
        else:
            self.btn_imprimir.setEnabled(False)
            self.btn_imprimir.setToolTip("Sem pagamentos para imprimir recibo")
    
    def imprimir_recibo(self):
        """Gera PDF do recibo anual"""
        
        # Validar valor total
        total_pago = self.dados.get('total_geral', 0.0)
        
        if total_pago <= 0:
            QMessageBox.warning(
                self,
                "Aviso",
                "Não é possível imprimir recibo.\n\nO valor total pago é zero."
            )
            return
        
        # Administrador em funções (definido na grelha de Condóminos)
        administrador = (self.administrador_nome or "").strip()
        
        if not administrador:
            QMessageBox.warning(
                self,
                "Aviso",
                "Não há administrador em funções definido.\n\n"
                "Na grelha de Condóminos, clique com o botão direito sobre o nome "
                "do condómino para o definir como administrador."
            )
            return
        
        # Verificar assinatura (em ICONS_DIR)
        iniciais = obter_iniciais(administrador)
        docs_dir = BASE_DIR / "docs"
        docs_dir.mkdir(exist_ok=True)
        
        assinatura_path = ICONS_DIR / f"assinatura_{iniciais}.png"
        
        if not assinatura_path.exists():
            resposta = QMessageBox.question(
                self,
                "Assinatura Não Encontrada",
                f"A assinatura do administrador não foi encontrada:\n\n"
                f"{assinatura_path}\n\n"
                f"Deseja continuar mesmo assim?\n"
                f"(O recibo será gerado com espaço para assinatura manual)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if resposta == QMessageBox.StandardButton.No:
                return
        
        # Gerar recibo
        try:
            v_normal = self.dados.get('total_normal', 0.0)
            v_extra  = self.dados.get('total_extra', 0.0)
            meses_n, meses_e = calcular_meses_quotas(
                v_normal, v_extra, self.quota_normal, self.quota_extra
            )

            pdf_path = gerar_recibo_pdf(
                fracao             = self.fracao,
                nome_condomino     = self.nome,
                valor_total        = total_pago,
                administrador_nome = administrador,
                pasta_dados        = self.pasta_dados,
                output_dir         = docs_dir,
                valor_normal       = v_normal,
                valor_extra        = v_extra,
                meses_normal       = meses_n,
                meses_extra        = meses_e,
            )
            
            # Mensagem de sucesso
            msg = QMessageBox(self)
            msg.setWindowTitle("Recibo Gerado")
            msg.setText(f"Recibo gerado com sucesso!")
            msg.setInformativeText(f"Localização:\n{pdf_path}")
            msg.setIcon(QMessageBox.Icon.Information)
            
            # Botão para abrir PDF
            btn_abrir = msg.addButton("Abrir PDF", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
            
            msg.exec()
            
            # Abrir PDF se solicitado
            if msg.clickedButton() == btn_abrir:
                import os
                import subprocess
                
                if os.name == 'nt':  # Windows
                    os.startfile(str(pdf_path))
                elif os.name == 'posix':  # Linux/Mac
                    subprocess.run(['xdg-open', str(pdf_path)])
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao gerar recibo:\n\n{str(e)}"
            )


# ====================================================================
# DIÁLOGO CC / NIF
# ====================================================================
class CCDialog(QDialog):
    """Pequena janela para editar Cartão de Cidadão, validade e NIF."""

    def __init__(self, parent=None, cc_numero="", cc_validade="", nif="", nome=""):
        super().__init__(parent)
        titulo = "Cartão de Cidadão"
        if nome:
            titulo = f"CC — {nome}"
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QDialog { background: #f7f7f7; }
            QLabel { font-size: 12px; }
            QLineEdit {
                padding: 4px 6px;
                border: 1px solid #aaa;
                border-radius: 3px;
                background: white;
                font-family: monospace;
            }
            QPushButton {
                padding: 5px 14px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ed_cc = QLineEdit(str(cc_numero or ""))
        self.ed_cc.setPlaceholderText("xxxxxxxx x xxx")
        self.ed_cc.setMaxLength(20)
        form.addRow("Cartão Cidadão:", self.ed_cc)

        self.ed_validade = QLineEdit(str(cc_validade or ""))
        self.ed_validade.setPlaceholderText("dd-mm-yyyy")
        self.ed_validade.setMaxLength(10)
        form.addRow("Data Validade:", self.ed_validade)

        self.ed_nif = QLineEdit(str(nif or ""))
        self.ed_nif.setPlaceholderText("xxxxxxxxx")
        self.ed_nif.setMaxLength(9)
        form.addRow("NIF:", self.ed_nif)

        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_salvar = QPushButton("OK")
        btn_salvar.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
            }
            QPushButton:hover { background-color: #218838; }
        """)
        btn_salvar.clicked.connect(self.accept)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        btn_cancelar.clicked.connect(self.reject)
        btns.addWidget(btn_cancelar)
        btns.addWidget(btn_salvar)
        layout.addLayout(btns)

    def valores(self):
        return {
            "CC_NUMERO": self.ed_cc.text().strip(),
            "CC_VALIDADE": self.ed_validade.text().strip(),
            "NIF": self.ed_nif.text().strip(),
        }


# ====================================================================
# DELEGATE BOTÃO CC
# ====================================================================
class CCButtonDelegate(QStyledItemDelegate):
    """Desenha um botãozinho verde com 'CC' na célula."""

    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyle

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            fundo = index.data(Qt.ItemDataRole.BackgroundRole)
            painter.fillRect(option.rect, fundo if fundo else option.palette.base())

        # Botão centrado
        btn_w, btn_h = 36, 20
        x = option.rect.x() + (option.rect.width() - btn_w) // 2
        y = option.rect.y() + (option.rect.height() - btn_h) // 2
        btn_rect = QRect(x, y, btn_w, btn_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor("#28a745"))
        painter.setPen(QPen(QColor("#1e7e34"), 1))
        painter.drawRoundedRect(btn_rect, 4, 4)

        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "CC")

    def sizeHint(self, option, index):
        return QSize(50, 28)


# ====================================================================
# MODELO DE TABELA
# ====================================================================
class CondominosTableModel(QAbstractTableModel):
    """Modelo de tabela para condóminos"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        # Identidades das linhas alteradas desde a última gravação.
        # Usar id(dict) mantém o destaque correto mesmo após ordenar a tabela.
        self._dirty_row_ids = set()
        # Identidades (id(dict)) dos condóminos com quotas em atraso — alimentado
        # por CondominosWidget.calcular_e_aplicar_atrasos(). Usar id(dict) mantém
        # a marcação correta mesmo após ordenar a tabela.
        self._atraso_row_ids = set()
        # Estado do "piscar" do nome (alternado por CondominosWidget via QTimer).
        self._blink_visible = True
        # Colunas visíveis. CC é só UI (botão); dados em CC_NUMERO/CC_VALIDADE/NIF no dict.
        self._fields = ['NOME', 'TELEMOVEL', 'CHECK', 'EMAIL', 'FRACAO', 'ANDAR',
                        'PERMILAGEM', 'QUOTAN', 'QUOTAE', 'CC', 'FOTO']
        self._headers = ['Nome', 'Telemóvel', '✓', 'Email', 'Fração', 'Andar',
                         'Permilagem', 'Quota N', 'Quota E', 'CC', 'Foto']
        # Cache da tabela `fracoes` — FRACAO é a chave canónica
        self._fracoes_por_fracao = {}  # {fracao: {'ANDAR':..., 'PERMILAGEM':...}}
        self._fracoes_por_andar = {}   # {andar:  {'FRACAO':..., 'PERMILAGEM':...}}

    def set_fracoes(self, fracoes):
        """Define a lista de frações (tabela `fracoes`) para a ComboBox da
        FRACAO e para derivar automaticamente ANDAR/PERMILAGEM."""
        self._fracoes_por_fracao, self._fracoes_por_andar, _dups = construir_mapas_fracoes(fracoes)
    
    def rowCount(self, parent=QModelIndex()):
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()):
        return len(self._fields)
    
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return super().headerData(section, orientation, role)
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        
        row = index.row()
        col = index.column()
        key = self._fields[col]
        row_dict = self._data[row]
        value = row_dict.get(key, '')
        
        # Fundo amarelo claro para qualquer registo alterado ainda não gravado.
        if role == Qt.ItemDataRole.BackgroundRole:
            if id(row_dict) in self._dirty_row_ids:
                return QBrush(QColor("#fff2b2"))
            return QVariant()

        # DisplayRole (o que aparece na tela)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 2:  # CHECK
                return ''  # Checkbox delegate cuida da visualização
            elif col == 9:  # CC — delegate desenha o botão
                return ''
            elif col in (7, 8):  # Quotas
                try:
                    return f"{float(value):.2f}"
                except Exception:
                    return "0.00"
            elif col == 6:  # Permilagem
                try:
                    return f"{float(value):.3f}"
                except Exception:
                    return "0.000"
            else:
                return str(value)
        
        # EditRole (valor para edição)
        elif role == Qt.ItemDataRole.EditRole:
            return value
        
        # TextAlignmentRole (alinhamento)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (6, 7, 8):  # Permilagem e Quotas
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            elif col in (2, 4, 9):  # CHECK, FRAÇÃO, CC
                return Qt.AlignmentFlag.AlignCenter
            else:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        
        # ForegroundRole (cor do texto)
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:  # NOME
                return QBrush(QColor("#1976d2"))
            if col in (7, 8):  # quotas só leitura (fracoes)
                return QBrush(QColor("#555555"))
        
        return QVariant()
    
    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        # ANDAR (5) e PERMILAGEM (6): derivados da FRACAO (read-only).
        # QUOTAN (7) e QUOTAE (8): só leitura — valores vêm da tabela fracoes.
        # CC (9) abre diálogo próprio. FRACAO (4) é editável via ComboBox.
        col = index.column()
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if col in (5, 6, 7, 8, 9):  # ANDAR, PERMILAGEM, QUOTAN, QUOTAE, CC
            return base
        return base | Qt.ItemFlag.ItemIsEditable
    
    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        
        row = index.row()
        if row >= len(self._data):
            return False
        
        key = self._fields[index.column()]
        # CC é só UI (abre diálogo próprio) — nunca se escreve diretamente.
        if key == 'CC':
            return False
        # Quotas: só leitura na grelha (fonte = tabela fracoes)
        if key in ('QUOTAN', 'QUOTAE'):
            return False
        row_dict = self._data[row]

        # Validação / normalização na lógica de negócio
        # Lista (mesmo vazia) = restrição estrita às frações da tabela `fracoes`
        fracoes_validas = list(self._fracoes_por_fracao.keys())
        ok, value = validar_e_normalizar_campo(key, value, fracoes_validas)
        if not ok:
            return False
        
        # Só marcar como alterado quando o valor realmente muda.
        valor_anterior = row_dict.get(key, '')
        if valor_anterior != value:
            self._dirty_row_ids.add(id(row_dict))
        row_dict[key] = value
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.BackgroundRole])
        # Repintar a linha completa para que o amarelo seja imediatamente visível.
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, self.columnCount() - 1),
            [Qt.ItemDataRole.BackgroundRole],
        )
        
        # Se alterou CHECK, atualizar também EMAIL para mudar a cor
        if index.column() == 2:  # Coluna CHECK
            email_index = self.index(index.row(), 3)  # Coluna EMAIL
            self.dataChanged.emit(email_index, email_index)

        # FRACAO é a chave canónica → derivar ANDAR + PERMILAGEM + quotas
        # (quotas: copia se fração/andar já existir; senão proporção pela permilagem).
        # QUOTAN/QUOTAE são só leitura (carregados de fracoes via carregar_condominos).
        if key == 'FRACAO':
            actualizadas = sincronizar_por_fracao(
                row_dict, value, self._fracoes_por_fracao,
                dados_condominos=self._data,
            )
            for campo_act in actualizadas:
                try:
                    col = self._fields.index(campo_act)
                except ValueError:
                    continue
                idx = self.index(row, col)
                self.dataChanged.emit(idx, idx)

        return True
    
    def setAdminData(self, row, value):
        """Método auxiliar para alterar campo ADMIN"""
        if 0 <= row < len(self._data):
            self._data[row]['ADMIN'] = value
            # Atualizar a coluna NOME de todas as linhas para refrescar os ícones
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0)
            )
            return True
        return False
    
    def insertRows(self, position, rows, parent=QModelIndex()):
        self.beginInsertRows(parent, position, position + rows - 1)
        for i in range(rows):
            new_row = criar_novo_condomino()
            self._data.insert(position, new_row)
            self._dirty_row_ids.add(id(new_row))
        self.endInsertRows()
        return True
    
    def removeRows(self, position, rows, parent=QModelIndex()):
        self.beginRemoveRows(parent, position, position + rows - 1)
        del self._data[position:position + rows]
        self.endRemoveRows()
        return True
    
    def load_from_db(self, caminho):
        self.beginResetModel()
        self._data = carregar_condominos_db(caminho)
        # Alinhar ANDAR/PERMILAGEM com a tabela `fracoes` (chave = FRACAO)
        if self._fracoes_por_fracao:
            n = reconciliar_com_fracoes(self._data, self._fracoes_por_fracao)
            if n:
                print(f"✓ Reconciliados {n} condómino(s) com a tabela fracoes")
        self._dirty_row_ids.clear()
        # Os dicts são recriados a cada load — os ids antigos ficam obsoletos.
        # CondominosWidget.carregar_tabela() recalcula o atraso logo a seguir.
        self._atraso_row_ids.clear()
        self.endResetModel()

    def set_atraso(self, atraso_ids):
        """Define o conjunto de condóminos (id(dict)) com quotas em atraso e
        repinta a coluna Nome para refletir a cor/piscar."""
        self._atraso_row_ids = set(atraso_ids or ())
        if self.rowCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [Qt.ItemDataRole.DisplayRole],
            )

    def esta_em_atraso(self, row):
        """Indica se o condómino na linha `row` tem quotas em atraso."""
        if row < 0 or row >= len(self._data):
            return False
        return id(self._data[row]) in self._atraso_row_ids

    def toggle_blink(self):
        """Alterna a visibilidade do nome dos condóminos em atraso (efeito piscar)."""
        self._blink_visible = not self._blink_visible
        if self._atraso_row_ids and self.rowCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [Qt.ItemDataRole.DisplayRole],
            )

    # Colunas pelas quais é permitido ordenar ao clicar no cabeçalho.
    COLUNAS_ORDENAVEIS = (4, 6)  # FRACAO, PERMILAGEM

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        """Ordena as linhas pela coluna indicada.

        Suportado apenas para FRACAO (col. 4) e PERMILAGEM (col. 6) — as
        únicas colunas cuja ordenação faz sentido na prática. Um pedido
        de ordenação por qualquer outra coluna é ignorado (ver também
        CondominosWidget._ao_clicar_cabecalho, que já filtra o clique
        antes de chegar aqui).
        """
        if column not in self.COLUNAS_ORDENAVEIS:
            return
        key = self._fields[column]
        descendente = (order == Qt.SortOrder.DescendingOrder)

        def chave_ordenacao(row_dict):
            valor = row_dict.get(key)
            if key == 'PERMILAGEM':
                try:
                    return float(valor)
                except (TypeError, ValueError):
                    return 0.0
            # FRACAO: ordenar como texto (A, B, C, ...)
            return str(valor or '').strip().upper()

        self.layoutAboutToBeChanged.emit()
        self._data.sort(key=chave_ordenacao, reverse=descendente)
        self.layoutChanged.emit()
    
    def save_to_db(self, caminho):
        return guardar_condominos_db(caminho, self._data)


# ====================================================================
# WIDGET PRINCIPAL
# ====================================================================
class CondominosWidget(QWidget):
    # Emitido após gravar com sucesso (Main pode ligar a ConfiguracoesWidget.recarregar_regras)
    quotas_atualizadas = pyqtSignal()

    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.caminho_condominos_db = None
        self.foto_label = None
        self.tooltip_label = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        title = QLabel("Ficha de Condóminos")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Barra de botões
        btn_bar = QHBoxLayout()
        
        btn_adicionar = QPushButton("→ Adicionar Condómino")
        btn_adicionar.setFixedHeight(45)
        icon_path = ICONS_DIR / "add-icon.png"
        if icon_path.exists():
            btn_adicionar.setIcon(QIcon(str(icon_path)))
            btn_adicionar.setIconSize(QSize(30, 30))
        btn_adicionar.clicked.connect(self.adicionar_registo)
        btn_bar.addWidget(btn_adicionar)
        btn_bar.addSpacing(10)
        
        btn_apagar = QPushButton("→ Apagar Condómino")
        btn_apagar.setFixedHeight(45)
        icon_path = ICONS_DIR / "delete-icon.png"
        if icon_path.exists():
            btn_apagar.setIcon(QIcon(str(icon_path)))
            btn_apagar.setIconSize(QSize(30, 30))
        btn_apagar.clicked.connect(self.apagar_registo)
        btn_bar.addWidget(btn_apagar)
        btn_bar.addSpacing(10)
        
        btn_guardar = QPushButton("→ Gravar Alterações")
        btn_guardar.setFixedHeight(45)
        icon_path = ICONS_DIR / "save-icon.png"
        if icon_path.exists():
            btn_guardar.setIcon(QIcon(str(icon_path)))
            btn_guardar.setIconSize(QSize(22, 22))
        btn_guardar.clicked.connect(self.guardar_alteracoes)
        btn_bar.addWidget(btn_guardar)
        btn_bar.addSpacing(10)

        btn_imprimir_recibos = QPushButton("🖨️ Imprimir Recibos")
        btn_imprimir_recibos.setFixedHeight(45)
        btn_imprimir_recibos.setToolTip("Gera recibos anuais em lote para todos os condóminos ativos")
        btn_imprimir_recibos.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #1b5e20;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        btn_imprimir_recibos.clicked.connect(self.imprimir_recibos_lote)
        btn_bar.addWidget(btn_imprimir_recibos)
        btn_bar.addSpacing(10)

        self.btn_whatsapp = QPushButton(" Atrasados ")
        self.btn_whatsapp.setFixedHeight(45)
        self.btn_whatsapp.setToolTip(
            "Abre o WhatsApp para todos os condóminos com quotas em atraso\n"
            "(mensagem pré-preenchida — confirma o envio em cada janela)\n"
            "Disponível apenas no exercício corrente."
        )
        wa_icon_path = ICONS_DIR / "whatsapp-icon.png"
        if wa_icon_path.exists():
            self.btn_whatsapp.setIcon(QIcon(str(wa_icon_path)))
            self.btn_whatsapp.setIconSize(QSize(42, 42))
        self.btn_whatsapp.setStyleSheet("""
            QPushButton {
                background-color: #337785;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 2px 12px 2px 4px;
            }
            QPushButton:hover {
                background-color: #1D6978;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        self.btn_whatsapp.clicked.connect(self.enviar_whatsapp_atrasados)
        btn_bar.addWidget(self.btn_whatsapp)
        self._atualizar_estado_whatsapp()

        btn_bar.addStretch()
        layout.addLayout(btn_bar)
        
        # Tabela
        self.table_view = QTableView()
        self.model = CondominosTableModel()
        self.table_view.setModel(self.model)
        
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        # Ordenação ao clicar no cabeçalho — apenas Fração e Permilagem
        # (as outras colunas ignoram o clique; ver _ao_clicar_cabecalho).
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        self._coluna_ordenada = 4  # FRACAO (ordem já aplicada por defeito ao carregar)
        self._ordem_ordenacao = Qt.SortOrder.AscendingOrder
        header.setSortIndicator(self._coluna_ordenada, self._ordem_ordenacao)
        header.sectionClicked.connect(self._ao_clicar_cabecalho)
        self.table_view.setColumnWidth(0, 220)  # Nome
        self.table_view.setColumnWidth(1, 100)  # Telemóvel
        self.table_view.setColumnWidth(2, 30)   # CHECK
        self.table_view.setColumnWidth(3, 200)  # Email
        self.table_view.setColumnWidth(4, 70)   # Fração
        self.table_view.setColumnWidth(5, 80)   # Andar
        self.table_view.setColumnWidth(6, 100)  # Permilagem
        self.table_view.setColumnWidth(7, 100)  # Quota N
        self.table_view.setColumnWidth(8, 100)  # Quota E
        self.table_view.setColumnWidth(9, 50)   # CC
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)  # Foto
        
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        # Setas de ordenação a amarelo (#FFD700) — imagens antialiased (Qt não permite
        # recolorir a seta nativa; a única forma estável é substituir por image:)
        _up = (ICONS_DIR / "sort_up_yellow.png").as_posix()
        _down = (ICONS_DIR / "sort_down_yellow.png").as_posix()
        self.table_view.setStyleSheet(f"""
            QTableView {{ 
                gridline-color: #C0C0C0; 
                border: 1px solid #C0C0C0; 
            }}
            QTableView::item {{ 
                padding: 5px; 
            }}
            QHeaderView::section {{
                background-color: #2F5597; 
                color: white;
                font-weight: bold; 
                padding: 8px; 
                border: 1px solid #1F4587;
            }}
            QHeaderView::up-arrow {{
                image: url({_up});
                width: 11px;
                height: 11px;
            }}
            QHeaderView::down-arrow {{
                image: url({_down});
                width: 11px;
                height: 11px;
            }}
        """)
        self.table_view.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.SelectedClicked
        )
        
        # Delegates
        nome_delegate = NomeComAdminDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(0, nome_delegate)
        
        checkbox_delegate = CheckBoxDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(2, checkbox_delegate)
        
        email_delegate = EmailColorDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(3, email_delegate)
        
        # FRACAO (col 4): ComboBox — chave canónica; ANDAR/PERMILAGEM derivados
        self.fracao_delegate = FracaoComboDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(4, self.fracao_delegate)

        cc_delegate = CCButtonDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(9, cc_delegate)

        # Timer a piscar o nome dos condóminos com quotas em atraso (a cada 500ms)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._piscar_atrasados)
        self._blink_timer.start()

        # Mouse tracking
        self.table_view.setMouseTracking(True)
        self.table_view.viewport().setMouseTracking(True)
        self.table_view.viewport().installEventFilter(self)
        self.table_view.viewport().setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        
        layout.addWidget(self.table_view)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("QStatusBar { background: white; padding: 5px; }")
        layout.addWidget(self.status_bar)
        
        # Label para foto
        self.foto_label = QLabel(self)
        self.foto_label.setStyleSheet("""
            QLabel {
                border: 3px solid #2F5597; 
                background-color: white;
                padding: 5px; 
                border-radius: 8px;
            }
        """)
        self.foto_label.setScaledContents(False)
        self.foto_label.setWindowFlags(Qt.WindowType.ToolTip)
        self.foto_label.hide()
        
        # Label para tooltips
        self.tooltip_label = QLabel(self)
        self.tooltip_label.setStyleSheet("""
            QLabel {
                background-color: #2F5597;
                color: white;
                border: 2px solid #1a3866;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        self.tooltip_label.setWindowFlags(Qt.WindowType.ToolTip)
        self.tooltip_label.hide()
        self.tooltip_label.setWordWrap(True)
        self.tooltip_label.setMaximumWidth(430)
        
        # Conectar seleção
        self.table_view.selectionModel().selectionChanged.connect(self.update_status_bar)
    
    def _ao_clicar_cabecalho(self, coluna):
        """Ordena a tabela ao clicar no cabeçalho de uma coluna.

        Apenas FRACAO (col. 4) e PERMILAGEM (col. 6) são ordenáveis; o
        clique em qualquer outra coluna é ignorado (sem indicador, sem
        reordenação), já que ordenar por NOME, EMAIL, etc. não tem
        utilidade prática aqui.
        """
        if coluna not in CondominosTableModel.COLUNAS_ORDENAVEIS:
            return

        if coluna == self._coluna_ordenada:
            self._ordem_ordenacao = (
                Qt.SortOrder.DescendingOrder
                if self._ordem_ordenacao == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._coluna_ordenada = coluna
            self._ordem_ordenacao = Qt.SortOrder.AscendingOrder

        self.model.sort(self._coluna_ordenada, self._ordem_ordenacao)
        self.table_view.horizontalHeader().setSortIndicator(
            self._coluna_ordenada, self._ordem_ordenacao
        )

    def update_status_bar(self, selected, deselected):
        indexes = self.table_view.selectionModel().selectedRows()
        if indexes:
            row = indexes[0].row()
            nome = str(self.model._data[row].get('NOME', ''))
            if nome.startswith('[') and nome.endswith(']'):
                self.status_bar.showMessage("⚠️ Condómino inativo.")
                return
        self.status_bar.showMessage("")
    
    def set_pasta_dados(self, pasta_dados):
        from Commons import pasta_de_dados
        self.pasta_dados = pasta_dados
        self.pasta = pasta_de_dados(pasta_dados)
        self.caminho_condominos_db = self.pasta  # alias pasta real
        self.carregar_fracoes()
        self.carregar_tabela()
        self._atualizar_estado_whatsapp()

    def _atualizar_estado_whatsapp(self):
        """Ativa o botão WhatsApp só no exercício corrente; desativa em histórico."""
        btn = getattr(self, "btn_whatsapp", None)
        if btn is None:
            return
        corrente = pasta_e_corrente(self.pasta_dados)
        btn.setEnabled(corrente)
        if corrente:
            btn.setToolTip(
                "Envia uma menssagem pelo WhatsApp para \n"
                "todos os condóminos com quotas em atraso."
            )
        else:
            btn.setToolTip(
                "WhatsApp indisponível em exercícios históricos.\n"
                "Só pode enviar mensagens no ano corrente."
            )

    def carregar_fracoes(self):
        """Lê a tabela `fracoes` e alimenta a ComboBox da FRACAO.

        ANDAR e PERMILAGEM passam a ser derivados automaticamente da fração
        escolhida (sem fallbacks inventados).
        """
        fracoes = obter_fracoes(self.pasta_dados)
        self.model.set_fracoes(fracoes)
        letras = [f['FRACAO'] for f in fracoes if f.get('FRACAO')]
        self.fracao_delegate.set_items(letras)
        if not letras:
            print("⚠️ Tabela fracoes vazia — ComboBox da FRACAO sem itens")
    
    def carregar_tabela(self):
        if self.caminho_condominos_db:
            self.model.load_from_db(str(self.caminho_condominos_db))
            self.status_bar.showMessage(f"✅ {self.model.rowCount()} Condóminos carregados")
            self.calcular_e_aplicar_atrasos()

    def _piscar_atrasados(self):
        """Alterna a intermitência do nome dos condóminos em atraso (chamado pelo QTimer)."""
        if hasattr(self, "model"):
            self.model.toggle_blink()

    def calcular_e_aplicar_atrasos(self):
        """Calcula, por ANDAR, quais condóminos têm quotas em atraso e marca-os
        no modelo para o nome aparecer a vermelho a piscar na grelha.

        Só calcula no exercício corrente: o critério de `calcular_estado_atraso`
        compara com o mês corrente do calendário, pelo que não se aplica da
        mesma forma a pastas de histórico (ver também `_atualizar_estado_whatsapp`).
        """
        if not hasattr(self, "model"):
            return
        if not self.pasta_dados or not pasta_e_corrente(self.pasta_dados):
            self.model.set_atraso(set())
            return

        atraso_ids = set()
        cache_total_por_andar = {}  # evita repetir obter_pagamentos_condomino por ANDAR

        for row_dict in self.model._data:
            andar = str(row_dict.get('ANDAR', '') or '').strip()
            nome = str(row_dict.get('NOME', '') or '').strip()
            if not andar or not nome:
                continue
            if nome.startswith('[') and nome.endswith(']'):
                continue  # condómino inativo

            try:
                if andar in cache_total_por_andar:
                    total_pago, divida_liq = cache_total_por_andar[andar]
                else:
                    dados = obter_pagamentos_condomino(andar, self.pasta_dados)
                    total_pago = dados.get('total_geral', 0.0)
                    divida_liq = dados.get('divida_anterior_liquidada', 0.0)
                    cache_total_por_andar[andar] = (total_pago, divida_liq)

                quota_normal = clean_numeric(row_dict.get('QUOTAN', 0))
                quota_extra = clean_numeric(row_dict.get('QUOTAE', 0))
                estado = calcular_estado_atraso(
                    total_pago, quota_normal, quota_extra,
                    divida_anterior=divida_liq,
                )
                if estado.get('em_atraso'):
                    atraso_ids.add(id(row_dict))
            except Exception as e:
                # Um condómino com dados incompletos não pode bloquear a grelha inteira.
                print(f"⚠ Não foi possível calcular o atraso de {nome}: {e}")
                continue

        self.model.set_atraso(atraso_ids)
    
    def adicionar_registo(self):
        """Adiciona um condómino novo, se ainda existir fração livre.

        Bloqueia quando todas as frações da tabela ``fracoes`` já estão
        atribuídas a pelo menos um registo em ``condominos``.
        """
        fracoes_cfg = {
            str(f.get("FRACAO") or "").strip().upper()
            for f in (obter_fracoes(self.pasta_dados) or [])
            if str(f.get("FRACAO") or "").strip()
        }
        fracoes_usadas = {
            str(row.get("FRACAO") or "").strip().upper()
            for row in (self.model._data or [])
            if str(row.get("FRACAO") or "").strip()
        }

        if fracoes_cfg and fracoes_cfg.issubset(fracoes_usadas):
            lista = ", ".join(sorted(fracoes_cfg))
            QMessageBox.warning(
                self,
                "Frações esgotadas",
                "<br><p style='color: red; font-weight: bold; font-size: 13pt;'>"
                "Não é possível adicionar um novo condómino:</p><br>"
                "Todas as frações ["f"{lista}] definidas na tabela de frações já estão "
                "atribuídas a condóminos.<br><br>"
                "Liberte uma fração (apagar/alterar o condómino correspondente) "
                "ou acrescenta frações em Configurações antes de continuar.",
            )
            return

        row = self.model.rowCount()
        self.model.insertRows(row, 1)
        self.table_view.scrollToBottom()
        index = self.model.index(row, 0)
        self.table_view.setCurrentIndex(index)
        self.table_view.edit(index)
    
    def selecionar_fotos(self, row, selecionar_pasta=False):
        """Seleciona uma ou mais fotos para o condómino e copia-as para FOTOS_DIR.

        Clique esquerdo na célula Foto: abre o seletor de ficheiros.
        Clique direito: permite escolher uma pasta e importar as imagens que contém.
        O campo FOTO guarda os nomes separados por ponto e vírgula; a pré-visualização
        apresenta a primeira imagem da lista.
        """
        extensoes = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tif', '.tiff'}
        try:
            if selecionar_pasta:
                pasta = QFileDialog.getExistingDirectory(
                    self,
                    "Selecionar pasta com fotografias",
                    str(FOTOS_DIR if FOTOS_DIR.exists() else BASE_DIR)
                )
                if not pasta:
                    return
                pasta_origem = Path(pasta)
                ficheiros = sorted(
                    f for f in pasta_origem.iterdir()
                    if f.is_file() and f.suffix.lower() in extensoes
                )
                if not ficheiros:
                    QMessageBox.information(
                        self, "Sem fotografias",
                        "A pasta selecionada não contém ficheiros de imagem suportados."
                    )
                    return
            else:
                caminhos, _ = QFileDialog.getOpenFileNames(
                    self,
                    "Selecionar fotografia(s) do condómino",
                    str(FOTOS_DIR if FOTOS_DIR.exists() else BASE_DIR),
                    "Imagens (*.jpg *.jpeg *.png *.bmp *.gif *.webp *.tif *.tiff);;Todos os ficheiros (*)"
                )
                if not caminhos:
                    return
                ficheiros = [Path(caminho) for caminho in caminhos]
                ficheiros = [f for f in ficheiros if f.suffix.lower() in extensoes]
                if not ficheiros:
                    QMessageBox.warning(self, "Ficheiros inválidos", "Selecione ficheiros de imagem suportados.")
                    return

            FOTOS_DIR.mkdir(parents=True, exist_ok=True)
            nomes_guardados = []
            for origem in ficheiros:
                destino = FOTOS_DIR / origem.name
                # Evitar copiar um ficheiro sobre si próprio.
                if origem.resolve() != destino.resolve():
                    # Se já existir um ficheiro com o mesmo nome mas conteúdo diferente,
                    # criar um nome alternativo para não o substituir silenciosamente.
                    if destino.exists() and origem.stat().st_size != destino.stat().st_size:
                        base, ext = origem.stem, origem.suffix
                        contador = 1
                        while destino.exists():
                            destino = FOTOS_DIR / f"{base}_{contador}{ext}"
                            contador += 1
                    shutil.copy2(origem, destino)
                nomes_guardados.append(destino.name)

            valor = '; '.join(dict.fromkeys(nomes_guardados))
            model_index = self.model.index(row, 9)
            if not self.model.setData(model_index, valor, Qt.ItemDataRole.EditRole):
                QMessageBox.warning(self, "Aviso", "Não foi possível atualizar o campo Foto.")
                return
            self.table_view.setCurrentIndex(model_index)
            self.status_bar.showMessage(
                f"{len(nomes_guardados)} fotografia(s) associada(s) ao condómino.", 5000
            )
        except Exception as e:
            QMessageBox.critical(self, "Erro ao selecionar fotografias", str(e))

    def apagar_registo(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.warning(self, "Aviso", "<br><b>Selecione uma linha para apagar.</br>")
            return
        row = indexes[0].row()
        reply = QMessageBox.question(
            self, "Confirmar", "<br><b>Tem certeza que deseja apagar este condómino?</b>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.model.removeRows(row, 1)
            self.status_bar.showMessage("❌ Condómino apagado.")
    
    def guardar_alteracoes(self):
        if not self.caminho_condominos_db:
            QMessageBox.warning(self, "Aviso", "Nenhum ficheiro carregado.")
            return
        try:
            # Validação (inclui frações duplicadas — UNIQUE na BD)
            validar_condominos(self.model._data)
            
            # Guardar
            if not self.model.save_to_db(str(self.caminho_condominos_db)):
                raise RuntimeError(
                    "Não foi possível gravar na base de dados.\n\n"
                    "Verifique se não há frações duplicadas e se a pasta de dados "
                    "está acessível."
                )
            
            # Sincronizar quotas normal/extra na tabela regras (sem INSERT)
            atualizar_quotas_regras(self.pasta_dados, self.model._data)

            # Refresh visual da aba Regras (se existir no Main)
            self.quotas_atualizadas.emit()
            self._tentar_refresh_regras()

            QMessageBox.information(
                self, "Sucesso",
                "<b>Alterações guardadas</b><br><br>"
                "Quota N / Quota E são lidas da tabela <b>frações</b> (editar em Configurações → Frações)."
            )

            self.carregar_tabela()
            self.status_bar.showMessage("✅ Guardado.")
        except ValueError as ve:
            QMessageBox.warning(self, "Validação falhou", str(ve))
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
    

    def _tentar_refresh_regras(self):
        """Procura ConfiguracoesWidget na árvore de widgets e recarrega Regras."""
        try:
            from PyQt6.QtWidgets import QWidget
            w = self.parent()
            visited = set()
            while w is not None and id(w) not in visited:
                visited.add(id(w))
                for child in w.findChildren(QWidget):
                    if hasattr(child, "recarregar_regras") and callable(child.recarregar_regras):
                        child.recarregar_regras()
                        return
                w = w.parent()
        except Exception as e:
            print(f"⚠️ refresh regras: {e}")

    def imprimir_recibos_lote(self):
        """Gera recibos anuais em lote para todos os condóminos ativos"""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Nenhuma pasta de dados carregada.")
            return

        reply = QMessageBox.question(
            self, "Confirmar Impressão em Lote",
            "<br><b>Deseja gerar os recibos anuais para TODOS os condóminos ativos?</b><br><br>"
            "Será criado um PDF por condómino na pasta docs/.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.status_bar.showMessage("⏳ A gerar recibos em lote...")
        QApplication.processEvents()

        try:
            resultado = gerar_recibos_para_todos_condominos(self.pasta_dados)

            total = resultado.get("total", 0)
            sucessos = resultado.get("sucessos", [])
            erros = resultado.get("erros", [])

            msg = QMessageBox(self)
            msg.setWindowTitle("Recibos em Lote")
            msg.setIcon(QMessageBox.Icon.Information if not erros else QMessageBox.Icon.Warning)

            texto = (
                f"Processados: {total} condómino(s)\n"
                f"Gerados com sucesso: {len(sucessos)}\n"
                f"Erros: {len(erros)}"
            )
            msg.setText(texto)

            detalhes = []
            if sucessos:
                detalhes.append("--- Recibos gerados ---")
                for s in sucessos:
                    detalhes.append(
                        f"  {s.get('fracao', '?')} – {s.get('nome', '')} "
                        f"({s.get('valor_total', 0):.2f} €)"
                    )
            if erros:
                detalhes.append("\n--- Erros ---")
                for e in erros:
                    detalhes.append(f"  ✗ {e}")

            if detalhes:
                msg.setDetailedText("\n".join(detalhes))

            if sucessos:
                from Commons import BASE_DIR
                docs_dir = BASE_DIR / "docs"
                msg.setInformativeText(f"PDFs guardados em:\n{docs_dir}")

            msg.exec()
            self.status_bar.showMessage(
                f"✅ {len(sucessos)} recibo(s) gerado(s)" if sucessos else "Nenhum recibo gerado"
            )

        except Exception as e:
            self.status_bar.showMessage("")
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao gerar recibos em lote:\n\n{str(e)}"
            )

    def enviar_whatsapp_atrasados(self):
        """Abre o WhatsApp para todos os condóminos com quotas em atraso."""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Nenhuma pasta de dados carregada.")
            return
        if not pasta_e_corrente(self.pasta_dados):
            QMessageBox.information(
                self,
                "Exercício histórico",
                "O envio de mensagens WhatsApp só está disponível no exercício corrente.\n\n"
                "Está a visualizar um ano do histórico — a operação foi bloqueada.",
            )
            return

        reply = QMessageBox.question(
            self,
            "WhatsApp — Quotas em Atraso",
            "Pretende abrir o WhatsApp para TODOS os condóminos com quotas em atraso?\n\n"
            "• Será aberta uma janela do WhatsApp por condómino\n"
            "• A mensagem já vai preenchida — confirme o envio em cada janela\n"
            "• Condóminos sem telefone ou inativos são ignorados",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.status_bar.showMessage("⏳ A processar condóminos com atraso...")
        QApplication.processEvents()

        try:
            resultado = enviar_whatsapp_a_todos_atrasados(self.pasta_dados, parent=self)
        except Exception as e:
            self.status_bar.showMessage("")
            QMessageBox.critical(self, "Erro", f"Erro ao enviar WhatsApp:\n\n{e}")
            return

        enviados = resultado.get("enviados", 0)
        total = resultado.get("total", 0)
        ignorados = resultado.get("ignorados", [])
        erros = resultado.get("erros", [])

        msg = QMessageBox(self)
        msg.setWindowTitle("WhatsApp — Resumo")
        msg.setIcon(
            QMessageBox.Icon.Information if enviados else QMessageBox.Icon.Warning
        )
        msg.setText(
            f"Processados: {total} condómino(s)\n"
            f"WhatsApp abertos: {enviados}\n"
            f"Ignorados: {len(ignorados)}\n"
            f"Erros: {len(erros)}"
        )

        detalhes = []
        if ignorados:
            detalhes.append("--- Ignorados ---")
            detalhes.extend(f"  • {i}" for i in ignorados[:30])
            if len(ignorados) > 30:
                detalhes.append(f"  ... e mais {len(ignorados) - 30}")
        if erros:
            detalhes.append("\n--- Erros ---")
            detalhes.extend(f"  ✗ {e}" for e in erros)
        if detalhes:
            msg.setDetailedText("\n".join(detalhes))

        msg.exec()
        self.status_bar.showMessage(
            f"✅ {enviados} mensagem(s) de WhatsApp aberta(s)" if enviados
            else "Nenhum condómino com atraso ou sem telefone"
        )

    def keyPressEvent(self, event):
        """Lida com teclas Insert, Delete e Enter"""
        if event.key() == Qt.Key.Key_Insert:
            self.adicionar_registo()
        elif event.key() == Qt.Key.Key_Delete:
            self.apagar_registo()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current_index = self.table_view.currentIndex()
            if current_index.isValid():
                self.table_view.edit(current_index)
        else:
            super().keyPressEvent(event)
    
    def eventFilter(self, obj, event):
        if obj == self.table_view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = event.pos()
                index = self.table_view.indexAt(pos)
                
                if index.isValid():
                    row = index.row()
                    col = index.column()
                    
                    # Coluna 0 (NOME) - foto + dica para alterar administrador
                    if col == 0:
                        pos = event.globalPosition().toPoint()
                        tooltip_text = "Clique botão Dto. para alterar<br>o administrador em funções"
                        foto_valor = str(self.model._data[row].get('FOTO', '') or '').strip()
                        foto_nome = foto_valor.split(';')[0].strip() if foto_valor else ''
                        foto_ok = False
                        if foto_nome:
                            foto_path = Path(foto_nome)
                            if not foto_path.is_absolute():
                                foto_path = FOTOS_DIR / foto_nome
                            if foto_path.exists() and foto_path.is_file():
                                foto_ok = self.mostrar_foto(str(foto_path), pos)
                            else:
                                self.foto_label.hide()
                        else:
                            self.foto_label.hide()
                        # Mensagem por baixo da foto (ou junto ao cursor se não houver foto)
                        self.mostrar_tooltip(
                            tooltip_text, pos,
                            below_widget=self.foto_label if foto_ok else None,
                        )

                    # Coluna 2 (ICON ATIVAR) - Tooltip baseado em CHECK
                    elif col == 2:
                        self.foto_label.hide()
                        check_value = self.model._data[row].get('CHECK', '.F.')
                        is_checked = check_value in (True, 'T', '.T.', 't')
                        
                        if is_checked:
                            tooltip_text = "✅ Desativar email"
                        else:
                            tooltip_text = "❌ Ativar email"
                        
                        self.mostrar_tooltip(tooltip_text, event.globalPosition().toPoint())
                        
                    # Coluna 3 (EMAIL) - Tooltip baseado em CHECK
                    elif col == 3:
                        self.foto_label.hide()
                        check_value = self.model._data[row].get('CHECK', '.F.')
                        is_checked = check_value in (True, 'T', '.T.', 't')
                        
                        if is_checked:
                            tooltip_text = "✅ Email ativo"
                        else:
                            tooltip_text = "❌ Email inativo"
                        
                        self.mostrar_tooltip(tooltip_text, event.globalPosition().toPoint())
                    
                    # Coluna 4 (FRACAO) - edição via ComboBox
                    elif col == 4:
                        self.foto_label.hide()
                        self.mostrar_tooltip(
                            "Clique para escolher a fração",
                            event.globalPosition().toPoint(),
                        )

                    # Coluna 5 (ANDAR) - clique = consultar pagamentos de quotas
                    elif col == 5:
                        self.foto_label.hide()
                        andar = str(self.model._data[row].get('ANDAR', '')).strip()
                        if andar:
                            tooltip_text = "💰 Clique para ver\npagamentos de quotas"
                        else:
                            tooltip_text = "Defina a FRAÇÃO para ver\npagamentos de quotas"
                        self.mostrar_tooltip(tooltip_text, event.globalPosition().toPoint())

                    # Coluna 9 (CC) - Tooltip
                    elif col == 9:
                        self.foto_label.hide()
                        self.mostrar_tooltip("Clique para editar<br>C. Cidadão & NIF",
                                             event.globalPosition().toPoint())
                    
                    # Outras colunas
                    else:
                        self.foto_label.hide()
                        self.tooltip_label.hide()
                else:
                    self.foto_label.hide()
                    self.tooltip_label.hide()
                    
            elif event.type() == QEvent.Type.Leave:
                self.foto_label.hide()
                self.tooltip_label.hide()

            elif event.type() == QEvent.Type.MouseButtonPress:
                index = self.table_view.indexAt(event.pos())
                if index.isValid():
                    # Coluna NOME (col 0): botão direito → administrador em funções
                    if (event.button() == Qt.MouseButton.RightButton and
                            index.column() == 0):
                        self.definir_administrador_por_linha(index.row())
                        return True

                    # Campo FOTO (col 10): botão esquerdo abre seleção de ficheiros
                    if index.column() == 10:
                        if event.button() == Qt.MouseButton.LeftButton:
                            self.selecionar_fotos(index.row(), selecionar_pasta=False)
                            return True

                    # Coluna CC (col 9): abrir diálogo de Cartão de Cidadão / NIF
                    if (event.button() == Qt.MouseButton.LeftButton and
                            index.column() == 9):
                        self.editar_cc(index.row())
                        return True

                    # Botão esquerdo na coluna ANDAR: consultar pagamentos.
                    # (FRACAO é editável via ComboBox; o clique de quotas passou para ANDAR)
                    if (event.button() == Qt.MouseButton.LeftButton and
                            index.column() == 5):
                        row = index.row()
                        andar = str(self.model._data[row].get('ANDAR', '')).strip()
                        if andar:
                            self.mostrar_pagamentos_quotas(row)
                        else:
                            QMessageBox.warning(
                                self, "Aviso",
                                "Defina a FRAÇÃO do condómino antes de consultar pagamentos."
                            )
                        return True

        return super().eventFilter(obj, event)

    def definir_administrador_por_linha(self, row):
        """Define o condómino da linha como administrador em funções (admin=1)."""
        if row < 0 or row >= len(self.model._data):
            return
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Nenhuma pasta de dados carregada.")
            return

        cond = self.model._data[row]
        nome = str(cond.get('NOME', '')).strip()
        if not nome:
            QMessageBox.warning(self, "Aviso", "O condómino não tem nome definido.")
            return
        if nome.startswith('[') and nome.endswith(']'):
            QMessageBox.warning(
                self, "Aviso",
                "Não é possível definir um condómino inactivo como administrador."
            )
            return

        if eh_admin_atual(cond.get('ADMIN', 0)):
            QMessageBox.information(
                self, "Administrador",
                f"<b>{nome}</b> já é o administrador em funções."
            )
            return

        reply = QMessageBox.question(
            self,
            "Administrador em funções",
            f"Definir <b>{nome}</b> como administrador em funções?\n\n"
            "O administrador actual passará a cessante.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if not definir_administrador(self.pasta_dados, nome):
                raise RuntimeError("definir_administrador falhou")
            self.carregar_tabela()
            self.status_bar.showMessage(
                f"✅ {nome} é agora o administrador em funções.", 5000
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Erro",
                f"Não foi possível alterar o administrador:\n\n{e}"
            )

    def editar_cc(self, row):
        """Abre o diálogo de edição do Cartão de Cidadão / NIF para a linha."""
        if row < 0 or row >= len(self.model._data):
            return
        cond = self.model._data[row]
        dlg = CCDialog(
            parent=self,
            cc_numero=cond.get("CC_NUMERO", ""),
            cc_validade=cond.get("CC_VALIDADE", ""),
            nif=cond.get("NIF", ""),
            nome=str(cond.get("NOME", "") or "").strip(),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.valores()
            # Capturar valores ANTES de atualizar, para detetar mudanças reais
            valores_anteriores = (
                cond.get("CC_NUMERO", ""),
                cond.get("CC_VALIDADE", ""),
                cond.get("NIF", ""),
            )
            novos_valores = (
                vals["CC_NUMERO"],
                vals["CC_VALIDADE"],
                vals["NIF"],
            )
            # Agora sim, atualizar o dicionário
            cond["CC_NUMERO"] = vals["CC_NUMERO"]
            cond["CC_VALIDADE"] = vals["CC_VALIDADE"]
            cond["NIF"] = vals["NIF"]
            # Só marcar como alterado se algo realmente mudou
            if novos_valores != valores_anteriores:
                self.model._dirty_row_ids.add(id(cond))
            # Refrescar a célula CC e o fundo da linha.
            idx = self.model.index(row, 9)
            inicio = self.model.index(row, 0)
            fim = self.model.index(row, self.model.columnCount() - 1)
            self.model.dataChanged.emit(inicio, fim, [Qt.ItemDataRole.BackgroundRole])
            self.model.dataChanged.emit(idx, idx)
            self.status_bar.showMessage(
                f"CC/NIF actualizados para {cond.get('NOME', '')} — grave as alterações.",
                5000,
            )
    
    def mostrar_foto(self, foto_path, global_pos) -> bool:
        """Mostra a foto junto ao cursor. Devolve True se ficou visível."""
        try:
            pixmap = QPixmap(foto_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    150, 200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.foto_label.setPixmap(scaled)
                self.foto_label.adjustSize()
                self.foto_label.move(global_pos.x() + 20, global_pos.y() - 125)
                self.foto_label.show()
                self.foto_label.raise_()
                return True
        except Exception:
            pass
        self.foto_label.hide()
        return False
    
    def mostrar_tooltip(self, text, global_pos, below_widget=None):
        """Mostra tooltip instantâneo.

        Se `below_widget` estiver visível, posiciona a mensagem imediatamente
        por baixo desse widget (ex.: por baixo da foto do condómino).
        """
        try:
            self.tooltip_label.setText(text)
            self.tooltip_label.adjustSize()
            if below_widget is not None and below_widget.isVisible():
                x = below_widget.x()
                y = below_widget.y() + below_widget.height() + 6
                self.tooltip_label.move(x, y)
            else:
                self.tooltip_label.move(global_pos.x() + 15, global_pos.y() + 10)
            self.tooltip_label.show()
            self.tooltip_label.raise_()
        except Exception:
            self.tooltip_label.hide()
    
    def mostrar_pagamentos_quotas(self, row):
        """Obtém dados do condómino e exibe dialog de pagamentos"""
        
        # Obter dados do condómino
        condomino = self.model._data[row]
        nome = str(condomino.get('NOME', '')).strip()
        andar = str(condomino.get('ANDAR', '')).strip()
        fracao = str(condomino.get('FRACAO', '')).strip()
        telemovel = str(condomino.get('TELEMOVEL', '')).strip()
        quota_normal = clean_numeric(condomino.get('QUOTAN', 0))
        quota_extra = clean_numeric(condomino.get('QUOTAE', 0))
        
        # Validar dados
        if not andar:
            QMessageBox.warning(self, "Aviso", "Condómino sem ANDAR definido")
            return

        # Controlo: deteta se este ANDAR está (ainda) partilhado por mais de
        # um condómino ativo (ex. transição de venda a meio do ano); reutiliza
        # a lista já carregada em memória, sem nova leitura à BD
        outros_na_fracao = condominos_ativos_na_fracao(
            self.model._data, andar, excluir_nome=nome
        )
        
        # Mostrar mensagem de processamento
        self.status_bar.showMessage("⏳ Processando pagamentos...")
        QApplication.processEvents()
        
        # Processar pagamentos
        try:
            dados = obter_pagamentos_condomino(andar, self.pasta_dados)
            
            # Exibir dialog
            dialog = PagamentosQuotasDialog(
                nome=nome,
                andar=andar,
                fracao=fracao,
                quota_normal=quota_normal,
                quota_extra=quota_extra,
                dados_pagamentos=dados,
                pasta_dados=self.pasta_dados,
                telemovel=telemovel,
                outros_na_fracao=outros_na_fracao,
                parent=self
            )
            
            self.status_bar.showMessage("✅ Pagamentos carregados")
            dialog.exec()
            
            # Recarregar grid
            self.carregar_tabela()
            self.status_bar.showMessage("")
            
        except Exception as e:
            self.status_bar.showMessage("")
            QMessageBox.critical(
                self, 
                "Erro", 
                f"Erro ao processar pagamentos:\n\n{str(e)}\n\n"
                f"Verifique se os ficheiros Bancos e Caixa existem e se "
                f"as quotas estão configuradas na aba Regras."
            )


# ====================================================================
# MAIN
# ====================================================================
if __name__ == "__main__":
    from Commons import get_app_stylesheet
    app = QApplication(sys.argv)
    
    app.setEffectEnabled(Qt.UIEffect.UI_FadeTooltip, True)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())
    
    widget = CondominosWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(1200, 700)
    widget.setWindowTitle("Gestão de Condóminos")
    widget.show()
    sys.exit(app.exec())