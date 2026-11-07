"""
Gerar_Ata.py - Geração automática da Ata de Assembleia de Condóminos.

Preenche o template templates/ATA_template.docx com:
  - dados de CONFIGS (ano exercício, nº administração)
  - dados de CONDOMINOS (administrador cessante e novo)
  - campos manuais do formulário (nº ata, data, horas, assuntos gerais)

API principal:
  gerar_ata(pasta_dados, dados: dict) -> Path  (caminho do .docx gerado)
  carregar_dados_iniciais(pasta_dados) -> dict  (pré-preenchimento do formulário)
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

try:
    from docx import Document
    from docx.shared import Pt, Cm, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    DOCX_AVAILABLE = True
except ImportError:
    Document = None  # type: ignore
    Pt = Cm = Inches = WD_ALIGN_PARAGRAPH = qn = None  # type: ignore
    DOCX_AVAILABLE = False

from Commons import (
    format_currency,
    BASE_DIR,
    DOCS_DIR,
    ICONS_DIR,
    TEMPLATES_DIR,
    obter_ano_exercicio,
    format_number,
)
from Database import (
    resolver_pasta,
    carregar_condominos,
    db_existe,
    configs as configs_repo,
    load_despesas_wide,
    load_receitas_wide,
    load_balanco_wide,
)
from Report import separar_balanco_por_marcador, emparelhar_balanco

TEMPLATE_PATH = TEMPLATES_DIR / "ATA_template.docx"

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def data_por_extenso(d: date | datetime | str) -> str:
    """Converte data para formato português: '15 de janeiro de 2027'."""
    if isinstance(d, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
            try:
                d = datetime.strptime(d.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return d
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} de {MESES_PT[d.month]} de {d.year}"


def formatar_hora(h: time | str | datetime) -> str:
    """Devolve hora no formato HH:MM."""
    if isinstance(h, str):
        h = h.strip()
        if len(h) >= 5 and h[2] == ":":
            return h[:5]
        return h
    if isinstance(h, datetime):
        h = h.time()
    return h.strftime("%H:%M")


def caminho_assinatura(nome_admin: str) -> Optional[Path]:
    """
    Localiza icons/assinatura_XX.png com a mesma lógica dos recibos
    (Imprimir_Recibo.obter_iniciais): 1ª letra do 1º nome + 1ª letra do 2º nome.
    Ex.: 'Luís Miguel Silva' → assinatura_lm.png
    """
    if not nome_admin:
        return None
    from Imprimir_Recibo import obter_iniciais
    sufixo = obter_iniciais(nome_admin)
    path = ICONS_DIR / f"assinatura_{sufixo}.png"
    return path if path.is_file() else None


def _is_admin(val: Any) -> bool:
    """Administrador atual (admin == 1)."""
    try:
        return int(val) == 1
    except (TypeError, ValueError):
        return val in (True, "1", "T", ".T.", "t", "True", "true")


def _is_admin_cessante(val: Any) -> bool:
    """Administrador cessante / ex-admin (admin == -1)."""
    try:
        return int(val) == -1
    except (TypeError, ValueError):
        return val in (-1, "-1")


# ---------------------------------------------------------------------------
# Carregamento de dados iniciais (para o formulário)
# ---------------------------------------------------------------------------

def _numero_administracao_base(pasta) -> int:
    """Lê CONFIGS GERAL/NUMERO_ADMINISTRACAO (ano da 1ª administração). Default 2005."""
    try:
        raw = configs_repo(pasta).get_value("GERAL", "NUMERO_ADMINISTRACAO", None)
        if raw is not None:
            return int(str(raw).strip())
    except Exception:
        pass
    return 2005


def carregar_dados_iniciais(pasta_dados=None) -> dict:
    """
    Devolve dicionário com valores pré-preenchidos a partir da BD.
    Chaves usadas pelo formulário e por gerar_ata().

    Timing real do processo anual:
      - A reunião de assembleia ocorre em janeiro de N+1.
      - Nessa altura as contas de N ainda NÃO estão encerradas: ANO_EXERCICIO
        na BD continua a ser N (só avança no Fim_Ano, depois da aprovação
        e da elaboração da ata).
      - Portanto:
          ano_exercicio_ant = ANO_EXERCICIO da BD  (= N, contas a aprovar)
          ano_exercicio     = N + 1                (orçamento / novo admin)
          num_adm           = N - NUMERO_ADMINISTRACAO
            ex.: 2026 - 2005 = 21ª administração  (ou 20ª se base=2006)

    Placeholders do template:
      {{ANO_EXERCICIO_ANT}} → contas / título da ata / nome do ficheiro
      {{ANO_EXERCICIO}}     → orçamento e exercício do novo administrador
    """
    pasta = resolver_pasta(pasta_dados)
    # ANO_EXERCICIO na BD = ano das contas ainda abertas (N), não o ano civil.
    ano_contas = obter_ano_exercicio(pasta)   # ex.: 2026 (contas a aprovar)
    ano_novo = ano_contas + 1                 # ex.: 2027 (orçamento / novo admin)
    base_admin = _numero_administracao_base(pasta)  # ex.: 2005
    num_adm = ano_contas - base_admin         # ex.: 2026 - 2005 = 21

    condominos = carregar_condominos(pasta) if db_existe(pasta) else []

    # Na reunião de janeiro o admin em exercício ainda é o cessante (ADMIN=1);
    # o novo admin pode já estar marcado ou ser escolhido no formulário.
    # Preferir ADMIN=-1 (cessante explícito) se existir; senão o admin actual.
    admin_cessante = None
    admin_atual = None
    for c in condominos:
        if _is_admin_cessante(c.get("ADMIN")):
            admin_cessante = c
        if _is_admin(c.get("ADMIN")):
            admin_atual = c

    # Nº da ata: tentativa de incremento a partir dos ficheiros existentes
    num_ata = _sugerir_num_ata()

    # admin_ant = quem conduz a reunião (ainda em exercício) = cessante
    # Se já existir flag de cessante, usa-o; caso contrário o admin actual.
    admin_ant_reg = admin_cessante or admin_atual or {}
    # Novo administrador: se houver um distinto do cessante marcado como admin, usa-o
    admin_novo_reg = admin_atual if (admin_atual and admin_atual is not admin_cessante) else {}

    return {
        "num_adm": num_adm,
        "ano_exercicio": ano_novo,          # N+1 — orçamento / novo exercício
        "ano_exercicio_ant": ano_contas,    # N   — contas aprovadas nesta ata
        "num_ata": num_ata,
        "data": date.today(),
        "hora_inicial": time(20, 0),
        "hora_final": time(22, 0),
        "admin_ant": admin_ant_reg.get("NOME", ""),
        "fracao_ant": admin_ant_reg.get("FRACAO", ""),
        # Pré-seleção do novo admin no formulário (pode ficar vazio para escolha manual)
        "administrador": admin_novo_reg.get("NOME", ""),
        "fracao": admin_novo_reg.get("FRACAO", ""),
        "andar": admin_novo_reg.get("ANDAR", ""),
        "cc_numero": admin_novo_reg.get("CC_NUMERO", ""),
        "cc_validade": admin_novo_reg.get("CC_VALIDADE", ""),
        "nif": admin_novo_reg.get("NIF", ""),
        "assuntos_gerais": _texto_assuntos_default(),
        "condominos": condominos,
    }


def _sugerir_num_ata() -> int:
    """Sugere o próximo número de ata com base nos ficheiros em docs/."""
    if not DOCS_DIR.exists():
        return 1
    nums = []
    for f in DOCS_DIR.glob("Ata_*.docx"):
        m = re.search(r"Ata_(\d+)", f.stem, re.I)
        if m:
            nums.append(int(m.group(1)))
    for f in DOCS_DIR.glob("Ata_*.pdf"):
        m = re.search(r"Ata_(\d+)", f.stem, re.I)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def _texto_assuntos_default() -> str:
    return (
        "• Foi deliberado manter o valor da quota normal mensal, acrescido da quota extra "
        "de montante idêntico ao atualmente em vigor, tal como aprovado em reunião anterior, "
        "para fazer face às despesas correntes e ao fundo comum de reserva.\n\n"
        "• Relativamente às obras previstas na fachada do edifício, foi aprovado que, "
        "aproveitando a eventual redução do IVA aplicável a obras de conservação e reabilitação "
        "(nomeadamente a taxa reduzida que possa vigorar em 2026 para empreitadas de reabilitação "
        "de edifícios habitacionais), o orçamento global para a realização das referidas obras "
        "fica condicionalmente aprovado até ao limite máximo de 8.600 € (valor já previamente "
        "referenciado). Caso o orçamento final apresentado pela empresa adjudicada fique abaixo "
        "desse montante, considerando a poupança resultante da redução do IVA, as obras ficam "
        "automaticamente autorizadas e o administrador fica mandatado para proceder à sua "
        "contratação e execução sem necessidade de nova assembleia. Caso o custo ultrapasse os "
        "8.600 €, deverá ser convocada nova reunião de condóminos para aprovação do orçamento ajustado.\n\n"
        "• Ficou decidido proceder à realização de um teste de carga (ou ensaio de "
        "estanqueidade/carga hidrostática) pela empresa que irá executar as obras na fachada, "
        "especificamente no solário da fração E (2.º Esq.), com o objetivo de verificar se existe "
        "infiltração clara de água para o interior dessa fração em caso de condições simuladas "
        "de chuva intensa ou exposição prolongada. O teste será efetuado antes ou durante a fase "
        "inicial das obras, sendo os resultados comunicados aos condóminos e servindo de base "
        "para eventuais ajustes no âmbito da intervenção na fachada. O administrador fica "
        "autorizado a coordenar e supervisionar a execução deste teste."
    )


# ---------------------------------------------------------------------------
# Geração do documento
# ---------------------------------------------------------------------------

def _substituir_placeholders(doc: Document, mapa: dict[str, str]) -> None:
    """Substitui {{CHAVE}} em todos os parágrafos e tabelas do documento."""
    def replace_in_paragraph(paragraph):
        full = "".join(run.text for run in paragraph.runs)
        if "{{" not in full:
            return
        novo = full
        for k, v in mapa.items():
            novo = novo.replace("{{" + k + "}}", v)
        if novo == full:
            return
        # Redistribuir o texto no primeiro run e limpar os restantes
        if paragraph.runs:
            paragraph.runs[0].text = novo
            for r in paragraph.runs[1:]:
                r.text = ""
        else:
            paragraph.add_run(novo)

    for p in doc.paragraphs:
        replace_in_paragraph(p)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    replace_in_paragraph(p)


def _inserir_assuntos(doc: Document, texto: str) -> None:
    """
    Substitui o parágrafo que contém {{ASSUNTOS_GERAIS}} por um ou mais
    parágrafos justificados com o texto fornecido (suporta \\n).
    """
    alvo = None
    for p in doc.paragraphs:
        if "{{ASSUNTOS_GERAIS}}" in "".join(r.text for r in p.runs):
            alvo = p
            break
    if alvo is None:
        return

    # Limpar o parágrafo placeholder
    for r in alvo.runs:
        r.text = ""

    linhas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    if not linhas:
        alvo.add_run("—")
        return

    # Primeira linha no próprio parágrafo
    run = alvo.add_run(linhas[0])
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    run.font.size = Pt(11)
    alvo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # Linhas seguintes: inserir novos parágrafos a seguir
    # (python-docx não tem insert_after simples; usamos o XML)
    from docx.oxml import OxmlElement

    ref = alvo._p
    parent = ref.getparent()
    idx = list(parent).index(ref)

    for i, linha in enumerate(linhas[1:], start=1):
        novo_p = OxmlElement("w:p")
        # Cópia mínima de formatação de justificação
        pPr = OxmlElement("w:pPr")
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), "both")
        pPr.append(jc)
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:after"), "120")
        pPr.append(spacing)
        novo_p.append(pPr)

        r = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        rFonts = OxmlElement("w:rFonts")
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rPr.append(rFonts)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "22")  # 11 pt
        rPr.append(sz)
        r.append(rPr)
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = linha
        r.append(t)
        novo_p.append(r)
        parent.insert(idx + i, novo_p)


def _inserir_assinatura(doc: Document, nome_admin: str) -> None:
    """Substitui {{ASSINATURA_PLACEHOLDER}} por imagem (se existir) ou deixa em branco.

    Tamanho igual aos recibos: 134×48 px → 15 mm × 7 mm.
    """
    img = caminho_assinatura(nome_admin)
    for p in doc.paragraphs:
        texto = "".join(r.text for r in p.runs)
        if "{{ASSINATURA_PLACEHOLDER}}" not in texto:
            continue
        for r in p.runs:
            r.text = ""
        if img and img.is_file():
            try:
                run = p.add_run()
                # Mesmas dimensões dos recibos (Imprimir_Recibo: 15 mm × 7 mm)
                run.add_picture(str(img), width=Cm(1.5), height=Cm(0.7))
            except Exception as e:
                print(f"  ⚠️ Não foi possível inserir assinatura: {e}")
        return


def _set_cell_border(cell, **kwargs) -> None:
    """Define bordas de uma célula (tcBorders). kwargs: top/left/bottom/right → {sz, val, color}."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.find(qn("w:tcBorders"))
    if tcBorders is None:
        from docx.oxml import OxmlElement
        tcBorders = OxmlElement("w:tcBorders")
        tcPr.append(tcBorders)
    from docx.oxml import OxmlElement
    for edge, attrs in kwargs.items():
        element = tcBorders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            tcBorders.append(element)
        for key, value in attrs.items():
            element.set(qn(f"w:{key}"), str(value))


