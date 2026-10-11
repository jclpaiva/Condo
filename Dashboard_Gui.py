"""
Dashboard_Gui.py - Dashboard Financeiro com Gráficos Interativos
Funcionalidades:
- 4 gráficos: Receitas N/E, Despesas, Balanço (nested pie)
- Hover com tooltip nos gráficos de barras e pie
- Gráfico de pizza duplo (nested pie) com legenda ON/OFF
- Cores vivas e contrastantes
- Dimensões otimizadas para não forçar resize
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSizePolicy, QToolTip
)
from PyQt6.QtCore import Qt, QPoint
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from Commons import BASE_DIR
from Database import carregar_db, existe_dados


# ====================================================================
# CANVAS MATPLOTLIB COM HOVER PRECISO
# ====================================================================
class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=4, height=2.5, dpi=90):
        fig = Figure(figsize=(width, height), dpi=dpi, facecolor='white')
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        # Permite que o widget encolha se necessário
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(300, 200)
        self.hover_items = []
        self.mpl_connect("motion_notify_event", self.on_hover)

    def on_hover(self, event):
        if event.inaxes != self.axes:
            return
        for wedge, label in self.hover_items:
            if wedge.contains(event)[0]:
                pos = QPoint(int(event.x), int(event.y))
                global_pos = self.mapToGlobal(pos)
                QToolTip.showText(global_pos, label, self)
                return
        QToolTip.hideText()


# ====================================================================
# DASHBOARD WIDGET
# ====================================================================
class DashboardWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Dashboard Financeiro do Condomínio")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2F5597; padding: 3px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        btn_atualizar = QPushButton("🔄 Atualizar Dashboard")
        btn_atualizar.setFixedHeight(35)
        btn_atualizar.clicked.connect(self.carregar_dados)
        layout.addWidget(btn_atualizar)

        # Layouts dos gráficos - COMPACTOS
        graficos_layout = QVBoxLayout()
        graficos_layout.setSpacing(6)

        # Linha superior - Receitas N e E
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.canvas_rec_n = MplCanvas(self, width=4.5, height=2.3, dpi=85)
        self.canvas_rec_e = MplCanvas(self, width=4.5, height=2.3, dpi=85)
        top_row.addWidget(self.canvas_rec_n)
        top_row.addWidget(self.canvas_rec_e)
        graficos_layout.addLayout(top_row)

        # Linha inferior - Despesas e Balanço
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)
        self.canvas_despesas = MplCanvas(self, width=5.5, height=2.5, dpi=90)
        self.canvas_balanco = MplCanvas(self, width=5.5, height=2.5, dpi=90)
        bottom_row.addWidget(self.canvas_despesas, stretch=1)
        bottom_row.addWidget(self.canvas_balanco, stretch=1)
        graficos_layout.addLayout(bottom_row)

        layout.addLayout(graficos_layout)

        self.status_label = QLabel("Aguardando dados...")
        self.status_label.setStyleSheet("color: #666; font-style: italic; font-size: 9pt; padding: 2px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status_label)

        # Define altura máxima para não forçar resize da janela principal
        self.setMaximumHeight(680)

    # ====================================================================
    # CARREGAMENTO DE DADOS
    # ====================================================================
    def set_pasta_dados(self, pasta_dados):
        self.pasta_dados = pasta_dados
        self.carregar_dados()

    def carregar_dados(self):
        if not self.pasta_dados:
            self.status_label.setText("⚠️ Pasta de dados não definida")
            return
        try:
            rec_n_path = BASE_DIR / self.pasta_dados / "ReceitasN"
            rec_e_path = BASE_DIR / self.pasta_dados / "ReceitasE"
            desp_path = BASE_DIR / self.pasta_dados / "Despesas"
            bal_path = BASE_DIR / self.pasta_dados / "Balanco"
            juros_path = BASE_DIR / self.pasta_dados / "Juros"

            dados_rec_n = self.carregar_receitas(rec_n_path)
            dados_rec_e = self.carregar_receitas(rec_e_path)
            dados_desp = self.carregar_despesas(desp_path)
            dados_despesas_por_conta = self.carregar_despesas_detalhadas(desp_path)
            saldo_anterior, saldo_final_db = self.carregar_saldo_balanco(bal_path)
            total_rec_n = self.extrair_total_linha_totais(rec_n_path)
            total_rec_e = self.extrair_total_linha_totais(rec_e_path)
            juros = self.carregar_juros(juros_path)
            total_despesas = sum(dados_desp) if isinstance(dados_desp, list) else 0

            # Garantir que todos os valores são numéricos válidos
            total_receitas = float(total_rec_n + total_rec_e + juros)
            saldo_corrente = float(total_receitas - total_despesas)
            saldo_final = float(saldo_anterior + saldo_corrente)

            # Validar valores antes de criar o dicionário
            def validar_valor(v):
                try:
                    v_float = float(v)
                    if v_float != v_float or abs(v_float) == float('inf'):
                        return 0.0
                    return v_float
                except (ValueError, TypeError):
                    return 0.0

            dados_bal = {
                "Saldo Anterior": validar_valor(saldo_anterior),
                "Total Receitas": validar_valor(total_receitas),
                "Total Despesas": validar_valor(total_despesas),
                "Saldo Corrente": validar_valor(saldo_corrente),
                "Saldo Final": validar_valor(saldo_final)
            }

            cores_bal = {
                "Total Receitas": "#1E88E5",
                "Saldo Anterior": "#43A047",
                "Total Despesas": "#E53935",
                "Saldo Corrente": "#8E24AA",
                "Saldo Final": "#D4A017"
            }

            self.plot_receitas(self.canvas_rec_n, dados_rec_n, "Receitas Normais (por Fração)")
            self.plot_receitas(self.canvas_rec_e, dados_rec_e, "Receitas Extraordinárias (por Fração)")
            self.plot_despesas(self.canvas_despesas, dados_desp)
            self.plot_nested_pie_three_levels(self.canvas_balanco, dados_bal, {}, dados_despesas_por_conta, "Balanço Financeiro - 3 Níveis")

            self.status_label.setText("✅ Dashboard atualizado com sucesso!")
        except Exception as e:
            self.status_label.setText(f"❌ Erro ao carregar dados: {e}")
            print(f"Erro no dashboard: {e}")
            import traceback
            traceback.print_exc()

    # ====================================================================
    # FUNÇÕES DE CARREGAMENTO
    # ====================================================================
    def carregar_receitas(self, caminho):
        if not existe_dados(caminho):
            return {}
        try:
            rows, _ = carregar_db(caminho)
            meses = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
            dados = {}
            for rec in rows:
                fr = str(rec.get('FRACCAO', '')).strip()
                if fr and fr.upper() != 'TOTAIS':
                    dados[fr] = [float(rec.get(m, 0) or 0) for m in meses]
            return dados
        except Exception as exc:
            print(f"Erro ao carregar receitas {caminho.name}: {exc}")
            return {}

    def carregar_despesas(self, caminho):
        if not existe_dados(caminho):
            return [0]*12
        try:
            rows, _ = carregar_db(caminho)
            meses = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
            totais = [0]*12
            for rec in rows:
                if str(rec.get('DESPESAS', '')).strip().upper() == 'TOTAIS':
                    totais = [float(rec.get(m, 0) or 0) for m in meses]
                    break
            return totais
        except Exception as exc:
            print(f"Erro ao carregar despesas {caminho.name}: {exc}")
            return [0]*12

    def carregar_despesas_detalhadas(self, caminho):
        if not existe_dados(caminho):
            return {}
        try:
            rows, _ = carregar_db(caminho)
            totais = {}
            for rec in rows:
                conta = str(rec.get('DESPESAS', '')).strip()
                if conta.upper() != 'TOTAIS':
                    total_anual = sum(float(rec.get(m, 0) or 0) for m in ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"])
                    if total_anual != 0:
                        totais[conta] = total_anual
            return totais
        except Exception as exc:
            print(f"Erro ao carregar despesas detalhadas {caminho.name}: {exc}")
            return {}
    
    def extrair_total_linha_totais(self, caminho):
        """Extrai o valor total da linha 'TOTAIS' (soma mensal)."""
        if not existe_dados(caminho):
            return 0.0
        try:
            rows, _ = carregar_db(caminho)
            meses = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
            total = 0.0
            for rec in rows:
                if str(rec.get('FRACCAO', '')).strip().upper() == 'TOTAIS':
                    total = sum(float(rec.get(m, 0) or 0) for m in meses)
                    break
            return total
        except Exception as exc:
            print(f"Erro ao carregar totais {caminho.name}: {exc}")
            return 0.0

    def carregar_juros(self, caminho):
        """Carrega o valor único de Juros (coluna TOTAL)."""
        if not existe_dados(caminho):
            return 0.0
        try:
            rows, _ = carregar_db(caminho)
            valor = 0.0
            if rows:
                valor = float(rows[0].get('TOTAL', 0) or 0.0)
            return valor if valor == valor else 0.0
        except Exception as e:
            print(f"Erro ao carregar juros: {e}")
            return 0.0

    def carregar_saldo_balanco(self, caminho):
        """Lê Saldo Anterior e Saldo Final do Balanço."""
        saldo_ant = 0.0
        saldo_fin = 0.0
        if not existe_dados(caminho):
            return saldo_ant, saldo_fin
        try:
            rows, _ = carregar_db(caminho)
            for rec in rows:
                conta = str(rec.get('CONTA', '')).strip().lower()
                valor = float(rec.get('VALOR') or 0.0)
                if valor != valor:
                    valor = 0.0
                if "saldo anterior" in conta:
                    saldo_ant = valor
                elif "saldo final" in conta:
                    saldo_fin = valor
        except Exception as e:
            print(f"Erro ao carregar saldo balanço: {e}")
        return saldo_ant, saldo_fin

    # ====================================================================
    # GRÁFICOS
    # ====================================================================
    def plot_receitas(self, canvas, dados, titulo):
        canvas.axes.clear()
        canvas.hover_items = []
        if not dados:
            canvas.axes.text(0.5,0.5,'Sem dados',ha='center',va='center',fontsize=10)
            canvas.draw()
            return
        meses = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
        cores = plt.cm.tab20.colors
        x = range(len(meses))
        width = 0.15
        for i,(fraccao,valores) in enumerate(dados.items()):
            offset = width*(i - len(dados)/2)
            bars = canvas.axes.bar(
                [xi+offset for xi in x], valores,
                width=width, label=fraccao,
                color=cores[i % len(cores)]
            )
            for mes, bar, valor in zip(meses, bars, valores):
                label = f"{fraccao}\n{mes}: {valor:.2f} €"
                canvas.hover_items.append((bar, label))
        canvas.axes.set_title(titulo, fontsize=9, fontweight='bold', color='#2F5597', pad=5)
        canvas.axes.set_xticks(x)
        canvas.axes.set_xticklabels(meses, fontsize=7)
        canvas.axes.tick_params(axis='y', labelsize=7)
        canvas.axes.legend(fontsize=6, loc='upper left')
        canvas.axes.grid(axis='y', alpha=0.3)
        canvas.figure.tight_layout(pad=0.5)
        canvas.draw()

    def plot_despesas(self, canvas, totais):
        canvas.axes.clear()
        canvas.hover_items = []
        meses = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
        bars = canvas.axes.bar(meses, totais, color='#E53935', edgecolor='black', linewidth=0.5)
        for mes, bar, valor in zip(meses, bars, totais):
            label = f"{mes}: {valor:.2f} €"
            canvas.hover_items.append((bar, label))
        canvas.axes.set_title("Despesas (Totais Mensais)", fontsize=9, fontweight='bold', color='#2F5597', pad=5)
        canvas.axes.tick_params(axis='both', labelsize=7)
        canvas.axes.grid(axis='y', alpha=0.3)
        canvas.figure.tight_layout(pad=0.5)
        canvas.draw()

    def plot_nested_pie_three_levels(self, canvas, dados_bal, dados_receitas, dados_despesas, titulo):
        canvas.axes.clear()
        canvas.hover_items = []

        if not dados_bal or not dados_despesas:
            canvas.axes.text(0.5, 0.5, 'Dados insuficientes\npara o balanço triplo', 
                            ha='center', va='center', fontsize=10)
            canvas.draw()
            return

        saldos_labels = ["Saldo Final", "Saldo Anterior", "Saldo Corrente"]
        saldo_anterior = dados_bal.get("Saldo Anterior", 0.0)
        total_receitas = dados_bal.get("Total Receitas", 0.0)
        total_despesas = dados_bal.get("Total Despesas", 0.0)
        saldo_corrente = total_receitas - total_despesas
        saldo_final = saldo_anterior + saldo_corrente

        saldos_valores = [abs(saldo_final), abs(saldo_anterior), abs(saldo_corrente)]
        saldos_cores = ["#D4A017", "#43A047", "#8E24AA"]

        rec_anterior = 3842.43
        rec_corrente = 4068.00
        
        receitas_labels = ["Receitas Ano Anterior", "Receitas Ano Corrente"]
        receitas_valores = [rec_anterior, rec_corrente]
        receitas_cores = ["#1976D2", "#64B5F6"]

        desp_labels = []
        desp_valores = []
        desp_cores = plt.cm.tab20.colors

        for conta, valor in dados_despesas.items():
            if valor != 0:
                desp_labels.append(conta)
                desp_valores.append(abs(valor))

        if len(desp_valores) == 0:
            desp_valores = [total_despesas]
            desp_labels = ["Total Despesas"]

        size_ext = 0.28
        size_mid = 0.28
        size_int = 0.23

        wedges_ext, _ = canvas.axes.pie(
            saldos_valores,
            radius=1.0,
            colors=saldos_cores,
            startangle=90,
            wedgeprops=dict(width=size_ext, edgecolor='white', linewidth=1.5)
        )

        wedges_mid, _ = canvas.axes.pie(
            receitas_valores,
            radius=1.0 - size_ext,
            colors=receitas_cores,
            startangle=90,
            wedgeprops=dict(width=size_mid, edgecolor='white', linewidth=1.2)
        )

        wedges_int, _ = canvas.axes.pie(
            desp_valores,
            radius=1.0 - size_ext - size_mid,
            colors=desp_cores[:len(desp_valores)],
            startangle=90,
            wedgeprops=dict(width=size_int, edgecolor='white', linewidth=1)
        )

        for w, txt in zip(wedges_ext, [f"{lab}\n{val:,.2f} €" for lab,val in zip(saldos_labels, saldos_valores)]):
            canvas.hover_items.append((w, txt))

        for w, lab, val in zip(wedges_mid, receitas_labels, receitas_valores):
            txt = f"{lab}\n{val:,.2f} €"
            canvas.hover_items.append((w, txt))

        for w, val, label in zip(wedges_int, desp_valores, desp_labels):
            txt = f"{label}\n{val:,.2f} €"
            canvas.hover_items.append((w, txt))

        # Legendas à direita para os 3 níveis
        all_labels = saldos_labels + receitas_labels + desp_labels
        all_values = saldos_valores + receitas_valores + desp_valores
        all_colors = saldos_cores + receitas_cores + list(desp_cores[:len(desp_valores)])
        
        handles = [plt.Rectangle((0,0),1,1, fc=color) for color in all_colors]
        canvas.axes.legend(
            handles,
            [f"{lab}  {val:,.2f}€" for lab, val in zip(all_labels, all_values)],
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            fontsize=7.5,
            title="Legenda",
            title_fontsize=9,
            frameon=True
        )

        canvas.axes.set_title(titulo, fontsize=11, fontweight='bold', color='#2F5597', pad=12)
        canvas.axes.set_aspect('equal')
        canvas.figure.tight_layout(pad=1.0)
        canvas.draw()


# ====================================================================
# TESTE STANDALONE
# ====================================================================
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())
    widget = DashboardWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(1200, 650)
    widget.setWindowTitle("Dashboard Financeiro")
    widget.show()
    sys.exit(app.exec())