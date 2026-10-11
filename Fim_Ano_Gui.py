"""
Fim_Ano_Gui.py - Widget de Encerramento de Ano
Layout com 8 elementos gráficos conforme especificação
"""

import sys
from pathlib import Path
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from Commons import BASE_DIR, carregar_db, existe_dados

# ====================================================================
# CANVAS PARA PIE CHART DE PROGRESSO
# ====================================================================
class ProgressPieCanvas(FigureCanvas):
    """Canvas para gráfico circular de progresso"""
    def __init__(self, parent=None):
        fig = Figure(figsize=(3, 3), dpi=80, facecolor='#395C8D')
        self.axes = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(240, 240)
        self.percentage = 0
        self.update_chart()

    def set_percentage(self, value):
        """Atualiza percentagem"""
        self.percentage = min(100, max(0, value))
        self.update_chart()

    def update_chart(self):
        """Redesenha o gráfico"""
        self.axes.clear()
        
        # Dados: progresso vs restante
        sizes = [self.percentage, 100 - self.percentage]
        colors = ['#FF8C42', '#2E5090']  # Laranja e Azul
        
        # Cria o pie chart
        wedges, _ = self.axes.pie(
            sizes,
            colors=colors,
            startangle=90,
            wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2)
        )
        
        # Texto central com percentagem
        self.axes.text(
            0, 0, f'{self.percentage}%',
            ha='center', va='center',
            fontsize=36, fontweight='bold', color='white'
        )
        
        self.axes.set_facecolor('#395C8D')
        self.figure.patch.set_facecolor('#395C8D')
        self.figure.tight_layout(pad=0)
        self.draw()


# ====================================================================
# WORKER THREAD
# ====================================================================
# ====================================================================
# WORKER THREAD
# ====================================================================
class FimAnoWorker(QThread):
    """Thread para executar Fim_Ano.py diretamente como módulo"""
    progresso = pyqtSignal(int)  # Percentagem 0-100
    concluido = pyqtSignal(bool, str)  # Sucesso, mensagem

    def __init__(self, pasta_dados):
        super().__init__()
        self.pasta_dados = pasta_dados

    def run(self):
        """Importa e executa fim_ano_e_transfere_saldo diretamente"""
        try:
            import sys
            from pathlib import Path

            pasta_trabalho = BASE_DIR / self.pasta_dados
            script_dir = str(BASE_DIR)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)

            self.progresso.emit(10)

            # Mudar diretório de trabalho
            import os
            old_cwd = os.getcwd()
            os.chdir(str(pasta_trabalho))

            # Importar e executar
            import Fim_Ano
            sucesso = Fim_Ano.fim_ano_e_transfere_saldo(pasta_dados=str(pasta_trabalho))

            os.chdir(old_cwd)  # Restaurar diretório

            self.progresso.emit(50)
            if sucesso:
                self.progresso.emit(100)
                self.concluido.emit(True, "Sucesso")
            else:
                self.concluido.emit(False, "Falha na execução de fim_ano_e_transfere_saldo()")
        except Exception as e:
            import traceback
            self.concluido.emit(False, f"{e}\n{traceback.format_exc()}")

