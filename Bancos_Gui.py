"""
Bancos_Gui.py - Widget de gestão de movimentos bancários

Funcionalidades:
- Importação de CSV com auto-deteção
- Tabela editável de movimentos
- ComboBox filtrada por tipo
- Guardar alterações
"""

import sys
import os
import pandas as pd
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableView, QHeaderView, QMessageBox, QFileDialog,
    QProgressDialog, QComboBox, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QBrush, QIcon

# Importa codigo compartilhado
from Commons import (
    BASE_DIR, ICONS_DIR, ContaComboBoxDelegate,
    carregar_contas, clean_numeric, format_currency, carregar_db,
    salvar_db, existe_dados
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
# WORKER THREAD PARA IMPORTAÇÃO
# ====================================================================
class ImportacaoWorker(QThread):
    """Thread para executar importação sem travar a GUI"""
    progresso = pyqtSignal(int, str)   # percentagem, mensagem
    concluido = pyqtSignal(bool, str)  # sucesso, mensagem
    
    def __init__(self, csv_path, pasta_trabalho):
        super().__init__()
        self.csv_path = csv_path
        self.pasta_trabalho = pasta_trabalho
    
    def run(self):
        """Executa importação chamando Bancos.py diretamente"""
        try:
            # Importa o modulo Bancos
            import sys
            from pathlib import Path
            
            # Adiciona o diretorio base ao path se necessario
            script_dir = str(BASE_DIR)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            
            self.progresso.emit(10, "Carregando modulo Bancos...")
            
            # Importa Bancos.py como modulo
            import Bancos
            
            self.progresso.emit(30, "Verificando estrutura do CSV...")
            
            # Muda para o diretorio de trabalho
            old_cwd = os.getcwd()
            os.chdir(str(self.pasta_trabalho))
            
            try:
                self.progresso.emit(50, "Importando movimentos bancarios...")

                # BUGFIX (arquitetural): nomes simples ('Configs',
                # 'Bancos') confiavam no os.chdir() acima, que deixou
                # de ter efeito sobre a resolução de caminhos do back-end
                # SQLite (ver nota equivalente em Balanco_Gui.py). Usar
                # caminhos completos a partir de self.pasta_trabalho
                # garante que a importação actua sempre na pasta
                # pretendida (mesmo quando é uma pasta histórica).
                configs_path = str(self.pasta_trabalho / 'Configs')
                bancos_path = str(self.pasta_trabalho / 'Bancos')

                # Chama as funções diretamente
                configs, condominos, regras_gerais = Bancos.carregar_configuracoes_e_regras(configs_path)
                
                self.progresso.emit(70, "Processando e categorizando...")
                
                # Usa o caminho CSV recebido do QFileDialog
                Bancos.importar_e_processar_bancos(
                    self.csv_path,
                    configs,
                    bancos_path,
                    condominos,
                    regras_gerais
                )
                
                self.progresso.emit(100, "Conclusão!")
                
                os.chdir(old_cwd)  # Restaurar diretorio
                
                self.concluido.emit(True, "Importação concluída com sucesso!")
                
            except Exception as e:
                os.chdir(old_cwd)  # Restaurar mesmo em caso de erro
                raise e
                
        except Exception as e:
            import traceback
            erro_msg = f"Erro na importação:\n{e}\n\n{traceback.format_exc()}"
            self.concluido.emit(False, erro_msg)


# ====================================================================
# MODELO DA TABELA BANCOS
# ====================================================================

class BancosTableModel(QAbstractTableModel):
    """Modelo de dados para tabela de movimentos bancários"""
    
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
        
        if index.row() >= len(self._data) or index.row() < 0:
            return QVariant()
        
        try:
            value = list(self._data[index.row()].values())[index.column()]
        except (IndexError, KeyError):
            return QVariant()
        
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:  # Data
                if isinstance(value, datetime):
                    return value.strftime("%d-%m-%Y")
                return str(value)
            if index.column() in (4, 5):  # Valor, Saldo
                try:
                    return format_currency(float(value))
                except (ValueError, TypeError):
                    return "0,00 €"
            return str(value)
        
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() in (4, 5):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        
        elif role == Qt.ItemDataRole.ForegroundRole:
            if index.column() == 1:  # Tipo
                tipo = list(self._data[index.row()].values())[1]
                if tipo == "RECEITA":
                    return QBrush(QColor("#2e7d32"))
                elif tipo == "DESPESA":
                    return QBrush(QColor("#c62828"))
            elif index.column() in (4, 5):  # Valor e Saldo
                try:
                    value_float = float(list(self._data[index.row()].values())[index.column()])
                    if value_float < 0:
                        return QBrush(QColor("#c62828"))  # Vermelho para valores negativos
                except (ValueError, TypeError):
                    pass
        
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
            if index.row() >= len(self._data) or index.row() < 0:
                return False
            
            try:
                col = index.column()
                row_dict = self._data[index.row()]
                keys = list(row_dict.keys())
                
                if col >= len(keys):
                    return False
                
                key = keys[col]
                
                if col == 0:  # Data
                    try:
                        if isinstance(value, str):
                            value = datetime.strptime(value, "%d-%m-%Y")
                        elif not isinstance(value, datetime):
                            return False
                    except (ValueError, TypeError):
                        return False
                elif col in (4, 5):  # Valor, Saldo
                    try:
                        value_str = str(value).replace("€", "").replace(".", "").replace(",", ".").strip()
                        value = float(value_str)
                    except (ValueError, TypeError):
                        return False
                
                row_dict[key] = value
                self.dataChanged.emit(index, index)
                return True
            except Exception as e:
                print(f"Erro em setData: {e}")
                return False
        return False

    def load_bancos_db(self, caminho):
        """Carrega dados de movimentos bancários (SQLite)."""
        self.beginResetModel()
        self._data = []
        path = Path(caminho)
        
        if not existe_dados(path):
            print(f"Ficheiro não encontrado: {caminho}")
            self.endResetModel()
            return
        
        try:
            rows, _ = carregar_db(path)
            for rec in rows:
                try:
                    data_val = rec.get('DATA')
                    if isinstance(data_val, str):
                        try:
                            data = datetime.fromisoformat(data_val[:10])
                        except Exception:
                            data = datetime(1900, 1, 1)
                    elif data_val is None:
                        data = datetime(1900, 1, 1)
                    else:
                        data = data_val
                    
                    self._data.append({
                        'DATA': data,
                        'TIPO': str(rec.get('TIPO', '')).strip(),
                        'CONTA': str(rec.get('CONTA', '')).strip(),
                        'DESCRICAO': str(rec.get('DESCRICAO', '')).strip(),
                        'VALOR': float(rec.get('VALOR') or 0.0),
                        'SALDO': float(rec.get('SALDO') or 0.0),
                        'OBSERVACAO': str(rec.get('OBSERVACAO', '')).strip()
                    })
                except Exception as e:
                    print(f"Erro ao processar registo: {e}")
                    continue
        except Exception as e:
            print(f"ERRO AO LER MOVIMENTOS BANCÁRIOS: {e}")
            import traceback
            traceback.print_exc()
        
        self.endResetModel()
    
    def save_to_db(self, caminho):
        """Guarda alterações em SQLite."""
        if not self._data:
            print("Nenhum dado para salvar")
            return False
        
        try:
            rows = []
            for row_data in self._data:
                try:
                    data_obj = row_data.get('DATA')
                    if isinstance(data_obj, datetime):
                        data_value = data_obj.date()
                    elif hasattr(data_obj, 'date'):
                        data_value = data_obj.date()
                    else:
                        data_value = datetime(1900, 1, 1).date()

                    rows.append({
                        'DATA': data_value,
                        'TIPO': str(row_data.get('TIPO', ''))[:10],
                        'CONTA': str(row_data.get('CONTA', ''))[:30],
                        'DESCRICAO': str(row_data.get('DESCRICAO', ''))[:30],
                        'VALOR': float(row_data.get('VALOR', 0.0)),
                        'SALDO': float(row_data.get('SALDO', 0.0)),
                        'OBSERVACAO': str(row_data.get('OBSERVACAO', ''))[:32]
                    })
                except Exception as e:
                    print(f"Erro ao preparar registo: {e}")
                    continue

            df = pd.DataFrame(rows, dtype=object)
            field_specs = 'DATA D; TIPO C(10); CONTA C(30); DESCRICAO C(30); VALOR N(10,2); SALDO N(10,2); OBSERVACAO C(32)'
            return salvar_db(df, caminho, field_specs)

        except Exception as e:
            print(f"Erro ao guardar movimentos: {e}")
            import traceback
            traceback.print_exc()
            return False


# ====================================================================
# WIDGET DE BANCOS
# ====================================================================

class BancosWidget(QWidget):
    """Widget principal para gestão de movimentos bancários"""

    # Sinal emitido quando o saldo final muda (ex.: após importação CSV)
    saldo_atualizado = pyqtSignal(float)
    
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.caminho_bancos_db = None
        self.conta_delegate = ContaComboBoxDelegate()
        self.tipo_delegate = TipoComboBoxDelegate()  # ✅ NOVO
        self.worker = None
        self.progress_dialog = None
        
        self.init_ui()
    
    def init_ui(self):
        """Inicializa interface"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
 
        # Barra de botoes
        btn_bar = QHBoxLayout()

        # Botao Importar CSV
        btn_importar = QPushButton("→ Importar Conta Corrente (CSV)")
        btn_importar.setFixedHeight(45)
        icon_path = ICONS_DIR / "downloads-folder-icon.png"
        if icon_path.exists():
            btn_importar.setIcon(QIcon(str(icon_path)))
            btn_importar.setIconSize(QSize(35, 35))
        btn_importar.clicked.connect(self.importar_csv)
        btn_bar.addWidget(btn_importar)
        
        btn_bar.addSpacing(10)
        
        # Botao Guardar
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
        self.model = BancosTableModel()
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
        self.table_view.setColumnWidth(6, 210)  # Observação
        
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
        try:
            self.pasta_dados = pasta_dados
            self.caminho_bancos_db = BASE_DIR / pasta_dados / "Bancos"
            
            # Carrega contas
            receitas, despesas, todas = carregar_contas(pasta_dados)
            
            if not todas:
                QMessageBox.warning(
                    self,
                    "Aviso",
                    "Nenhuma conta carregada!\n\n"
                    "Verifique se o ficheiro existe e tem a estrutura correta."
                )
            
            self.conta_delegate.set_contas(receitas, despesas, todas)
            
            # Carrega tabela
            self.carregar_tabela()
        except Exception as e:
            print(f"Erro em set_pasta_dados: {e}")
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao configurar pasta de dados:\n{e}"
            )
    
    def carregar_tabela(self):
        """Carrega dados dos movimentos bancários"""
        if self.caminho_bancos_db:
            try:
                self.model.load_bancos_db(str(self.caminho_bancos_db))
            except Exception as e:
                print(f"Erro ao carregar tabela: {e}")
                QMessageBox.warning(
                    self,
                    "Aviso",
                    f"Erro ao carregar dados:\n{e}"
                )
    
    def get_saldo_final(self):
        """Retorna saldo final (ultima linha)"""
        try:
            if self.model.rowCount() > 0:
                ultima_linha = self.model._data[-1]
                return float(ultima_linha.get('SALDO', 0.0))
            return 0.0
        except Exception as e:
            print(f"Erro ao obter saldo final: {e}")
            return 0.0
    
    def guardar_alteracoes(self):
        """Guarda alterações"""
        if not self.caminho_bancos_db:
            QMessageBox.warning(self, "Aviso", "Nenhum ficheiro carregado.")
            return
        
        try:
            if self.model.save_to_db(str(self.caminho_bancos_db)):
                QMessageBox.information(self, "Sucesso", "Alterações guardadas com sucesso!")
                self.carregar_tabela()
            else:
                QMessageBox.critical(self, "Erro", "Erro ao guardar alterações.")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao guardar alterações:\n{e}"
            )
    
    def importar_csv(self):
        """Importa CSV do banco usando thread worker"""
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return
        
        try:
            csv_path, _ = QFileDialog.getOpenFileName(
                self,
                "Selecionar extrato bancario CSV",
                str(BASE_DIR / self.pasta_dados),
                "CSV (*.csv)"
            )
            
            if not csv_path:
                return
            
            # Define pasta de trabalho (pasta de dados do ano)
            pasta_trabalho = BASE_DIR / self.pasta_dados
            
            # Verifica se Configs existe
            configs_path = pasta_trabalho / "Configs"
            if not existe_dados(configs_path):
                QMessageBox.critical(
                    self,
                    "Erro",
                    f"Configs não encontrado!\n\n"
                    f"Localização esperada:\n{configs_path}\n\n"
                    f"Por favor, certifique-se que a pasta de dados está correta:\n{pasta_trabalho}"
                )
                return
            
            # Cria progress dialog
            self.progress_dialog = QProgressDialog(
                "Importando movimentos bancarios...",
                "Cancelar",
                0, 100,
                self
            )
            self.progress_dialog.setWindowTitle("Importação em Progresso")
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.setValue(0)
            
            # Cria e inicia worker
            self.worker = ImportacaoWorker(csv_path, pasta_trabalho)
            self.worker.progresso.connect(self.atualizar_progresso)
            self.worker.concluido.connect(self.importacao_concluida)
            self.worker.start()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao iniciar importação:\n{e}"
            )
    
    def atualizar_progresso(self, percentagem, mensagem):
        """Atualiza barra de progresso"""
        try:
            if self.progress_dialog:
                self.progress_dialog.setValue(percentagem)
                self.progress_dialog.setLabelText(mensagem)
        except Exception as e:
            print(f"Erro ao atualizar progresso: {e}")
    
    def importacao_concluida(self, sucesso, mensagem):
        """Chamado quando importação termina"""
        try:
            if self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None
            
            if sucesso:
                QMessageBox.information(self, "Sucesso", mensagem)
                self.carregar_tabela()
                # Notifica Main_Gui para atualizar o saldo no rodapé
                self.saldo_atualizado.emit(self.get_saldo_final())
            else:
                QMessageBox.critical(self, "Erro", mensagem)
            
            # Limpa worker
            if self.worker:
                self.worker.deleteLater()
                self.worker = None
                
        except Exception as e:
            print(f"Erro em importacao_concluida: {e}")
            import traceback
            traceback.print_exc()  # ← Para ver erros reais no console


# ====================================================================
# TESTE STANDALONE
# ====================================================================

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet

    screen_center = lambda widget: QApplication.desktop().screen().rect().center()- widget.rect().center()
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())
    
    widget = BancosWidget()
    widget.set_pasta_dados("corrente")
    widget.resize(1200, 600)
    widget.move(screen_center(widget))
    widget.show()
    
    sys.exit(app.exec())