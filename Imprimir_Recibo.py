"""
Imprimir_Recibo.py - Geração de recibos anuais em PDF (talão 80×150 mm)

Funcionalidades:
- Gera recibo anual de quotas pagas pelo condómino
- Formato talão 80 mm × 150 mm
- Valor por extenso
- Numeração automática: FRACAO/ANO  (ex: "A/2026")
- A fração é deduzida a partir do ANDAR
- NIF fixo do condomínio
"""

import os
from pathlib import Path
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# ---------------------------------------------------------------------------
# Importações do projecto (presentes no ambiente real)
# ---------------------------------------------------------------------------
try:
    from Commons import BASE_DIR, ICONS_DIR, DOCS_DIR, obter_ano_exercicio
except ImportError:
    # Fallback para testes standalone
    BASE_DIR = Path(".")
    ICONS_DIR = Path(".")
    DOCS_DIR = Path("docs")

# ---------------------------------------------------------------------------
# Constantes do condomínio
# ---------------------------------------------------------------------------
CONDOMINIO_NOME = "Condomínio Av. Sto. António, 42"
CONDOMINIO_NIF  = "901579220"

# Mapeamento ANDAR → FRAÇÃO (letra)
ANDAR_PARA_FRACAO = {
    "R/c Esq.":  "A",
    "R/c Dto.":  "B",
    "1º Esq.":   "C",
    "1º Dto.":   "D",
    "2º Esq.":   "E",
    "2º Dto.":   "F",
}

# ---------------------------------------------------------------------------
# Dimensões do talão
# ---------------------------------------------------------------------------
_MM = 2.8346          # 1 mm em pontos ReportLab
TALAO_WIDTH  = 85  * _MM   # 240.9 pt
TALAO_HEIGHT = 120 * _MM   # 300.0 pt

# ---------------------------------------------------------------------------
# Cor tema
# ---------------------------------------------------------------------------
COR_TEMA = colors.HexColor('#4A321A')


# ====================================================================
# VALOR POR EXTENSO
# ====================================================================

def valor_por_extenso(valor: float) -> str:
    """Converte um valor numérico para extenso em português de Portugal."""
    unidades = [
        "", "um", "dois", "três", "quatro", "cinco",
        "seis", "sete", "oito", "nove",
    ]
    dezenas = [
        "", "dez", "vinte", "trinta", "quarenta", "cinquenta",
        "sessenta", "setenta", "oitenta", "noventa",
    ]
    especiais = [
        "dez", "onze", "doze", "treze", "catorze", "quinze",
        "dezasseis", "dezassete", "dezoito", "dezanove",
    ]
    centenas = [
        "", "cem", "duzentos", "trezentos", "quatrocentos", "quinhentos",
        "seiscentos", "setecentos", "oitocentos", "novecentos",
    ]

    def _ate_999(n: int) -> str:
        """Converte 0-999 para extenso (sem a palavra 'euros')."""
        if n == 0:
            return ""
        if n == 100:
            return "cem"
        partes = []
        c = n // 100
        d = (n % 100) // 10
        u = n % 10
        if c > 0:
            partes.append("cento" if (c == 1 and (d > 0 or u > 0)) else centenas[c])
        if d == 1:
            partes.append(especiais[u])
        else:
            if d > 1:
                partes.append(dezenas[d])
            if u > 0:
                partes.append(unidades[u])
        return " e ".join(p for p in partes if p)

    def _numero(n: int) -> str:
        """Converte inteiro positivo para extenso (sem 'euros')."""
        if n == 0:
            return "zero"
        if n < 1000:
            return _ate_999(n)
        mil = n // 1000
        resto = n % 1000
        txt_mil = ("mil" if mil == 1 else _ate_999(mil) + " mil")
        if resto == 0:
            return txt_mil
        return txt_mil + " e " + _ate_999(resto)

    # Usar divisão inteira de cêntimos para evitar erros de float
    total_centimos = int(round(valor * 100))
    euros, centimos = divmod(total_centimos, 100)

    ext_euros = _numero(euros)
    resultado  = ext_euros + (" euro" if euros == 1 else " euros")

    if centimos > 0:
        ext_cent = _ate_999(centimos)
        resultado += " e " + ext_cent + (" cêntimo" if centimos == 1 else " cêntimos")

    return resultado