# ====================================================================
# WIDGET PRINCIPAL
# ====================================================================
class FimAnoWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # ============================================================
        # 1. TÍTULO
        # ============================================================
        title = QLabel("Encerramento do Ano")
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #2F5597;
            padding: 8px;
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Espaçamento adicional de 30-35px (~10-12mm) após o título
        layout.addSpacing(35)

        # Layout horizontal: Botão + Form + Pie
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)

        # Coluna esquerda: Botão
        left_layout = QVBoxLayout()
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ============================================================
        # 2. BOTÃO (cor ajustada para #4A90E2)
        # ============================================================
        self.btn_encerrar = QPushButton("🔒 Encerrar Ano")
        self.btn_encerrar.setFixedSize(150, 120)
        self.btn_encerrar.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #888;
            }
        """)
        self.btn_encerrar.clicked.connect(self.iniciar_encerramento)
        left_layout.addWidget(self.btn_encerrar)
        left_layout.addStretch()
        main_layout.addLayout(left_layout)

        # Coluna central: Form
        center_layout = QVBoxLayout()

        # ============================================================
        # 3. FORM (Frame azul)
        # ============================================================
        self.form_frame = QFrame()
        self.form_frame.setStyleSheet("""
            QFrame {
                background-color: #395C8D;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        form_layout = QVBoxLayout(self.form_frame)
        form_layout.setSpacing(12)

        # Header do form
        form_header = QLabel("⚠️  ATENÇÃO: OPERAÇÃO DE ENCERRAMENTO DE ANO")
        form_header.setStyleSheet("""
            color: white;
            font-size: 13px;
            font-weight: bold;
            padding: 5px;
        """)
        form_layout.addWidget(form_header)

        # ============================================================
        # 4. INFORMAÇÕES
        # ============================================================
        self.info_label = QLabel()
        self.info_label.setStyleSheet("""
            color: white;
            font-size: 11px;
            line-height: 1.6;
            padding: 10px;
        """)
        self.info_label.setWordWrap(True)
        self.set_info_inicial()
        form_layout.addWidget(self.info_label)

        # Separador
        separator = QLabel("⚠️  ESTA OPERAÇÃO NÃO PODE SER DESFEITA!")
        separator.setStyleSheet("""
            color: #FFD700;
            font-size: 11px;
            font-weight: bold;
            padding: 8px;
        """)
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_layout.addWidget(separator)

        # ============================================================
        # 5. PASSWORD INPUT
        # ============================================================
        pass_layout = QHBoxLayout()
        pass_layout.setSpacing(10)

        pass_icon = QLabel("ℹ️")
        pass_icon.setStyleSheet("color: white; font-size: 16px;")
        pass_layout.addWidget(pass_icon)

        pass_text = QLabel("Insira a password para continuar:")
        pass_text.setStyleSheet("color: white; font-size: 11px;")
        pass_layout.addWidget(pass_text)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Password...")
        self.password_input.setFixedHeight(35)
        self.password_input.setStyleSheet("""
            QLineEdit {
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 2px solid #FFD700;
            }
        """)
        pass_layout.addWidget(self.password_input)

        form_layout.addLayout(pass_layout)

        center_layout.addWidget(self.form_frame)
        main_layout.addLayout(center_layout, stretch=2)

        # Coluna direita: Pie Chart
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pie_label = QLabel("Progresso")
        pie_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #2F5597;")
        pie_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(pie_label)

        # ============================================================
        # 6. PROGRESS PIE BAR
        # ============================================================
        self.progress_pie = ProgressPieCanvas(self)
        right_layout.addWidget(self.progress_pie)

        main_layout.addLayout(right_layout)

        layout.addLayout(main_layout)

        layout.addStretch()

        # ============================================================
        # 7. MENSAGEM DE CONCLUSÃO (rodapé)
        # ============================================================
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            font-size: 12px;
            font-weight: bold;
            color: #4CAF50;
            padding: 8px;
            border-top: 2px solid #ddd;
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status_label)

        # ============================================================
        # 8. RODAPÉ
        # ============================================================
        footer = QLabel("💡 Execute esta operação apenas no final do ano fiscal")
        footer.setStyleSheet("""
            font-size: 10px;
            color: #666;
            font-style: italic;
            padding: 5px;
        """)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

    def set_info_inicial(self):
        """Define texto inicial das informações"""
        texto = (
            "Esta operação irá:\n\n"            
            "1. Limpar todas as despesas mensais\n"
            "2. Transferir saldos de quotas para o próximo ano\n"
            "3. Limpar pagamentos mensais de quotas\n"
            "4. Limpar movimentos de Bancos e Caixa\n"
            "5. Transferir saldos finais para saldos iniciais\n\n"
        )
        self.info_label.setText(texto)

    def set_info_final(self):
        """Define texto final com checkmarks"""
        texto = (
            "✅  ENCERRAMENTO CONCLUÍDO!\n\n"
            "✅  Todas as operações foram executadas:\n"
            "🟢   Backup criado\n"
            "🟢   Dados limpos\n"
            "📊  Quotas atualizadas\n"
            "💰  Saldos transferidos\n"
            "💼  Balanço atualizado\n"
            "⭕   Sistema está pronto para o novo ano fiscal!"
        )
        self.info_label.setText(texto)

    def set_pasta_dados(self, pasta_dados):
        """Define pasta de dados"""
        self.pasta_dados = pasta_dados

    def validar_movimentos_bancarios(self):
        """Valida se existem movimentos em todos os meses do ano (condominio.db)."""
        try:
            bancos_path = BASE_DIR / self.pasta_dados / "Bancos"
            if not existe_dados(bancos_path):
                return True

            rows, _ = carregar_db(bancos_path)
            meses_com_movimento = set()
            for rec in rows:
                descricao = str(rec.get('DESCRICAO', '')).strip()
                if 'SALDO ANTERIOR' in descricao.upper() or '***' in descricao:
                    continue
                data = rec.get('DATA')
                if data:
                    try:
                        mes = pd.to_datetime(data).month
                        meses_com_movimento.add(mes)
                    except Exception:
                        pass

            if len(meses_com_movimento) < 12:
                meses_nomes = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", 
                              "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
                ultimo_mes = max(meses_com_movimento) if meses_com_movimento else 0
                ultimo_mes_nome = meses_nomes[ultimo_mes - 1] if ultimo_mes > 0 else "NENHUM"
                
                from PyQt6.QtWidgets import QMessageBox
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("⚠️ Aviso: Movimentos Incompletos")
                msg.setText(f"⚠️ ATENÇÃO: Só existem movimentos até {ultimo_mes_nome}!")
                msg.setInformativeText(
                    f"Foram detectados movimentos apenas em {len(meses_com_movimento)} meses.\n"
                    f"Último mês com movimentos: {ultimo_mes_nome}\n\n"
                    f"Deseja realmente encerrar o ano agora?"
                )
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setDefaultButton(QMessageBox.StandardButton.No)
                
                return msg.exec() == QMessageBox.StandardButton.Yes
            
            return True
            
        except Exception as e:
            print(f"Erro ao validar movimentos: {e}")
            return True

    def iniciar_encerramento(self):
        """Inicia processo de encerramento"""
        if not self.pasta_dados:
            self.status_label.setText("⚠️ Pasta de dados não definida")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            return

        # Valida password
        if self.password_input.text() != "admin123":
            self.status_label.setText("❌ Password incorreta!")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.password_input.clear()
            self.password_input.setFocus()
            return

        # ✅ NOVA VALIDAÇÃO: Verifica movimentos bancários
        if not self.validar_movimentos_bancarios():
            self.status_label.setText("⚠️ Encerramento cancelado pelo utilizador")
            self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            return

        # Desabilita controles
        self.btn_encerrar.setEnabled(False)
        self.password_input.setEnabled(False)
        self.status_label.setText("⏳ Processando encerramento...")
        self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")

        # Inicia worker
        self.worker = FimAnoWorker(self.pasta_dados)
        self.worker.progresso.connect(self.atualizar_progresso)
        self.worker.concluido.connect(self.encerramento_concluido)
        self.worker.start()

    def atualizar_progresso(self, percentagem):
        """Atualiza pie chart de progresso"""
        self.progress_pie.set_percentage(percentagem)

    def encerramento_concluido(self, sucesso, mensagem):
        """Chamado quando processo termina"""
        self.btn_encerrar.setEnabled(True)
        self.password_input.setEnabled(True)

        if sucesso:
            # Limpa password
            self.password_input.clear()
            
            # Atualiza informações com checkmarks
            self.set_info_final()
            
            # Mensagem de sucesso
            self.status_label.setText("✅ Encerramento concluído - A refrescar dados...")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 14px;")
            
            # Progresso 100%
            self.progress_pie.set_percentage(100)
            
            # Atualiza mensagem após 1 segundo
            QTimer.singleShot(1000, lambda: self.status_label.setText("✅ Encerramento concluído - Dados atualizados!"))
        else:
            self.status_label.setText(f"❌ Erro: {mensagem}")
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            self.progress_pie.set_percentage(0)


# ====================================================================
# TESTE STANDALONE
# ====================================================================
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())

    widget = FimAnoWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(1200, 675)
    widget.setWindowTitle("Encerramento de Ano")
    widget.show()

    sys.exit(app.exec())