def _set_cell_shading(cell, fill: str) -> None:
    """Fundo da célula (ex.: 'D9E2F3')."""
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.append(shd)
    shd.set(qn("w:fill"), fill)
    shd.set(qn("w:val"), "clear")


def _formatar_permilagem(val: Any) -> str:
    """0.146 → '0,146'; 146 → '0,146' (se > 1 assume milésimos)."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val or "")
    if f > 1.5:  # veio em milésimos (146) em vez de fração (0.146)
        f = f / 1000.0
    return f"{f:.3f}".replace(".", ",")


def _inserir_lista_presencas(
    doc: Document,
    condominos: Optional[list] = None,
    fracoes_presentes: Optional[list] = None,
) -> None:
    """
    No parágrafo «Lista de Presenças» (fim da ata): mantém o título e insere
    uma tabela Word só com os condóminos presentes, no layout da antiga imagem:
      título | Fração | Andar | Condómino | % | Rúbrica | total permilagem.
    """
    alvo = None
    for p in doc.paragraphs:
        if "Lista de Presenças" in "".join(r.text for r in p.runs):
            alvo = p
            break
    if alvo is None:
        print("  ⚠️ Parágrafo 'Lista de Presenças' não encontrado no template.")
        return

    condominos = list(condominos or [])
    presentes_set = {str(f).strip().upper() for f in (fracoes_presentes or []) if f}
    # Filtrar e ordenar por fração (A, B, C…)
    if presentes_set:
        rows_data = [
            c for c in condominos
            if str(c.get("FRACAO") or "").strip().upper() in presentes_set
        ]
    else:
        rows_data = list(condominos)
    rows_data.sort(key=lambda c: str(c.get("FRACAO") or "").strip().upper())

    if not rows_data:
        print("  ⚠️ Nenhum condómino presente para a lista de presenças.")
        return

    # --- construir tabela (título + cabeçalho + linhas + total) ---
    n_data = len(rows_data)
    # 1 título + 1 header + n dados + 1 total
    table = doc.add_table(rows=2 + n_data + 1, cols=5)
    # mover a tabela para logo a seguir ao título «Lista de Presenças»
    alvo._p.addnext(table._tbl)

    # Larguras aproximadas (cm) — página útil ~16,5 cm
    widths = (Cm(1.6), Cm(2.4), Cm(7.5), Cm(1.6), Cm(3.0))
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            cell.width = widths[idx]

    thin = {"sz": "4", "val": "single", "color": "000000"}
    borders_all = {"top": thin, "left": thin, "bottom": thin, "right": thin}

    def _cell_text(cell, text: str, *, bold=False, center=False, size=9):
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
        # compactar espaçamento
        pf = p.paragraph_format
        pf.space_before = Pt(1)
        pf.space_after = Pt(1)
        run = p.add_run(text)
        run.font.name = "Times New Roman"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        run.font.size = Pt(size)
        run.bold = bold
        # centrar na vertical
        from docx.oxml import OxmlElement
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        vAlign = tcPr.find(qn("w:vAlign"))
        if vAlign is None:
            vAlign = OxmlElement("w:vAlign")
            tcPr.append(vAlign)
        vAlign.set(qn("w:val"), "center")

    # Linha 0 — título mesclado
    title_cell = table.rows[0].cells[0]
    for i in range(1, 5):
        title_cell.merge(table.rows[0].cells[i])
    _cell_text(
        title_cell,
        "Condomínio do Nº 42 da Av. Sto. António – Sta Joana",
        bold=True,
        center=True,
        size=10,
    )
    _set_cell_shading(title_cell, "D6E3F0")
    _set_cell_border(title_cell, **borders_all)

    # Linha 1 — cabeçalhos
    headers = ("Fração", "Andar", "Condómino", "%", "Rúbrica")
    for i, h in enumerate(headers):
        cell = table.rows[1].cells[i]
        _cell_text(cell, h, bold=True, center=True, size=9)
        _set_cell_shading(cell, "E7E6E6")
        _set_cell_border(cell, **borders_all)

    # Linhas de dados
    total_perm = 0.0
    for r_idx, c in enumerate(rows_data):
        row = table.rows[2 + r_idx]
        fracao = str(c.get("FRACAO") or "").strip()
        andar = str(c.get("ANDAR") or "").strip()
        nome = str(c.get("NOME") or "").strip()
        perm_raw = c.get("PERMILAGEM")
        try:
            perm_f = float(perm_raw)
            if perm_f > 1.5:
                perm_f = perm_f / 1000.0
        except (TypeError, ValueError):
            perm_f = 0.0
        total_perm += perm_f

        values = (
            fracao,
            andar,
            nome,
            _formatar_permilagem(perm_raw),
            "",  # rúbrica em branco para assinatura
        )
        centers = (True, True, False, True, True)
        for i, (val, ctr) in enumerate(zip(values, centers)):
            cell = row.cells[i]
            _cell_text(cell, val, center=ctr, size=9)
            _set_cell_border(cell, **borders_all)

    # Linha total
    total_row = table.rows[2 + n_data]
    # mesclar Fração+Andar+Condómino para o rótulo
    label_cell = total_row.cells[0]
    label_cell.merge(total_row.cells[1])
    label_cell.merge(total_row.cells[2])
    _cell_text(label_cell, "Total permilagem", bold=True, center=True, size=9)
    _set_cell_border(label_cell, **borders_all)

    perm_cell = total_row.cells[3]
    _cell_text(
        perm_cell,
        f"{total_perm:.3f}".replace(".", ","),
        bold=True,
        center=True,
        size=9,
    )
    _set_cell_border(perm_cell, **borders_all)

    rub_cell = total_row.cells[4]
    _cell_text(rub_cell, "", center=True)
    _set_cell_border(rub_cell, **borders_all)

    # Evitar que a tabela herde estilo «Table Grid» demasiado pesado
    try:
        table.style = "Table Grid"
    except Exception:
        pass

    print(f"  ✓ Lista de presenças (tabela) inserida: {n_data} condómino(s)")


def _pdf_paginas_para_imagens(
    pdf_path: Path,
    pasta_tmp: Path,
    prefixo: str = "relatorio",
    dpi: int = 300,
    crop_margin_cm: float = 0.0,
) -> list[Path]:
    """
    Converte cada página do PDF em PNG (PyMuPDF).
    - crop_margin_cm: remove margem uniforme do PDF (alinhar com mapas).
    - Depois corta ainda o whitespace residual (topo/fundo) via bounding box
      do conteúdo, para a imagem não ocupar uma página Word inteira vazia.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise ImportError(
            "PyMuPDF (fitz) é necessário para inserir o relatório PDF na ata.\n"
            "Execute: pip install pymupdf"
        ) from e

    pasta_tmp.mkdir(parents=True, exist_ok=True)
    doc_pdf = fitz.open(str(pdf_path))
    imagens: list[Path] = []
    zoom = max(dpi, 150) / 72.0
    mat = fitz.Matrix(zoom, zoom)
    crop_pt = max(0.0, float(crop_margin_cm)) * 72.0 / 2.54

    for i in range(len(doc_pdf)):
        page = doc_pdf[i]
        rect = page.rect
        clip = rect
        if crop_pt > 0:
            cand = fitz.Rect(
                rect.x0 + crop_pt,
                rect.y0 + crop_pt,
                rect.x1 - crop_pt,
                rect.y1 - crop_pt,
            )
            if cand.width > 10 and cand.height > 10:
                clip = cand

        # Apertar ao conteúdo real da página (evita fundo branco enorme)
        try:
            blocks = page.get_text("blocks") or []
            if blocks:
                x0 = min(b[0] for b in blocks)
                y0 = min(b[1] for b in blocks)
                x1 = max(b[2] for b in blocks)
                y1 = max(b[3] for b in blocks)
                # pequena folga (6 pt)
                content = fitz.Rect(x0 - 6, y0 - 6, x1 + 6, y1 + 6)
                content = content & clip  # interseção
                if content.width > 20 and content.height > 20:
                    clip = content
        except Exception:
            pass

        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        out = pasta_tmp / f"{prefixo}_pag_{i + 1:02d}.png"
        pix.save(str(out))

        # Trim final de pixéis quase-brancos (PIL)
        try:
            from PIL import Image, ImageChops
            im = Image.open(out).convert("RGB")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            diff = ImageChops.difference(im, bg)
            # tolerância a anti-aliasing
            diff = ImageChops.add(diff, diff, 2.0, -25)
            bbox = diff.getbbox()
            if bbox:
                # margem de 4 px
                x0, y0, x1, y1 = bbox
                x0 = max(0, x0 - 4)
                y0 = max(0, y0 - 4)
                x1 = min(im.width, x1 + 4)
                y1 = min(im.height, y1 + 4)
                im.crop((x0, y0, x1, y1)).save(out)
        except Exception:
            pass

        imagens.append(out)
    doc_pdf.close()
    return imagens


