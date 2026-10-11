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
- ComboBox para campo ANDAR
- Checkbox para campo CHECK (verde quando ativa, vermelha quando inativa)
- Dialogue de pagamentos com combobox de seleção administrador
- Icon de administrador atualiza em tempo real na combobox do dialogue de pagamentos
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableView, QHeaderView, QMessageBox, QStatusBar,
    QLabel, QApplication, QItemDelegate, QComboBox, QStyledItemDelegate, QMenu, QDialog, QTableWidget,
    QTableWidgetItem, QFrame, QGridLayout, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize, QEvent, QPoint, QPropertyAnimation, QSequentialAnimationGroup, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QIcon, QPixmap, QCursor, QPen

from Commons import (
    BASE_DIR, ICONS_DIR, PASTA_CORRENTE, PASTA_HISTORICO,
    FOTOS_DIR, clean_numeric, format_currency, carregar_db, salvar_db, existe_dados
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
    atualizar_quotas_configs,
    obter_pagamentos_condomino,
    criar_novo_condomino,
    obter_lista_administradores,
    definir_administrador,
    MORADA_FIXA,
    CPOSTAL_FIXO,
    CIDADE_FIXA
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
            # Linha não selecionada - usar cor neutra
            painter.fillRect(option.rect, option.palette.base())
        
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
    Delegate que mostra nome com ícone de admin ao lado se ADMIN = .T.
    
    NOTA: O ícone é apenas VISUAL (somente leitura).
    Para alterar o administrador, use a ComboBox no dialog de pagamentos.
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
            
            # Verificar se é administrador (buscar diretamente dos dados)
            is_admin = False
            try:
                if row < len(model._data):
                    admin_value = model._data[row].get('ADMIN', '.F.')
                    is_admin = admin_value in (True, 'T', '.T.', 't')
            except (IndexError, AttributeError, KeyError):
                is_admin = False
            
            # Preencher fundo da célula
            from PyQt6.QtWidgets import QStyle
            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            else:
                painter.fillRect(option.rect, option.palette.base())
            
            # Obter o texto do nome
            nome = str(model.data(index, Qt.ItemDataRole.DisplayRole))
            
            # Configurar a cor do texto (azul para nomes)
            if option.state & QStyle.StateFlag.State_Selected:
                painter.setPen(option.palette.highlightedText().color())
            else:
                painter.setPen(QColor("#1976d2"))
            
            # Calcular espaço disponível para o texto
            text_rect = option.rect.adjusted(5, 0, -40 if (is_admin and self.admin_pixmap) else -5, 0)
            
            # Desenhar o texto do nome
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
# DELEGATE PARA COMBOBOX DO ANDAR
# ====================================================================
class AndarComboDelegate(QStyledItemDelegate):
    """Delegate que mostra ComboBox para o campo ANDAR"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = ["R/c Esq.", "R/c Dto.", "1º Esq.", "1º Dto.", "2º Esq.", "2º Dto."]
    
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self.items)
        combo.setEditable(False)
        return combo
    
    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        if value in self.items:
            editor.setCurrentText(value)
        else:
            editor.setCurrentIndex(0)
    
    def setModelData(self, editor, model, index):
        value = editor.currentText()
        model.setData(index, value, Qt.ItemDataRole.EditRole)


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
                 dados_pagamentos, pasta_dados=None, parent=None):
        super().__init__(parent)
        
        self.nome = nome
        self.andar = andar
        self.fracao = fracao
        self.quota_normal = quota_normal
        self.quota_extra = quota_extra
        self.dados = dados_pagamentos
        self.pasta_dados = pasta_dados
        
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
        # LAYOUT HORIZONTAL: Administrador + Botões
        # ====================================================================
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        
        # ESQUERDA: Administrador
        lbl_admin = QLabel("Administrador:")
        lbl_admin.setStyleSheet("font-size: 12px; font-weight: bold;")
        bottom_layout.addWidget(lbl_admin)
        
        self.combo_administrador = QComboBox()
        self.combo_administrador.setStyleSheet("""
            QComboBox {
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 11px;
                min-width: 250px;
            }
        """)
        self.combo_administrador.setToolTip("Clique para alterar o administrador")
        self.carregar_administradores()
        bottom_layout.addWidget(self.combo_administrador)
        
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
        
        # Calcular esperado e saldo
        esperado_anual = (self.quota_normal * 12) + (self.quota_extra * 12)
        saldo = self.dados['total_geral'] - esperado_anual
        
        lbl_esperado_desc = QLabel("<b>Esperado Anual:</b>")
        lbl_esperado_desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(lbl_esperado_desc, 2, 2)
        
        lbl_esperado = QLabel(format_currency(esperado_anual))
        lbl_esperado.setStyleSheet("font-size: 12px; font-weight: bold; color: #6c757d;")
        lbl_esperado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_esperado, 2, 3)
        
        # Saldo
        lbl_saldo_desc = QLabel("<b>Saldo:</b>")
        lbl_saldo_desc.setStyleSheet("font-size: 13px;")
        layout.addWidget(lbl_saldo_desc, 3, 0)
        
        lbl_saldo = QLabel(format_currency(saldo))
        if saldo < -0.01:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #dc3545;")  # Vermelho
            status_msg = "Em Dívida"
            status_color = "#dc3545"
        elif saldo > 0.01:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #28a745;")  # Verde
            status_msg = "Crédito"
            status_color = "#28a745"
        else:
            lbl_saldo.setStyleSheet("font-size: 13px; font-weight: bold; color: #28a745;")  # Verde (Em Dia)
            status_msg = "Em Dia"
            status_color = "#28a745"
        lbl_saldo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(lbl_saldo, 3, 1)
        
        lbl_status = QLabel(f"<b>{status_msg}</b>")
        lbl_status.setStyleSheet(f"font-size: 12px; color: {status_color};")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)  # CENTRALIZAR
        layout.addWidget(lbl_status, 3, 2, 1, 2)
        
        # Se estiver em dívida, criar animação de piscar
        if saldo < -0.01:
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
    
    def carregar_administradores(self):
        """Carrega lista de condóminos e seleciona o que tem ADMIN = .T."""
        if not self.pasta_dados:
            self.combo_administrador.addItem("Administrador Padrão")
            return

        try:
            condominos_path = BASE_DIR / self.pasta_dados / "Condominos"

            if not existe_dados(condominos_path):
                self.combo_administrador.addItem("Administrador Padrão")
                return

            rows, _ = carregar_db(condominos_path)
            nomes = []
            admin_ativo = None

            for row in rows:
                nome = str(row.get('NOME', '')).strip()
                if not nome:
                    continue
                nomes.append(nome)

                # Normalização do boolean de ADMIN para formato legacy
                flag_admin = row.get('ADMIN', False)
                if isinstance(flag_admin, str):
                    flag_admin = flag_admin.strip().upper() in ('T', '.T.', 'TRUE', '1')
                elif isinstance(flag_admin, int):
                    flag_admin = bool(flag_admin)
                elif isinstance(flag_admin, float):
                    flag_admin = bool(flag_admin)
                if flag_admin:
                    admin_ativo = nome

            if nomes:
                nomes.sort()
                for nome in nomes:
                    if nome == admin_ativo:
                        self.combo_administrador.addItem(f"👑 {nome}")
                    else:
                        self.combo_administrador.addItem(nome)

                if admin_ativo:
                    for i in range(self.combo_administrador.count()):
                        item_text = self.combo_administrador.itemText(i)
                        nome_limpo = item_text.replace("👑 ", "")
                        if nome_limpo == admin_ativo:
                            self.combo_administrador.setCurrentIndex(i)
                            break

                self.combo_administrador.currentTextChanged.connect(self.ao_mudar_administrador)
            else:
                self.combo_administrador.addItem("Administrador Padrão")

        except Exception as e:
            print(f"Erro ao carregar administradores: {e}")
            self.combo_administrador.addItem("Administrador Padrão")
    
    def ao_mudar_administrador(self, novo_admin):
        """Atualiza campo ADMIN quando mudar a seleção"""
        if not novo_admin or not self.pasta_dados:
            return

        novo_admin = novo_admin.replace("👑 ", "")

        try:
            condominos_path = BASE_DIR / self.pasta_dados / "Condominos"
            if not existe_dados(condominos_path):
                return

            rows, _ = carregar_db(condominos_path)
            df = pd.DataFrame(rows, dtype=object)
            if df.empty:
                return

            # Primeiro: desativar ADMIN em todos os condóminos
            for idx, row in df.iterrows():
                df.at[idx, 'ADMIN'] = False

            # Segundo: ativar ADMIN apenas no condómino selecionado
            for idx, row in df.iterrows():
                nome = str(row.get('NOME', '')).strip()
                if nome == novo_admin:
                    df.at[idx, 'ADMIN'] = True
                    break

            field_specs = 'NOME C(40); MORADA C(40); CPOSTAL C(8); CIDADE C(10); TELEMOVEL C(11); EMAIL C(40); FRACAO C(1); ANDAR C(10); PERMILAGEM N(5,3); QUOTAN N(10,2); QUOTAE N(10,2); FOTO C(30); CHECK L; ADMIN L'
            if not salvar_db(df, str(condominos_path), field_specs):
                raise RuntimeError('salvar_db falhou para Condominos')

            self.atualizar_coroa_combobox(novo_admin)
            if self.parent() and hasattr(self.parent(), 'carregar_tabela'):
                self.parent().carregar_tabela()
                print(f"✓ Grid atualizado em tempo real - Novo admin: {novo_admin}")

        except Exception as e:
            print(f"Erro ao atualizar administrador: {e}")
    
    def atualizar_coroa_combobox(self, novo_admin):
        """Atualiza a combobox para mover a coroa para o novo administrador"""
        # Desconectar temporariamente o evento para evitar loops
        try:
            self.combo_administrador.currentTextChanged.disconnect(self.ao_mudar_administrador)
        except:
            pass
        
        # Guardar índice atual
        indice_atual = self.combo_administrador.currentIndex()
        
        # Atualizar todos os itens da combobox
        for i in range(self.combo_administrador.count()):
            texto_item = self.combo_administrador.itemText(i)
            nome_limpo = texto_item.replace("👑 ", "")
            
            # Adicionar coroa apenas ao novo admin
            if nome_limpo == novo_admin:
                self.combo_administrador.setItemText(i, f"👑 {nome_limpo}")
            else:
                # Remover coroa dos outros
                self.combo_administrador.setItemText(i, nome_limpo)
        
        # Manter seleção atual (mas agora com coroa atualizada)
        self.combo_administrador.setCurrentIndex(indice_atual)
        
        # Reconectar evento
        self.combo_administrador.currentTextChanged.connect(self.ao_mudar_administrador)
    
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
        
        # Obter administrador selecionado
        administrador = self.combo_administrador.currentText().replace("👑 ", "")
        
        if not administrador or administrador == "Administrador Padrão":
            QMessageBox.warning(
                self,
                "Aviso",
                "Por favor, selecione um administrador válido."
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
            # Nº de meses = total pago ÷ valor da quota mensal
            # (corrige o caso em que o condómino paga vários meses de uma só vez)
            v_normal = self.dados.get('total_normal', 0.0)
            v_extra  = self.dados.get('total_extra', 0.0)
            meses_n  = round(v_normal / self.quota_normal) if self.quota_normal > 0 else 0
            meses_e  = round(v_extra  / self.quota_extra)  if self.quota_extra  > 0 else 0

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
# MODELO DE TABELA
# ====================================================================
class CondominosTableModel(QAbstractTableModel):
    """Modelo de tabela para condóminos"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._fields = ['NOME', 'TELEMOVEL', 'CHECK', 'EMAIL', 'FRACAO', 'ANDAR', 
                        'PERMILAGEM', 'QUOTAN', 'QUOTAE', 'FOTO']
        self._headers = ['Nome', 'Telemóvel', '✓', 'Email', 'Fração', 'Andar', 
                         'Permilagem', 'Quota N', 'Quota E', 'Foto']
    
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
        
        # DisplayRole (o que aparece na tela)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 2:  # CHECK
                return ''  # Checkbox delegate cuida da visualização
            elif col in (7, 8):  # Quotas
                try:
                    return f"{float(value):.2f}"
                except:
                    return "0.00"
            elif col == 6:  # Permilagem
                try:
                    return f"{float(value):.3f}"
                except:
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
            elif col == 2:  # CHECK
                return Qt.AlignmentFlag.AlignCenter
            else:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        
        # ForegroundRole (cor do texto)
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:  # NOME
                return QBrush(QColor("#1976d2"))
        
        return QVariant()
    
    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        # Coluna FOTO (9) é somente leitura
        if index.column() == 9:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
    
    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        
        row = index.row()
        if row >= len(self._data):
            return False
        
        key = self._fields[index.column()]
        row_dict = self._data[row]
        
        # Validações específicas
        if key == 'TELEMOVEL':
            value = str(value).strip()
            if value and not value.isdigit():
                return False
            if len(value) > 11:
                return False
        
        elif key == 'EMAIL':
            value = str(value).strip()
            if value and '@' not in value:
                return False
        
        elif key == 'FRACAO':
            value = str(value).strip().upper()
            if value and value not in ('A', 'B', 'C', 'D', 'E', 'F'):
                return False
        
        elif key == 'PERMILAGEM':
            try:
                if value:
                    value = float(str(value).replace(',', '.'))
                    if not 0 <= value <= 999.999:
                        return False
            except:
                return False
        
        elif index.column() in (7, 8):  # Quotas
            try:
                if value:
                    s = str(value).replace("€", "").replace(" ", "").strip()
                    if "," in s and "." in s:
                        # Ambos presentes: o último é o separador decimal
                        # ex: "1.234,56" → remove os pontos, troca vírgula por ponto
                        if s.rfind(",") > s.rfind("."):
                            s = s.replace(".", "").replace(",", ".")
                        else:
                            s = s.replace(",", "")
                    else:
                        # Só vírgula  →  é o separador decimal  ("24,5" → "24.5")
                        s = s.replace(",", ".")
                    value = float(s)
            except:
                return False
        
        row_dict[key] = value
        self.dataChanged.emit(index, index)
        
        # Se alterou CHECK, atualizar também EMAIL para mudar a cor
        if index.column() == 2:  # Coluna CHECK
            email_index = self.index(index.row(), 3)  # Coluna EMAIL
            self.dataChanged.emit(email_index, email_index)
        
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
        self.endResetModel()
    
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
                font-weight: bold;
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

        btn_bar.addStretch()
        layout.addLayout(btn_bar)
        
        # Tabela
        self.table_view = QTableView()
        self.model = CondominosTableModel()
        self.table_view.setModel(self.model)
        
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.setColumnWidth(0, 220)  # Nome
        self.table_view.setColumnWidth(1, 100)  # Telemóvel
        self.table_view.setColumnWidth(2, 30)   # CHECK
        self.table_view.setColumnWidth(3, 200)  # Email
        self.table_view.setColumnWidth(4, 70)   # Fração
        self.table_view.setColumnWidth(5, 80)   # Andar
        self.table_view.setColumnWidth(6, 100)  # Permilagem
        self.table_view.setColumnWidth(7, 100)  # Quota N
        self.table_view.setColumnWidth(8, 100)  # Quota E
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)  # Foto
        
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setStyleSheet("""
            QTableView { 
                gridline-color: #C0C0C0; 
                border: 1px solid #C0C0C0; 
            }
            QTableView::item { 
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
        
        andar_delegate = AndarComboDelegate(self.table_view)
        self.table_view.setItemDelegateForColumn(5, andar_delegate)
        
        # Menu de contexto
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_context_menu)
        
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
        self.pasta_dados = pasta_dados
        self.caminho_condominos_db = BASE_DIR / pasta_dados / "Condominos"
        self.carregar_tabela()
    
    def carregar_tabela(self):
        if self.caminho_condominos_db:
            self.model.load_from_db(str(self.caminho_condominos_db))
            self.status_bar.showMessage(f"✅ {self.model.rowCount()} Condóminos carregados")
    
    def adicionar_registo(self):
        row = self.model.rowCount()
        self.model.insertRows(row, 1)
        self.table_view.scrollToBottom()
        index = self.model.index(row, 0)
        self.table_view.setCurrentIndex(index)
        self.table_view.edit(index)
    
    def apagar_registo(self):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.warning(self, "Aviso", "Selecione uma linha para apagar.")
            return
        row = indexes[0].row()
        reply = QMessageBox.question(
            self, "Confirmar", "Tem certeza que deseja apagar este condómino?",
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
            # Validação
            validar_condominos(self.model._data)
            
            # Guardar
            if not self.model.save_to_db(str(self.caminho_condominos_db)):
                raise Exception("Erro ao guardar alterações.")
            
            # Sincronizar quotas normal/extra na tabela regras (sem INSERT)
            atualizar_quotas_configs(self.pasta_dados, self.model._data)

            # Refresh visual da aba Regras (se existir no Main)
            self.quotas_atualizadas.emit()
            self._tentar_refresh_regras()

            QMessageBox.information(
                self, "Sucesso",
                "Alterações guardadas.\n"
                "Quotas (normal/extra) sincronizadas na tabela regras."
            )
            self.carregar_tabela()
            self.status_bar.showMessage("✅ Guardado — quotas sincronizadas em regras.")
        except ValueError as ve:
            QMessageBox.warning(self, "Validação Falhou", str(ve))
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
            self,
            "Confirmar Impressão em Lote",
            "Deseja gerar os recibos anuais para TODOS os condóminos ativos?\n\n"
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
                    
                    # Coluna 0 (NOME) - Mostrar foto
                    if col == 0:
                        foto_nome = self.model._data[row].get('FOTO', '')
                        if foto_nome:
                            foto_path = FOTOS_DIR / foto_nome
                            if foto_path.exists():
                                self.mostrar_foto(str(foto_path), event.globalPosition().toPoint())
                                self.tooltip_label.hide()
                            else:
                                self.foto_label.hide()
                                self.tooltip_label.hide()
                        else:
                            self.foto_label.hide()
                            self.tooltip_label.hide()
                    
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
                    
                    # Coluna 5 (ANDAR) - Tooltip para pagamentos
                    elif col == 5:
                        self.foto_label.hide()
                        andar = str(self.model._data[row].get('ANDAR', '')).strip()
                        if andar:
                            tooltip_text = "💰 Clique com o botão direito para\n    ver pagamentos de quotas deste\n    condómino"
                        else:
                            tooltip_text = "Defina o ANDAR para ver\npagamentos de quotas"
                        self.mostrar_tooltip(tooltip_text, event.globalPosition().toPoint())
                    
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
                
        return super().eventFilter(obj, event)
    
    def mostrar_foto(self, foto_path, global_pos):
        try:
            pixmap = QPixmap(foto_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(150, 200, Qt.AspectRatioMode.KeepAspectRatio, 
                                     Qt.TransformationMode.SmoothTransformation)
                self.foto_label.setPixmap(scaled)
                self.foto_label.adjustSize()
                self.foto_label.move(global_pos.x() + 20, global_pos.y() - 125)
                self.foto_label.show()
                self.foto_label.raise_()
        except:
            self.foto_label.hide()
    
    def mostrar_tooltip(self, text, global_pos):
        """Mostra tooltip instantâneo"""
        try:
            self.tooltip_label.setText(text)
            self.tooltip_label.adjustSize()
            self.tooltip_label.move(global_pos.x() + 15, global_pos.y() + 10)
            self.tooltip_label.show()
            self.tooltip_label.raise_()
        except:
            self.tooltip_label.hide()
    
    def show_context_menu(self, position):
        """Exibe menu ao clicar com botão direito"""
        index = self.table_view.indexAt(position)
        
        if not index.isValid():
            return
        
        # Verificar se clicou na coluna ANDAR (coluna 5)
        if index.column() != 5:
            return
        
        # Verificar se o ANDAR está preenchido
        row = index.row()
        andar = str(self.model._data[row].get('ANDAR', '')).strip()
        
        if not andar:
            return
        
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
            }
            QMenu::item {
                padding: 8px 25px;
            }
            QMenu::item:selected {
                background-color: #1976d2;
                color: white;
            }
        """)
        
        action_ver_quotas = menu.addAction("💰 Ver Pagamentos de Quotas")
        action_ver_quotas.setToolTip("Visualizar histórico de pagamentos deste condómino")
        
        action = menu.exec(self.table_view.viewport().mapToGlobal(position))
        
        if action == action_ver_quotas:
            self.mostrar_pagamentos_quotas(row)
    
    def mostrar_pagamentos_quotas(self, row):
        """Obtém dados do condómino e exibe dialog de pagamentos"""
        
        # Obter dados do condómino
        condomino = self.model._data[row]
        nome = str(condomino.get('NOME', '')).strip()
        andar = str(condomino.get('ANDAR', '')).strip()
        fracao = str(condomino.get('FRACAO', '')).strip()
        quota_normal = clean_numeric(condomino.get('QUOTAN', 0))
        quota_extra = clean_numeric(condomino.get('QUOTAE', 0))
        
        # Validar dados
        if not andar:
            QMessageBox.warning(self, "Aviso", "Condómino sem ANDAR definido")
            return
        
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
                f"Erro ao processar pagamentos:\n\n{str(e)}\n\nVerifique se os ficheiros Bancos, Caixa e Configs existem."
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