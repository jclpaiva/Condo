"""
Docs_Gui.py - Visualizar de PDF integrado com envio por Gmail
Com zoom suave, slider horizontal e envio de emails via SMTP do Gmail
"""
import os
import sys
import smtplib

from pathlib import Path
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QPixmap, QImage, QKeySequence, QShortcut, QIcon, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QMessageBox, QFileDialog, QScrollArea, QSlider,
    QDialog, QTextEdit, QListWidget, QListWidgetItem, QLineEdit
)
# Importações compartilhadas
from Commons import (
    BASE_DIR,
    DOCS_DIR,
    ICONS_DIR,
    carregar_db,
    existe_dados
)
# Importação condicional do PyMuPDF
try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

# ====================================================================
# CONFIGURAÇÕES DE EMAIL
# ====================================================================
SENDER_EMAIL = "42condominio@gmail.com"
SENDER_PASSWORD = "ajmk cfdd zckh cqal"
EMAIL_SUBJECT = "Envio da Ata da reunião e relatório de contas"
EMAIL_BODY = """Caros condóminos,
Serve a presente para vos enviar a Ata da reunião e o relatório de contas.
Cumprimentos,
Administração do Condomínio
"""

# ====================================================================
# FUNÇÕES DE ENVIO DE EMAIL (MANTIDAS LOCALMENTE)
# ====================================================================
def carregar_emails_condominos(pasta_dados):
    """
    Carrega emails e nomes dos condóminos do ficheiro Condominos.
    Retorna lista de tuplas (nome, email) válidos.
    """
    condominos_path = BASE_DIR / pasta_dados / "Condominos"
    if not existe_dados(condominos_path):
        raise FileNotFoundError(f"Condominos não encontrado: {condominos_path}")
    contatos = []
    try:
        rows, _ = carregar_db(condominos_path)
        for rec in rows:
            email = str(rec.get('EMAIL', '')).strip()
            nome = str(rec.get('NOME', '')).strip()
            check_val = rec.get('CHECK')
            if check_val in (False, 'F', '.F.', 'f', '', None, 0):
                print(f"  Ignorando {nome} ({email}) - CHECK = {check_val}")
                continue
            if email and '@' in email and '.' in email:
                contatos.append((nome, email))
                print(f"  Adicionado: {nome} ({email})")
    except Exception as e:
        raise Exception(f"Erro ao ler Condominos: {e}")
    
    print(f"\nTotal de contatos carregados: {len(contatos)}")
    return contatos

def enviar_email_gmail_custom(destinatarios, anexos, assunto, corpo, contatos=None):
    """
    Envia email via Gmail SMTP com anexos e conteúdo customizado
    """
    if not destinatarios:
        return False, "Nenhum destinatário válido encontrado"
    if not anexos:
        return False, "Nenhum ficheiro selecionado para anexar"
    try:
        message = MIMEMultipart()
        message['Subject'] = assunto
        message['From'] = SENDER_EMAIL
        message['To'] = ", ".join(destinatarios)
        html_part = MIMEText(corpo, 'plain', 'utf-8')
        message.attach(html_part)
        for anexo_path in anexos:
            if not Path(anexo_path).exists():
                return False, f"Ficheiro não encontrado: {anexo_path}"
            with open(anexo_path, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                filename = Path(anexo_path).name
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {filename}",
                )
                message.attach(part)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, destinatarios, message.as_string())
        msg = "Destinatários:\n"
        if contatos:
            for nome, email in contatos:
                exibicao = nome.strip() if nome.strip() else email
                msg += f"  • {exibicao}\n"
        else:
            for email in destinatarios:
                msg += f"  • {email}\n"
        msg += "\nAnexos:\n"
        for anexo in anexos:
            msg += f"  • {Path(anexo).name}\n"
        return True, msg
    except smtplib.SMTPAuthenticationError:
        return False, "❌ Erro de autenticação Gmail\nVerifique as credenciais"
    except smtplib.SMTPException as e:
        return False, f"❌ Erro SMTP:\n{e}"
    except Exception as e:
        return False, f"❌ Erro ao enviar email:\n{e}"

