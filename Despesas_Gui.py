"""
Despesas_Gui.py - Widget de visualização de despesas (Pivot Table)
Funcionalidades:
- Preferência pela view pivot relacional (v_despesas_pivot)
- Fallback para tabela Despesas via bridge (condominio.db)
- Botão Atualizar executa Despesas.py e sincroniza para condominio.db
- Linha TOTAIS destacada, formatação de moeda, somente leitura
"""
import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt6.QtGui import QColor, QBrush, QFont
# Importa código compartilhado
from Commons import BASE_DIR, PASTA_CORRENTE, clean_numeric, carregar_db, existe_dados
try:
    from Database import (
        despesas as despesas_repo,
        db_path,
        ensure_views_and_fts,
        ConfigsRepo,
    )
    _HAS_RELATIONAL = True
except ImportError:
    _HAS_RELATIONAL = False

# Importa o módulo Despesas diretamente
import Despesas  # Agora importa e chama main()

# ====================================================================
# MODELO DA TABELA DESPESAS (PIVOT)
# ====================================================================
class DespesasPivotModel(QAbstractTableModel):
    """Modelo para tabela pivot de despesas (Contas x Meses)"""
    # Ordem dos meses
    MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
             "JUL", "AGO", "SET", "OUT", "NOV", "DEZ", "TOTAL"]
    
    def __init__(self):
        super().__init__()
        self._data = []  # Lista de dicts {DESPESAS, JAN, FEV, ..., TOTAL}
        self.headers = ["DESPESAS"] + self.MESES  # Renomeado de _headers para headers

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        row = self._data[index.row()]
        col_name = self.headers[index.column()]
        value = row.get(col_name, 0)

        # Linha TOTAIS
        is_total_row = str(row.get("DESPESAS", "")).upper() == "TOTAIS"

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:  # Coluna DESPESAS (texto)
                return str(value)
            else:  # Colunas de valores
                if isinstance(value, (int, float)) and value != 0:
                    # Formato: 1,200.28
                    return f"{value:,.2f}"
                return ""  # Células vazias para 0

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() == 0:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.BackgroundRole:
            if is_total_row:
                return QBrush(QColor("#E9EFF7"))  # Azul claro para TOTAIS

        elif role == Qt.ItemDataRole.FontRole:
            if is_total_row:
                font = QFont()
                font.setBold(True)
                return font

        elif role == Qt.ItemDataRole.ForegroundRole:
            if is_total_row:
                return QBrush(QColor("#2F5597"))  # Azul escuro para TOTAIS

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return QVariant()

    def flags(self, index):
        # Somente leitura
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def load_from_pivot(self, pasta, ano=None):
        """Carrega a partir de v_despesas_pivot (schema relacional)."""
        self.beginResetModel()
        self._data = []
        if not _HAS_RELATIONAL:
            self.endResetModel()
            return False
        try:
            pasta = Path(pasta) if pasta else PASTA_CORRENTE
            if not db_path(pasta).exists():
                self.endResetModel()
                return False
            ensure_views_and_fts(pasta)
            if ano is None:
                ano = int(ConfigsRepo(pasta).get_value("GERAL", "ANO_EXERCICIO", 2026) or 2026)
            rows = despesas_repo(pasta).pivot(ano)
            meses_cols = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                          "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
            mes_keys = ["jan", "fev", "mar", "abr", "mai", "jun",
                        "jul", "ago", "set", "out", "nov", "dez"]

            totals = {m: 0.0 for m in meses_cols}
            totals["TOTAL"] = 0.0

            for r in rows:
                row = {"DESPESAS": str(r["conta"] or "")}
                total = 0.0
                for mk, col in zip(mes_keys, meses_cols):
                    val = float(r[mk] or 0)
                    row[col] = val
                    totals[col] += val
                    total += val
                row["TOTAL"] = float(r["total"] or total)
                totals["TOTAL"] += row["TOTAL"]
                self._data.append(row)

            if self._data:
                tot_row = {"DESPESAS": "TOTAIS"}
                tot_row.update(totals)
                self._data.append(tot_row)

            self.endResetModel()
            return len(self._data) > 0
        except Exception as e:
            print(f"❌ Erro ao carregar pivot despesas: {e}")
            self.endResetModel()
            return False

    def load_from_db(self, caminho):
        """Fallback: carrega tabela Despesas via bridge (condominio.db)."""
        self.beginResetModel()
        self._data = []
        path = Path(caminho)
        if not existe_dados(path):
            self.endResetModel()
            return False
        try:
            rows, _ = carregar_db(path)
            for rec in rows:
                row = {
                    "DESPESAS": str(rec.get("DESPESAS", "")).strip(),
                }
                for mes in self.MESES:
                    row[mes] = float(rec.get(mes, 0.0) or 0.0)
                self._data.append(row)
            self.endResetModel()
            return True
        except Exception as e:
            print(f"❌ Erro ao carregar Despesas: {e}")
            self.endResetModel()
            return False

