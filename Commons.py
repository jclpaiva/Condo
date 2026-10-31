"""
Commons.py - Código compartilhado entre todos os módulos GUI

Contém:
- Configurações globais
- Delegates reutilizáveis
- Funções auxiliares de formatação
- Estilos CSS
- Camada de dados 100% relacional (condominio.db)

API de compatibilidade mantida:
  API canónica reexportada de Database (sem bridge legado)
passam a usar exclusivamente condominio.db (sem fallback para dados.sqlite).
"""

import sys
import datetime
import unicodedata
import pandas as pd

from pathlib import Path
try:
    from PyQt6.QtWidgets import QStyledItemDelegate, QComboBox
    from PyQt6.QtCore import Qt
    _HAS_QT = True
except ImportError:
    QStyledItemDelegate = object  # type: ignore
    QComboBox = object  # type: ignore
    Qt = None  # type: ignore
    _HAS_QT = False
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    pdfmetrics = None
    TTFont = None

# ====================================================================
# CONFIGURAÇÕES GLOBAIS
# ====================================================================

def get_base_dir():
    """
    Retorna o diretório base correto tanto para desenvolvimento quanto para executável.
    
    Quando rodando como executável PyInstaller:
    - sys.executable aponta para dist/GestaoCondominio/GestaoCondominio.exe
    - Precisamos do diretório pai (dist/) onde estão as pastas de dados
    
    Quando rodando como script Python:
    - __file__ aponta para o arquivo .py
    - O diretório do arquivo é o diretório base
    """
    if getattr(sys, 'frozen', False):
        # Rodando como executável PyInstaller
        # sys.executable = dist/GestaoCondominio/GestaoCondominio.exe
        # Queremos dist/ (o pai do pai)
        return Path(sys.executable).parent.parent
    else:
        # Rodando como script Python
        return Path(__file__).resolve().parent

# Versão da aplicação
# 1.00 — produção testada (ciclo completo OK)
# 1.01 — matemática de quotas extraída para Quotas.py (testes de regressão)
APP_VERSION = "1.01"

# Paths
BASE_DIR = get_base_dir()
IMPORT_DIR = BASE_DIR / "import"
ICONS_DIR = BASE_DIR / "icons"
FOTOS_DIR = BASE_DIR / "fotos"
DOCS_DIR = BASE_DIR / "docs"
FONTS_DIR = BASE_DIR / "fonts"
PASTA_CORRENTE = BASE_DIR / "corrente"
PASTA_HISTORICO = BASE_DIR / "historico"
EXPORT_DIR = BASE_DIR / "export"
DB_NAME = "condominio.db"
DB_EXPORT_NAME = "condo42.db"


def db_path(pasta: Path | None = None) -> Path:
    """Caminho do ficheiro de base de dados na pasta indicada (default = corrente)."""
    return (pasta or PASTA_CORRENTE) / DB_NAME


def db_export_path() -> Path:
    """Caminho da mini bdados exportada (condo42.db), usada pelo site web."""
    return EXPORT_DIR / DB_EXPORT_NAME


def pasta_de_dados(pasta_dados=None) -> Path:
    """
    Resolve o identificador usado pelas GUIs para a pasta real com condominio.db.

    Aceita: None, ``"corrente"``, ``"historico/2025"``, Path absoluto, …
    **Não** construa paths legados do tipo ``…/Bancos`` ou ``…/Configs`` —
    passe só a pasta lógica; ``resolver_pasta`` trata o resto.
    """
    # Import local evita ciclo Commons ↔ Database no carregamento do módulo
    from Database import resolver_pasta
    if pasta_dados is None or str(pasta_dados).strip() == "":
        return resolver_pasta(None)
    p = Path(pasta_dados)
    if not p.is_absolute():
        return resolver_pasta(BASE_DIR / p)
    return resolver_pasta(p)


def pasta_e_corrente(pasta_dados=None) -> bool:
    """True se a pasta de dados corresponde ao exercício **corrente** (não histórico).

    Usado para desativar operações só válidas no ano em curso (ex.: WhatsApp
    de cobrança de quotas em atraso).

    Critérios (qualquer um basta para considerar histórico → False):
      - o path contém ``historico`` (ex.: ``historico/2025``)
      - o path resolvido não é ``PASTA_CORRENTE``
    """
    if pasta_dados is None or str(pasta_dados).strip() in ("", "corrente"):
        return True
    s = str(pasta_dados).replace("\\", "/").strip().lower()
    if "historico" in s.split("/"):
        return False
    if s == "corrente" or s.endswith("/corrente"):
        return True
    try:
        resolved = pasta_de_dados(pasta_dados).resolve()
        corrente = PASTA_CORRENTE.resolve()
        if resolved == corrente:
            return True
        # pasta resolvida dentro de historico/
        hist = PASTA_HISTORICO.resolve()
        try:
            resolved.relative_to(hist)
            return False
        except ValueError:
            pass
        return resolved.name.lower() == "corrente"
    except Exception:
        return False


