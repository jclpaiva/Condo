"""
Main_Gui.py - VERSÃO COMPLETA COM INTEGRAÇÃO GMAIL (com leitura dinâmica do registry)
"""
import os
import sys
import shlex
import winreg
import subprocess

from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QFrame, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QPixmap, QIcon

# Importa código compartilhado
from Commons import BASE_DIR, ICONS_DIR, FOTOS_DIR, PASTA_CORRENTE, PASTA_HISTORICO, get_app_stylesheet

# Importa widgets específicos
from Bancos_Gui import BancosWidget
from Caixa_Gui import CaixaWidget
from DPrazo_Gui import DPrazoWidget
from Despesas_Gui import DespesasWidget
from Receitas_Gui import ReceitasWidget
from Balanco_Gui import BalancoWidget
from Dashboard_Gui import DashboardWidget
from Fim_Ano_Gui import FimAnoWidget
from Configuracoes_Gui import ConfiguracoesWidget
from Condominos_Gui import CondominosWidget
from Docs_Gui import DocsWidget


# ====================================================================
# Função auxiliar para ler comando do registry (Mailspring)
# ====================================================================
def get_mailspring_launch_cmd():
    """Lê o comando de lançamento do Mailspring do registry (se for cliente de email default)"""
    try:
        key_path = r"Software\Clients\Mail\Mailspring\Protocols\mailto\shell\open\command"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "")
        winreg.CloseKey(key)

        if not value:
            return None

        # Parseia o comando respeitando aspas e caminhos com espaços
        parts = shlex.split(value)

        # Formato esperado: "C:\...\Update.exe" --processStart mailspring.exe --process-start-args "%1"
        if len(parts) >= 3 and parts[1] == "--processStart" and parts[2].lower() == "mailspring.exe":
            # Retornamos só o launcher + --processStart (sem args extras como %1)
            return [parts[0], "--processStart", "mailspring.exe"]

        # Caso raro: se registou directamente o mailspring.exe
        if parts and parts[0].lower().endswith("mailspring.exe"):
            return [parts[0]]

        return None

    except (OSError, FileNotFoundError, Exception) as e:
        # Key não existe (Mailspring não é default mail client) ou erro de leitura
        print(f"Erro ao ler registry Mailspring: {e}")
        return None


# ====================================================================
# BOTÃO CUSTOMIZADO COM HOVER
# ====================================================================
class HoverButton(QPushButton):
    """Botão com troca de ícone no hover"""
    def __init__(self, normal_path, hover_path, parent=None):
        super().__init__(parent)
        
        self.normal_icon = QIcon(str(normal_path)) if normal_path.exists() else QIcon()
        self.hover_icon = QIcon(str(hover_path)) if hover_path.exists() else QIcon()
        self.setIcon(self.normal_icon)
        self.setIconSize(QSize(100, 50))
        self.setFixedSize(100, 50)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, event):
        self.setIcon(self.hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self.normal_icon)
        super().leaveEvent(event)


