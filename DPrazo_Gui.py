"""
DPrazo_Gui.py - Widget de gestão de movimentos de DPrazo

Funcionalidades:
- Adicionar registos manualmente
- Editar registos existentes
- Apagar registos selecionados
- Recalcular saldos automaticamente
- Guardar alterações
- ComboBox filtrada por tipo

SUBSTITUI: DPrazo.py (antigo) que estava com problemas
"""

import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QMessageBox, QComboBox, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize, QTimer
from PyQt6.QtGui import QColor, QBrush, QIcon

# Importa código compartilhado
from Commons import (
    BASE_DIR, ICONS_DIR, PASTA_CORRENTE, PASTA_HISTORICO,
    ContaComboBoxDelegate, carregar_contas, carregar_db,
    clean_numeric, format_currency, salvar_db, existe_dados
)


# ====================================================================
# DELEGATE PARA COMBOBOX DO TIPO (RECEITA/DESPESA)
# ====================================================================

class TipoComboBoxDelegate(QStyledItemDelegate):
    """Delegate que mostra ComboBox com RECEITA/DESPESA na coluna Tipo"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tipos = ["RECEITA", "DESPESA"]
    
    def createEditor(self, parent, option, index):
        """Cria combobox ao editar"""
        combo = QComboBox(parent)
        combo.addItems(self.tipos)
        combo.setEditable(False)
        # ✅ Abre popup após widget estar posicionado corretamente
        QTimer.singleShot(0, combo.showPopup)
        return combo
    
    def setEditorData(self, editor, index):
        """Define valor atual no combobox"""
        value = index.data(Qt.ItemDataRole.DisplayRole)
        if value in self.tipos:
            editor.setCurrentText(value)
        else:
            editor.setCurrentIndex(0)
    
    def setModelData(self, editor, model, index):
        """Atualiza modelo com valor selecionado"""
        value = editor.currentText()
        model.setData(index, value, Qt.ItemDataRole.EditRole)
    
    def updateEditorGeometry(self, editor, option, index):
        """Define geometria do editor"""
        editor.setGeometry(option.rect)


# ====================================================================
# MODELO DA TABELA DPrazo
# ====================================================================

class DPrazoTableModel(QAbstractTableModel):
    """Modelo de dados para tabela de movimentos de Depósitos a Prazo"""
    
    HEADERS = ["Data", "Tipo", "Conta", "Descrição", "Valor", "Saldo", "Observação"]

    def __init__(self):
        super().__init__()
        self._data = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        
        value = list(self._data[index.row()].values())[index.column()]
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:  # Data
                return value.strftime("%d-%m-%Y")
            if index.column() in (4, 5):  # Valor, Saldo
                return format_currency(value)
            return str(value)
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() in (4, 5):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        
        elif role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            tipo = list(self._data[index.row()].values())[1]
            if tipo == "RECEITA":
                return QBrush(QColor("#2e7d32"))
            elif tipo == "DESPESA":
                return QBrush(QColor("#c62828"))
        
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if 0 <= section < len(self.HEADERS):
                    return self.HEADERS[section]
            elif orientation == Qt.Orientation.Vertical:
                return str(section + 1)  # Números das linhas (1, 2, 3, ...)
        return QVariant()

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.isValid():
            col = index.column()
            row_dict = self._data[index.row()]
            keys = list(row_dict.keys())
            key = keys[col]
            
            if col == 0:  # Data
                try:
                    value = datetime.strptime(value, "%d-%m-%Y")
                except:
                    return False
            elif col in (4, 5):  # Valor, Saldo
                try:
                    # Remove €, espaços e vírgulas (separadores de milhares no formato americano)
                    value = float(str(value).replace("€", "").replace(" ", "").replace(",", ""))
                except:
                    return False
            
            row_dict[key] = value
            self.dataChanged.emit(index, index)
            return True
        return False

    def insertRows(self, position, rows, parent=QModelIndex()):
        """Insere novas linhas vazias"""
        self.beginInsertRows(parent, position, position + rows - 1)
        
        for i in range(rows):
            new_row = {
                'DATA': datetime.today(),
                'TIPO': '',
                'CONTA': '',
                'DESCRICAO': '',
                'VALOR': 0.0,
                'SALDO': 0.0,
                'OBSERVACAO': ''
            }
            self._data.insert(position, new_row)
        
        self.endInsertRows()
        return True

    def removeRows(self, position, rows, parent=QModelIndex()):
        """Remove linhas selecionadas"""
        self.beginRemoveRows(parent, position, position + rows - 1)
        del self._data[position:position + rows]
        self.endRemoveRows()
        return True

    def recalculate_saldos(self):
        """
        Recalcula todos os saldos baseado nos valores.
        
        Lógica:
        1. Ordena por data
        2. Começa com saldo da primeira linha (SALDO ANTERIOR)
        3. Para cada linha subsequente:
           - Se RECEITA: saldo += valor
           - Se DESPESA: saldo -= valor
        """
        if not self._data:
            return
        
        # Ordena por data
        self._data.sort(key=lambda x: x['DATA'])
        
        # Recalcula saldos
        saldo = 0.0
        
        for i, row in enumerate(self._data):
            if i == 0:
                # Primeira linha define o saldo inicial
                saldo = row['SALDO']
            else:
                # Calcula incremento baseado no tipo
                valor = row['VALOR']
                tipo = row['TIPO'].strip().upper()
                
                if tipo == 'RECEITA':
                    saldo += valor
                elif tipo == 'DESPESA':
                    saldo += valor #⚠️ O incremento é sempre positivo porque as despesas são registadas com valores negativos
                
                row['SALDO'] = round(saldo, 2)
        
        # Atualiza view
        self.layoutChanged.emit()

    def load_from_db(self, caminho):
        """Carrega dados de DPrazo ou do SQLite compatível do diretório."""
        self.beginResetModel()
        self._data = []
        path = Path(caminho)
        
        if existe_dados(path):
            try:
                rows, _ = carregar_db(path)
                for rec in rows:
                    raw_data = rec.get('DATA')
                    if isinstance(raw_data, str):
                        try:
                            data = datetime.fromisoformat(raw_data[:10])
                        except Exception:
                            data = datetime(1900, 1, 1)
                    elif raw_data is None:
                        data = datetime(1900, 1, 1)
                    else:
                        data = raw_data

                    self._data.append({
                        'DATA': data,
                        'TIPO': str(rec.get('TIPO', '')).strip(),
                        'CONTA': str(rec.get('CONTA', '')).strip(),
                        'DESCRICAO': str(rec.get('DESCRICAO', '')).strip(),
                        'VALOR': float(rec.get('VALOR') or 0.0),
                        'SALDO': float(rec.get('SALDO') or 0.0),
                        'OBSERVACAO': str(rec.get('OBSERVACAO', '')).strip()
                    })
            except Exception as exc:
                print(f"❌ Erro ao carregar {path.name}: {exc}")
        
        self.endResetModel()
    
    def save_to_db(self, caminho):
        """Salva alterações usando o bridge compatível comum do projeto."""
        try:
            rows = []
            for row_data in self._data:
                data_obj = row_data['DATA']
                if isinstance(data_obj, datetime):
                    data_value = data_obj.date()
                elif hasattr(data_obj, 'date'):
                    data_value = data_obj.date()
                else:
                    data_value = datetime(1900, 1, 1).date()

                rows.append({
                    'DATA': data_value,
                    'TIPO': str(row_data['TIPO'])[:10],
                    'CONTA': str(row_data['CONTA'])[:30],
                    'DESCRICAO': str(row_data['DESCRICAO'])[:30],
                    'VALOR': float(row_data['VALOR']),
                    'SALDO': float(row_data['SALDO']),
                    'OBSERVACAO': str(row_data['OBSERVACAO'])[:30]
                })

            df = pd.DataFrame(rows, dtype=object)
            field_specs = 'DATA D; TIPO C(10); CONTA C(30); DESCRICAO C(30); VALOR N(10,2); SALDO N(10,2); OBSERVACAO C(30)'
            return salvar_db(df, caminho, field_specs)

        except Exception as e:
            print(f"❌ Erro ao guardar DPrazo: {e}")
            return False


# ====================================================================
# WIDGET DE DPrazo
# ====================================================================

class DPrazoWidget(QWidget):
    """Widget principal para gestão de movimentos de Depósitos a Prazo"""
    
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.caminho_dprazo_db = None
        self.conta_delegate = ContaComboBoxDelegate()
        self.tipo_delegate = TipoComboBoxDelegate()  # ✅ NOVO
        
        self.init_ui()
    
    def init_ui(self):
        """Inicializa interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Barra de botões
        btn_bar = QHBoxLayout()
        
        # Botão Adicionar
        btn_adicionar = QPushButton("→ Adicionar Registo")
        btn_adicionar.setFixedHeight(42)
        icon_path = ICONS_DIR / "add-icon.png"
        if icon_path.exists():
            btn_adicionar.setIcon(QIcon(str(icon_path)))
            btn_adicionar.setIconSize(QSize(30, 30))
        btn_adicionar.clicked.connect(self.adicionar_registo)
        btn_bar.addWidget(btn_adicionar)
        
        btn_bar.addSpacing(10)
        
        # Botão Apagar
        btn_apagar = QPushButton("→ Apagar Registo")
        btn_apagar.setFixedHeight(45)
        icon_path = ICONS_DIR / "delete-icon.png"
        if icon_path.exists():
            btn_apagar.setIcon(QIcon(str(icon_path)))
            btn_apagar.setIconSize(QSize(30, 30))
        btn_apagar.clicked.connect(self.apagar_registo)
        btn_bar.addWidget(btn_apagar)
        
        btn_bar.addSpacing(10)
        
        # Botão Recalcular
        btn_recalcular = QPushButton("→ Recalcular Saldos")
        btn_recalcular.setFixedHeight(45)
        icon_path = ICONS_DIR / "refresh-icon.png"
        if icon_path.exists():
            btn_recalcular.setIcon(QIcon(str(icon_path)))
            btn_recalcular.setIconSize(QSize(30, 30))
        btn_recalcular.clicked.connect(self.recalcular_saldos)
        btn_bar.addWidget(btn_recalcular)
        
        btn_bar.addSpacing(10)
        
        # Botão Guardar
        btn_guardar = QPushButton("→ Guardar Alterações")
        btn_guardar.setFixedHeight(45)
        icon_path = ICONS_DIR / "save-icon.png"
        if icon_path.exists():
            btn_guardar.setIcon(QIcon(str(icon_path)))
            btn_guardar.setIconSize(QSize(30, 30))
        btn_guardar.clicked.connect(self.guardar_alteracoes)
        btn_bar.addWidget(btn_guardar)
        
        layout.addLayout(btn_bar)
        
        # Tabela
        self.table_view = QTableView()
        self.model = DPrazoTableModel()
        self.table_view.setModel(self.model)
        
        # Aplicar delegates
        self.table_view.setItemDelegateForColumn(1, self.tipo_delegate)   # ✅ NOVO: Tipo
        self.table_view.setItemDelegateForColumn(2, self.conta_delegate)  # Conta
        
        # Configurar colunas
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Descrição estica
        self.table_view.setColumnWidth(0, 100)  # Data
        self.table_view.setColumnWidth(1, 80)   # Tipo
        self.table_view.setColumnWidth(2, 180)  # Conta
        self.table_view.setColumnWidth(4, 120)  # Valor
        self.table_view.setColumnWidth(5, 120)  # Saldo
        self.table_view.setColumnWidth(6, 180)  # Observação
        
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | 
            QTableView.EditTrigger.SelectedClicked |  # ✅ NOVO: Um clique em célula já selecionada
            QTableView.EditTrigger.AnyKeyPressed
        )

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
        
        layout.addWidget(self.table_view)
    
    def set_pasta_dados(self, pasta_dados):
        """Define pasta de dados e carrega contas + tabela"""
        self.pasta_dados = pasta_dados
        self.caminho_dprazo_db = BASE_DIR / pasta_dados / "DPrazo"
        
        # Carrega contas
        receitas, despesas, todas = carregar_contas(pasta_dados)
        
        if not todas:
            QMessageBox.warning(
                self,
                "Aviso",
                "Nenhuma conta carregada!"
            )
        
        self.conta_delegate.set_contas(receitas, despesas, todas)
        
        # Carrega tabela
        self.carregar_tabela()
    
    def carregar_tabela(self):
        """Carrega dados de depósito a prazo"""
        if self.caminho_dprazo_db:
            self.model.load_from_db(str(self.caminho_dprazo_db))
  
    def get_saldo_final(self):
        # Retorna saldo final (ultima linha)
        try:
            if self.model.rowCount() > 0:
                ultima_linha = self.model._data[-1]
                return float(ultima_linha.get('SALDO', 0.0))
            return 0.0
        except Exception as e:
            print(f"Erro ao obter saldo final: {e}")
            return 0.0
   
    def adicionar_registo(self):
        """Adiciona novo registo vazio no final"""
        row = self.model.rowCount()
        self.model.insertRows(row, 1)
        self.table_view.scrollToBottom()
        
        # Seleciona a nova linha para edição imediata
        index = self.model.index(row, 0)
        self.table_view.setCurrentIndex(index)
        self.table_view.edit(index)
    
    def apagar_registo(self):
        """Apaga registo selecionado"""
        indexes = self.table_view.selectionModel().selectedRows()
        
        if not indexes:
            QMessageBox.warning(self, "Aviso", "Selecione uma linha para apagar.")
            return
        
        row = indexes[0].row()
        
        # Confirmação
        reply = QMessageBox.question(
            self,
            "Confirmar",
            "Tem certeza que deseja apagar este registo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.model.removeRows(row, 1)
    
    def recalcular_saldos(self):
        """Recalcula todos os saldos"""
        self.model.recalculate_saldos()
        QMessageBox.information(self, "Sucesso", "Saldos recalculados!")
    
    def guardar_alteracoes(self):
        """Guarda alterações"""
        if not self.caminho_dprazo_db:
            QMessageBox.warning(self, "Aviso", "Nenhum ficheiro carregado.")
            return
        
        # Recalcula saldos antes de guardar
        self.model.recalculate_saldos()
        
        if self.model.save_to_db(str(self.caminho_dprazo_db)):
            QMessageBox.information(self, "Sucesso", "Alterações guardadas com sucesso!")
            self.carregar_tabela()
        else:
            QMessageBox.critical(self, "Erro", "Erro ao guardar alterações.")


# ====================================================================
# TESTE STANDALONE
# ====================================================================

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())
    
    widget = DPrazoWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(900, 600)
    widget.show()
    
    sys.exit(app.exec())