# Outros
LOGGING_LEVEL = 'INFO'

# ====================================================================
# DELEGATES REUTILIZÁVEIS
# ====================================================================

class ContaComboBoxDelegate(QStyledItemDelegate):
    """
    Delegate que cria uma ComboBox editável na coluna Conta.
    Filtra as contas baseado no TIPO (RECEITA/DESPESA) da linha.
    
    USADO POR: Bancos_Gui, Caixa_Gui, e futuros módulos
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.receitas = []
        self.despesas = []
        self.todas_contas = []
    
    def set_contas(self, receitas, despesas, todas):
        """Define as listas de contas disponíveis"""
        self.receitas = sorted(receitas)
        self.despesas = sorted(despesas)
        self.todas_contas = sorted(todas)
    
    def createEditor(self, parent, option, index):
        """Cria o editor (ComboBox) quando a célula é editada"""
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMaxVisibleItems(15)
        
        # Obter o TIPO da linha atual para filtrar contas
        model = index.model()
        tipo_index = model.index(index.row(), 1)  # Coluna 1 = TIPO
        tipo = model.data(tipo_index, Qt.ItemDataRole.DisplayRole)
        
        # Preencher combo baseado no tipo
        if tipo == "RECEITA":
            combo.addItems(self.receitas)
        elif tipo == "DESPESA":
            combo.addItems(self.despesas)
        else:
            combo.addItems(self.todas_contas)
        
        return combo
    
    def setEditorData(self, editor, index):
        """Define o valor atual no editor"""
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        editor.setCurrentText(str(value))
        editor.showPopup()
    
    def setModelData(self, editor, model, index):
        """Salva o valor do editor de volta no modelo"""
        value = editor.currentText()
        model.setData(index, value, Qt.ItemDataRole.EditRole)
    
    def updateEditorGeometry(self, editor, option, index):
        """Ajusta a geometria do editor"""
        editor.setGeometry(option.rect)


# ====================================================================
# ESTILOS CSS GLOBAIS
# ====================================================================

def get_app_stylesheet():
    """
    Retorna stylesheet CSS global para a aplicação.
    Usado em Main_Gui.py no QApplication.
    """
    return """
        QMainWindow { 
            background: #f8f9fa; 
        }
        
        QTabBar::tab { 
            padding: 8px 18px; 
            margin-right: 2px; 
            border-top-left-radius: 6px; 
            border-top-right-radius: 6px; 
            background: #e9ecef; 
            font-size: 12px; 
        }
        
        QTabBar::tab:selected { 
            background: white; 
            border-bottom: 3px solid #1976d2; 
            font-weight: bold; 
        }
        
        QTabBar::tab:hover:!selected { 
            background: #dee2e6; 
        }
        
        QPushButton { 
            background: #1976d2; 
            color: white; 
            border-radius: 6px; 
            padding: 8px; 
            font-size: 14px; 
        }
        
        QPushButton:hover { 
            background: #1565c0; 
        }
        
        QTableView { 
            alternate-background-color: #f8f9fa; 
            selection-background-color: #bbdefb; 
        }
        
        QTableView::item:selected { 
            background: #e3f2fd; 
            color: #1b15c0; 
            font-weight: bold; 
        }
        
        QHeaderView::section { 
            background: #e9ecef; 
            padding: 6px; 
            font-weight: bold; 
        }
        
        QComboBox { 
            padding: 4px; 
            border: 1px solid #ccc; 
            border-radius: 3px; 
        }
        
        QComboBox:editable { 
            background: white; 
        }
        
        QComboBox::drop-down { 
            border: none; 
        }
    """


# ====================================================================
# VALIDAÇÕES E UTILITÁRIOS → Database.existe_dados / criar_backup_db
# ====================================================================

# ====================================================================
# FUNÇÕES AUXILIARES
# ====================================================================


def clean_numeric(value):
    """Retorna 0.0 se o valor for NaN ou None."""
    return 0.0 if pd.isna(value) else float(value)


def remover_acentos(texto):
    """Remove acentos de um texto para normalização."""
    if not isinstance(texto, str):
        return texto
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(char for char in nfd if unicodedata.category(char) != "Mn")


def format_currency(value):
    """Formata valor como moeda (1,234.56 €)"""
    if pd.isna(value):
        return "0.00 €"
    return f"{value:,.2f} €"


def format_number(value):
    """Formata número como 1,234.56 (sem símbolo €)."""
    if value is None or value == "":
        return ""
    try:
        num = float(value)
        if abs(num) < 0.01:
            return ""
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return str(value) if value else ""


def format_date(date_obj, format_str="%d-%m-%Y"):
    """Formata data"""
    if date_obj is None or pd.isna(date_obj):
        return ""
    return date_obj.strftime(format_str)



# ---------------------------------------------------------------------------
# Camada de dados: reexporta API canónica de Database.py
# ---------------------------------------------------------------------------
from Database import (  # noqa: E402
    existe_dados,
    validar_db_existe,
    criar_backup_db,
    carregar_contas,
    # API canónica
    resolver_pasta,
    db_existe,
    quotas_por_fracao,
    regras_condominos_lista,
    movimentos_dataframe,
    aglutinar_movimentos,
    carregar_movimentos_fonte,
    guardar_movimentos_fonte,
    carregar_condominos,
    guardar_condominos,
    carregar_configs,
    guardar_configs,
    ano_exercicio as _ano_exercicio_db,
    configs as configs_repo,
)


def calcular_numero_admin(pasta_ou_configs=None):
    """
    Calcula o número da administração corrente.
    Lê ANO_EXERCICIO e NUMERO_ADMINISTRACAO via ConfigsRepo (SQL).
    Fórmula: numero_admin = ano_exercicio - numero_administracao + 1

    pasta_ou_configs: pasta de dados, path .../Configs, ou None (= corrente).
    """
    try:
        pasta = resolver_pasta(pasta_ou_configs)
        repo = configs_repo(pasta)
        ano_raw = repo.get_value("GERAL", "ANO_EXERCICIO", None)
        num_raw = repo.get_value("GERAL", "NUMERO_ADMINISTRACAO", None)
        if ano_raw is None or num_raw is None:
            raise ValueError("ANO_EXERCICIO ou NUMERO_ADMINISTRACAO em falta")
        ano_exercicio = int(clean_numeric(ano_raw))
        numero_administracao = int(clean_numeric(num_raw))
        print(f"  ✓ Ano exercício lido de Configs: {ano_exercicio}")
        print(f"  ✓ Ano da 1ª administração lido de Configs: {numero_administracao}")
    except Exception as e:
        print(f"  ⚠️  Erro ao ler Configs: {e}. Usando valores padrão.")
        ano_exercicio = datetime.date.today().year
        numero_administracao = 2005

    numero_admin = ano_exercicio - numero_administracao + 1
    print(
        f"  ✓ Administração corrente calculada: {numero_admin}ª "
        f"({ano_exercicio} - {numero_administracao} + 1)"
    )
    return numero_admin


def obter_ano_exercicio(pasta_dados="corrente"):
    """
    Obtém o ano do exercício (API canónica → ConfigsRepo).
    Aceita pasta de dados ou path legado (.../Configs, .../Bancos).
    """
    from datetime import datetime
    try:
        return int(_ano_exercicio_db(pasta_dados))
    except Exception as e:
        print(f"  ⚠️ Erro ao ler ANO_EXERCICIO: {e}, usando ano atual")
        return datetime.now().year

def registar_fonte():
    """Regista a fonte Segoe UI do diretório fonts
        Usado pelos modulos Condóminos e Report
    """
    try:
        font_path = FONTS_DIR / "segoeui.ttf"
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("SegoeUI", str(font_path)))
            return "SegoeUI"
        else:
            print(f"⚠️ Fonte não encontrada: {font_path}")
            return "Helvetica"
    except Exception as e:
        print(f"⚠️ Erro ao registar fonte: {e}")
        return "Helvetica"

# ====================================================================
# INICIALIZAÇÃO
# ====================================================================
# Criar diretórios se não existirem
for directory in [FOTOS_DIR, DOCS_DIR, EXPORT_DIR]:  # ✅ EXPORT_DIR incluído
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        print(f"📁 Diretório criado: {directory}")