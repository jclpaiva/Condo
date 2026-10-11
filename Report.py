"""
Report.py - Geração de relatório consolidado em PDF (Despesas, Receitas, Balanço)
- Lê dados SQLite da pasta relativa fornecida
- Salva SEMPRE como: BASE_DIR / "docs" / "Relatorio_Condominio.pdf"
- Usa DOCS_DIR e format_number de Commons.py
"""

import sys

from pathlib import Path
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, red
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Importações compartilhadas
from Commons import (
    BASE_DIR,
    DOCS_DIR,
    FONTS_DIR,
    format_number,
    carregar_db,
    registar_fonte
)

# ===================== CONFIG =====================
THEME = {
    "primary": "#2F5597",
    "border": "#C0C0C0",
    "total_bg": "#E9EFF7"
}

# Registar fonte ao importar módulo
FONT_NAME = registar_fonte()


def _numero_seguro(valor):
    """
    Converte um valor vindo do bridge (carregar_db) para float, tratando
    None/'' como 0.0. Necessário porque, com o SQLite-first, todos os
    valores voltam como texto (str), mesmo os campos numéricos - ao
    contrário de valores já tipados.
    """
    if valor is None or valor == "":
        return 0.0
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


# ===================== BALANÇO =====================
def separar_balanco_por_marcador(rows):
    esq, dir = [], []
    lado = "ESQ"
    for r in rows:
        conta = str(r.get("CONTA", "")).strip()
        if conta.startswith("---"):
            lado = "DIR"
            continue
        item = (conta, _numero_seguro(r.get("VALOR")))
        (esq if lado == "ESQ" else dir).append(item)
    return esq, dir

def emparelhar_balanco(esq, dir):
    max_linhas = max(len(esq), len(dir))
    return [(esq[i] if i < len(esq) else ("", 0), dir[i] if i < len(dir) else ("", 0)) for i in range(max_linhas)]

# ===================== GERAÇÃO DE PDF =====================
def gerar_pdf_relatorio(pasta_dados: str):
    """
    Gera um único PDF com Despesas, Receitas Normais, Receitas Extraordinárias e Balanço.
    Salva SEMPRE como: BASE_DIR / "docs" / "Relatorio_Condominio.pdf"
    """
    pasta_dados = BASE_DIR / pasta_dados
    if not pasta_dados.exists():
        raise FileNotFoundError(f"Pasta de dados não encontrada: {pasta_dados}")

    despesas = carregar_db(pasta_dados / "Despesas")
    receitasN = carregar_db(pasta_dados / "ReceitasN")
    receitasE = carregar_db(pasta_dados / "ReceitasE")
    balanco_rows, _ = carregar_db(pasta_dados / "Balanco")

    if not any([despesas[0], receitasN[0], receitasE[0], balanco_rows]):
        raise ValueError("Nenhum dado válido encontrado.")

    pdf_file = DOCS_DIR / "Relatorio_Condominio.pdf"

    try:
        pdfmetrics.registerFont(TTFont("SegoeUI", "segoeui.ttf"))
        FONT_NAME = "SegoeUI"
    except:
        FONT_NAME = "Helvetica"

    doc = SimpleDocTemplate(
        str(pdf_file),
        pagesize=landscape(A4),
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    page_width, _ = landscape(A4)
    usable_width = page_width - 72
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        fontName=FONT_NAME,
        fontSize=16,
        alignment=1,
        textColor=HexColor(THEME["primary"]),
        spaceAfter=20
    ))
    elements = []

    def tabela_simples(titulo, rows, fields, colWidths):
        elements.append(Paragraph(titulo, styles["ReportTitle"]))
        data = [fields]
        negativos = []
        for row_idx, r in enumerate(rows, start=1):
            linha = []
            for col_idx, f in enumerate(fields):
                v = r.get(f)
                if v not in ("", None):
                    try:
                        if float(v) < 0:
                            negativos.append((row_idx, col_idx))
                    except (TypeError, ValueError):
                        pass
                linha.append(format_number(v) if v not in ("", None) else "")
            data.append(linha)
        t = Table(data, repeatRows=1, colWidths=colWidths)
        style = [
            ("FONT", (0,0), (-1,-1), FONT_NAME),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.25, HexColor(THEME["border"])),
            ("BACKGROUND", (0,0), (-1,0), HexColor(THEME["total_bg"])),
            ("ALIGN", (1,0), (-1,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]
        for r, c in negativos:
            style.append(("TEXTCOLOR", (c, r), (c, r), red))
        t.setStyle(TableStyle(style))
        elements.append(t)
        elements.append(Spacer(1, 14))

    if despesas[0]:
        num_cols_d = len(despesas[1])
        first_col = 140
        rest_width = usable_width - first_col
        other_cols = rest_width / (num_cols_d - 1)
        colWidths_d = [first_col] + [other_cols] * (num_cols_d - 1)
        tabela_simples("Despesas", despesas[0], despesas[1], colWidths_d)
        elements.append(PageBreak())

    if receitasN[0]:
        num_cols_r = len(receitasN[1])
        col_width = usable_width / num_cols_r
        colWidths_r = [col_width] * num_cols_r
        tabela_simples("Receitas Normais", receitasN[0], receitasN[1], colWidths_r)
        elements.append(Spacer(1, 18))
    if receitasE[0]:
        tabela_simples("Receitas Extraordinárias", receitasE[0], receitasE[1], colWidths_r)
        elements.append(PageBreak())

    if balanco_rows:
        esq, dir = separar_balanco_por_marcador(balanco_rows)
        linhas = emparelhar_balanco(esq, dir)
        elements.append(Paragraph("Balanço da Administração", styles["ReportTitle"]))
        data = [["Débitos", "", "Créditos", ""]]
        negativos = []
        for row_idx, (e, d) in enumerate(linhas, start=1):
            if e[1] < 0: negativos.append((row_idx, 1))
            if d[1] < 0: negativos.append((row_idx, 3))
            data.append([e[0], format_number(e[1]), d[0], format_number(d[1])])
        t = Table(data, colWidths=[
            usable_width * 0.35,
            usable_width * 0.15,
            usable_width * 0.35,
            usable_width * 0.15
        ])
        style = [
            ("FONT", (0,0), (-1,-1), FONT_NAME),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.25, HexColor(THEME["border"])),
            ("BACKGROUND", (0,0), (-1,0), HexColor(THEME["total_bg"])),
            ("ALIGN", (1,0), (1,-1), "RIGHT"),
            ("ALIGN", (3,0), (3,-1), "RIGHT"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]
        for r, c in negativos:
            style.append(("TEXTCOLOR", (c, r), (c, r), red))
        t.setStyle(TableStyle(style))
        elements.append(t)

    try:
        doc.build(elements)
    except Exception as e:
        if pdf_file.exists():
            pdf_file.unlink()
        raise RuntimeError(f"Erro ao construir o PDF: {e}")

    return str(pdf_file.resolve())

# ===================== EXECUÇÃO STANDALONE =====================
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python Report.py <pasta_dados>")
        sys.exit(1)
    pasta = sys.argv[1]
    try:
        caminho_pdf = gerar_pdf_relatorio(pasta)
        print(f"✅ Relatório gerado: {caminho_pdf}")
    except Exception as e:
        print(f"❌ Erro: {e}")
        sys.exit(1)