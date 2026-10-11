"""
Balanco_Gui.py - Widget de visualização do Balanço Anual (CORRIGIDO)
✅ Remove redundância: lê Saldo Exercício de Saldos (fonte única de verdade)
"""

import os
import sys
import Balanco

from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QHeaderView, QMessageBox, QLabel, QStyledItemDelegate,
    QProgressDialog
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize, QUrl, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QDesktopServices
from Commons import BASE_DIR, carregar_db, existe_dados
from Report import gerar_pdf_relatorio
from Report_AI import gerar_report_ai

class CompactDelegate(QStyledItemDelegate):
    """Delegate para reduzir altura das linhas"""
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(22)
        return size


class BalancoTableModel(QAbstractTableModel):
    """Modelo para tabela de balanço em formato T (Débitos | Créditos)"""
    
    def __init__(self):
        super().__init__()
        self._data_esquerda = []
        self._data_direita = []
        self.headers = ["DÉBITOS", "VALOR", "CRÉDITOS", "VALOR"]

    def rowCount(self, parent=QModelIndex()):
        return max(len(self._data_esquerda), len(self._data_direita))

    def columnCount(self, parent=QModelIndex()):
        return 4

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return QVariant()
        
        row = index.row()
        col = index.column()
        
        if col < 2:
            if row >= len(self._data_esquerda):
                return QVariant()
            data_row = self._data_esquerda[row]
        else:
            if row >= len(self._data_direita):
                return QVariant()
            data_row = self._data_direita[row]
        
        conta = data_row.get('CONTA', '')
        tipo = data_row.get('TIPO', '')
        valor = data_row.get('VALOR', 0.0)
        
        if col in [0, 2]:  # Coluna de texto
            if role == Qt.ItemDataRole.DisplayRole:
                return conta
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            elif role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setPointSize(9)
                if tipo in ['TOTAL', 'SUBTOTAL']:
                    font.setBold(True)
                elif tipo == 'TITULO':
                    font.setBold(True)
                return font
            elif role == Qt.ItemDataRole.ForegroundRole:
                if tipo in ['TOTAL', 'TITULO', 'SUBTOTAL']:
                    return QBrush(QColor("#2F5597"))
            elif role == Qt.ItemDataRole.BackgroundRole:
                if tipo == 'TOTAL':
                    return QBrush(QColor("#E9EFF7"))
        
        elif col in [1, 3]:  # Coluna de valor
            if role == Qt.ItemDataRole.DisplayRole:
                if valor > 0.01 or tipo in ['TOTAL', 'SUBTOTAL', 'SALDO']:
                    return f"{valor:,.2f}"
                return ""
            elif role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            elif role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setPointSize(9)
                if tipo in ['TOTAL', 'SUBTOTAL']:
                    font.setBold(True)
                return font
            elif role == Qt.ItemDataRole.ForegroundRole:
                if tipo in ['TOTAL', 'SUBTOTAL', 'SALDO']:
                    return QBrush(QColor("#2F5597"))
            elif role == Qt.ItemDataRole.BackgroundRole:
                if tipo == 'TOTAL':
                    return QBrush(QColor("#E9EFF7"))
        
        return QVariant()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return QVariant()

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def load_from_db(self, caminho):
        """Carrega o balanço a partir de condominio.db, mantendo o layout em dois lados."""
        self.beginResetModel()
        self._data_esquerda = []
        self._data_direita = []
        
        if not existe_dados(caminho):
            self.endResetModel()
            return False
        
        try:
            rows, _ = carregar_db(caminho)
            lado_esquerdo = True
            
            for rec in rows:
                conta = str(rec.get('CONTA', '')).strip()
                tipo = str(rec.get('TIPO', '')).strip()
                valor = float(rec.get('VALOR') or 0.0)
                
                if conta == '--- LADO DIREITO ---':
                    lado_esquerdo = False
                    continue
                
                row = {'CONTA': conta, 'TIPO': tipo, 'VALOR': valor}
                
                if lado_esquerdo:
                    self._data_esquerda.append(row)
                else:
                    self._data_direita.append(row)
            
            self.endResetModel()
            return True
            
        except Exception as e:
            print(f"❌ Erro ao carregar Balanco: {e}")
            self.endResetModel()
            return False