# ====================================================================
# DIÁLOGO DE ENVIO DE EMAIL
# ====================================================================
class EmailDialog(QDialog):
    """Diálogo simples para enviar email com anexos - estilo Gmail"""
    def __init__(self, contatos, anexos_iniciais=None, parent=None):
        super().__init__(parent)
        self.contatos = contatos
        self.destinatarios = [email for nome, email in contatos]
        self.anexos_selecionados = list(anexos_iniciais) if anexos_iniciais else []
        self.resultado = None
        self.setWindowTitle("Nova Mensagem")
        self.setMinimumWidth(750)
        self.setMinimumHeight(550)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # === CABEÇALHO ===
        header = QWidget()
        header.setStyleSheet("background: white; border-bottom: 1px solid #ddd;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        title = QLabel("Nova Mensagem")
        title_font = QFont()
        title_font.setPointSize(12)
        title.setFont(title_font)
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addWidget(header)

        # === CORPO ===
        body_widget = QWidget()
        body_widget.setStyleSheet("background: white;")
        body_layout = QVBoxLayout(body_widget)
        body_layout.setSpacing(8)
        body_layout.setContentsMargins(15, 15, 15, 15)

        # === PARA ===
        para_layout = QHBoxLayout()
        para_label = QLabel("Para:")
        para_label.setFixedWidth(70)
        para_label.setStyleSheet("color: #666; font-weight: normal;")
        para_layout.addWidget(para_label)
        if self.contatos:
            nomes = [nome if nome.strip() else email for nome, email in self.contatos]
            destinatarios_texto = ", ".join(nomes)
        else:
            destinatarios_texto = "[]"
        para_text = QLineEdit()
        para_text.setText(destinatarios_texto)
        para_text.setReadOnly(True)
        para_text.setStyleSheet("""
            QLineEdit {
                background: #f5f5f5;
                border: none;
                padding: 5px;
                color: #666;
            }
        """)
        para_layout.addWidget(para_text)
        body_layout.addLayout(para_layout)

        # === FROM ===
        from_layout = QHBoxLayout()
        from_label = QLabel("De:")
        from_label.setFixedWidth(70)
        from_label.setStyleSheet("color: #666; font-weight: normal;")
        from_layout.addWidget(from_label)
        from_text = QLineEdit()
        from_text.setText(SENDER_EMAIL)
        from_text.setReadOnly(True)
        from_text.setStyleSheet("""
            QLineEdit {
                background: #f5f5f5;
                border: none;
                padding: 5px;
                color: #666;
            }
        """)
        from_layout.addWidget(from_text)
        body_layout.addLayout(from_layout)

        # === ASSUNTO (EDITÁVEL) ===
        subj_layout = QHBoxLayout()
        subj_label = QLabel("Assunto:")
        subj_label.setFixedWidth(70)
        subj_label.setStyleSheet("color: #666; font-weight: normal;")
        subj_layout.addWidget(subj_label)
        self.subj_text = QLineEdit()
        self.subj_text.setText(EMAIL_SUBJECT)
        self.subj_text.setReadOnly(False)  # ← EDITÁVEL
        self.subj_text.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 5 5px;
                color: #333;
            }
        """)
        subj_layout.addWidget(self.subj_text)
        body_layout.addLayout(subj_layout)

        body_layout.addSpacing(10)

        # === CORPO DA MENSAGEM ===
        msg_label = QLabel("Mensagem:")
        msg_label.setStyleSheet("color: #666; font-weight: normal; margin-bottom: 5px;")
        body_layout.addWidget(msg_label)
        self.body_edit = QTextEdit()
        self.body_edit.setPlainText(EMAIL_BODY)
        self.body_edit.setStyleSheet("""
            QTextEdit {
                background: white;
                border: 1px solid #ddd;
                border-radius: 2px;
                padding: 8px;
                font-family: 'Segoe UI', Arial;
                font-size: 10pt;
                color: #333;
            }
        """)
        self.body_edit.setMinimumHeight(185)
        body_layout.addWidget(self.body_edit)

        body_layout.addSpacing(10)

        # === ANEXOS ===
        # Lista de anexos (sem borda superior para remover o traço)
        self.anexos_list = QListWidget()
        self.anexos_list.setStyleSheet("""
            QListWidget {
                background: #fafafa;
                border-left: 1px solid #ddd;
                border-right: 1px solid #ddd;
                border-bottom: 1px solid #ddd;
                border-top: 1px solid #ddd;
                border-radius: 0px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 4px;
                color: #333;
            }
        """)

        self.anexos_list.setMaximumHeight(100)
        body_layout.addWidget(self.anexos_list)

        # Criar contador ANTES de atualizar (será adicionado ao rodapé depois)
        self.anexos_counter = QLabel("0 anexos")
        self.anexos_counter.setStyleSheet("""
            color: #666; 
            font-size: 9pt; 
            margin-left: 8px;
            padding: 0px;
            border: none;
        """)
        self.anexos_counter.setFixedHeight(30)  # Mesma altura dos botões
        self.anexos_counter.setAlignment(Qt.AlignmentFlag.AlignVCenter)  # Centralizado verticalmente

        # Preencher lista inicial
        self.atualizar_lista_anexos()

        layout.addWidget(body_widget)

        # === RODAPÉ COM BOTÃO ENVIAR ===
        footer = QWidget()
        footer.setStyleSheet("background: white; border-top: 1px solid #ddd;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(15, 5, 15, 5)  # Reduzido de 10 para 5
        
        # Botões do lado esquerdo - ORDEM: Lixo | Clip | Contador
        self.btn_remover = QPushButton()
        self.btn_remover.setIcon(QIcon(str(ICONS_DIR / "Recyclebin.png")))
        self.btn_remover.setIconSize(QSize(24, 24))
        self.btn_remover.setFixedSize(32, 32)
        self.btn_remover.setToolTip("Desmarque o ficheiro a enviar")
        self.btn_remover.setStyleSheet("""
            QPushButton {
                background: white;
                border: 1px solid #ddd;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: #ffe6e6;
                border-color: #ff4444;
            }
        """)
        self.btn_remover.clicked.connect(self.remover_anexo)
        footer_layout.addWidget(self.btn_remover)
        
        # Botão CLIP (segundo)
        self.btn_anexar = QPushButton()
        self.btn_anexar.setIcon(QIcon(str(ICONS_DIR / "clip.png")))
        self.btn_anexar.setIconSize(QSize(24, 24))
        self.btn_anexar.setFixedSize(32, 32)
        self.btn_anexar.setToolTip("Selecione ficheiro a enviar")
        self.btn_anexar.setStyleSheet("""
            QPushButton {
                background: white;
                border: 1px solid #ddd;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: #f5f5f5;
                border-color: #1976d2;
            }
        """)
        self.btn_anexar.clicked.connect(self.escolher_anexos)
        footer_layout.addWidget(self.btn_anexar)
        
        # Adicionar contador ao rodapé (já foi criado antes)
        footer_layout.addWidget(self.anexos_counter)
        
        # Espaço entre contador e botão Enviar
        footer_layout.addStretch()

        btn_enviar = QPushButton("✈ Enviar")
        btn_enviar.clicked.connect(self.enviar_email)
        btn_enviar.setStyleSheet("""
            QPushButton {
                background: #1a73e8;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 10pt;
                min-height: 22px;
            }
            QPushButton:hover {
                background: #1557b0;
            }
        """)
        footer_layout.addWidget(btn_enviar)

        layout.addWidget(footer)

    def atualizar_lista_anexos(self):
        self.anexos_list.clear()
        for anexo in self.anexos_selecionados:
            item = QListWidgetItem(Path(anexo).name)
            item.setToolTip(anexo)
            self.anexos_list.addItem(item)
        
        # Atualizar contador com singular/plural correto
        num = len(self.anexos_selecionados)
        if num == 0:
            self.anexos_counter.setText("0 anexos")
        elif num == 1:
            self.anexos_counter.setText("1 anexo")
        else:
            self.anexos_counter.setText(f"{num} anexos")

    def escolher_anexos(self):
        MAX_ANEXOS = 10
        if len(self.anexos_selecionados) >= MAX_ANEXOS:
            QMessageBox.warning(self, "Limite Atingido", f"Já tem {MAX_ANEXOS} ficheiros anexados.")
            return
        ficheiros, _ = QFileDialog.getOpenFileNames(
            self, "Escolher ficheiros para anexar", str(DOCS_DIR),
            "Documentos PDF (*.pdf);;Documentos Word (*.docx);;Documentos Excel (*.xls);;Todos os ficheiros (*.*)"
        )
        if ficheiros:
            novos = [f for f in ficheiros if f not in self.anexos_selecionados]
            if len(self.anexos_selecionados) + len(novos) > MAX_ANEXOS:
                excesso = len(self.anexos_selecionados) + len(novos) - MAX_ANEXOS
                novos = novos[:MAX_ANEXOS - len(self.anexos_selecionados)]
            self.anexos_selecionados.extend(novos)
            self.atualizar_lista_anexos()

    def remover_anexo(self):
        current_row = self.anexos_list.currentRow()
        if current_row >= 0:
            caminho = self.anexos_selecionados.pop(current_row)
            self.atualizar_lista_anexos()
        else:
            QMessageBox.warning(self, "Atenção", "Selecione um ficheiro da lista para remover.")

    def enviar_email(self):
        corpo_email = self.body_edit.toPlainText()
        assunto_atual = self.subj_text.text().strip() or EMAIL_SUBJECT
        if not self.anexos_selecionados:
            QMessageBox.warning(self, "Aviso", "Por favor, selecione pelo menos um ficheiro para anexar.")
            return
        sucesso, mensagem = enviar_email_gmail_custom(
            self.destinatarios,
            self.anexos_selecionados,
            assunto_atual,
            corpo_email,
            self.contatos
        )
        if sucesso:
            QMessageBox.information(self, "Sucesso", "😊 Email enviado com sucesso!")
            self.resultado = True
            self.accept()
        else:
            QMessageBox.critical(self, "Erro", mensagem)

# ====================================================================
# JANELA DE VISUALIZAÇÃO DE PDF
# ====================================================================
class DocsViewerWindow(QWidget):
    def __init__(self, pdf_path, pasta_dados=None):
        super().__init__()
        if not FITZ_AVAILABLE:
            raise ImportError("PyMuPDF não está instalado")
        self.pdf_path = pdf_path
        self.pasta_dados = pasta_dados
        self.doc = None
        self.current_page = 0
        self.zoom_factor = 1.0
        self.pending_zoom = self.zoom_factor
        try:
            self.doc = fitz.open(str(pdf_path))
        except Exception as e:
            raise Exception(f"Erro ao abrir PDF: {e}")
        self.setWindowTitle(f"Visualizar PDF's - {Path(pdf_path).name}")
        self.zoom_timer = QTimer()
        self.zoom_timer.setSingleShot(True)
        self.zoom_timer.timeout.connect(self.apply_smooth_zoom)
        self.init_ui()
        self.load_page(0)
        QShortcut(QKeySequence("Left"), self, self.prev_page)
        QShortcut(QKeySequence("Right"), self, self.next_page)
        QShortcut(QKeySequence("Up"), self, self.prev_page)
        QShortcut(QKeySequence("Down"), self, self.next_page)
        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Ctrl++"), self, self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, self.zoom_out)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        control_bar = QHBoxLayout()
        control_bar.setContentsMargins(10, 0, 10, 0)
        control_bar.setSpacing(5)
        estilo_botao = """
            QPushButton {
                font-size: 18px;
                border: none;
                background-color: #FCFCFC;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }
            QPushButton:hover {
                background-color: #e9ecef;
                border-radius: 17px;
            }
        """
        btn_prev = QPushButton("◀️")
        btn_prev.setStyleSheet(estilo_botao)
        btn_prev.setToolTip("Página Anterior")
        btn_prev.clicked.connect(self.prev_page)
        control_bar.addWidget(btn_prev)

        self.page_label = QLabel()
        self.page_label.setStyleSheet("font-weight: bold; padding: 0 10px; font-size: 11px;")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_bar.addWidget(self.page_label)

        btn_next = QPushButton("▶️")
        btn_next.setStyleSheet(estilo_botao)
        btn_next.clicked.connect(self.next_page)
        control_bar.addWidget(btn_next)
        control_bar.addSpacing(20)

        btn_zoom = QPushButton("🔍")
        btn_zoom.setStyleSheet(estilo_botao)
        control_bar.addWidget(btn_zoom)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(50)
        self.zoom_slider.setMaximum(150)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(140)
        self.zoom_slider.valueChanged.connect(self.on_zoom_slider_changed)
        control_bar.addWidget(self.zoom_slider)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("font-size: 11px; min-width: 40px;")
        control_bar.addWidget(self.zoom_label)
        control_bar.addStretch()

        """Adiciona botão Mail no canto superior direito das tabs"""
        btn_send = QPushButton()
        icon_path = ICONS_DIR / "mail-icon.png"
        
        if icon_path.exists():
            btn_send.setIcon(QIcon(str(icon_path)))
            btn_send.setIconSize(QSize(24, 24))
        else:
            # Fallback: emoji se não encontrar ícone
            btn_send.setText("📧")
            btn_send.setStyleSheet("font-size: 14px;")
        
        btn_send.setFixedSize(36, 36)
        btn_send.setStyleSheet("""
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
        btn_send.setToolTip("Enviar documentos por email")
        btn_send.clicked.connect(self.enviar_por_email)
        control_bar.addWidget(btn_send)

        layout.addLayout(control_bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background-color: #f0f0f0; padding: 20px;")
        scroll.setWidget(self.label)
        layout.addWidget(scroll)
        self.setLayout(layout)

    def load_page(self, page_num):
        if not self.doc:
            return
        if 0 <= page_num < len(self.doc):
            try:
                page = self.doc.load_page(page_num)
                mat = fitz.Matrix(self.zoom_factor, self.zoom_factor)
                pix = page.get_pixmap(matrix=mat)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                self.label.setPixmap(QPixmap.fromImage(img))
                self.current_page = page_num
                self.page_label.setText(f"{self.current_page + 1} / {len(self.doc)}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível carregar a página {page_num + 1}:\n{e}")

    def next_page(self):
        if self.current_page < len(self.doc) - 1:
            self.load_page(self.current_page + 1)

    def prev_page(self):
        if self.current_page > 0:
            self.load_page(self.current_page - 1)

    def on_zoom_slider_changed(self, value):
        self.zoom_label.setText(f"{value}%")
        self.pending_zoom = value / 100
        self.zoom_timer.start(120)

    def apply_smooth_zoom(self):
        self.zoom_factor = self.pending_zoom
        self.load_page(self.current_page)

    def zoom_in(self):
        self.zoom_slider.setValue(min(self.zoom_slider.value() + 5, self.zoom_slider.maximum()))

    def zoom_out(self):
        self.zoom_slider.setValue(max(self.zoom_slider.value() - 5, self.zoom_slider.minimum()))

    def enviar_por_email(self):
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aviso", "Pasta de dados não definida.")
            return
        try:
            contatos = carregar_emails_condominos(self.pasta_dados)
            if not contatos:
                QMessageBox.warning(self, "Aviso", "Nenhum email de condómino encontrado.")
                return
            anexos_iniciais = [str(self.pdf_path)]
            dialogo = EmailDialog(contatos, anexos_iniciais, self)
            dialogo.exec()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao preparar envio de email:\n{e}")

    def closeEvent(self, event):
        if self.doc:
            try:
                self.doc.close()
            except Exception:
                pass
        event.accept()

# ====================================================================
# WIDGET DA ABA DOCUMENTOS
# ====================================================================
class DocsWidget(QWidget):
    def __init__(self, pasta_dados=None, parent=None):
        super().__init__(parent)
        self.pasta_dados = pasta_dados
        self.viewer_window = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        title = QLabel("Visualizar Documentos")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2F5597; padding: 6px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        btn_bar = QHBoxLayout()
        btn_selecionar = QPushButton("→ Selecionar PDF")
        btn_selecionar.setFixedSize(155, 42)
        icon_path = ICONS_DIR / "pdf-icon.png"
        if icon_path.exists():
            btn_selecionar.setIcon(QIcon(str(icon_path)))
        btn_selecionar.setIconSize(QSize(30, 30))
        btn_selecionar.clicked.connect(self.abrir_seletor_pdf)
        btn_bar.addWidget(btn_selecionar)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)
        info_text = (
            "Clique no botão acima para selecionar um documento PDF para visualização.\n"
            "📁 Pasta de documentos padrão: docs/\n"
            "🔍 Navegue com as setas ← → ou ↑ ↓ dentro do visualizador\n"
            "📘 Controle de zoom com slider ou Ctrl++ / Ctrl+-\n"
            "✉️ Use o botão de envelope para enviar documentos por email\n"
            "⎋ ESC para fechar o visualizador"
        )
        if FITZ_AVAILABLE:
            info_text += "\n✅ PyMuPDF instalado - visualização disponível"
        else:
            info_text += "\n❌ PyMuPDF não instalado\nExecute: pip install PyMuPDF"
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #666; font-size: 11px; padding: 15px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        layout.addStretch()
        self.status_label = QLabel("⏳ Aguardando seleção de documento...")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

    def abrir_seletor_pdf(self):
        if not FITZ_AVAILABLE:
            QMessageBox.warning(self, "Biblioteca Não Instalada", "PyMuPDF (fitz) não está instalado.")
            return
        pasta_inicial = DOCS_DIR
        if not pasta_inicial.exists():
            try:
                pasta_inicial.mkdir(parents=True, exist_ok=True)
            except Exception:
                pasta_inicial = BASE_DIR
        caminho_pdf, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Documento PDF", str(pasta_inicial),
            "Documentos PDF (*.pdf);;Documentos Word (*.docx);;Documentos Excel (*.xls);;Todos os ficheiros (*.*)"
        )
        if caminho_pdf:
            if not Path(caminho_pdf).exists():
                QMessageBox.critical(self, "Erro", f"Arquivo não encontrado:\n{caminho_pdf}")
                return
            try:
                if self.viewer_window:
                    self.viewer_window.close()
                self.viewer_window = DocsViewerWindow(caminho_pdf, self.pasta_dados)
                self.viewer_window.showMaximized()
                self.viewer_window.raise_()
                self.viewer_window.activateWindow()
                self.status_label.setText(f"✅ Visualizando: {Path(caminho_pdf).name}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Não foi possível abrir o PDF:\n{e}")
                self.status_label.setText("❌ Erro ao carregar PDF")
        else:
            self.status_label.setText("⚠️ Nenhum documento selecionado.")

    def set_pasta_dados(self, pasta_dados):
        self.pasta_dados = pasta_dados

# ====================================================================
# TESTE STANDALONE
# ====================================================================
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from Commons import get_app_stylesheet
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_app_stylesheet())
    widget = DocsWidget(pasta_dados="corrente")
    widget.resize(800, 600)
    widget.setWindowTitle("Visualizador de Documentos")
    widget.show()
    sys.exit(app.exec())