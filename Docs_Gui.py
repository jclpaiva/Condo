"""
Docs_Gui.py - Documentos do condomínio
- Visualização de PDF com zoom e envio por Gmail
- Geração automática da Ata de Assembleia de Condóminos
"""
import os
import sys
import smtplib
from datetime import date, time

from pathlib import Path
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from PyQt6.QtCore import Qt, QSize, QTimer, QDate, QTime
from PyQt6.QtGui import QPixmap, QImage, QKeySequence, QShortcut, QIcon, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox,
    QLabel, QMessageBox, QFileDialog, QScrollArea, QSlider,
    QDialog, QTextEdit, QListWidget, QListWidgetItem, QLineEdit,
    QFormLayout, QComboBox, QDateEdit, QTimeEdit, QSpinBox,
    QFrame, QSizePolicy, QSplitter,
)
# Acesso a dados → Database
from Database import carregar_condominos, existe_dados
# Constantes / utilitários
from Commons import (
    BASE_DIR,
    DOCS_DIR,
    ICONS_DIR,
)
# Geração de ata (opcional — não bloqueia o arranque da app)
try:
    from Gerar_Ata import carregar_dados_iniciais, gerar_ata, DOCX_AVAILABLE
    ATA_AVAILABLE = True
except ImportError as _e:
    carregar_dados_iniciais = None  # type: ignore
    gerar_ata = None  # type: ignore
    DOCX_AVAILABLE = False
    ATA_AVAILABLE = False
    print(f"  ⚠️ Gerar_Ata indisponível: {_e}")
# Importação condicional do PyMuPDF
try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