class ReportAIWorker(QThread):
    """
    Thread para gerar o Relatório AI sem bloquear a GUI - o pedido ao serviço
    de IA (OpenRouter) pode demorar dezenas de segundos (com retries em caso
    de timeout/rate-limit), e correr isso na thread principal congela a
    janela inteira sem qualquer indicação visual de progresso.
    """
    concluido = pyqtSignal(bool, str)  # sucesso, caminho_pdf_ou_mensagem_de_erro

    def __init__(self, pasta_dados):
        super().__init__()
        self.pasta_dados = pasta_dados

    def run(self):
        try:
            pdf_path = gerar_report_ai(self.pasta_dados)
            if pdf_path:
                self.concluido.emit(True, pdf_path)
            else:
                self.concluido.emit(
                    False,
                    "Não foi possível gerar o relatório de IA.\n\n"
                    "Motivo mais provável: falha ao contactar o serviço de IA "
                    "(chave de API em falta/inválida, sem créditos, ou sem rede).\n"
                    "Consulte a consola/logs para o erro exacto."
                )
        except Exception as e:
            self.concluido.emit(False, f"Erro ao gerar relatório de IA:\n{e}")


class BalancoWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        title = QLabel("Balanço da Administração")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        btn_bar = QHBoxLayout()
        btn_atualizar = QPushButton("💰 Atualizar Balanço  ")
        btn_atualizar.setFixedSize(150, 42)
        btn_atualizar.clicked.connect(self.atualizar_balanco)
        btn_bar.addWidget(btn_atualizar)

        btn_report = QPushButton("📄 Pdf do Balanço")
        btn_report.setFixedSize(130, 42)
        btn_report.clicked.connect(self.gerar_report)
        btn_bar.addWidget(btn_report)

        btn_report_ai = QPushButton("🤖 Report AI")
        btn_report_ai.setFixedSize(110, 42)
        btn_report_ai.clicked.connect(self.gerar_report_ai)
        btn_bar.addWidget(btn_report_ai)

        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        self.table_view = QTableView()
        self.model = BalancoTableModel()
        self.table_view.setModel(self.model)
        
        self.compact_delegate = CompactDelegate()
        self.table_view.setItemDelegate(self.compact_delegate)

        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)
        header.setDefaultSectionSize(100)
        header.setFixedHeight(32)
        
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        
        header.resizeSection(1, 110)
        header.resizeSection(3, 110)

        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setStyleSheet("""
            QTableView {
                gridline-color: #C0C0C0;
                border: 1px solid #C0C0C0;
                font-size: 9pt;
            }
            QTableView::item {
                padding: 2px 5px;
            }
            QHeaderView::section {
                background-color: #2F5597;
                color: white;
                font-weight: bold;
                font-size: 9pt;
                padding: 5px;
                border: 1px solid #1F4587;
            }
        """)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_view.verticalHeader().setVisible(False)  # Esconder números das linhas
        
        layout.addWidget(self.table_view)

        self.status_label = QLabel("Aguardando dados...")
        self.status_label.setStyleSheet("color: #666; font-style: italic; font-size: 8pt; padding: 2px;")
        layout.addWidget(self.status_label)

    def set_pasta_dados(self, pasta_dados):
        """Define pasta de dados e carrega Balanço se existir"""
        self.pasta_dados = pasta_dados
        self.caminho_balanco_db = BASE_DIR / pasta_dados / "Balanco"
        self.caminho_saldos_db = BASE_DIR / pasta_dados / "Saldos"  # ✅ NOVO
        self.caminho_juros_db = BASE_DIR / pasta_dados / "Juros"  # ✅ NOVO
 
        if existe_dados(self.caminho_balanco_db):
            if self.model.load_from_db(str(self.caminho_balanco_db)):
                # ✅ CORRIGIDO: Lê de Saldos (fonte única de verdade)
                self._carregar_saldo_exercicio()
            else:
                self.status_label.setText("⚠️ Erro ao carregar Balanço")
        else:
            self.status_label.setText("📂 Balanço não encontrado. Clique em 'Atualizar Balanço'.")
            
        
    def atualizar_balanco(self):
        """Executa processar_balanco() e atualizar_saldos_finais()"""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return

        pasta_trabalho = BASE_DIR / self.pasta_dados
        script_dir = str(BASE_DIR)

        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        #self.status_label.setText("⏳ Processando balanço...")
        #QMessageBox.information(
        #    self,
        #    "Processamento",
        #    "A calcular balanço...\nEste processo pode demorar alguns segundos.",
        #    QMessageBox.StandardButton.Ok
        #)

        try:
            old_cwd = os.getcwd()
            os.chdir(str(pasta_trabalho))

            # BUGFIX (arquitetural): antes, estas chamadas usavam nomes de
            # ficheiro simples (ex.: 'Despesas') confiando no
            # os.chdir() acima para "apontar" para pasta_trabalho. Isso
            # funcionava com o back-end anterior, mas deixou de funcionar com o
            # back-end SQLite: o bridge (Commons.py) resolve nomes sem
            # componente de pasta sempre para a PASTA_CORRENTE global,
            # fixada uma única vez no arranque — ignora por completo
            # os.chdir(). Na prática, ao processar o balanço de uma pasta
            # histórica (self.pasta_dados apontado para PASTA_HISTORICO/ano
            # via Main_Gui), isto lia e GRAVAVA sempre no condominio.db da
            # pasta corrente (ano corrente) em vez do ano histórico
            # pretendido — confirmado com teste. A correção é passar
            # caminhos completos, resolvidos explicitamente a partir de
            # pasta_trabalho, em vez de depender do directório de trabalho
            # do processo. O os.chdir() é mantido por segurança/
            # compatibilidade mas deixa de ser necessário para a
            # correção dos caminhos.
            despesas_db = str(pasta_trabalho / 'Despesas')
            receitas_n_db = str(pasta_trabalho / 'ReceitasN')
            receitas_e_db = str(pasta_trabalho / 'ReceitasE')
            saldos_db = str(pasta_trabalho / 'Saldos')
            juros_db = str(pasta_trabalho / 'Juros')
            balanco_db = str(pasta_trabalho / 'Balanco')
            bancos_db = str(pasta_trabalho / 'Bancos')
            caixa_db = str(pasta_trabalho / 'Caixa')
            dprazo_db = str(pasta_trabalho / 'DPrazo')

            # Chamar funções diretamente
            resultado = Balanco.processar_balanco(
                despesas_db=despesas_db,
                receitas_n_db=receitas_n_db,
                receitas_e_db=receitas_e_db,
                saldos_db=saldos_db,
                juros_db=juros_db,
                balanco_db=balanco_db,
                exportar_excel=False,
                bancos_db=bancos_db,
                caixa_db=caixa_db,
            )

            # ✅ IMPORTANTE: Atualizar Saldos (inclui Saldo Exercício)
            Balanco.atualizar_saldos_finais(
                saldos_db=saldos_db,
                bancos_db=bancos_db,
                caixa_db=caixa_db,
                juros_db=juros_db,
                dprazo_db=dprazo_db,
            )

            os.chdir(old_cwd)  # Restaurar diretório original

            # ✅ CORRIGIDO: Obtém valores do resultado
            receitas = resultado.get('total_receitas', 0.0)
            despesas = resultado.get('total_despesas', 0.0)
            saldo_exercicio = resultado.get('saldo_exercicio', 0.0)
            
            if self.model.load_from_db(str(self.caminho_balanco_db)):
                # ✅ CORRIGIDO: Lê de Saldos para garantir consistência
                self._carregar_saldo_exercicio()
                
                QMessageBox.information(
                    self,
                    "Sucesso",
                    "✅ Balanço gerado com sucesso!\nConsulte os detalhes na tabela."
                )
            else:
                QMessageBox.warning(self, "Aviso", "Balanço não encontrado ou vazio.")
                self.status_label.setText("⚠️ Sem dados")

        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Erro", f"Erro inesperado:\n{e}\n\n{traceback.format_exc()}")
            self.status_label.setText("❌ Erro")
    
    def _carregar_saldo_exercicio(self):
        """
        ✅ CORRIGIDO: Lê Saldo Exercício de Saldos (fonte única de verdade)
        Não usa mais Balanço para esta informação
        """
        try:
            if not existe_dados(self.caminho_saldos_db):
                self.status_label.setText("📂 Saldos não encontrado.")
                return

            rows, _ = carregar_db(self.caminho_saldos_db)
            saldo_exercicio = 0.0
            for row in rows:
                conta = str(row.get('CONTA', '')).strip().upper()
                import unicodedata
                conta_norm = ''.join(
                    c for c in unicodedata.normalize('NFD', conta)
                    if unicodedata.category(c) != 'Mn'
                )
                if 'SALDO' in conta_norm and 'EXERCICIO' in conta_norm:
                    saldo_exercicio = float(row.get('VALOR') or 0.0)
                    break

            valor_formatado = f"{saldo_exercicio:+,.2f}"
            self.status_label.setText(f"💰 Saldo do Exercício: {valor_formatado} €")

        except FileNotFoundError:
            self.status_label.setText("📂 Saldos não encontrado.")
        except Exception as e:
            print(f"❌ Erro ao carregar Saldo Exercício: {e}")
            self.status_label.setText("Aguardando dados...")

    def gerar_report(self):
        """Gera o relatório PDF completo (Despesas, Receitas, Balanço)"""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return

        try:
            pdf_path = gerar_pdf_relatorio(self.pasta_dados)
            QMessageBox.information(
                self,
                "Relatório Gerado",
                f"PDF criado com sucesso!\n\nGuardado em:\n{pdf_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao gerar relatório:\n{str(e)}")

    def gerar_report_ai(self):
        """Gera o relatório AI em PDF, em segundo plano, sem bloquear a GUI."""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return

        self.report_ai_progress = QProgressDialog(
            "A gerar relatório com IA (pode demorar até cerca de um minuto)...",
            "Cancelar",
            0, 0,  # intervalo (0, 0) = barra indeterminada (não há percentagem)
            self
        )
        self.report_ai_progress.setWindowTitle("Relatório AI em Progresso")
        self.report_ai_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.report_ai_progress.setMinimumDuration(0)
        self._report_ai_cancelado = False
        self.report_ai_progress.canceled.connect(self._cancelar_report_ai)
        self.report_ai_progress.show()

        self.report_ai_worker = ReportAIWorker(self.pasta_dados)
        self.report_ai_worker.concluido.connect(self._report_ai_concluido)
        self.report_ai_worker.start()

    def _cancelar_report_ai(self):
        """
        O utilizador cancelou: o pedido à IA já em curso não pode ser
        interrompido em segurança a meio, mas deixamos de mostrar o
        resultado quando ele chegar.
        """
        self._report_ai_cancelado = True

    def _report_ai_concluido(self, sucesso, mensagem_ou_caminho):
        """Chamado quando a geração do relatório AI termina (sucesso ou erro)"""
        if getattr(self, 'report_ai_progress', None):
            # Desliga o sinal 'canceled' ANTES de fechar: QProgressDialog.close()
            # dispara sempre 'canceled' (mesmo quando fechado programaticamente,
            # não só quando o utilizador clica em Cancelar), o que marcava
            # _report_ai_cancelado=True e engolia a mensagem final de sucesso/erro.
            try:
                self.report_ai_progress.canceled.disconnect(self._cancelar_report_ai)
            except TypeError:
                pass
            self.report_ai_progress.close()
            self.report_ai_progress = None

        if not getattr(self, '_report_ai_cancelado', False):
            if sucesso:
                QMessageBox.information(
                    self,
                    "Relatório AI Gerado",
                    f"Relatório terminado e gravado em:\n{mensagem_ou_caminho}"
                )
            else:
                QMessageBox.critical(self, "Erro", mensagem_ou_caminho)

        if getattr(self, 'report_ai_worker', None):
            self.report_ai_worker.deleteLater()
            self.report_ai_worker = None


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())

    widget = BalancoWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(900, 600)
    widget.setWindowTitle("Balanço da Administração")
    widget.show()

    sys.exit(app.exec())