# ====================================================================
# FUNÇÃO PARA OBTER INICIAIS DO NOME
# ====================================================================

def obter_iniciais(nome_completo: str) -> str:
    """
    Obtém iniciais dos dois primeiros nomes, ignorando tokens que não
    comecem por letra (emojis, símbolos, etc.).

    Args:
        nome_completo: str com nome completo

    Returns:
        str: iniciais em minúsculas (ex: "lm", "jp")
    """
    import unicodedata

    def _e_letra(c: str) -> bool:
        return unicodedata.category(c).startswith("L")

    # Filtrar só tokens que comecem por letra
    partes = [p for p in nome_completo.strip().split() if p and _e_letra(p[0])]

    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).lower()
    elif len(partes) == 1:
        return (partes[0][0] * 2).lower()
    else:
        return "xx"


# ====================================================================
# FUNÇÃO PRINCIPAL
# ====================================================================

def gerar_recibo_pdf(
    fracao: str,
    nome_condomino: str,
    valor_total: float,
    administrador_nome: str,
    pasta_dados: str,
    output_dir: Path | None = None,
    valor_normal: float = 0.0,
    valor_extra: float = 0.0,
    meses_normal: int = 0,
    meses_extra: int = 0,
) -> Path:
    """
    Gera recibo em PDF formato talão (80 × 150 mm).

    Args:
        fracao            : Fração do condómino (ex: "A")
        nome_condomino    : Nome completo do condómino
        valor_total       : Valor total pago no ano (normal + extra)
        administrador_nome: Nome do administrador
        pasta_dados       : Pasta de dados (ex: "corrente")
        output_dir        : Diretório de saída (padrão: BASE_DIR/docs)
        valor_normal      : Total de quotas normais (opcional)
        valor_extra       : Total de quotas extras (opcional)
        meses_normal      : Nº de meses de quotas normais pagos (opcional)
        meses_extra       : Nº de meses de quotas extras pagos (opcional)

    Returns:
        Path: Caminho do PDF gerado
    """
    if valor_total <= 0:
        raise ValueError("Valor do recibo deve ser maior que zero.")

    # --- Diretório de saída ---
    if output_dir is None:
        output_dir = BASE_DIR / "docs"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # --- Dados derivados ---
    try:
        ano_exercicio = str(obter_ano_exercicio(pasta_dados))
    except Exception:
        from datetime import datetime
        ano_exercicio = str(datetime.now().year)

    num_recibo  = f"{fracao}/{ano_exercicio}"
    data_recibo = f"31/12/{ano_exercicio}"

    extenso = valor_por_extenso(valor_total)
    extenso = extenso[0].upper() + extenso[1:]

    # Truncar nome para caber na coluna esquerda (talão 85mm)
    _MAX_NOME = 30
    nome_display = (nome_condomino[:_MAX_NOME - 1] + "…") if len(nome_condomino) > _MAX_NOME else nome_condomino

    # Flag: mostrar breakdown normal/extra ou só total
    _mostrar_extras = valor_extra > 0 or valor_normal > 0

    # --- Ficheiro de saída ---
    nome_ficheiro = f"Recibo_{fracao}_{ano_exercicio}.pdf"
    pdf_path      = Path(output_dir) / nome_ficheiro

    # ================================================================
    # ESTILOS
    # ================================================================
    fs_base  = 6.5    # fonte base para talão
    fs_small = 5.5
    fs_bold  = 7.0

    def _style(name, font="Helvetica", size=fs_base, align=0, leading=None):
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size,
            leading=leading or (size * 1.35),
            textColor=COR_TEMA,
            alignment=align,   # 0=left, 1=center, 2=right
        )

    s_normal   = _style("Norm")
    s_bold     = _style("Bold",   font="Helvetica-Bold", size=fs_bold)
    s_right    = _style("Right",  align=2)
    s_rb       = _style("RightB", font="Helvetica-Bold", size=fs_bold, align=2)
    s_center   = _style("Ctr",    align=1)
    s_small    = _style("Small",  size=fs_small)
    s_small_b  = _style("SmallB", font="Helvetica-Bold", size=fs_small)

    # ================================================================
    # DOCUMENT
    # ================================================================
    margin = 5 * _MM
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=(TALAO_WIDTH, TALAO_HEIGHT),
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=10 * _MM,
    )

    # Email fixo na última linha inferior do talão (altura total: 120 mm).
    def _desenhar_rodape(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", fs_small)
        canvas.setFillColor(COR_TEMA)
        canvas.drawString(margin, 4 * _MM, "42condominio@gmail.com")
        canvas.restoreState()

    col_total = TALAO_WIDTH - 2 * margin   # largura útil ≈ 197 pt

    elements = []

    # ----------------------------------------------------------------
    # Helper: linha horizontal dupla
    # ----------------------------------------------------------------
    def _linha_dupla():
        t = Table([[""]], colWidths=[col_total], rowHeights=[3])
        t.setStyle(TableStyle([
            ("LINEABOVE",  (0, 0), (-1, -1), 1.2, COR_TEMA),
            ("LINEBELOW",  (0, 0), (-1, -1), 0.4, COR_TEMA),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t

    def _linha_dupla_inv():
        t = Table([[""]], colWidths=[col_total], rowHeights=[3])
        t.setStyle(TableStyle([
            ("LINEABOVE",  (0, 0), (-1, -1), 0.4, COR_TEMA),  # fina em cima
            ("LINEBELOW",  (0, 0), (-1, -1), 1.2, COR_TEMA),  # grossa em baixo
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t
        
    def _linha_simples():
        t = Table([[""]], colWidths=[col_total], rowHeights=[1])
        t.setStyle(TableStyle([
            ("LINEABOVE",  (0, 0), (-1, -1), 0.4, COR_TEMA),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t

    def _sp(h=4):
        return Spacer(1, h)

    # ================================================================
    # CABEÇALHO
    # ================================================================
    elements.append(_linha_dupla())
    elements.append(_sp(5))

    # Nome do condomínio | NIF
    col_l = col_total * 0.60
    col_r = col_total * 0.40
    t_cab = Table(
        [[
            Paragraph(CONDOMINIO_NOME, s_bold),
            Paragraph(f"NIF: {CONDOMINIO_NIF}", s_rb),
        ]],
        colWidths=[col_l, col_r],
    )
    t_cab.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(t_cab)
    elements.append(_sp(5))
    elements.append(_linha_dupla())
    elements.append(_sp(6))

    # ================================================================
    # BLOCO DE IDENTIFICAÇÃO
    # ================================================================
    t_id = Table(
        [
            [
                Paragraph(f"Recibo Nº: <b>{num_recibo}</b>", s_normal),
                Paragraph(f"Data: <b>{data_recibo}</b>", s_rb),
            ],
            [
                Paragraph(f"Condómino: {nome_display}", s_normal),
                Paragraph(f"Fração: {fracao}", s_right),
            ],
        ],
        colWidths=[col_l, col_r],
    )
    t_id.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(t_id)
    elements.append(_sp(8))

    # ================================================================
    # TABELA DE VALORES
    # ================================================================
    # Colunas: Descrição | Nº Meses | Valor
    col_desc  = col_total * 0.50
    col_meses = col_total * 0.22
    col_valor = col_total * 0.28

    s_center_s = _style("CtrS", align=1, size=fs_small)
    s_center_n = _style("CtrN", align=1, size=fs_base)

    elements.append(_linha_simples())
    elements.append(_sp(4))

    # Cabeçalho da tabela
    t_th = Table(
        [[
            Paragraph("Descrição",  s_small_b),
            Paragraph("Meses", _style("ThC", font="Helvetica-Bold", size=fs_small, align=1)),
            Paragraph("Valor",  _style("ThR", font="Helvetica-Bold", size=fs_small, align=2)),
        ]],
        colWidths=[col_desc, col_meses, col_valor],
    )
    t_th.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(t_th)
    elements.append(_sp(4))
    elements.append(_linha_simples())
    elements.append(_sp(5))

    # Linhas de dados
    if _mostrar_extras:
        meses_n_str = str(meses_normal) if meses_normal > 0 else "-"
        meses_e_str = str(meses_extra)  if meses_extra  > 0 else "-"
        linhas = [
            [Paragraph("Quotas Normais", s_normal), Paragraph(meses_n_str, s_center_n), Paragraph(f"{valor_normal:.2f}", s_right)],
            [Paragraph("Quotas Extras",  s_normal), Paragraph(meses_e_str, s_center_n), Paragraph(f"{valor_extra:.2f}",  s_right)],
        ]
    else:
        linhas = [
            [Paragraph("Quotas de Condomínio", s_normal), Paragraph("-", s_center_n), Paragraph(f"{valor_total:.2f}", s_right)],
        ]
    t_linhas = Table(linhas, colWidths=[col_desc, col_meses, col_valor])
    t_linhas.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(t_linhas)
    elements.append(_sp(5))
    elements.append(_linha_simples())
    elements.append(_sp(5))

    # Total (span as 3 colunas, valor alinhado à direita)
    t_total = Table(
        [[
            Paragraph("TOTAL PAGO:", s_bold),
            Paragraph("EUR", _style("TotC", font="Helvetica-Bold", size=fs_bold, align=1)),
            Paragraph(f"{valor_total:.2f}", s_rb),
        ]],
        colWidths=[col_desc, col_meses, col_valor],
    )
    t_total.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(t_total)
    elements.append(_sp(8))

    # ================================================================
    # RODAPÉ
    # ================================================================
    elements.append(_linha_simples())
    elements.append(_sp(7))

    recebido_txt = (
        f"<b>Recebido</b> : &mdash;&mdash; {extenso} &mdash;&mdash;"
    )
    elements.append(Paragraph(recebido_txt, s_normal))
    elements.append(_sp(8))

    elements.append(Paragraph("O Administrador:", s_normal))
    elements.append(_sp(3))

    # Assinatura PNG (134×48 px → 20×7 mm no talão)
    iniciais = obter_iniciais(administrador_nome)
    assinatura_path = ICONS_DIR / f"assinatura_{iniciais}.png"

    if assinatura_path.exists():
        from reportlab.platypus import Image as RLImage
        sig = RLImage(str(assinatura_path), width=15 * _MM, height=7 * _MM)
        sig.hAlign = "LEFT"
        elements.append(sig)
        elements.append(_sp(3))
    else:
        # Fallback: espaço em branco para assinatura manual
        elements.append(_sp(20))

    elements.append(Paragraph(f"({administrador_nome})", _style("AdminNome", size=fs_small)))
    elements.append(_sp(7))
    elements.append(_linha_dupla_inv())

    # ================================================================
    # BUILD
    # ================================================================
    doc.build(elements, onFirstPage=_desenhar_rodape, onLaterPages=_desenhar_rodape)
    print(f"✓ Recibo gerado: {pdf_path}")
    return pdf_path


# ====================================================================
# TESTE STANDALONE
# ====================================================================

if __name__ == "__main__":
    print("=== TESTE: VALOR POR EXTENSO ===")
    for v in [100.00, 200.00, 300.00, 768.00, 1250.50, 1.01]:
        print(f"  {v:>10.2f} € => {valor_por_extenso(v)}")

    print("\n=== TESTE: GERAÇÃO DE RECIBO ===")
    pdf = gerar_recibo_pdf(
        fracao             = "A",
        nome_condomino     = "João Manuel Teixeira da Silva",
        valor_total        = 300.00,
        administrador_nome = "João Paiva",
        pasta_dados        = "corrente",
        output_dir         = Path("docs"),
        valor_normal       = 100.00,
        valor_extra        = 200.00,
        meses_normal       = 12,
        meses_extra        = 10,
    )
    print(f"  PDF: {pdf}")