# ====================================================================
# CONFIGURAÇÕES DE EMAIL (credenciais no .env — nunca no código)
# ====================================================================
def _carregar_env_email():
    """Carrega .env junto à app (e cwd) para Gmail / OpenRouter."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    candidatos = [
        BASE_DIR / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
    ]
    for p in candidatos:
        if p.is_file():
            # override=True: alterações no .env aplicam-se sem reiniciar a sessão Windows
            load_dotenv(p, override=True)
            return


def _credenciais_gmail():
    """Lê email/password do ambiente (sempre actualizado a partir do .env)."""
    _carregar_env_email()
    email = os.environ.get("GMAIL_SENDER_EMAIL", "42condominio@gmail.com").strip()
    # App Password Gmail: os espaços são só visuais — SMTP quer 16 chars seguidos
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    subject = os.environ.get(
        "GMAIL_EMAIL_SUBJECT",
        "Envio da Ata da reunião e relatório de contas",
    )
    body = os.environ.get(
        "GMAIL_EMAIL_BODY",
        "Caros condóminos,\n"
        "Serve a presente para vos enviar a Ata da reunião e o relatório de contas.\n"
        "Cumprimentos,\n"
        "Administração do Condomínio\n",
    )
    return email, password, subject, body


_carregar_env_email()
SENDER_EMAIL, SENDER_PASSWORD, EMAIL_SUBJECT, EMAIL_BODY = _credenciais_gmail()

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
        rows = carregar_condominos(condominos_path)
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
    Envia email via Gmail SMTP com anexos e conteúdo customizado.

    Tenta primeiro STARTTLS:587 (mais fiável em redes com proxy/firewall);
    se falhar, tenta SSL:465.
    """
    if not destinatarios:
        return False, "Nenhum destinatário válido encontrado"
    if not anexos:
        return False, "Nenhum ficheiro selecionado para anexar"

    sender_email, sender_password, _, _ = _credenciais_gmail()
    if not sender_password:
        return False, (
            "Password de e-mail não configurada.\n"
            "Defina GMAIL_APP_PASSWORD no ficheiro .env\n"
            "(App Password do Google, 16 caracteres)."
        )
    if len(sender_password) < 16:
        return False, (
            f"GMAIL_APP_PASSWORD parece incompleta ({len(sender_password)} chars).\n"
            "A App Password do Gmail tem 16 caracteres (pode colar com ou sem espaços)."
        )

    try:
        message = MIMEMultipart()
        message["Subject"] = assunto
        message["From"] = sender_email
        message["To"] = ", ".join(destinatarios)
        message.attach(MIMEText(corpo, "plain", "utf-8"))
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
                    f'attachment; filename="{filename}"',
                )
                message.attach(part)

        payload = message.as_string()
        erros = []

        # 1) STARTTLS na porta 587 (recomendado pelo Gmail)
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, destinatarios, payload)
        except Exception as e587:
            erros.append(f"587/STARTTLS: {e587}")
            # 2) Fallback SSL implícito na porta 465
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
                    server.ehlo()
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, destinatarios, payload)
            except Exception as e465:
                erros.append(f"465/SSL: {e465}")
                detalhe = "\n".join(erros)
                return False, (
                    "Erro SMTP Gmail — ligação recusada ou credenciais inválidas.\n\n"
                    f"{detalhe}\n\n"
                    "Verifique:\n"
                    "• GMAIL_APP_PASSWORD no .env (App Password, não a password normal)\n"
                    "• Conta Google com verificação em 2 passos + App Password activa\n"
                    "• Firewall/antivírus a bloquear portas 587 ou 465"
                )

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
        self._condominos_cache = []
        self.init_ui()
        self.carregar_form_ata()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ========== SECÇÃO 1: Visualizar Documentos ==========
        grp_view = QGroupBox("Visualizar Documentos")
        grp_view.setStyleSheet(
            "QGroupBox { font-size: 14px; font-weight: bold; color: #2F5597; "
            "border: 1px solid #c5d0e0; border-radius: 6px; margin-top: 10px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        lay_view = QVBoxLayout(grp_view)
        lay_view.setSpacing(8)

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
        lay_view.addLayout(btn_bar)

        info_text = (
            "Selecione um documento PDF para visualização (pasta padrão: docs/)."
        )
        if FITZ_AVAILABLE:
            info_text += "  ✅ PyMuPDF disponível"
        else:
            info_text += "  ❌ PyMuPDF não instalado (pip install PyMuPDF)"
        info_label = QLabel(info_text)
        info_label.setStyleSheet("color: #666; font-size: 11px; font-weight: normal;")
        info_label.setWordWrap(True)
        lay_view.addWidget(info_label)

        self.status_label = QLabel("⏳ Aguardando seleção de documento...")
        self.status_label.setStyleSheet("color: #666; font-style: italic; font-weight: normal;")
        lay_view.addWidget(self.status_label)

        root.addWidget(grp_view)

        # ========== SECÇÃO 2: Criar Ata de Reunião ==========
        grp_ata = QGroupBox("Criar Ata de Reunião")
        grp_ata.setStyleSheet(
            "QGroupBox { font-size: 14px; font-weight: bold; color: #2F5597; "
            "border: 1px solid #c5d0e0; border-radius: 6px; margin-top: 10px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        lay_ata = QVBoxLayout(grp_ata)
        lay_ata.setSpacing(12)
        lay_ata.setContentsMargins(12, 14, 12, 10)

        def _lbl(texto: str) -> QLabel:
            w = QLabel(texto)
            w.setStyleSheet("font-weight: normal; color: #333;")
            return w

        # ----- Linha 1: Anos | Nº Ata | Nº Administração |   | Data | Hora -----
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.lbl_anos = QLabel("—")
        self.lbl_anos.setStyleSheet("font-weight: normal;")
        row1.addWidget(_lbl("Anos (ant. → atual):"))
        row1.addWidget(self.lbl_anos)
        row1.addSpacing(16)

        self.spin_num_ata = QSpinBox()
        self.spin_num_ata.setRange(1, 999)
        self.spin_num_ata.setValue(1)
        self.spin_num_ata.setFixedWidth(60)
        row1.addWidget(_lbl("Nº da Ata:"))
        row1.addWidget(self.spin_num_ata)
        row1.addSpacing(16)

        self.spin_num_adm = QSpinBox()
        self.spin_num_adm.setRange(1, 99)
        self.spin_num_adm.setReadOnly(True)
        self.spin_num_adm.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_num_adm.setFixedWidth(50)
        row1.addWidget(_lbl("Nº Administração:"))
        row1.addWidget(self.spin_num_adm)

        row1.addStretch(1)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setFixedWidth(110)
        row1.addWidget(_lbl("Data da reunião:"))
        row1.addWidget(self.date_edit)
        row1.addSpacing(16)

        self.time_ini = QTimeEdit()
        self.time_ini.setDisplayFormat("HH:mm")
        self.time_ini.setTime(QTime(20, 0))
        self.time_ini.setFixedWidth(70)
        self.time_fim = QTimeEdit()
        self.time_fim.setDisplayFormat("HH:mm")
        self.time_fim.setTime(QTime(22, 0))
        self.time_fim.setFixedWidth(70)
        row1.addWidget(_lbl("Hora (início → fim):"))
        row1.addWidget(self.time_ini)
        row1.addWidget(_lbl("→"))
        row1.addWidget(self.time_fim)
        lay_ata.addLayout(row1)

        # ----- Linha 2: Admin. cessante | Fração |   | Novo admin | Fr. | Andar -----
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.edit_admin_ant = QLineEdit()
        self.edit_admin_ant.setPlaceholderText("Administrador cessante")
        self.edit_admin_ant.setMinimumWidth(180)
        row2.addWidget(_lbl("Admin. cessante:"))
        row2.addWidget(self.edit_admin_ant, 2)

        self.edit_fracao_ant = QLineEdit()
        self.edit_fracao_ant.setFixedWidth(44)
        self.edit_fracao_ant.setPlaceholderText("Fr.")
        row2.addWidget(_lbl("Fração:"))
        row2.addWidget(self.edit_fracao_ant)

        row2.addSpacing(24)

        self.combo_novo_admin = QComboBox()
        self.combo_novo_admin.setMinimumWidth(180)
        self.combo_novo_admin.currentIndexChanged.connect(self._on_novo_admin_changed)
        row2.addWidget(_lbl("Novo administrador:"))
        row2.addWidget(self.combo_novo_admin, 2)

        self.edit_fracao = QLineEdit()
        self.edit_fracao.setFixedWidth(44)
        self.edit_fracao.setPlaceholderText("Fr.")
        row2.addWidget(_lbl("Fr.:"))
        row2.addWidget(self.edit_fracao)

        self.edit_andar = QLineEdit()
        self.edit_andar.setPlaceholderText("Andar")
        self.edit_andar.setFixedWidth(90)
        row2.addWidget(_lbl("Andar:"))
        row2.addWidget(self.edit_andar)
        lay_ata.addLayout(row2)

        # ----- Linha 3: CC |   | Validade | NIF -----
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        self.edit_cc = QLineEdit()
        self.edit_cc.setPlaceholderText("N.º Cartão de Cidadão")
        row3.addWidget(_lbl("CC / NIF:"))
        row3.addWidget(self.edit_cc, 3)

        row3.addSpacing(24)

        self.edit_cc_val = QLineEdit()
        self.edit_cc_val.setPlaceholderText("dd-mm-aaaa")
        self.edit_cc_val.setFixedWidth(110)
        row3.addWidget(_lbl("Validade:"))
        row3.addWidget(self.edit_cc_val)
        row3.addSpacing(16)

        self.edit_nif = QLineEdit()
        self.edit_nif.setPlaceholderText("NIF")
        self.edit_nif.setFixedWidth(100)
        row3.addWidget(_lbl("NIF:"))
        row3.addWidget(self.edit_nif)
        lay_ata.addLayout(row3)

        # --- assuntos de interesse geral (máximo espaço vertical) ---
        lbl_assuntos = QLabel("4. Assuntos de interesse geral:")
        lbl_assuntos.setStyleSheet("font-weight: bold; color: #333; margin-top: 8px;")
        lay_ata.addWidget(lbl_assuntos)

        self.txt_assuntos = QTextEdit()
        self.txt_assuntos.setPlaceholderText(
            "Texto das deliberações do ponto 4 (quotas, obras, testes, etc.).\n"
            "Pode editar livremente o texto sugerido."
        )
        self.txt_assuntos.setMinimumHeight(180)
        self.txt_assuntos.setStyleSheet("font-weight: normal; font-size: 12px;")
        self.txt_assuntos.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        lay_ata.addWidget(self.txt_assuntos, 1)

        # --- botões ---
        btn_row = QHBoxLayout()
        self.btn_gerar = QPushButton("📄  Gerar Ata (.docx)")
        self.btn_gerar.setFixedHeight(40)
        self.btn_gerar.setStyleSheet(
            "QPushButton { background-color: #2F5597; color: white; font-weight: bold; "
            "border-radius: 5px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #3a6bb0; }"
            "QPushButton:pressed { background-color: #244578; }"
        )
        self.btn_gerar.clicked.connect(self.gerar_ata_clicked)

        #self.btn_recarregar = QPushButton("🔄")
        #self.btn_recarregar.setFixedSize(40, 40)
        #self.btn_recarregar.setToolTip("Recarregar dados da base de dados")
        #self.btn_recarregar.clicked.connect(self.carregar_form_ata)

        btn_row.addWidget(self.btn_gerar)
        #btn_row.addWidget(self.btn_recarregar)
        btn_row.addStretch()
        lay_ata.addLayout(btn_row)

        self.lbl_ata_status = QLabel("")
        self.lbl_ata_status.setStyleSheet("color: #666; font-style: italic; font-weight: normal;")
        self.lbl_ata_status.setWordWrap(True)
        lay_ata.addWidget(self.lbl_ata_status)

        root.addWidget(grp_ata, 1)

    # ------------------------------------------------------------------
    # Carregamento / preenchimento do formulário
    # ------------------------------------------------------------------

    def carregar_form_ata(self):
        """Pré-preenche o formulário com dados da BD."""
        if not ATA_AVAILABLE or carregar_dados_iniciais is None:
            self.lbl_ata_status.setText(
                "⚠️ Módulo Gerar_Ata indisponível. Verifique se python-docx está instalado "
                "(pip install python-docx)."
            )
            return
        try:
            dados = carregar_dados_iniciais(self.pasta_dados)
        except Exception as e:
            self.lbl_ata_status.setText(f"⚠️ Erro ao carregar dados: {e}")
            return

        self.spin_num_adm.setValue(int(dados.get("num_adm") or 1))
        ano = dados.get("ano_exercicio") or date.today().year
        ano_ant = dados.get("ano_exercicio_ant") or (ano - 1)
        self.lbl_anos.setText(f"{ano_ant}  →  {ano}")
        self._ano_exercicio = ano
        self._ano_exercicio_ant = ano_ant

        self.spin_num_ata.setValue(int(dados.get("num_ata") or 1))

        d = dados.get("data") or date.today()
        if isinstance(d, date):
            self.date_edit.setDate(QDate(d.year, d.month, d.day))

        hi = dados.get("hora_inicial") or time(20, 0)
        hf = dados.get("hora_final") or time(22, 0)
        self.time_ini.setTime(QTime(hi.hour, hi.minute))
        self.time_fim.setTime(QTime(hf.hour, hf.minute))

        self.edit_admin_ant.setText(dados.get("admin_ant") or "")
        self.edit_fracao_ant.setText(dados.get("fracao_ant") or "")

        self._condominos_cache = dados.get("condominos") or []
        self.combo_novo_admin.blockSignals(True)
        self.combo_novo_admin.clear()
        self.combo_novo_admin.addItem("— selecionar —", None)
        idx_novo = 0
        nome_novo = (dados.get("administrador") or "").strip()
        for i, c in enumerate(self._condominos_cache, start=1):
            nome = c.get("NOME") or ""
            self.combo_novo_admin.addItem(nome, c)
            if nome_novo and nome == nome_novo:
                idx_novo = i
        self.combo_novo_admin.setCurrentIndex(idx_novo)
        self.combo_novo_admin.blockSignals(False)
        # Preencher CC/NIF/fração do novo admin já selecionado
        self._on_novo_admin_changed(idx_novo)

        self.txt_assuntos.setPlainText(dados.get("assuntos_gerais") or "")
        self.lbl_ata_status.setText("Dados carregados da base de dados.")

    def _on_novo_admin_changed(self, index: int):
        data = self.combo_novo_admin.itemData(index)
        if not data:
            self.edit_fracao.clear()
            self.edit_andar.clear()
            self.edit_cc.clear()
            self.edit_cc_val.clear()
            self.edit_nif.clear()
            return
        self.edit_fracao.setText(str(data.get("FRACAO") or ""))
        self.edit_andar.setText(str(data.get("ANDAR") or ""))
        self.edit_cc.setText(str(data.get("CC_NUMERO") or ""))
        self.edit_cc_val.setText(str(data.get("CC_VALIDADE") or ""))
        self.edit_nif.setText(str(data.get("NIF") or ""))

    def _recolher_dados_form(self) -> dict:
        qd = self.date_edit.date()
        data_py = date(qd.year(), qd.month(), qd.day())
        ti = self.time_ini.time()
        tf = self.time_fim.time()

        nome_novo = ""
        data_combo = self.combo_novo_admin.currentData()
        if data_combo:
            nome_novo = data_combo.get("NOME") or ""
        else:
            txt = self.combo_novo_admin.currentText().strip()
            if txt and not txt.startswith("—"):
                nome_novo = txt

        return {
            "num_adm": self.spin_num_adm.value(),
            "ano_exercicio": getattr(self, "_ano_exercicio", date.today().year),
            "ano_exercicio_ant": getattr(self, "_ano_exercicio_ant", date.today().year - 1),
            "num_ata": self.spin_num_ata.value(),
            "data": data_py,
            "hora_inicial": time(ti.hour(), ti.minute()),
            "hora_final": time(tf.hour(), tf.minute()),
            "admin_ant": self.edit_admin_ant.text().strip(),
            "fracao_ant": self.edit_fracao_ant.text().strip(),
            "administrador": nome_novo,
            "fracao": self.edit_fracao.text().strip(),
            "andar": self.edit_andar.text().strip(),
            "cc_numero": self.edit_cc.text().strip(),
            "cc_validade": self.edit_cc_val.text().strip(),
            "nif": self.edit_nif.text().strip(),
            "assuntos_gerais": self.txt_assuntos.toPlainText().strip(),
        }

    def gerar_ata_clicked(self):
        if not ATA_AVAILABLE or gerar_ata is None:
            QMessageBox.warning(
                self, "Módulo indisponível",
                "Não foi possível carregar Gerar_Ata.\n"
                "Instale a dependência:\n\npip install python-docx"
            )
            return
        if not DOCX_AVAILABLE:
            QMessageBox.warning(
                self, "python-docx em falta",
                "A biblioteca python-docx não está instalada.\n\n"
                "Execute no terminal:\npip install python-docx"
            )
            return
        dados = self._recolher_dados_form()
        if not dados.get("admin_ant"):
            QMessageBox.warning(
                self, "Dados em falta",
                "Indique o nome do administrador cessante (em exercício)."
            )
            return
        if not dados.get("administrador"):
            QMessageBox.warning(
                self, "Dados em falta",
                "Selecione o novo administrador."
            )
            return

        try:
            path = gerar_ata(self.pasta_dados, dados)
            self.lbl_ata_status.setText(f"✅ Ata gerada: {path.name}")
            resp = QMessageBox.information(
                self,
                "Ata gerada",
                f"Documento criado com sucesso:\n\n{path}\n\n"
                "Deseja abrir a pasta docs/?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp == QMessageBox.StandardButton.Yes:
                self.abrir_pasta_docs()
        except Exception as e:
            self.lbl_ata_status.setText(f"❌ Erro: {e}")
            QMessageBox.critical(self, "Erro ao gerar ata", str(e))

    def abrir_pasta_docs(self):
        pasta = DOCS_DIR
        pasta.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(pasta))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{pasta}"')
            else:
                os.system(f'xdg-open "{pasta}"')
        except Exception as e:
            QMessageBox.information(self, "Pasta docs/", f"Pasta:\n{pasta}\n\n({e})")

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
        self.carregar_form_ata()

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