# ====================================================================
# JANELA PRINCIPAL
# ====================================================================
class MainWindow(QMainWindow):
    """Janela principal da aplicação"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("O Meu Condomínio R2.0 - Av. Sto António 42")
        appicon_dir = ICONS_DIR / "app_icon.png"
        self.setWindowIcon(QIcon(str(appicon_dir))) # Define o ícone da barra de título
        self.resize(1200, 700)
        
        # Centraliza na tela
        try:
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - 1200) // 2, (screen.height() - 770) // 2)
        except Exception as e:
            print(f"Erro ao centralizar janela: {e}")
        
        # Estado
        self.pasta_dados = None
        self.ano_selecionado = None
        
        # Widgets dos módulos
        self.dashboard_widget = None
        self.bancos_widget = None
        self.caixa_widget = None
        self.dprazo_widget = None        
        self.despesas_widget = None
        self.receitas_widget = None
        self.balanco_widget = None
        self.condominos_widget = None
        self.configuracoes_widget = None
        self.fim_ano_widget = None
        self.docs_widget = None
        
        # ✅ NOVO: Comando de lançamento do Mailspring (lido do registry ou fallback)
        self.mailspring_launch_cmd = get_mailspring_launch_cmd()
        
        self.init_ui()

    def init_ui(self):
        """Inicializa interface"""
        try:
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Tabs
            self.tabs = QTabWidget()
            self.tabs.setTabPosition(QTabWidget.TabPosition.North)
            # CSS para estilizar a aba "Sair"
            self.tabs.setStyleSheet("""
                QTabBar::tab[text="Sair"] {
                    background-color: #ffcccc;
                    color: red;
                    font-weight: bold;
                    border: 1px solid #ff9999;
                    padding: 8px 16px;
                }
                QTabBar::tab[text="Sair"]:hover {
                    background-color: #ff9999;
                    color: white;
                }
            """)
            
            # ✅ NOVO: Adiciona botão Gmail no canto direito
            self.adicionar_botao_gmail()
            
            layout.addWidget(self.tabs)

            # Tab Home
            self.home_widget = self.criar_home()
            self.tabs.addTab(self.home_widget, "Home")

            # Tabs dos módulos (serão inicializados quando selecionar ano)
            self.tab_dashboard_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Dashboard"
            )
            self.tab_bancos_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "D.Ordem"
            )
            self.tab_dprazo_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "D.Prazo"
            )
            self.tab_caixa_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Caixa"
            )
            self.tab_receitas_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Receitas"
            )
            self.tab_despesas_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Despesas"
            )
            self.tab_balanco_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Balanço"
            )
            self.tab_condominos_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Condóminos"
            )
            self.tab_docs_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Documentos"
            )
            self.tab_fim_ano_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Encerrar Ano"
            )
            self.tab_configuracoes_index = self.tabs.addTab(
                QLabel("<h2>Selecione o ano de trabalho</h2>", alignment=Qt.AlignmentFlag.AlignCenter), 
                "Configurações"
            )

            # ABA "SAIR" NO FINAL
            self.exit_tab_index = self.tabs.addTab(QWidget(), "Sair")

            # Conectar clique na barra de abas
            self.tabs.tabBar().tabBarClicked.connect(self.on_tab_clicked)

            # Footer com saldo consolidado
            self.footer = QFrame()
            self.footer.setFixedHeight(25)
            footer_layout = QHBoxLayout(self.footer)
            footer_layout.setContentsMargins(0, 0, 0, 0)
            
            # Label Saldo Bancário (centralizado, inicialmente oculto)
            self.lbl_saldo_bancario = QLabel("Saldo Bancário => 0,00 €")
            self.lbl_saldo_bancario.setStyleSheet("font-size: 12px; font-weight: bold; color: #1976d2;")
            self.lbl_saldo_bancario.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_saldo_bancario.setVisible(False)
            
            # Label Saldo Poupança (centralizado, inicialmente oculto)
            self.lbl_saldo_dprazo = QLabel("Saldo Poupança => 0,00 €")
            self.lbl_saldo_dprazo.setStyleSheet("font-size: 12px; font-weight: bold; color: #A349A4;")
            self.lbl_saldo_dprazo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_saldo_dprazo.setVisible(False)

            # Label Saldo Caixa (centralizado, inicialmente oculto)
            self.lbl_saldo_caixa = QLabel("Saldo Caixa => 0,00 €")
            self.lbl_saldo_caixa.setStyleSheet("font-size: 12px; font-weight: bold; color: #2e7d32;")
            self.lbl_saldo_caixa.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_saldo_caixa.setVisible(False)
            
            footer_layout.addWidget(self.lbl_saldo_bancario)
            footer_layout.addWidget(self.lbl_saldo_dprazo)
            footer_layout.addWidget(self.lbl_saldo_caixa)
            
            layout.addWidget(self.footer)

            # Conecta mudança de tab para atualizar Msg saldo no rodape
            self.tabs.currentChanged.connect(self.atualizar_saldos)
            
        except Exception as e:
            print(f"Erro ao inicializar UI: {e}")
            import traceback
            traceback.print_exc()

    # ✅ NOVO MÉTODO: Adiciona botão Gmail
    def adicionar_botao_gmail(self):
        """Adiciona botão Gmail no canto superior direito das tabs"""
        try:
            self.btn_gmail = QPushButton()
            icon_path = ICONS_DIR / "gmail-icon.png"
            
            if icon_path.exists():
                self.btn_gmail.setIcon(QIcon(str(icon_path)))
                self.btn_gmail.setIconSize(QSize(24, 24))
            else:
                # Fallback: emoji se não encontrar ícone
                self.btn_gmail.setText("📧")
                self.btn_gmail.setStyleSheet("font-size: 14px;")
            
            self.btn_gmail.setFixedSize(36, 36)
            self.btn_gmail.setToolTip("Abrir Cliente Gmail (Mailspring)")
            self.btn_gmail.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: 2px solid transparent;
                    border-radius: 18px;
                }
                QPushButton:hover {
                    background-color: #f0f0f0;
                    border: 2px solid #1976d2;
                }
                QPushButton:pressed {
                    background-color: #e0e0e0;
                }
            """)
            
            self.btn_gmail.clicked.connect(self.abrir_mailspring)
            
            # Coloca no canto direito da barra de tabs
            self.tabs.setCornerWidget(self.btn_gmail, Qt.Corner.TopRightCorner)
            
        except Exception as e:
            print(f"Erro ao adicionar botão Gmail: {e}")

    # ✅ MÉTODO ATUALIZADO: Abre Mailspring usando registry ou fallback
    def abrir_mailspring(self):
        """Abre o cliente Mailspring (Gmail) usando o comando do registry quando possível"""
        try:
            launched = False

            # 1. Tentar via registry (mais fiel e respeita updates)
            if self.mailspring_launch_cmd:
                try:
                    subprocess.Popen(
                        self.mailspring_launch_cmd, 
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    launched = True
                except Exception as e:
                    print(f"Erro ao lançar via registry: {e}")

            # 2. Fallback: caminhos comuns no LOCALAPPDATA (se registry não existir)
            if not launched:
                local_appdata = os.getenv('LOCALAPPDATA')
                if local_appdata:
                    # Caminho mais comum
                    candidate = os.path.join(local_appdata, r"Mailspring\mailspring.exe")
                    if os.path.isfile(candidate):
                        try:
                            subprocess.Popen([candidate], creationflags=subprocess.CREATE_NO_WINDOW)
                            launched = True
                        except Exception as e:
                            print(f"Erro ao lançar via caminho comum: {e}")

                    # Fallback para pastas de versão (ex: app-1.14.0\mailspring.exe)
                    if not launched:
                        mailspring_dir = os.path.join(local_appdata, "Mailspring")
                        if os.path.isdir(mailspring_dir):
                            for entry in os.scandir(mailspring_dir):
                                if entry.is_dir() and entry.name.startswith("app-"):
                                    exe = os.path.join(entry.path, "mailspring.exe")
                                    if os.path.isfile(exe):
                                        try:
                                            subprocess.Popen(
                                                [exe], 
                                                creationflags=subprocess.CREATE_NO_WINDOW
                                            )
                                            launched = True
                                            break
                                        except Exception as e:
                                            print(f"Erro ao lançar via versão: {e}")

            # Se ainda não lançou → aviso ao utilizador
            if not launched:
                QMessageBox.warning(
                    self,
                    "❌ Cliente Gmail Não Encontrado",
                    "Não foi possível encontrar ou abrir o Mailspring.\n\n"
                    "Verifique se está instalado corretamente."
                )
                
        except Exception as e:
            print(f"Erro em abrir_mailspring: {e}")
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao abrir cliente de email:\n{e}"
            )

    def on_tab_clicked(self, index):
        """Trata clique em qualquer aba – se for 'Sair', mostra confirmação"""
        try:
            if index == self.exit_tab_index:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Confirmação de Saída")
                msg_box.setText("Deseja realmente sair da aplicação?")
                msg_box.setIcon(QMessageBox.Icon.Question)
                msg_box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                msg_box.setDefaultButton(QMessageBox.StandardButton.No)
                
                msg_box.setStyleSheet("""
                    QMessageBox {
                        min-width: 400px;
                        min-height: 150px;
                    }
                    QPushButton {
                        min-width: 90px;
                        min-height: 25px;
                        font-size: 12px;
                        font-weight: bold;
                    }
                """)

                result = msg_box.exec()

                if result == QMessageBox.StandardButton.Yes:
                    self.close()
                else:
                    self.tabs.setCurrentIndex(0)
        except Exception as e:
            print(f"Erro em on_tab_clicked: {e}")

    def criar_home(self):
        """Cria widget da tela Home"""
        try:
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            lay.setSpacing(30)
            lay.setContentsMargins(40, 60, 40, 40)

            # Logo centralizado
            logo_container = QHBoxLayout()
            logo_container.addStretch()
            logo_label = QLabel()
            logo_path = ICONS_DIR / "logo.png"
            if logo_path.exists():
                pix = QPixmap(str(logo_path)).scaled(
                    300, 300,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                logo_label.setPixmap(pix)
            else:
                logo_label.setText("o meu condomínio")
                logo_label.setStyleSheet("font-size: 36px; font-weight: bold; color: #1976d2;")
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_container.addWidget(logo_label)
            logo_container.addStretch()
            lay.addLayout(logo_container)
            lay.addSpacing(20)

            # Botões de seleção de ano
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            btn_corrente = QPushButton("Trabalhar no Ano Corrente")
            btn_corrente.setFixedSize(250, 70)
            btn_corrente.clicked.connect(self.selecionar_corrente)
            btn_historico = QPushButton("Consultar Exercícios Anteriores")
            btn_historico.setFixedSize(250, 70)
            btn_historico.clicked.connect(self.selecionar_historico)
            btn_layout.addWidget(btn_corrente)
            btn_layout.addSpacing(30)
            btn_layout.addWidget(btn_historico)
            btn_layout.addStretch()
            lay.addLayout(btn_layout)
            lay.addStretch()
            return w
        except Exception as e:
            print(f"Erro ao criar home: {e}")
            return QWidget()

    def selecionar_corrente(self):
        """Seleciona ano corrente para trabalho"""
        try:
            self.pasta_dados = PASTA_CORRENTE
            self.ano_selecionado = "Ano Corrente"
            self.setWindowTitle(f"O Meu Condomínio - Av. Sto António 42 | Exercício: Ano Corrente")
            self.inicializar_widgets()
        except Exception as e:
            print(f"Erro ao selecionar corrente: {e}")
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao selecionar ano corrente:\n{e}"
            )

    def selecionar_historico(self):
        """Seleciona ano histórico para consulta"""
        try:
            hist_path = BASE_DIR / PASTA_HISTORICO
            if not hist_path.exists():
                QMessageBox.warning(self, "Aviso", "Pasta 'historico' não encontrada.")
                return
            anos = sorted(
                [d.name for d in hist_path.iterdir() if d.is_dir() and d.name.isdigit()],
                reverse=True
            )
            if not anos:
                QMessageBox.information(self, "Info", "Nenhum ano histórico encontrado.")
                return
            ano, ok = QInputDialog.getItem(
                self,
                "Selecionar Ano",
                "Exercício:",
                anos,
                0,
                False
            )
            if ok:
                self.pasta_dados = os.path.join(PASTA_HISTORICO, ano)
                self.ano_selecionado = ano
                self.setWindowTitle(f"O Meu Condomínio - Av. Sto António 42 | Exercício: {ano}")
                self.inicializar_widgets()
        except Exception as e:
            print(f"Erro ao selecionar histórico: {e}")
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao selecionar ano histórico:\n{e}"
            )

    def inicializar_widgets(self):
        """Inicializa widgets dos módulos após seleção de ano"""
        if not self.pasta_dados:
            return

        try:
            # ✅ Força recriação de todos os widgets ao mudar de ano
            self.dashboard_widget = None
            self.bancos_widget = None
            self.caixa_widget = None
            self.dprazo_widget = None
            self.despesas_widget = None
            self.receitas_widget = None
            self.balanco_widget = None
            self.condominos_widget = None
            self.configuracoes_widget = None
            self.fim_ano_widget = None
            self.docs_widget = None

            # Widget de Dashboard
            self.dashboard_widget = DashboardWidget(parent=self)
            self.tabs.removeTab(self.tab_dashboard_index)
            self.tab_dashboard_index = self.tabs.insertTab(
                self.tab_dashboard_index, self.dashboard_widget, "Dashboard"
            )
            self.dashboard_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Bancos
            self.bancos_widget = BancosWidget(parent=self)
            self.tabs.removeTab(self.tab_bancos_index)
            self.tab_bancos_index = self.tabs.insertTab(
                self.tab_bancos_index, self.bancos_widget, "D.Ordem"
            )
            self.bancos_widget.set_pasta_dados(self.pasta_dados)
            # Atualiza o saldo no rodapé após importação de CSV
            self.bancos_widget.saldo_atualizado.connect(self.atualizar_saldos)

            # Widget de DPrazo
            self.dprazo_widget = DPrazoWidget(parent=self)
            self.tabs.removeTab(self.tab_dprazo_index)
            self.tab_dprazo_index = self.tabs.insertTab(
                self.tab_dprazo_index, self.dprazo_widget, "D.Prazo"
            )
            self.dprazo_widget.set_pasta_dados(self.pasta_dados)
            
            # Widget de Caixa
            self.caixa_widget = CaixaWidget(parent=self)
            self.tabs.removeTab(self.tab_caixa_index)
            self.tab_caixa_index = self.tabs.insertTab(
                self.tab_caixa_index, self.caixa_widget, "Caixa"
            )
            self.caixa_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Receitas
            self.receitas_widget = ReceitasWidget(parent=self)
            self.tabs.removeTab(self.tab_receitas_index)
            self.tab_receitas_index = self.tabs.insertTab(
                self.tab_receitas_index, self.receitas_widget, "Receitas"
            )
            self.receitas_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Despesas
            self.despesas_widget = DespesasWidget(parent=self)
            self.tabs.removeTab(self.tab_despesas_index)
            self.tab_despesas_index = self.tabs.insertTab(
                self.tab_despesas_index, self.despesas_widget, "Despesas"
            )
            self.despesas_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Balanço
            self.balanco_widget = BalancoWidget(parent=self)
            self.tabs.removeTab(self.tab_balanco_index)
            self.tab_balanco_index = self.tabs.insertTab(
                self.tab_balanco_index, self.balanco_widget, "Balanço"
            )
            self.balanco_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Documentos
            self.docs_widget = DocsWidget(parent=self)
            self.tabs.removeTab(self.tab_docs_index)
            self.tab_docs_index = self.tabs.insertTab(
                self.tab_docs_index, self.docs_widget, "Documentos"
            )
            self.docs_widget.set_pasta_dados(self.pasta_dados)
            
            # Widget de Condominos
            self.condominos_widget = CondominosWidget(parent=self)
            self.tabs.removeTab(self.tab_condominos_index)
            self.tab_condominos_index = self.tabs.insertTab(
                self.tab_condominos_index, self.condominos_widget, "Condóminos"
            )
            self.condominos_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Encerramento do exercicio
            self.fim_ano_widget = FimAnoWidget(parent=self)
            self.tabs.removeTab(self.tab_fim_ano_index)
            self.tab_fim_ano_index = self.tabs.insertTab(
                self.tab_fim_ano_index, self.fim_ano_widget, "Encerrar Ano"
            )
            self.fim_ano_widget.set_pasta_dados(self.pasta_dados)

            # Widget de Configurações
            self.configuracoes_widget = ConfiguracoesWidget(parent=self)
            self.tabs.removeTab(self.tab_configuracoes_index)
            self.tab_configuracoes_index = self.tabs.insertTab(
                self.tab_configuracoes_index, self.configuracoes_widget, "Configurações"
            )
            self.configuracoes_widget.set_pasta_dados(self.pasta_dados)

            # Atualiza Msg saldos no rodapé
            self.atualizar_saldos()
            
            # Muda para tab Dashboard automaticamente
            self.tabs.setCurrentIndex(self.tab_dashboard_index)
            
        except Exception as e:
            print(f"Erro ao inicializar widgets: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao inicializar módulos:\n{e}"
            )

    def atualizar_saldos(self):
        """Atualiza saldos no footer - mostra apenas na aba correspondente"""
        try:
            current_index = self.tabs.currentIndex()
            
            is_bancos = (current_index == self.tab_bancos_index)
            is_dprazo = (current_index == self.tab_dprazo_index)
            is_caixa = (current_index == self.tab_caixa_index)
            
            if is_bancos and self.bancos_widget:
                saldo_bancario = float(self.bancos_widget.get_saldo_final() or 0.0)
                txt = f"{saldo_bancario:,.2f} €"
                self.lbl_saldo_bancario.setText(f"Saldo Bancário => {txt}")
                self.lbl_saldo_bancario.setVisible(True)
            else:
                self.lbl_saldo_bancario.setVisible(False)

            if is_dprazo and self.dprazo_widget:
                self.dprazo_widget.carregar_tabela()  # Atualiza tabela DPrazo na UI
                saldo_dprazo = float(self.dprazo_widget.get_saldo_final() or 0.0)
                txt = f"{saldo_dprazo:,.2f} €"
                self.lbl_saldo_dprazo.setText(f"Saldo Poupança => {txt}")
                self.lbl_saldo_dprazo.setVisible(True)
            else:
                self.lbl_saldo_dprazo.setVisible(False)
            
            if is_caixa and self.caixa_widget:
                saldo_caixa = float(self.caixa_widget.get_saldo_final() or 0.0)
                txt = f"{saldo_caixa:,.2f} €"
                self.lbl_saldo_caixa.setText(f"Saldo Caixa => {txt}")
                self.lbl_saldo_caixa.setVisible(True)
            else:
                self.lbl_saldo_caixa.setVisible(False)
                
        except Exception as e:
            print(f"Erro ao atualizar saldos: {e}")


# ====================================================================
# PONTO DE ENTRADA
# ====================================================================
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setStyleSheet(get_app_stylesheet())
        app.setFont(QFont("Segoe UI", 9))
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"Erro fatal na aplicação: {e}")
        import traceback
        traceback.print_exc()