# ====================================================================
# WIDGET DE DESPESAS
# ====================================================================
class DespesasWidget(QWidget):
    """Widget principal para visualização de despesas"""
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.caminho_despesas_db = None
        self.primeiro_carregamento = True
        self.init_ui()

    def init_ui(self):
        """Inicializa interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # Título
        title_layout = QHBoxLayout()
        title = QLabel("Despesas do Ano")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title)
        layout.addLayout(title_layout)

        # Botão Atualizar
        btn_bar = QHBoxLayout()
        btn_atualizar = QPushButton("🔄 Atualizar Despesas")
        btn_atualizar.setFixedSize(150, 42)
        btn_atualizar.clicked.connect(self.atualizar_despesas)
        btn_bar.addWidget(btn_atualizar)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        # Tabela
        self.table_view = QTableView()
        self.model = DespesasPivotModel()
        self.table_view.setModel(self.model)

        # Configuração do header
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Coluna DESPESAS

        # Estilo da tabela
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
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.verticalHeader().setVisible(False)  # Esconder números das linhas
        
        layout.addWidget(self.table_view)

        # Status bar
        self.status_label = QLabel("Aguardando dados...")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

    def ajustar_larguras_colunas(self):
        """Ajusta larguras das colunas JAN–DEZ para igualar ao TOTAL, como em Receitas_Gui.py"""
        header = self.table_view.horizontalHeader()
        model = self.model
        meses = {"JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"}

        # Encontrar índices
        total_idx = None
        meses_idx = []
        for i, h in enumerate(model.headers):
            if h == "TOTAL":
                total_idx = i
            elif h in meses:
                meses_idx.append(i)

        if total_idx is None:
            total_idx = model.columnCount() - 1  # fallback

        # Medir largura ideal do TOTAL
        header.setSectionResizeMode(total_idx, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.resizeColumnToContents(total_idx)
        total_width = self.table_view.columnWidth(total_idx)

        # Aplicar largura interativa (igual a Receitas)
        header.setSectionResizeMode(total_idx, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(total_idx, total_width)

        for idx in meses_idx:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(idx, total_width)
    
    def _carregar_despesas(self):
        """Preferência: view pivot relacional; fallback: tabela plana."""
        pasta = BASE_DIR / self.pasta_dados if self.pasta_dados else PASTA_CORRENTE
        ok = False
        src = "legado"

        if _HAS_RELATIONAL and db_path(pasta).exists():
            ok = self.model.load_from_pivot(pasta)
            if ok:
                src = "views pivot"

        if not ok and self.caminho_despesas_db and existe_dados(self.caminho_despesas_db):
            ok = self.model.load_from_db(str(self.caminho_despesas_db))
            src = "SQLite"

        if ok:
            self.ajustar_larguras_colunas()
            n = sum(1 for row in self.model._data
                    if str(row.get("DESPESAS", "")).upper() != "TOTAIS")
            self.status_label.setText(f"✅ Dados carregados ({src}) – {n} contas")
            return True

        self.status_label.setText("📁 Sem dados de despesas. Clique em 'Atualizar Despesas'.")
        return False

    def set_pasta_dados(self, pasta_dados):
        """Define pasta de dados e carrega despesas (sem recalcular)."""
        self.pasta_dados = pasta_dados
        self.caminho_despesas_db = BASE_DIR / pasta_dados / "Despesas"
        self._carregar_despesas()

    def atualizar_despesas(self):
        """Chama Despesas.main(), sincroniza schema relacional e recarrega."""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return

        pasta_trabalho = BASE_DIR / self.pasta_dados
        if not pasta_trabalho.exists():
            QMessageBox.critical(self, "Erro", f"Pasta de trabalho não existe: {pasta_trabalho}")
            return

        self.status_label.setText("⏳ Processando despesas...")

        try:
            Despesas.main(pasta_trabalho, exportar_excel=False)

            if self._carregar_despesas():
                num_contas = sum(1 for row in self.model._data
                                 if str(row.get("DESPESAS", "")).upper() != "TOTAIS")
                QMessageBox.information(
                    self,
                    "Sucesso",
                    f"Despesas atualizadas com sucesso!\n\n"
                    f"Contas processadas: {num_contas} registos",
                )
            else:
                QMessageBox.warning(self, "Aviso", "Sem dados de despesas após o processamento.")
                self.status_label.setText("⚠️ Sem dados")

        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao processar despesas:\n{e}")
            self.status_label.setText("❌ Erro")

# ====================================================================
# TESTE STANDALONE
# ====================================================================
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())

    widget = DespesasWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(900, 600)
    widget.setWindowTitle("Despesas do Ano Corrente")
    widget.show()

    sys.exit(app.exec())