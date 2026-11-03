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
    BASE_DIR,
    DOCS_DIR,
    ICONS_DIR,
    TEMPLATES_DIR,
    obter_ano_exercicio,
)
from Database import (
    resolver_pasta,
    carregar_condominos,
    db_existe,
    configs as configs_repo,
)

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

    A ata da administração do ano N é feita em janeiro de N+1.
    Com ANO_EXERCICIO já em N+1 na BD:
      - ano_exercicio_ant = N          (contas aprovadas)
      - ano_exercicio     = N+1        (orçamento / novo admin)
      - num_adm           = N - NUMERO_ADMINISTRACAO
        ex.: 2026 - 2005 = 21ª administração
    """
    pasta = resolver_pasta(pasta_dados)
    ano = obter_ano_exercicio(pasta)          # ex.: 2027 (já no novo exercício)
    ano_ant = ano - 1                         # ex.: 2026 (administração a que a ata se refere)
    base_admin = _numero_administracao_base(pasta)  # ex.: 2005
    num_adm = ano_ant - base_admin            # ex.: 2026 - 2005 = 21

    condominos = carregar_condominos(pasta) if db_existe(pasta) else []

    # Cessante = admin -1 (já foi substituído na BD antes de redigir a ata)
    admin_cessante = None
    admin_atual = None
    for c in condominos:
        if _is_admin_cessante(c.get("ADMIN")):
            admin_cessante = c
        if _is_admin(c.get("ADMIN")):
            admin_atual = c

    # Nº da ata: tentativa de incremento a partir dos ficheiros existentes
    num_ata = _sugerir_num_ata()

    return {
        "num_adm": num_adm,
        "ano_exercicio": ano,
        "ano_exercicio_ant": ano_ant,
        "num_ata": num_ata,
        "data": date.today(),
        "hora_inicial": time(20, 0),
        "hora_final": time(22, 0),
        "admin_ant": (admin_cessante or {}).get("NOME", ""),
        "fracao_ant": (admin_cessante or {}).get("FRACAO", ""),
        # Pré-seleção do novo admin (admin == 1) no formulário
        "administrador": (admin_atual or {}).get("NOME", ""),
        "fracao": (admin_atual or {}).get("FRACAO", ""),
        "andar": (admin_atual or {}).get("ANDAR", ""),
        "cc_numero": (admin_atual or {}).get("CC_NUMERO", ""),
        "cc_validade": (admin_atual or {}).get("CC_VALIDADE", ""),
        "nif": (admin_atual or {}).get("NIF", ""),
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


def _inserir_lista_presencas(doc: Document) -> None:
    """
    No parágrafo «Lista de Presenças» (fim da ata):
    mantém o título e insere icons/Lista_presenças.png (15 cm × 7 cm).
    """
    lista_path = TEMPLATES_DIR / "Lista_presenças.png"
    alvo = None
    for p in doc.paragraphs:
        if "Lista de Presenças" in "".join(r.text for r in p.runs):
            alvo = p
            break
    if alvo is None:
        print("  ⚠️ Parágrafo 'Lista de Presenças' não encontrado no template.")
        return

    if not lista_path.is_file():
        print(f"  ⚠️ Lista de presenças não encontrada: {lista_path}")
        return

    try:
        # Nova linha a seguir ao título, com a imagem centrada
        from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN
        novo = doc.add_paragraph()
        novo.alignment = _ALIGN.CENTER
        # Mover o parágrafo novo para logo a seguir a «alvo»
        alvo._p.addnext(novo._p)
        run = novo.add_run()
        run.add_picture(str(lista_path), width=Cm(15), height=Cm(7))
        print(f"  ✓ Lista de presenças inserida: {lista_path.name}")
    except Exception as e:
        print(f"  ⚠️ Erro ao inserir lista de presenças: {e}")


def _pdf_paginas_para_imagens(pdf_path: Path, pasta_tmp: Path) -> list[Path]:
    """Converte cada página do PDF em PNG (PyMuPDF). Devolve lista de paths."""
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
    # ~150 dpi: bom compromisso qualidade/tamanho para A4 no Word
    zoom = 150 / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(doc_pdf)):
        page = doc_pdf[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out = pasta_tmp / f"relatorio_pag_{i + 1:02d}.png"
        pix.save(str(out))
        imagens.append(out)
    doc_pdf.close()
    return imagens


def _inserir_relatorio_pdf(doc: Document, ano_movimentos=None) -> int:
    """
    Insere docs/Relatorio_{ano}.pdf (ano dos movimentos / contas aprovadas).
    Cada página do PDF ocupa uma página nova do docx.
    Devolve o número de páginas inseridas (0 se falhar / não existir).
    """
    candidatos = []
    if ano_movimentos:
        candidatos.append(DOCS_DIR / f"Relatorio_{ano_movimentos}.pdf")
    candidatos.append(DOCS_DIR / "Relatorio_Condominio.pdf")  # compatibilidade legada

    pdf_path = next((p for p in candidatos if p.is_file()), None)
    if pdf_path is None:
        nomes = ", ".join(p.name for p in candidatos)
        print(f"  ⚠️ Relatório não encontrado em docs/ (procurou: {nomes})")
        return 0
    print(f"  → A inserir relatório: {pdf_path.name}")

    import tempfile
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="ata_relatorio_"))
    try:
        imagens = _pdf_paginas_para_imagens(pdf_path, tmp)
    except Exception as e:
        print(f"  ⚠️ Erro ao converter PDF do relatório: {e}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 0

    from docx.enum.text import WD_BREAK
    from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN

    n = 0
    for img in imagens:
        # Quebra de página antes de cada folha do relatório
        p_break = doc.add_paragraph()
        run_br = p_break.add_run()
        run_br.add_break(WD_BREAK.PAGE)

        p_img = doc.add_paragraph()
        p_img.alignment = _ALIGN.CENTER
        # Quase a largura útil de A4 (margens ~2.5 cm → ~16 cm)
        try:
            p_img.add_run().add_picture(str(img), width=Cm(16))
            n += 1
        except Exception as e:
            print(f"  ⚠️ Erro ao inserir página do relatório ({img.name}): {e}")

    shutil.rmtree(tmp, ignore_errors=True)
    if n:
        print(f"  ✓ Relatório inserido: {n} página(s) de {pdf_path.name}")
    return n


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
    }

    doc = Document(str(TEMPLATE_PATH))
    _substituir_placeholders(doc, mapa)
    _inserir_assuntos(doc, d.get("assuntos_gerais") or "")
    _inserir_assinatura(doc, mapa["ADMIN_ANT"])
    _inserir_lista_presencas(doc)
    # Relatório do ano das contas (ano_exercicio_ant), não do ano civil atual
    _inserir_relatorio_pdf(doc, ano_movimentos=d.get("ano_exercicio_ant"))
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