def _inserir_pdf_no_docx(
    doc: Document,
    pdf_path: Path,
    label: str = "relatório",
    *,
    crop_margin_cm: float = 0.0,
    largura_cm: float | None = None,
) -> int:
    """
    Insere cada página do PDF como imagem, uma por página Word.
    Evita página em branco:
      - sem parágrafo extra só com page-break (usa page_break_before na imagem)
      - imagem limitada a max ~24 cm de altura
      - crop apertado ao conteúdo
    """
    if not pdf_path.is_file():
        return 0

    print(f"  → A inserir {label}: {pdf_path.name}")

    import tempfile
    import shutil

    if largura_cm is None:
        largura_cm = _MAPAS_TABLE_WIDTH_CM

    tmp = Path(tempfile.mkdtemp(prefix="ata_pdf_"))
    try:
        imagens = _pdf_paginas_para_imagens(
            pdf_path,
            tmp,
            prefixo=pdf_path.stem[:20],
            dpi=300,
            crop_margin_cm=crop_margin_cm,
        )
    except Exception as e:
        print(f"  ⚠️ Erro ao converter PDF ({pdf_path.name}): {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 0

    from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN

    # Folga abaixo de 29,7 − margens − rodapé; evita overflow → página em branco
    max_altura_cm = 24.0

    def _largura_ajustada(path_img: Path, largura: float) -> float:
        try:
            from PIL import Image
            with Image.open(path_img) as im:
                w_px, h_px = im.size
            if w_px <= 0:
                return largura
            altura = largura * (h_px / float(w_px))
            if altura > max_altura_cm:
                return largura * (max_altura_cm / altura)
            return largura
        except Exception:
            return largura

    n = 0
    for img in imagens:
        # page_break_before no próprio parágrafo da imagem —
        # evita o parágrafo vazio+break que gerava folha em branco
        p_img = doc.add_paragraph()
        p_img.alignment = _ALIGN.CENTER
        p_img.paragraph_format.space_before = Pt(0)
        p_img.paragraph_format.space_after = Pt(0)
        p_img.paragraph_format.page_break_before = True
        try:
            w_cm = _largura_ajustada(img, float(largura_cm))
            p_img.add_run().add_picture(str(img), width=Cm(w_cm))
            n += 1
        except Exception as e:
            print(f"  ⚠️ Erro ao inserir página ({img.name}): {e}")

    shutil.rmtree(tmp, ignore_errors=True)
    if n:
        print(f"  ✓ {label.capitalize()} inserido: {n} página(s) de {pdf_path.name}")
    return n


# ---------------------------------------------------------------------------
# Relatórios de contas em tabelas Word nativas (nítidas, A4 portrait)
# ---------------------------------------------------------------------------

_THEME_HEADER_FILL = "D6E3F0"
_THEME_TOTAL_FILL = "E9EFF7"
_BORDER_THIN = {"sz": "4", "val": "single", "color": "808080"}

# Largura útil dos mapas (A4 − margens estreitas 0,6 cm)
_MAPAS_MARGIN_CM = 1.5
_MAPAS_TABLE_WIDTH_CM = 21.0 - 2 * _MAPAS_MARGIN_CM  # ≈ 19,8 cm

# Cabeçalhos curtos para caber numa linha
_HEADER_LABELS = {
    "DESPESAS": "Despesas",
    "FRACCAO": "Fração",
    "FRACÇÃO": "Fração",
    "SALDO_ANT": "S.Ant",
    "SALDO ANT": "S.Ant",
    "TOTAL": "Total",
    "TOTAIS": "Total",
    "SALDO": "Saldo",
    "JAN": "Jan", "FEV": "Fev", "MAR": "Mar", "ABR": "Abr",
    "MAI": "Mai", "JUN": "Jun", "JUL": "Jul", "AGO": "Ago",
    "SET": "Set", "OUT": "Out", "NOV": "Nov", "DEZ": "Dez",
}


def _fmt_num_compacto(valor) -> str:
    """Número compacto para células estreitas: 1054.00 (sem separador de milhares)."""
    if valor is None or valor == "":
        return ""
    try:
        num = float(valor)
        if abs(num) < 0.005:
            return ""
        # sem separador de milhares → cabe em colunas estreitas
        return f"{num:.2f}"
    except (TypeError, ValueError):
        return str(valor)


def _docx_set_run_font(run, *, size=8, bold=False, name="Times New Roman"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold


def _docx_cell_no_wrap(cell) -> None:
    """Impede quebra de linha dentro da célula (títulos/valores numa só linha)."""
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    noWrap = tcPr.find(qn("w:noWrap"))
    if noWrap is None:
        noWrap = OxmlElement("w:noWrap")
        tcPr.append(noWrap)


def _docx_set_table_width(table, width_cm: float) -> None:
    """Define largura total da tabela e desactiva autofit."""
    from docx.oxml import OxmlElement
    table.autofit = False
    table.allow_autofit = False
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement("w:tblPr")
    if tbl.tblPr is None:
        tbl.insert(0, tblPr)
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    # twips: 1 cm ≈ 567 twips
    twips = int(width_cm * 567)
    tblW.set(qn("w:w"), str(twips))
    tblW.set(qn("w:type"), "dxa")
    # alinhamento centrado da tabela na página
    jc = tblPr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        tblPr.append(jc)
    jc.set(qn("w:val"), "center")


def _docx_set_col_widths(table, widths_cm: list[float]) -> None:
    """Aplica larguras fixas a todas as colunas (cm)."""
    from docx.oxml import OxmlElement
    # gridCol no tblGrid
    tbl = table._tbl
    tblGrid = tbl.find(qn("w:tblGrid"))
    if tblGrid is not None:
        for gc in list(tblGrid):
            tblGrid.remove(gc)
        for w in widths_cm:
            gc = OxmlElement("w:gridCol")
            gc.set(qn("w:w"), str(int(w * 567)))
            tblGrid.append(gc)
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            if idx < len(widths_cm):
                cell.width = Cm(widths_cm[idx])


def _docx_fill_cell(
    cell,
    text: str,
    *,
    bold=False,
    center=False,
    right=False,
    size=8,
    fill: Optional[str] = None,
    no_wrap: bool = True,
):
    cell.text = ""
    p = cell.paragraphs[0]
    if right:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    # padding mínimo via cell margins + alinhamento vertical ao centro
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    vAlign = tcPr.find(qn("w:vAlign"))
    if vAlign is None:
        vAlign = OxmlElement("w:vAlign")
        tcPr.append(vAlign)
    vAlign.set(qn("w:val"), "center")
    tcMar = tcPr.find(qn("w:tcMar"))
    if tcMar is None:
        tcMar = OxmlElement("w:tcMar")
        tcPr.append(tcMar)
    for edge, val in (("top", "20"), ("bottom", "20"), ("left", "30"), ("right", "30")):
        el = tcMar.find(qn(f"w:{edge}"))
        if el is None:
            el = OxmlElement(f"w:{edge}")
            tcMar.append(el)
        el.set(qn("w:w"), val)
        el.set(qn("w:type"), "dxa")

    run = p.add_run(text if text is not None else "")
    _docx_set_run_font(run, size=size, bold=bold)
    _set_cell_border(
        cell,
        top=_BORDER_THIN,
        left=_BORDER_THIN,
        bottom=_BORDER_THIN,
        right=_BORDER_THIN,
    )
    if fill:
        _set_cell_shading(cell, fill)
    if no_wrap:
        _docx_cell_no_wrap(cell)


def _docx_add_section_title(doc: Document, titulo: str, size: int = 11) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(titulo)
    _docx_set_run_font(run, size=size, bold=True)
    from docx.oxml import OxmlElement
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "2F5597")
    run._element.rPr.append(color)


def _larguras_colunas_pivot(fields: list) -> list[float]:
    """
    Calcula larguras (cm) para todas as tabelas pivot usarem a MESMA largura total
    (_MAPAS_TABLE_WIDTH_CM), com 1.ª coluna mais larga e restantes iguais.
    """
    n = len(fields)
    total = _MAPAS_TABLE_WIDTH_CM
    if n <= 1:
        return [total]
    # 1.ª coluna (rótulo): ~2,6 cm; últimas (Total/Saldo) um pouco mais largas
    label_w = 2.6
    # identificar colunas de total/saldo no fim
    extras = []
    for f in fields[1:]:
        fu = str(f).strip().upper()
        if fu in ("TOTAL", "TOTAIS", "SALDO", "SALDO_ANT") or fu.startswith("SALDO"):
            extras.append(1.35)
        else:
            extras.append(0.0)  # placeholder → depois equaliza
    # repartir o resto pelas colunas mensais de forma igual
    fixed_extra = sum(w for w in extras if w > 0)
    n_month = sum(1 for w in extras if w == 0)
    rest = total - label_w - fixed_extra
    month_w = rest / n_month if n_month else 0
    widths = [label_w]
    for w in extras:
        widths.append(w if w > 0 else month_w)
    # correcção de arredondamento
    diff = total - sum(widths)
    if abs(diff) > 0.01:
        widths[-1] += diff
    return widths


def _docx_tabela_pivot(
    doc: Document,
    titulo: str,
    rows: list,
    fields: list,
    *,
    label_field: str,
    font_size: int = 7,
) -> None:
    """Tabela mensal (Despesas / Receitas) — largura fixa igual para todos os mapas."""
    if not rows or not fields:
        return
    _docx_add_section_title(doc, titulo, size=10)

    table = doc.add_table(rows=1 + len(rows), cols=len(fields))
    try:
        table.style = "Table Grid"
    except Exception:
        pass

    widths = _larguras_colunas_pivot(fields)
    _docx_set_table_width(table, _MAPAS_TABLE_WIDTH_CM)
    _docx_set_col_widths(table, widths)

    # Cabeçalho (rótulos curtos, sem wrap)
    for i, f in enumerate(fields):
        key = str(f).strip().upper()
        label = _HEADER_LABELS.get(key, str(f))
        _docx_fill_cell(
            table.rows[0].cells[i],
            label,
            bold=True,
            center=True,
            size=font_size,
            fill=_THEME_HEADER_FILL,
            no_wrap=True,
        )

    # Dados
    for r_idx, r in enumerate(rows):
        is_total = str(r.get(label_field) or "").strip().upper() in (
            "TOTAIS", "TOTAL", "TOTAIS:", "TOTAL:"
        )
        fill = _THEME_TOTAL_FILL if is_total else None
        for c_idx, f in enumerate(fields):
            v = r.get(f)
            if f == label_field or c_idx == 0:
                txt = "" if v in (None, "") else str(v)
                _docx_fill_cell(
                    table.rows[r_idx + 1].cells[c_idx],
                    txt,
                    bold=is_total,
                    size=font_size,
                    fill=fill,
                    no_wrap=True,
                )
            else:
                txt = _fmt_num_compacto(v)
                _docx_fill_cell(
                    table.rows[r_idx + 1].cells[c_idx],
                    txt,
                    bold=is_total,
                    right=True,
                    size=font_size,
                    fill=fill,
                    no_wrap=True,
                )


def _docx_tabela_balanco(doc: Document, balanco_rows: list) -> None:
    """Balanço Débitos | Créditos — mesma largura total dos outros mapas."""
    if not balanco_rows:
        return
    _docx_add_section_title(doc, "Balanço da Administração", size=10)

    esq, dir_ = separar_balanco_por_marcador(balanco_rows)
    linhas = emparelhar_balanco(esq, dir_)

    table = doc.add_table(rows=1 + len(linhas), cols=4)
    try:
        table.style = "Table Grid"
    except Exception:
        pass

    # Mesma largura total; colunas de valor mais estreitas
    total_w = _MAPAS_TABLE_WIDTH_CM
    widths = [total_w * 0.34, total_w * 0.16, total_w * 0.34, total_w * 0.16]
    _docx_set_table_width(table, total_w)
    _docx_set_col_widths(table, widths)

    headers = ("Débitos", "Valor", "Créditos", "Valor")
    for i, h in enumerate(headers):
        _docx_fill_cell(
            table.rows[0].cells[i],
            h,
            bold=True,
            center=True,
            size=8,
            fill=_THEME_HEADER_FILL,
            no_wrap=True,
        )

    for r_idx, (e, d) in enumerate(linhas):
        e_conta, e_val = e
        d_conta, d_val = d
        e_up = str(e_conta).strip().upper()
        d_up = str(d_conta).strip().upper()
        e_is_tot = e_up.startswith("TOTAL")
        d_is_tot = d_up.startswith("TOTAL")
        e_fill = _THEME_TOTAL_FILL if e_is_tot else None
        d_fill = _THEME_TOTAL_FILL if d_is_tot else None

        _docx_fill_cell(
            table.rows[r_idx + 1].cells[0], e_conta or "",
            bold=e_is_tot, size=8, fill=e_fill, no_wrap=True,
        )
        _docx_fill_cell(
            table.rows[r_idx + 1].cells[1],
            _fmt_num_compacto(e_val),
            bold=e_is_tot, right=True, size=8, fill=e_fill, no_wrap=True,
        )
        _docx_fill_cell(
            table.rows[r_idx + 1].cells[2], d_conta or "",
            bold=d_is_tot, size=8, fill=d_fill, no_wrap=True,
        )
        _docx_fill_cell(
            table.rows[r_idx + 1].cells[3],
            _fmt_num_compacto(d_val),
            bold=d_is_tot, right=True, size=8, fill=d_fill, no_wrap=True,
        )


def _inserir_relatorios_contas(doc: Document, pasta_dados=None, ano_movimentos=None) -> int:
    """
    Insere Despesas, Receitas (N+E) e Balanço como tabelas Word nativas
    (mesma fonte de dados de Report.gerar_pdf_relatorio), compactas para
    caberem numa página A4 portrait sempre que o volume de dados o permitir.

    Devolve o número de blocos inseridos (0 se sem dados).
    """
    from docx.enum.section import WD_SECTION

    pasta = resolver_pasta(pasta_dados)
    if not db_existe(pasta):
        print(f"  ⚠️ BD não encontrada em {pasta} — relatórios de contas omitidos.")
        return 0

    def _load(fn, *args):
        try:
            rows, fields = fn(*args, pasta=pasta)
            return rows or [], fields or []
        except Exception as exc:
            print(f"  ⚠️ load relatório: {exc}")
            return [], []

    despesas_rows, despesas_fields = _load(load_despesas_wide)
    rec_n_rows, rec_n_fields = _load(load_receitas_wide, "NORMAL")
    rec_e_rows, rec_e_fields = _load(load_receitas_wide, "EXTRA")
    balanco_rows, _ = _load(load_balanco_wide)

    if not any([despesas_rows, rec_n_rows, rec_e_rows, balanco_rows]):
        # Fallback: PDF pré-gerado (se existir)
        candidatos = []
        if ano_movimentos:
            candidatos.append(DOCS_DIR / f"Relatorio_{ano_movimentos}.pdf")
        candidatos.append(DOCS_DIR / "Relatorio_Condominio.pdf")
        pdf_path = next((p for p in candidatos if p.is_file()), None)
        if pdf_path is not None:
            print("  ℹ️ Sem dados wide — a usar PDF de relatório existente.")
            return _inserir_pdf_no_docx(doc, pdf_path, label="relatório de contas")
        print("  ⚠️ Sem dados de despesas/receitas/balanço para inserir na ata.")
        return 0

    # Nova secção A4 portrait com margens estreitas (só para os mapas)
    prev = doc.sections[0]
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.page_width = prev.page_width
    sec.page_height = prev.page_height
    sec.left_margin = Cm(_MAPAS_MARGIN_CM)
    sec.right_margin = Cm(_MAPAS_MARGIN_CM)
    sec.top_margin = Cm(1.0)
    sec.bottom_margin = Cm(1.0)

    ano_txt = str(ano_movimentos or obter_ano_exercicio(pasta) or "")
    _docx_add_section_title(
        doc,
        f"Mapas de Contas — Exercício {ano_txt}".strip(),
        size=12,
    )

    n = 0
    if despesas_rows:
        label = despesas_fields[0] if despesas_fields else "DESPESAS"
        _docx_tabela_pivot(
            doc, "Despesas", despesas_rows, despesas_fields,
            label_field=label, font_size=7,
        )
        n += 1

    if rec_n_rows:
        label = rec_n_fields[0] if rec_n_fields else "FRACCAO"
        _docx_tabela_pivot(
            doc, "Receitas Normais", rec_n_rows, rec_n_fields,
            label_field=label, font_size=7,
        )
        n += 1

    if rec_e_rows:
        label = rec_e_fields[0] if rec_e_fields else "FRACCAO"
        _docx_tabela_pivot(
            doc, "Receitas Extraordinárias", rec_e_rows, rec_e_fields,
            label_field=label, font_size=7,
        )
        n += 1

    if balanco_rows:
        _docx_tabela_balanco(doc, balanco_rows)
        n += 1

    print(f"  ✓ Relatórios de contas inseridos como tabelas Word ({n} mapa(s), A4 portrait)")
    return n


def _inserir_relatorio_pdf(doc: Document, ano_movimentos=None, pasta_dados=None) -> int:
    """
    Compatibilidade: delega para tabelas Word nativas (_inserir_relatorios_contas).
    O PDF só é usado como fallback se não houver dados na BD.
    """
    return _inserir_relatorios_contas(
        doc, pasta_dados=pasta_dados, ano_movimentos=ano_movimentos
    )


def _inserir_analise_ia_pdf(doc: Document) -> int:
    """
    Se existir docs/Relatorio_Analise_IA.pdf, anexa-o no final da ata.
    Corta a margem interna do PDF (Report_AI._AI_MARGIN_CM) e usa a mesma
    largura dos mapas de contas, para as barras azuis alinharem com o balanço.
    """
    pdf_path = DOCS_DIR / "Relatorio_Analise_IA.pdf"
    if not pdf_path.is_file():
        print("  ℹ️ Relatorio_Analise_IA.pdf não encontrado em docs/ — não será anexado.")
        return 0
    # Margem do PDF da IA (Report_AI._AI_MARGIN_CM); fallback 1.5 cm
    try:
        from Report_AI import _AI_MARGIN_CM as _ai_m
        crop = float(_ai_m)
    except Exception:
        crop = 1.5
    return _inserir_pdf_no_docx(
        doc,
        pdf_path,
        label="análise IA",
        crop_margin_cm=crop,
        largura_cm=_MAPAS_TABLE_WIDTH_CM,
    )


def _adicionar_numeracao_paginas(doc: Document) -> None:
    """
    Rodapé centrado com numeração no formato «1/4», «2/4», …
    (campos Word PAGE e NUMPAGES).
    """
    from docx.oxml import OxmlElement

    def _add_field(paragraph, instr: str) -> None:
        """Insere um campo Word (PAGE / NUMPAGES) no parágrafo."""
        # begin
        r = paragraph.add_run()
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        r._r.append(fld_begin)
        # instruction
        r2 = paragraph.add_run()
        instr_text = OxmlElement("w:instrText")
        instr_text.set(qn("xml:space"), "preserve")
        instr_text.text = f" {instr} "
        r2._r.append(instr_text)
        # separate
        r3 = paragraph.add_run()
        fld_sep = OxmlElement("w:fldChar")
        fld_sep.set(qn("w:fldCharType"), "separate")
        r3._r.append(fld_sep)
        # placeholder
        r4 = paragraph.add_run("1")
        # end
        r5 = paragraph.add_run()
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        r5._r.append(fld_end)

    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        # Limpar parágrafos existentes do rodapé
        for p in list(footer.paragraphs):
            p.clear()
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p.runs:
            r.text = ""
        _add_field(p, "PAGE")
        p.add_run("/")
        _add_field(p, "NUMPAGES")


def _carregar_mapa_quotas_aprovadas(pasta_dados=None) -> tuple[str, list[dict]]:
    """
    Lê corrente/quotas_aprovadas.json e enriquece com andar (tabela fracoes).

    Returns:
        (valor_orcamentado_formatado, lista de linhas para a tabela)
        Se não houver proposta: ("— (sem proposta aprovada)", [])
    """
    try:
        from Orcamento import ler_quotas_aprovadas
        from Database import FracoesRepo, resolver_pasta
    except Exception as exc:
        print(f"  ⚠️ quotas aprovadas: import falhou: {exc}")
        return "— (sem proposta aprovada)", []

    data = ler_quotas_aprovadas(pasta_dados)
    if not data:
        return "— (sem proposta aprovada)", []

    # Preferir valor_orcamentado (Σ quotas mensais × 12); fallback se JSON antigo
    if data.get("valor_orcamentado") is not None:
        total = float(data.get("valor_orcamentado") or 0)
    else:
        total = 0.0
        if data.get("incluir_normais", True):
            total += float(data.get("total_normais_proj") or 0)
        if data.get("incluir_extras", True):
            total += float(data.get("total_extras_proj") or 0)
        # JSON antigo sem valor_orcamentado: recalcular a partir das linhas
        if data.get("fracoes") and total <= 0:
            total = sum(
                (float(x.get("quota_normal") or 0) + float(x.get("quota_extra") or 0)) * 12.0
                for x in data["fracoes"]
            )
    try:
        valor_txt = format_currency(total)
    except Exception:
        valor_txt = f"{total:.2f} €"

    andares = {}
    try:
        for r in FracoesRepo(resolver_pasta(pasta_dados)).all_ordered():
            fr = str(r["fracao"] or "").strip().upper()
            andares[fr] = str(r["andar"] or "").strip()
    except Exception as exc:
        print(f"  ⚠️ fracoes para mapa quotas: {exc}")

    linhas = []
    for item in data.get("fracoes") or []:
        fr = str(item.get("fracao") or "").strip().upper()
        if not fr:
            continue
        qn = float(item.get("quota_normal") or 0)
        qe = float(item.get("quota_extra") or 0)
        linhas.append({
            "fracao": fr,
            "andar": andares.get(fr, ""),
            "quota_normal": qn,
            "quota_extra": qe,
            "total": qn + qe,
        })
    return valor_txt, linhas


def _inserir_mapa_quotas_aprovadas(doc: Document, linhas: list[dict]) -> None:
    """
    Substitui o parágrafo {{MAPA_QUOTAS_APROVADAS}} por uma tabela Word
    (Fração | Andar | Quota N | Quota E | Total) ou por texto se vazio.
    """
    from docx.oxml import OxmlElement
    from docx.shared import Cm, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT

    alvo = None
    for p in doc.paragraphs:
        if "{{MAPA_QUOTAS_APROVADAS}}" in "".join(r.text for r in p.runs) or            "{{MAPA_QUOTAS_APROVADAS}}" in (p.text or ""):
            alvo = p
            break
    if alvo is None:
        print("  ⚠️ Placeholder MAPA_QUOTAS_APROVADAS não encontrado.")
        return

    # Limpar placeholder
    for r in alvo.runs:
        r.text = ""

    if not linhas:
        run = alvo.add_run(
            "Não foi apresentada/aprovada alteração às quotas mensais "
            "(sem proposta em quotas_aprovadas.json)."
        )
        run.font.name = "Times New Roman"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        run.font.size = Pt(11)
        run.font.italic = True
        alvo.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        return

    # Tabela a seguir ao parágrafo (vazio) do placeholder
    n_cols = 5
    table = doc.add_table(rows=1 + len(linhas), cols=n_cols)
    try:
        table.style = "Table Grid"
    except Exception:
        pass
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = ["Fração", "Andar", "Quota N", "Quota E", "Total"]
    hdr = table.rows[0]
    for i, h in enumerate(headers):
        cell = hdr.cells[i]
        cell.text = h
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10)
                r.font.name = "Times New Roman"
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        # fundo azul
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "2F5597")
        shd.set(qn("w:val"), "clear")
        tcPr.append(shd)

    for ri, item in enumerate(linhas, start=1):
        row = table.rows[ri]
        vals = [
            item["fracao"],
            item["andar"],
            f"{item['quota_normal']:.2f}",
            f"{item['quota_extra']:.2f}",
            f"{item['total']:.2f}",
        ]
        for ci, val in enumerate(vals):
            cell = row.cells[ci]
            cell.text = val
            for p in cell.paragraphs:
                p.alignment = (
                    WD_ALIGN_PARAGRAPH.CENTER if ci < 2 else WD_ALIGN_PARAGRAPH.RIGHT
                )
                for r in p.runs:
                    r.font.size = Pt(10)
                    r.font.name = "Times New Roman"

    # Colocar a tabela no sítio do placeholder (sem linha em branco antes)
    # e deixar uma linha em branco depois, antes do ponto 3.
    tbl = table._tbl
    parent = alvo._p.getparent()
    idx = list(parent).index(alvo._p)
    parent.insert(idx, tbl)
    parent.remove(alvo._p)  # remove o parágrafo vazio do placeholder

    # Linha em branco após a tabela
    blank = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "120")
    pPr.append(spacing)
    blank.append(pPr)
    # inserir logo a seguir à tabela
    tbl_idx = list(parent).index(tbl)
    parent.insert(tbl_idx + 1, blank)


