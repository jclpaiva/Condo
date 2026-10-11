"""
Receitas_Gui.py - Widget de visualização de receitas (Quotas + Juros)
Funcionalidades:
- Preferência pelas views pivot relacionais (v_receitas_pivot)
- Fallback para tabelas Receitas/Juros via bridge (condominio.db)
- Botão Atualizar executa Receitas.py e sincroniza para condominio.db
- Linha TOTAIS destacada, formatação de moeda, somente leitura
"""

import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTabWidget, QTableView, QHeaderView, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt6.QtGui import QColor, QBrush, QFont
from Commons import BASE_DIR, PASTA_CORRENTE, carregar_db, existe_dados
try:
    from Database import (
        receitas as receitas_repo,
        db_path,
        ensure_views_and_fts,
        ConfigsRepo,
        get_connection,
    )
    _HAS_RELATIONAL = True
except ImportError:
    _HAS_RELATIONAL = False
    def get_connection(pasta):
        raise RuntimeError("Database não disponível")

# Importa o módulo Receitas diretamente
import Receitas  # Agora importa e chama main()


class ReceitasTableModel(QAbstractTableModel):
    MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
             "JUL", "AGO", "SET", "OUT", "NOV", "DEZ", "TOTAL"]
    
    def __init__(self, tipo="QUOTAS"):
        super().__init__()
        self.tipo = tipo
        if tipo == "JUROS":
            self.col_descricao = "JUROS"
        else:
            self.col_descricao = "FRACCAO"
        self._data = []
        if tipo == "JUROS":
            self.headers = [self.col_descricao] + self.MESES
        else:
            self.headers = [self.col_descricao, "SALDO_ANT"] + ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                           "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"] + ["SALDO", "TOTAL"]

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

        is_total_row = str(row.get(self.col_descricao, "")).upper() == "TOTAIS"

        if role == Qt.ItemDataRole.DisplayRole:
            if col_name == self.col_descricao:
                return str(value)
            elif isinstance(value, (int, float)) and value != 0:
                return f"{value:,.2f}"
            return ""

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col_name == self.col_descricao:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.BackgroundRole and is_total_row:
            return QBrush(QColor("#E9EFF7"))
        
        elif role == Qt.ItemDataRole.FontRole and is_total_row:
            font = QFont()
            font.setBold(True)
            return font
        
        elif role == Qt.ItemDataRole.ForegroundRole:
            if is_total_row:
                return QBrush(QColor("#2F5597"))
            elif col_name != self.col_descricao:
                if isinstance(value, (int, float)) and value < 0:
                    return QBrush(QColor("#DC3545"))

        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return QVariant()

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def load_from_pivot(self, pasta, ano=None, tipo_quota=None):
        """Carrega a partir de v_receitas_pivot + receitas_resumo (saldos)."""
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
            tipo_quota = tipo_quota or ("NORMAL" if self.tipo == "QUOTAS" else "EXTRA")
            rows = receitas_repo(pasta).pivot(ano)
            meses_cols = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                          "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
            mes_keys = ["jan", "fev", "mar", "abr", "mai", "jun",
                        "jul", "ago", "set", "out", "nov", "dez"]

            # Carregar saldos de receitas_resumo (por letra E por rótulo)
            saldos = {}  # chave → (saldo_ant, saldo)  — chave pode ser letra ou rótulo
            mapa_label = {
                "A": "R/c Esq.", "B": "R/c Dto.", "C": "1º Esq.",
                "D": "1º Dto.", "E": "2º Esq.", "F": "2º Dto.",
            }
            mapa_letra = {v: k for k, v in mapa_label.items()}
            try:
                with get_connection(pasta) as conn:
                    for rsum in conn.execute(
                        """SELECT c.fracao, rr.fracao_label, rr.saldo_ant, rr.saldo,
                                  c.quota_normal, c.quota_extra
                           FROM receitas_resumo rr
                           JOIN condominos c ON c.id = rr.condominio_id
                           WHERE rr.ano = ? AND UPPER(rr.tipo_quota) = ?""",
                        (ano, tipo_quota.upper()),
                    ):
                        letra = str(rsum[0] or "").strip()
                        label_r = str(rsum[1] or "").strip()
                        sa = float(rsum[2] or 0)
                        sf = float(rsum[3] or 0)
                        qn = float(rsum[4] or 0)
                        qe = float(rsum[5] or 0)
                        entry = (sa, sf, qn, qe)
                        if letra:
                            saldos[letra] = entry
                            if letra in mapa_label:
                                saldos[mapa_label[letra]] = entry
                        if label_r:
                            saldos[label_r] = entry
            except Exception as e:
                print(f"⚠️ Não foi possível carregar receitas_resumo: {e}")

            totals = {m: 0.0 for m in meses_cols}
            totals["TOTAL"] = 0.0
            totals["SALDO_ANT"] = 0.0
            totals["SALDO"] = 0.0

            data_rows = []
            for r in rows:
                if str(r["tipo_quota"]).upper() != tipo_quota:
                    continue
                fracao = str(r["fracao"] or "").strip()
                label = mapa_label.get(fracao, str(r["condominio"] or fracao))
                row = {self.col_descricao: label}
                total = 0.0
                for mk, col in zip(mes_keys, meses_cols):
                    val = float(r[mk] or 0)
                    row[col] = val
                    totals[col] += val
                    total += val
                total_pago = float(r["total"] or total)
                row["TOTAL"] = total_pago

                # SALDO_ANT do resumo; SALDO recalculado com a fórmula clássica
                entry = saldos.get(fracao) or saldos.get(label) or (0.0, 0.0, 0.0, 0.0)
                sa = float(entry[0] or 0)
                quota_mensal = float(entry[2] if tipo_quota == "NORMAL" else entry[3] or 0)
                if quota_mensal <= 0:
                    # tentar quota a partir do total esperado se não veio do join
                    quota_mensal = 0.0
                quota_anual = quota_mensal * 12
                if quota_anual > 0 or abs(sa) > 0.0005:
                    # SALDO = (Quota_Anual - Total_Pago) × -1 + Saldo_Anterior
                    sf = (quota_anual - total_pago) * -1 + sa
                else:
                    sf = float(entry[1] or 0)

                row["SALDO_ANT"] = sa
                row["SALDO"] = sf
                totals["TOTAL"] += total_pago
                totals["SALDO_ANT"] += sa
                totals["SALDO"] += sf
                data_rows.append(row)

            # Ordenar alfabeticamente pelo rótulo da fracção
            data_rows.sort(key=lambda x: str(x.get(self.col_descricao, "")))
            self._data = data_rows

            if self._data:
                tot_row = {self.col_descricao: "TOTAIS"}
                tot_row.update(totals)
                self._data.append(tot_row)

            self.endResetModel()
            return len(self._data) > 0
        except Exception as e:
            print(f"❌ Erro ao carregar pivot receitas: {e}")
            self.endResetModel()
            return False

    def _obter_saldos_ant(self, caminho, tipo_quota_sql="NORMAL"):
        """Lê SALDO_ANT de receitas_resumo (SQLite)."""
        saldos = {}
        pasta = Path(caminho).parent
        mapa_letra = {
            "A": "R/c Esq.", "B": "R/c Dto.", "C": "1º Esq.",
            "D": "1º Dto.", "E": "2º Esq.", "F": "2º Dto.",
        }

        def _norm(label):
            label = str(label or "").strip()
            if len(label) == 1 and label.upper() in mapa_letra:
                return mapa_letra[label.upper()]
            return label

        # receitas_resumo
        if _HAS_RELATIONAL:
            try:
                pasta_db = pasta
                if db_path(pasta_db).exists():
                    try:
                        ano = int(ConfigsRepo(pasta_db).get_value(
                            "GERAL", "ANO_EXERCICIO", 0) or 0)
                    except Exception:
                        ano = 0
                    with get_connection(pasta_db) as conn:
                        sql = """
                            SELECT COALESCE(NULLIF(TRIM(rr.fracao_label), ''), c.fracao),
                                   rr.saldo_ant
                            FROM receitas_resumo rr
                            JOIN condominos c ON c.id = rr.condominio_id
                            WHERE UPPER(TRIM(rr.tipo_quota)) = ?
                        """
                        params = [tipo_quota_sql]
                        if ano:
                            sql += " AND rr.ano = ?"
                            params.append(ano)
                        for label, sa in conn.execute(sql, params):
                            fracao = _norm(label)
                            if not fracao:
                                continue
                            try:
                                val = float(sa or 0)
                            except (TypeError, ValueError):
                                val = 0.0
                            if abs(val) > 0.0005:
                                saldos[fracao] = val
            except Exception as e:
                print(f"⚠️ GUI: resumo SALDO_ANT: {e}")
        return saldos

    def load_from_db(self, caminho):
        """Carrega tabelas planas e corrige SALDO_ANT a partir de receitas_resumo."""
        self.beginResetModel()
        self._data = []
        caminho = Path(caminho)

        if not existe_dados(caminho):
            self.endResetModel()
            return False

        try:
            rows, _ = carregar_db(caminho)
            tipo_sql = "NORMAL" if self.tipo == "QUOTAS" else "EXTRA"
            saldos_ant = {}
            if self.tipo != "JUROS":
                saldos_ant = self._obter_saldos_ant(caminho, tipo_sql)

            # Quotas mensais para recalcular SALDO (se disponível via resumo/condominos)
            quotas_mensais = {}
            if self.tipo != "JUROS" and _HAS_RELATIONAL:
                try:
                    pasta = Path(caminho).parent
                    if db_path(pasta).exists():
                        with get_connection(pasta) as conn:
                            col = "quota_normal" if tipo_sql == "NORMAL" else "quota_extra"
                            mapa_letra = {
                                "A": "R/c Esq.", "B": "R/c Dto.", "C": "1º Esq.",
                                "D": "1º Dto.", "E": "2º Esq.", "F": "2º Dto.",
                            }
                            for fr, q in conn.execute(
                                f"SELECT fracao, {col} FROM condominos"
                            ):
                                label = mapa_letra.get(str(fr).strip(), str(fr).strip())
                                quotas_mensais[label] = float(q or 0)
                except Exception:
                    pass

            for rec in rows:
                if self.tipo == "JUROS":
                    descricao = str(rec.get("JUROS", "")).strip()
                else:
                    descricao = str(rec.get("FRACCAO", "")).strip()

                if not descricao:
                    continue

                row = {self.col_descricao: descricao}

                for mes in ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                           "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]:
                    val = rec.get(mes, 0.0)
                    row[mes] = float(val) if str(val) != "" else 0.0

                total_pago = float(rec.get("TOTAL", 0.0) or 0.0)
                row["TOTAL"] = total_pago

                if self.tipo != "JUROS":
                    # Preferir SALDO_ANT de receitas_resumo; senão o da tabela
                    sa_tabela = float(rec.get("SALDO_ANT", 0.0) or 0.0)
                    sa = saldos_ant.get(descricao, sa_tabela)
                    if abs(sa) < 0.0005 and abs(sa_tabela) > 0.0005:
                        sa = sa_tabela

                    q_mensal = quotas_mensais.get(descricao, 0.0)
                    q_anual = q_mensal * 12
                    # SALDO = (Quota_Anual - Total_Pago) × -1 + Saldo_Anterior
                    if q_anual > 0 or abs(sa) > 0.0005:
                        sf = (q_anual - total_pago) * -1 + sa
                    else:
                        sf = float(rec.get("SALDO", 0.0) or 0.0)

                    row["SALDO_ANT"] = sa
                    row["SALDO"] = sf

                self._data.append(row)

            self.endResetModel()
            return True

        except Exception as e:
            print(f"❌ Erro ao carregar {caminho.name}: {e}")
            import traceback
            traceback.print_exc()
            self.endResetModel()
            return False


class ReceitasWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        title = QLabel("Receitas do Ano")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        btn_bar = QHBoxLayout()
        btn_atualizar = QPushButton("🔄 Atualizar Receitas  ")
        btn_atualizar.setFixedSize(150, 42)
        btn_atualizar.clicked.connect(self.atualizar_receitas)
        btn_bar.addWidget(btn_atualizar)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        # ABAS - REMOVE BORDER DO QTABWIDGET
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

        self.tab_n = QWidget()
        self.tabs.addTab(self.tab_n, "Quotas")
        self.model_n = ReceitasTableModel(tipo="QUOTAS")
        self._setup_tab(self.tab_n, self.model_n)

        self.tab_e = QWidget()
        self.tabs.addTab(self.tab_e, "Quotas Ext")
        self.model_e = ReceitasTableModel(tipo="QUOTASEXT")
        self._setup_tab(self.tab_e, self.model_e)

        self.tab_j = QWidget()
        self.tabs.addTab(self.tab_j, "Juros")
        self.model_j = ReceitasTableModel(tipo="JUROS")
        self._setup_tab(self.tab_j, self.model_j)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

    def _setup_tab(self, tab_widget, model):
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        table = QTableView()
        table.setModel(model)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)  # Esconder números das linhas 
        
        layout.addWidget(table)

        if model.tipo == "QUOTAS":
            self.table_n = table
        elif model.tipo == "QUOTASEXT":
            self.table_e = table
        else:
            self.table_j = table

    def ajustar_larguras_colunas(self, table):
        header = table.horizontalHeader()
        model = table.model()
        meses = {"JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"}
        total_idx = None
        saldo_idx = None
        meses_idx = []
        
        for i, h in enumerate(model.headers):
            if h == "TOTAL":
                total_idx = i
            elif h == "SALDO":
                saldo_idx = i
            elif h in meses:
                meses_idx.append(i)
        
        if total_idx is None:
            total_idx = model.columnCount() - 1

        # Mede largura ideal do TOTAL
        header.setSectionResizeMode(total_idx, QHeaderView.ResizeMode.ResizeToContents)
        table.resizeColumnToContents(total_idx)
        total_width = table.columnWidth(total_idx)

        # Aplica largura do TOTAL a: TOTAL, SALDO e meses
        header.setSectionResizeMode(total_idx, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(total_idx, total_width)
        
        # SALDO com mesma largura
        if saldo_idx is not None:
            header.setSectionResizeMode(saldo_idx, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(saldo_idx, total_width)
        
        # Meses com mesma largura
        for idx in meses_idx:
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(idx, total_width)

    def set_pasta_dados(self, pasta_dados):
        self.pasta_dados = pasta_dados
        self.caminho_receitas_n = BASE_DIR / pasta_dados / "ReceitasN"
        self.caminho_receitas_e = BASE_DIR / pasta_dados / "ReceitasE"
        self.caminho_juros = BASE_DIR / pasta_dados / "Juros"
        self.carregar_dados()
        
    def carregar_dados(self, preferir_planas=False):
        """
        Carrega quotas N/E e juros.
        preferir_planas=True  → usa tabelas ReceitasN/E (após Atualizar, têm saldos corretos)
        preferir_planas=False → tenta pivot relacional (com saldos de receitas_resumo)
        """
        pasta = BASE_DIR / self.pasta_dados if self.pasta_dados else PASTA_CORRENTE
        loaded_from = "legado"

        def _tem_saldos(model):
            """True se alguma linha (exceto TOTAIS) tem SALDO ou SALDO_ANT != 0."""
            for row in model._data:
                if str(row.get(model.col_descricao, "")).upper() == "TOTAIS":
                    continue
                if abs(float(row.get("SALDO", 0) or 0)) > 0.005:
                    return True
                if abs(float(row.get("SALDO_ANT", 0) or 0)) > 0.005:
                    return True
            return False

        # 1) Tabelas planas (fonte completa após Receitas.main)
        ok_flat_n = False
        ok_flat_e = False
        if existe_dados(self.caminho_receitas_n):
            ok_flat_n = self.model_n.load_from_db(str(self.caminho_receitas_n))
        if existe_dados(self.caminho_receitas_e):
            ok_flat_e = self.model_e.load_from_db(str(self.caminho_receitas_e))

        use_flat = preferir_planas or (ok_flat_n and _tem_saldos(self.model_n))

        if use_flat and (ok_flat_n or ok_flat_e):
            loaded_from = "planas"
            if ok_flat_n:
                self.ajustar_larguras_colunas(self.table_n)
            if ok_flat_e:
                self.ajustar_larguras_colunas(self.table_e)
        elif _HAS_RELATIONAL and db_path(pasta).exists():
            # 2) Pivot relacional (com saldos de receitas_resumo)
            ok_n = self.model_n.load_from_pivot(pasta, tipo_quota="NORMAL")
            ok_e = self.model_e.load_from_pivot(pasta, tipo_quota="EXTRA")
            if ok_n or ok_e:
                loaded_from = "relacional"
                if ok_n:
                    self.ajustar_larguras_colunas(self.table_n)
                if ok_e:
                    self.ajustar_larguras_colunas(self.table_e)
            # Se pivot não trouxe saldos mas as planas têm, usar planas
            if ok_n and not _tem_saldos(self.model_n) and ok_flat_n:
                self.model_n.load_from_db(str(self.caminho_receitas_n))
                self.ajustar_larguras_colunas(self.table_n)
                loaded_from = "planas"
            if ok_e and not _tem_saldos(self.model_e) and ok_flat_e:
                self.model_e.load_from_db(str(self.caminho_receitas_e))
                self.ajustar_larguras_colunas(self.table_e)
                loaded_from = "planas"
        else:
            # 3) Fallback puro para planas (já carregadas acima)
            if ok_flat_n:
                self.ajustar_larguras_colunas(self.table_n)
            if ok_flat_e:
                self.ajustar_larguras_colunas(self.table_e)

        # Juros continua nas tabelas planas
        if existe_dados(self.caminho_juros):
            if self.model_j.load_from_db(str(self.caminho_juros)):
                self.ajustar_larguras_colunas(self.table_j)

        n = self.model_n.rowCount()
        src = {"relacional": "views pivot", "planas": "tabelas planas", "legado": "SQLite"}.get(
            loaded_from, loaded_from
        )
        self.status_label.setText(f"✅ Dados carregados ({src}) – {n} linhas quotas N")
                
    def atualizar_receitas(self):
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return

        pasta_trabalho = BASE_DIR / self.pasta_dados
        if not pasta_trabalho.exists():
            QMessageBox.critical(self, "Erro", f"Pasta de trabalho não existe: {pasta_trabalho}")
            return

        self.status_label.setText("⏳ Processando receitas...")

        try:
            # Chama a função principal de Receitas, passando pasta_trabalho
            # Receitas.main grava ReceitasN / ReceitasE / Juros com saldos corretos
            Receitas.main(pasta_trabalho)

            # Preferir tabelas planas (fonte completa após processamento)
            self.carregar_dados(preferir_planas=True)
            
            total_n = self.model_n.rowCount()
            total_e = self.model_e.rowCount()
            total_j = self.model_j.rowCount()
            
            self.status_label.setText(f"✅ Receitas atualizadas! (N:{total_n} E:{total_e} J:{total_j})")
            
            QMessageBox.information(
                self,
                "Sucesso",
                f"Receitas atualizadas com sucesso!\n\n"
                f"Quotas Normais: {total_n} registos\n"
                f"Quotas Extras: {total_e} registos\n"
                f"Juros: {total_j} registos"
            )

        except Exception as e:
            erro_msg = f"Erro ao processar receitas:\n{e}"
            QMessageBox.critical(self, "Erro", erro_msg)
            self.status_label.setText("❌ Erro no processamento")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())

    widget = ReceitasWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(900, 600)
    widget.setWindowTitle("Receitas do Ano")
    widget.show()

    sys.exit(app.exec())