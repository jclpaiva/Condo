"""
Configuracoes_Gui.py - Widget de configurações (Configs, Contas, Regras e Analisar CSV)
Funcionalidades:
- Aba "Configurações" com quatro sub-abas: "Analisar CSV", "Configs", "Contas" e "Regras"
- Aba "Regras": CRUD completo sobre regras_classificacao (tabela relacional)
  - Colunas: Prioridade | Nome | Pattern | Classe | Conta | Valor
  - Insert/Delete com teclado (Ins / Del) ou botões
  - Combo para Classe (RECEITA/DESPESA) e Conta (lista de contas ativas)
  - Grava directamente na DB via RegrasRepo (V5)
- Botão "Gravar" no topo (Configs + Contas legacy)
- Estilo idêntico ao widget de Receitas
"""

import pandas as pd
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QTableView, QHeaderView, QMessageBox, QLabel,
    QFileDialog, QTextEdit, QSplitter, QFrame,
    QStyledItemDelegate, QComboBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize
from PyQt6.QtGui import QColor, QBrush, QIcon
from Commons import BASE_DIR, ICONS_DIR, carregar_db, salvar_db, existe_dados
from Database import RegrasRepo, get_connection, db_path

# Importar módulo de análise CSV
from Analisar_csv import analyze_and_update


class ConfigsTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._data = []
        self.headers = ["CATEGORIA", "CHAVE", "VALOR", "TIPO", "DESCRICAO"]

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        row = self._data[index.row()]
        col_name = self.headers[index.column()]
        value = row.get(col_name, "")
        if role == Qt.ItemDataRole.DisplayRole:
            return str(value) if value is not None else ""
        elif role == Qt.ItemDataRole.EditRole:
            # Retorna o valor original para edição
            return str(value) if value is not None else ""
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QBrush(QColor("#F5F5F5"))
            return QVariant()
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.headers[section]
            elif orientation == Qt.Orientation.Vertical:
                return str(section + 1)  # ou section se quiser começar do 0
        return QVariant()

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        
        row = index.row()
        col_name = self.headers[index.column()]
        
        # Converte valor para string
        new_value = str(value) if value is not None else ""
        
        # Pega valor atual
        current_value = str(self._data[row][col_name]) if self._data[row][col_name] is not None else ""
        
        # Se o valor não mudou, não faz nada (importante!)
        if new_value == current_value:
            return False
        
        # Se o novo valor é vazio E o campo tinha conteúdo, cancela a edição
        # (previne apagar acidentalmente com Enter)
        if not new_value.strip() and current_value.strip():
            return False
        
        # Atualiza apenas se houve mudança real
        self._data[row][col_name] = new_value
        self.dataChanged.emit(index, index)
        return True

    def load_from_db(self, caminho):
        self.beginResetModel()
        self._data = []
        caminho = Path(caminho)
        if not existe_dados(caminho):
            self.endResetModel()
            return False
        try:
            rows, _ = carregar_db(caminho)
            for rec in rows:
                row = {}
                for field in self.headers:
                    val = rec.get(field, "") if rec.get(field, "") is not None else ""
                    row[field] = str(val).strip() if val is not None else ""
                self._data.append(row)
            self.endResetModel()
            return True
        except Exception as e:
            print(f"❌ Erro ao carregar {caminho.name}: {e}")
            self.endResetModel()
            return False

    def add_row(self):
        new_row = {h: "" for h in self.headers}
        self.beginInsertRows(QModelIndex(), len(self._data), len(self._data))
        self._data.append(new_row)
        self.endInsertRows()
        return len(self._data) - 1

    def remove_row(self, row_index):
        if 0 <= row_index < len(self._data):
            self.beginRemoveRows(QModelIndex(), row_index, row_index)
            del self._data[row_index]
            self.endRemoveRows()
            return True
        return False

    def save_to_db(self, caminho):
        caminho = Path(caminho)
        try:
            rows = []
            for row in self._data:
                rows.append({
                    'CATEGORIA': str(row.get('CATEGORIA', ''))[:16],
                    'CHAVE': str(row.get('CHAVE', ''))[:35],
                    'VALOR': str(row.get('VALOR', ''))[:20],
                    'TIPO': str(row.get('TIPO', ''))[:7],
                    'DESCRICAO': str(row.get('DESCRICAO', ''))[:30]
                })
            df = pd.DataFrame(rows, dtype=object)
            field_specs = 'CATEGORIA C(16);CHAVE C(35);VALOR C(20);TIPO C(7);DESCRICAO C(30)'
            return salvar_db(df, caminho, field_specs)
        except Exception as e:
            print(f"❌ Erro ao salvar {caminho.name}: {e}")
            import traceback
            traceback.print_exc()
            return False


class ContasTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._data = []
        self.headers = ["TIPO", "CONTA"]

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        row = self._data[index.row()]
        col_name = self.headers[index.column()]
        value = row.get(col_name, "")
        if role == Qt.ItemDataRole.DisplayRole:
            return str(value) if value is not None else ""
        elif role == Qt.ItemDataRole.EditRole:
            # Retorna o valor original para edição
            return str(value) if value is not None else ""
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QBrush(QColor("#F5F5F5"))
            return QVariant()
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.headers[section]
            elif orientation == Qt.Orientation.Vertical:
                return str(section + 1)  # ou section se quiser começar do 0
        return QVariant()

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        
        row = index.row()
        col_name = self.headers[index.column()]
        
        # Converte valor para string
        new_value = str(value) if value is not None else ""
        
        # Pega valor atual
        current_value = str(self._data[row][col_name]) if self._data[row][col_name] is not None else ""
        
        # Se o valor não mudou, não faz nada (importante!)
        if new_value == current_value:
            return False
        
        # Se o novo valor é vazio E o campo tinha conteúdo, cancela a edição
        # (previne apagar acidentalmente com Enter)
        if not new_value.strip() and current_value.strip():
            return False
        
        # Atualiza apenas se houve mudança real
        self._data[row][col_name] = new_value
        self.dataChanged.emit(index, index)
        return True

    def load_from_db(self, caminho):
        self.beginResetModel()
        self._data = []
        caminho = Path(caminho)
        if not existe_dados(caminho):
            self.endResetModel()
            return False
        try:
            rows, _ = carregar_db(caminho)
            for rec in rows:
                row = {}
                for field in self.headers:
                    val = rec.get(field, "") if rec.get(field, "") is not None else ""
                    row[field] = str(val).strip() if val is not None else ""
                self._data.append(row)
            self.endResetModel()
            return True
        except Exception as e:
            print(f"❌ Erro ao carregar {caminho.name}: {e}")
            self.endResetModel()
            return False

    def add_row(self):
        new_row = {h: "" for h in self.headers}
        self.beginInsertRows(QModelIndex(), len(self._data), len(self._data))
        self._data.append(new_row)
        self.endInsertRows()
        return len(self._data) - 1

    def remove_row(self, row_index):
        if 0 <= row_index < len(self._data):
            self.beginRemoveRows(QModelIndex(), row_index, row_index)
            del self._data[row_index]
            self.endRemoveRows()
            return True
        return False

    def save_to_db(self, caminho):
        caminho = Path(caminho)
        try:
            rows = []
            for row in self._data:
                rows.append({
                    'TIPO': str(row.get('TIPO', ''))[:10],
                    'CONTA': str(row.get('CONTA', ''))[:30]
                })
            df = pd.DataFrame(rows, dtype=object)
            field_specs = 'TIPO C(10);CONTA C(30)'
            return salvar_db(df, caminho, field_specs)
        except Exception as e:
            print(f"❌ Erro ao salvar {caminho.name}: {e}")
            import traceback
            traceback.print_exc()
            return False


# ──────────────────────────────────────────────────────────────────────────────
# Model + Delegates para a aba Regras
# ──────────────────────────────────────────────────────────────────────────────

_REGRAS_HEADERS  = ["Prioridade", "Classe", "Conta", "Pattern", "Valor"]
_COL_PRIO   = 0
_COL_CLASSE = 1
_COL_CONTA  = 2
_COL_PAT    = 3
_COL_VALOR  = 4

_CLASSE_OPCOES = ["RECEITA", "DESPESA"]