def gerar_ata(pasta_dados=None, dados: Optional[dict] = None) -> Path:
    """
    Gera o ficheiro .docx da ata.

    `dados` deve conter (mínimo):
      num_adm, ano_exercicio, ano_exercicio_ant, num_ata,
      data, hora_inicial, hora_final,
      admin_ant, fracao_ant,
      administrador, fracao, andar, cc_numero, cc_validade, nif,
      assuntos_gerais

    Devolve o Path do ficheiro gerado em docs/.
    """
    if not DOCX_AVAILABLE:
        raise ImportError(
            "Biblioteca python-docx não instalada.\n"
            "Execute: pip install python-docx"
        )
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(
            f"Template não encontrado: {TEMPLATE_PATH}\n"
            "Copie ATA_template.docx para a pasta templates/."
        )

    d = dict(dados or {})
    # Garantir defaults a partir da BD se faltarem
    base = carregar_dados_iniciais(pasta_dados)
    for k, v in base.items():
        if k == "condominos":
            continue
        d.setdefault(k, v)

    data_txt = data_por_extenso(d.get("data") or date.today())
    hora_ini = formatar_hora(d.get("hora_inicial") or time(20, 0))
    hora_fim = formatar_hora(d.get("hora_final") or time(22, 0))

    fracoes_txt = str(d.get("fracoes_presentes_txt") or "").strip()
    if not fracoes_txt:
        # Fallback: lista explícita ou todas as letras clássicas
        lista = d.get("fracoes_presentes") or []
        if lista:
            if len(lista) == 1:
                fracoes_txt = lista[0]
            else:
                fracoes_txt = ", ".join(lista[:-1]) + " e " + lista[-1]
        else:
            fracoes_txt = "A, B, C, D, E e F"
    perm = d.get("permilagem_presentes")
    if perm is None or perm == "":
        perm_txt = "1000"
    else:
        try:
            perm_txt = str(int(perm))
        except (TypeError, ValueError):
            perm_txt = str(perm)

    # Quotas aprovadas (orçamento) — NÃO altera a lógica ANO_EXERCICIO*
    valor_orc, linhas_quotas = _carregar_mapa_quotas_aprovadas(pasta_dados)

    mapa = {
        "NUM_ADM": str(d.get("num_adm", "")),
        "ANO_EXERCICIO_ANT": str(d.get("ano_exercicio_ant", "")),
        "ANO_EXERCICIO": str(d.get("ano_exercicio", "")),
        "NUM_ATA": str(d.get("num_ata", "")),
        "DATA": data_txt,
        "HORA_INICIAL": hora_ini,
        "HORA_FINAL": hora_fim,
        "ADMIN_ANT": str(d.get("admin_ant") or ""),
        "FRACAO_ANT": str(d.get("fracao_ant") or ""),
        "ADMINISTRADOR": str(d.get("administrador") or ""),
        "FRACAO": str(d.get("fracao") or ""),
        "ANDAR": str(d.get("andar") or ""),
        "CC_NUMERO": str(d.get("cc_numero") or "—"),
        "CC_VALIDADE": str(d.get("cc_validade") or "—"),
        "NIF": str(d.get("nif") or "—"),
        "FRACOES_PRESENTES": fracoes_txt,
        "PERMILAGEM_PRESENTES": perm_txt,
        "VALOR_ORCAMENTADO": valor_orc,
    }

    doc = Document(str(TEMPLATE_PATH))
    # Mapa de quotas ANTES dos placeholders (precisa de {{MAPA_QUOTAS_APROVADAS}})
    _inserir_mapa_quotas_aprovadas(doc, linhas_quotas)
    _substituir_placeholders(doc, mapa)
    _inserir_assuntos(doc, d.get("assuntos_gerais") or "")
    _inserir_assinatura(doc, mapa["ADMIN_ANT"])
    _inserir_lista_presencas(
        doc,
        condominos=d.get("condominos") or base.get("condominos") or [],
        fracoes_presentes=d.get("fracoes_presentes") or [],
    )
    # Mapas de contas (Despesas / Receitas / Balanço) em tabelas Word nativas
    # — mesma fonte de dados de Report.gerar_pdf_relatorio, A4 portrait
    _inserir_relatorio_pdf(
        doc,
        ano_movimentos=d.get("ano_exercicio_ant"),
        pasta_dados=pasta_dados,
    )
    # Análise IA (se existir em docs/Relatorio_Analise_IA.pdf) — 300 dpi
    _inserir_analise_ia_pdf(doc)
    _adicionar_numeracao_paginas(doc)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    num = d.get("num_ata", "X")
    ano = d.get("ano_exercicio_ant", "")
    nome_ficheiro = f"Ata_{num}_{ano}.docx"
    destino = DOCS_DIR / nome_ficheiro
    # Evitar sobrescrever sem aviso: acrescenta sufixo se já existir
    if destino.exists():
        i = 2
        while True:
            destino = DOCS_DIR / f"Ata_{num}_{ano}_{i}.docx"
            if not destino.exists():
                break
            i += 1

    doc.save(str(destino))
    return destino


# ---------------------------------------------------------------------------
# Teste standalone
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Teste Gerar_Ata ===")
    iniciais = carregar_dados_iniciais("corrente")
    print("Dados iniciais:")
    for k, v in iniciais.items():
        if k == "condominos":
            print(f"  condominos: {len(v)} registos")
        else:
            print(f"  {k}: {v}")

    # Dados de exemplo (como no Excel fornecido)
    exemplo = {
        **{k: v for k, v in iniciais.items() if k != "condominos"},
        "num_ata": 24,
        "admin_ant": "Luís Silva",
        "fracao_ant": "D",
        "administrador": "Rosa Carvalhal",
        "fracao": "B",
        "andar": "R/c Dto.",
        "cc_numero": "",
        "cc_validade": "",
        "nif": "",
    }
    try:
        path = gerar_ata("corrente", exemplo)
        print(f"\n✅ Ata gerada: {path}")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        raise