class RegrasTableModel(QAbstractTableModel):
    """
    Model em memória para regras_classificacao.
    Cada linha é um dict com as chaves dos headers.
    '_id' guarda o id da DB (None = linha nova ainda não gravada).
    """

    def __init__(self):
        super().__init__()
        self._rows: list[dict] = []   # [{"_id", "Prioridade", "Conta", "Pattern", "Classe", "Valor"}, ...]
        self._dirty = False

    # ── QAbstractTableModel API ───────────────────────────────────────────────
    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_REGRAS_HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return _REGRAS_HEADERS[section]
            return str(section + 1)
        return QVariant()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        row = self._rows[index.row()]
        col = index.column()
        key = _REGRAS_HEADERS[col]
        val = row.get(key, "")

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if val is None:
                return "" if role == Qt.ItemDataRole.DisplayRole else QVariant()
            return str(val) if col != _COL_PRIO else int(val)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (_COL_PRIO, _COL_VALOR):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QBrush(QColor("#F5F5F5"))
        return QVariant()

    def flags(self, index):
        return (Qt.ItemFlag.ItemIsEnabled |
                Qt.ItemFlag.ItemIsSelectable |
                Qt.ItemFlag.ItemIsEditable)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        row = self._rows[index.row()]
        key = _REGRAS_HEADERS[index.column()]
        row[key] = value
        self._dirty = True
        self.dataChanged.emit(index, index)
        return True

    def load(self, pasta: Path):
        """Carrega TODAS as regras activas da DB.

        Schema real (Database.py):
          id, prioridade, classe, conta, pattern, normal, extra, ativo
        """
        self.beginResetModel()
        self._rows = []
        try:
            repo = RegrasRepo(pasta)
            rows = repo.find_ativas()  # SELECT * WHERE ativo=1 — todas

            rows.sort(key=lambda r: (
                0 if (r["classe"] or "").upper() == "RECEITA" else 1,    #(r["conta"] or "").upper(),
                int(r["prioridade"] or 100),
            ))

            print(f"📋 Regras.load() pasta={pasta}  db={db_path(pasta)}  n_rows={len(rows)}")
            for r in rows:
                self._rows.append({
                    "_id":        r["id"],
                    "Prioridade": int(r["prioridade"] or 100),
                    "Conta":      r["conta"] or "",
                    "Pattern":    r["pattern"] or "",
                    "Classe":     (r["classe"] or "").upper(),
                    "Valor":      "" if r["normal"] is None else str(r["normal"]),
                    "_extra":     r["extra"],  # preservado no save
                })
        except Exception as e:
            print(f"❌ RegrasTableModel.load() erro: {e}")
            import traceback
            traceback.print_exc()
        self._dirty = False
        self.endResetModel()
    

    def add_row(self):
        new = {"_id": None, "Prioridade": 100, "Classe": "DESPESA",
               "Conta": "", "Pattern": "", "Valor": ""}
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(new)
        self.endInsertRows()
        self._dirty = True
        return len(self._rows) - 1

    def remove_row(self, row_index: int):
        if 0 <= row_index < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row_index, row_index)
            self._rows.pop(row_index)
            self.endRemoveRows()
            self._dirty = True

    def save(self, pasta: Path) -> tuple[int, int, list[str]]:
        """
        V5: Persiste o estado do model na tabela regras.
        Apaga todas as regras gerais (normal IS NULL) e re-insere.
        As regras de condóminos (normal IS NOT NULL) são preservadas.
        Devolve (inseridas, n_erros, mensagens_erro).
        """
        erros: list[str] = []
        inseridas = 0

        try:
            with get_connection(pasta) as conn:
                # Apagar só regras gerais (condóminos ficam intactos)
                conn.execute("DELETE FROM regras WHERE normal IS NULL")

                for i, row in enumerate(self._rows):
                    pattern = str(row.get("Pattern", "")).strip()
                    conta   = str(row.get("Conta",   "")).strip()
                    if not pattern:
                        erros.append(f"Linha {i+1}: Pattern vazio — ignorada")
                        continue
                    if not conta:
                        erros.append(f"Linha {i+1}: Conta vazia — ignorada")
                        continue

                    prio   = int(row.get("Prioridade") or 100)
                    classe = str(row.get("Classe") or "DESPESA").strip().upper()
                    if classe not in ("RECEITA", "DESPESA"):
                        classe = "DESPESA"

                    valor_str = str(row.get("Valor") or "").strip()
                    normal: float | None = None
                    if valor_str:
                        try:
                            normal = float(valor_str.replace(",", "."))
                        except ValueError:
                            erros.append(f"Linha {i+1} ({conta}): Valor inválido '{valor_str}' — ignorado")

                    conn.execute(
                        """INSERT INTO regras (prioridade, classe, conta, pattern, normal)
                           VALUES (?, ?, ?, ?, ?)""",
                        (prio, classe, conta, pattern, normal),
                    )
                    inseridas += 1

        except Exception as e:
            erros.append(f"Erro de DB: {e}")

        self._dirty = False
        return inseridas, len(erros), erros

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(_CLASSE_OPCOES)
        return cb

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.EditRole) or "DESPESA"
        idx = editor.findText(val)
        editor.setCurrentIndex(max(idx, 0))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class _ClasseDelegate(QStyledItemDelegate):
    """Combo RECEITA / DESPESA para a coluna Classe."""

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(_CLASSE_OPCOES)
        return cb

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.EditRole) or "DESPESA"
        idx = editor.findText(val)
        editor.setCurrentIndex(max(idx, 0))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class _PrioDelegate(QStyledItemDelegate):
    """SpinBox 1-999 para a coluna Prioridade."""

    def createEditor(self, parent, option, index):
        sb = QSpinBox(parent)
        sb.setRange(1, 999)
        return sb

    def setEditorData(self, editor, index):
        try:
            editor.setValue(int(index.data(Qt.ItemDataRole.EditRole) or 100))
        except (ValueError, TypeError):
            editor.setValue(100)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.value(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


# ──────────────────────────────────────────────────────────────────────────────
class ConfiguracoesWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("Ficheiros de Configurações")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        btn_bar = QHBoxLayout()
        btn_gravar = QPushButton(" →  Gravar")
        btn_gravar.setFixedSize(130, 42)
        icon_path = ICONS_DIR / "save-icon.png"
        if icon_path.exists():
            btn_gravar.setIcon(QIcon(str(icon_path)))
            btn_gravar.setIconSize(QSize(30, 30))
        btn_gravar.clicked.connect(self.gravar_tabelas)
        btn_bar.addWidget(btn_gravar)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
        QTabWidget::pane {
            border: none;
        }
        QTabBar::tab {
            padding: 8px 16px;
        }
        """)
        layout.addWidget(self.tabs)
        

        # Aba Analisar CSV
        self.tab_analisar = QWidget()
        self.tabs.addTab(self.tab_analisar, "Analisar CSV")
        self._setup_analisar_tab()
        
        # Aba Configs
        self.tab_configs = QWidget()
        self.tabs.addTab(self.tab_configs, "Configs")
        self.model_configs = ConfigsTableModel()
        self._setup_tab(self.tab_configs, self.model_configs, is_configs=True)

        # Aba Regras
        self.tab_regras = QWidget()
        self.tabs.addTab(self.tab_regras, "Regras")
        self.model_regras = RegrasTableModel()
        self._setup_regras_tab()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

    def _setup_tab(self, tab_widget, model, is_configs):
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        table = QTableView()
        table.setModel(model)

        header = table.horizontalHeader()
        header.setStretchLastSection(False)

        if is_configs:
            # Configs: primeiras 4 fixas, última stretch
            fixed_widths = [200, 310, 150, 110]
            for i in range(4):
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                header.resizeSection(i, fixed_widths[i])
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        else:
            # Contas: primeira fixa, segunda stretch
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(0, 100)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setStyleSheet("""
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
        table.setEditTriggers(QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.SelectedClicked)

        # Suporte a teclas Insert/Delete
        if not hasattr(table, 'keyPressEvent_original'):
            table.keyPressEvent_original = table.keyPressEvent
        table.keyPressEvent = lambda event, t=table, m=model: self.handle_key_press(event, t, m)

        layout.addWidget(table)

        if is_configs:
            self.table_configs = table
        else:
            self.table_contas = table

    def handle_key_press(self, event, table, model):
        if event.key() == Qt.Key.Key_Insert:
            model.add_row()
        elif event.key() == Qt.Key.Key_Delete:
            indexes = table.selectedIndexes()
            if indexes:
                row = indexes[0].row()
                reply = QMessageBox.question(
                    self,
                    "Confirmar",
                    "Tem a certeza que deseja apagar este registo?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    model.remove_row(row)
        else:
            table.keyPressEvent_original(event)

    # ── Aba Regras ─────────────────────────────────────────────────────────────

    def _setup_regras_tab(self):
        layout = QVBoxLayout(self.tab_regras)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        # Barra de botões
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(4, 0, 4, 0)

        btn_add = QPushButton("＋  Adicionar")
        btn_add.setFixedHeight(34)
        btn_add.setStyleSheet(
            "QPushButton{background:#1976D2;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{background:#1565C0;}"
        )
        btn_add.clicked.connect(self._regras_add_row)

        btn_del = QPushButton("✕  Apagar")
        btn_del.setFixedHeight(34)
        btn_del.setStyleSheet(
            "QPushButton{background:#C62828;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{background:#B71C1C;}"
        )
        btn_del.clicked.connect(self._regras_del_row)

        btn_gravar = QPushButton("💾  Gravar Regras")
        btn_gravar.setFixedHeight(34)
        btn_gravar.setStyleSheet(
            "QPushButton{background:#2E7D32;color:white;font-weight:bold;"
            "border:none;border-radius:4px;padding:0 12px;}"
            "QPushButton:hover{background:#1B5E20;}"
        )
        btn_gravar.clicked.connect(self._gravar_regras)

        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_del)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_gravar)
        layout.addLayout(btn_bar)

        # Tabela
        self.table_regras = QTableView()
        self.table_regras.setModel(self.model_regras)
        self.table_regras.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_regras.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked |
            QTableView.EditTrigger.SelectedClicked
        )
        self.table_regras.setAlternatingRowColors(True)
        self.table_regras.setStyleSheet("""
            QTableView {
                gridline-color: #C0C0C0;
                border: 1px solid #C0C0C0;
            }
            QTableView::item { padding: 5px; }
            QHeaderView::section {
                background-color: #2F5597;
                color: white;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #1F4587;
            }
        """)

        # Delegates
        self.table_regras.setItemDelegateForColumn(
            _COL_PRIO, _PrioDelegate(self.table_regras))
        self.table_regras.setItemDelegateForColumn(
            _COL_CLASSE, _ClasseDelegate(self.table_regras))
        # Larguras de colunas
        hdr = self.table_regras.horizontalHeader()
        hdr.setSectionResizeMode(_COL_PRIO,   QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(_COL_PRIO, 90)
        hdr.setSectionResizeMode(_COL_CLASSE, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(_COL_CLASSE, 90)
        hdr.setSectionResizeMode(_COL_CONTA,  QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(_COL_CONTA, 200)
        hdr.setSectionResizeMode(_COL_PAT,    QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_VALOR,  QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(_COL_VALOR, 90)

        # Teclas Ins/Del
        self.table_regras.keyPressEvent = self._regras_key_press

        layout.addWidget(self.table_regras)

        # Nota de rodapé
        nota = QLabel(
            "  ℹ️  Ins = nova linha  |  Del = apagar linha seleccionada  |  "
            "Duplo-clique para editar  |  'Gravar Regras' persiste na base de dados"
        )
        nota.setStyleSheet("color:#666;font-style:italic;font-size:11px;padding:4px;")
        layout.addWidget(nota)

    def _regras_key_press(self, event):
        if event.key() == Qt.Key.Key_Insert:
            self._regras_add_row()
        elif event.key() == Qt.Key.Key_Delete:
            self._regras_del_row()
        else:
            QTableView.keyPressEvent(self.table_regras, event)

    def _regras_add_row(self):
        row = self.model_regras.add_row()
        idx = self.model_regras.index(row, _COL_PAT)
        self.table_regras.setCurrentIndex(idx)
        self.table_regras.scrollToBottom()
        self.table_regras.edit(idx)

    def _regras_del_row(self):
        indexes = self.table_regras.selectedIndexes()
        if not indexes:
            return
        row = indexes[0].row()
        nome = self.model_regras._rows[row].get("Conta") or \
               self.model_regras._rows[row].get("Pattern") or f"linha {row+1}"
        reply = QMessageBox.question(
            self, "Confirmar",
            f"Apagar a regra «{nome}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.model_regras.remove_row(row)

    def _gravar_regras(self):
        if not hasattr(self, "caminho_configs"):
            QMessageBox.warning(self, "Sem dados", "Pasta de dados não definida.")
            return
        pasta = self.caminho_configs.parent
        inseridas, n_erros, msgs = self.model_regras.save(pasta)
        if msgs:
            QMessageBox.warning(self, "Avisos",
                                f"{inseridas} regra(s) gravada(s).\n\n" +
                                "\n".join(msgs))
        else:
            QMessageBox.information(self, "Regras gravadas",
                                    f"{inseridas} regra(s) gravada(s) com sucesso.")
        self.status_label.setText(
            f"✅ Regras: {inseridas} gravadas"
            + (f", {n_erros} erro(s)" if n_erros else "")
        )

    # ── Aba Analisar CSV ───────────────────────────────────────────────────────
    def _setup_analisar_tab(self):
        """Configura a aba de análise CSV"""
        layout = QVBoxLayout(self.tab_analisar)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Botão de análise
        btn_layout = QHBoxLayout()
        self.btn_analisar = QPushButton(" →  Analisar")
        self.btn_analisar.setFixedSize(130, 42)
        
        # Carregar ícone se existir
        icon_path = ICONS_DIR / "analisar-icon.png"
        if icon_path.exists():
            self.btn_analisar.setIcon(QIcon(str(icon_path)))
            self.btn_analisar.setIconSize(QSize(30, 30))
        
        self.btn_analisar.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #1565C0;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        self.btn_analisar.clicked.connect(self.analisar_csv)
        btn_layout.addWidget(self.btn_analisar)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Splitter para dividir a área em duas colunas
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Painel esquerdo - Valores detectados no CSV
        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.Shape.StyledPanel)
        left_layout = QVBoxLayout(left_panel)
        
        left_title = QLabel("Valores Detectados no CSV")
        left_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2F5597; padding: 5px;")
        left_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(left_title)
        
        self.text_detectados = QTextEdit()
        self.text_detectados.setReadOnly(True)
        self.text_detectados.setStyleSheet("""
            QTextEdit {
                background-color: #F8F9FA;
                border: 1px solid #C0C0C0;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        left_layout.addWidget(self.text_detectados)
        
        # Painel direito - Valores gravados em Configs
        right_panel = QFrame()
        right_panel.setFrameShape(QFrame.Shape.StyledPanel)
        right_layout = QVBoxLayout(right_panel)
        
        right_title = QLabel("Valores Gravados em Configs")
        right_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2F5597; padding: 5px;")
        right_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(right_title)
        
        self.text_gravados = QTextEdit()
        self.text_gravados.setReadOnly(True)
        self.text_gravados.setStyleSheet("""
            QTextEdit {
                background-color: #F8F9FA;
                border: 1px solid #C0C0C0;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        right_layout.addWidget(self.text_gravados)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)

    def analisar_csv(self):
        """Abre diálogo para selecionar CSV e executa análise"""
        # Define o diretório inicial - usa a pasta de dados se disponível, caso contrário BASE_DIR
        diretorio_inicial = str(BASE_DIR / self.pasta_dados) if self.pasta_dados else str(BASE_DIR)
        
        csv_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Ficheiro CSV",
            diretorio_inicial,
            "Ficheiros CSV (*.csv);;Todos os Ficheiros (*.*)"
        )
        
        if not csv_path:
            return
        
        # Limpar áreas de texto
        self.text_detectados.clear()
        self.text_gravados.clear()
        
        # Caminho do Configs
        configs_path = BASE_DIR / self.pasta_dados / "Configs"
        
        # Executar análise
        self.text_detectados.append("🔍 ANALISANDO FICHEIRO CSV...\n")
        self.text_detectados.append(f"📁 Ficheiro: {Path(csv_path).name}\n")
        self.text_detectados.append("=" * 60 + "\n")
        
        try:
            success, message, params = analyze_and_update(csv_path, str(configs_path))
            
            if success and params:
                # Mostrar parâmetros detectados
                self.text_detectados.append("\n✅ ANÁLISE CONCLUÍDA COM SUCESSO!\n")
                self.text_detectados.append("\n📊 PARÂMETROS DETECTADOS:\n")
                self.text_detectados.append("-" * 60 + "\n")
                
                for key, value in params.items():
                    self.text_detectados.append(f"  • {key:<20} = {value}\n")
                
                # Ler e mostrar valores gravados em Configs
                self.text_gravados.append("💾 VALORES GRAVADOS EM CONFIGS:\n")
                self.text_gravados.append("=" * 60 + "\n")
                
                if existe_dados(configs_path):
                    rows, _ = carregar_db(configs_path)
                    importacao_params = []
                    for rec in rows:
                        categoria = str(rec.get('CATEGORIA', '')).strip().upper()
                        if categoria == 'IMPORTACAO':
                            importacao_params.append(rec)

                    if importacao_params:
                        self.text_gravados.append("\n📋 Parâmetros de IMPORTACAO:\n")
                        self.text_gravados.append("-" * 60 + "\n")
                        for rec in importacao_params:
                            chave = str(rec.get('CHAVE', '')).strip()
                            valor = str(rec.get('VALOR', '')).strip()
                            tipo = str(rec.get('TIPO', '')).strip()
                            self.text_gravados.append(
                                f"  {chave:<20} = {valor:<15} "
                                f"[{tipo}]\n"
                            )
                    else:
                        self.text_gravados.append("\n⚠ Nenhum parâmetro de IMPORTACAO encontrado.\n")
                else:
                    self.text_gravados.append("\n❌ Ficheiro Configs não encontrado.\n")
                
                # Recarregar a aba Configs para mostrar as alterações
                self.carregar_dados()
                
                QMessageBox.information(
                    self,
                    "Sucesso",
                    f"Análise concluída com sucesso!\n\n{message}"
                )
            else:
                self.text_detectados.append(f"\n❌ ERRO: {message}\n")
                QMessageBox.warning(
                    self,
                    "Erro na Análise",
                    f"Não foi possível analisar o ficheiro CSV.\n\n{message}"
                )
                
        except Exception as e:
            error_msg = f"Erro ao analisar ficheiro: {str(e)}"
            self.text_detectados.append(f"\n❌ {error_msg}\n")
            QMessageBox.critical(
                self,
                "Erro",
                error_msg
            )

    def set_pasta_dados(self, pasta_dados):
        self.pasta_dados = pasta_dados
        self.caminho_configs = BASE_DIR / pasta_dados / "Configs"
        self.carregar_dados()

    def carregar_dados(self):
        # Configs
        if existe_dados(self.caminho_configs):
            if self.model_configs.load_from_db(str(self.caminho_configs)):
                self.status_label.setText(
                    f"✅ Configs carregadas ({self.model_configs.rowCount()} registos)")
            else:
                self.status_label.setText("❌ Erro ao carregar Configs")
        else:
            self.model_configs.beginResetModel()
            self.model_configs._data = []
            self.model_configs.endResetModel()
            self.status_label.setText("📂 Configs não encontrado")

        # Regras (tabela relacional)
        pasta = self.caminho_configs.parent
        try:
            self.model_regras.load(pasta)
            n = self.model_regras.rowCount()
            self.status_label.setText(
                f"✅ Regras carregadas ({n} regras activas)")
        except Exception as e:
            self.status_label.setText(f"⚠️ Regras: {e}")

    def gravar_tabelas(self):
        errors = []

        if not self.caminho_configs.parent.exists():
            self.caminho_configs.parent.mkdir(parents=True, exist_ok=True)

        if not self.model_configs.save_to_db(str(self.caminho_configs)):
            errors.append("Configs")

        if errors:
            QMessageBox.critical(self, "Erro", f"Falha ao gravar: {', '.join(errors)}")
            self.status_label.setText(f"❌ Erro ao gravar: {', '.join(errors)}")
        else:
            QMessageBox.information(self, "Sucesso", "Tabelas gravadas com sucesso!")
            self.status_label.setText("✅ Tabelas gravadas com sucesso!")