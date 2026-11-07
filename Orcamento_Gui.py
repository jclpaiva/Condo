"""
Orcamento_Gui.py — Projeção de despesas/receitas e quotas por fração.

Layout:
  Esquerda  → mapa CORRENTE | PROJEÇÃO (despesas + receitas)
  Direita   → quotas calculadas por fração (demonstrativo)
  Rodapé esquerdo → incremento % + botão «=»
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QDoubleSpinBox, QAbstractItemView, QSizePolicy, QSplitter,
    QMessageBox, QToolButton,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QBrush, QIcon

from Commons import (
    format_currency,
    ICONS_DIR,
)
from Orcamento import (
    carregar_dados_orcamento,
    projetar_despesas,
    projetar_total_anual,
    calcular_quotas_por_fracao,
    gravar_quotas_aprovadas,
    estado_proposta_aprovada,
    ler_quotas_aprovadas,
)


# Cores alinhadas com o resto da app
_HDR_BG = "#2F5597"
_HDR_FG = "#ffffff"
_TITULO_BG = "#D6E3F0"
_TOTAL_BG = "#E8EEF7"
_PROJ_COLOR = "#C62828"
_OK_COLOR = "#1565C0"
_ROW_ALT = "#F5F7FA"


class OrcamentoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pasta_dados = None
        self._despesas: list[dict] = []
        self._qn_corrente = 0.0
        self._qe_corrente = 0.0
        self._fracoes: list[dict] = []
        # Inclusão no cálculo de projeção / quotas (UI: caixas verde/vermelho)
        self._incluir_qn = True
        self._incluir_qe = True
        self._ultimas_quotas: list[dict] = []
        self._ultimo_pct = 0.0
        self._ultimo_qn_proj = 0.0
        self._ultimo_qe_proj = 0.0
        self._setup_ui()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        titulo = QLabel("Orçamento — Projeção de Despesas e Quotas")
        titulo.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #2F5597; padding: 4px 2px;"
        )
        root.addWidget(titulo)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Painel esquerdo ──────────────────────────────────────────────────
        left = QFrame()
        left.setObjectName("orcLeft")
        left.setStyleSheet(
            "QFrame#orcLeft { background:#fff; border:1px solid #D0D5DD; border-radius:8px; }"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(8)

        self.tbl_mapa = QTableWidget(0, 3)
        self.tbl_mapa.setHorizontalHeaderLabels(["Descrição", "Corrente", "Projeção"])
        self.tbl_mapa.verticalHeader().setVisible(False)
        self.tbl_mapa.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_mapa.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl_mapa.setAlternatingRowColors(False)
        self.tbl_mapa.setShowGrid(True)
        self.tbl_mapa.setStyleSheet(self._table_css())
        hdr = self.tbl_mapa.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(1, 110)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(2, 110)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        left_lay.addWidget(self.tbl_mapa, 1)

        # Barra incremento
        bar = QHBoxLayout()
        bar.setSpacing(10)
        lbl_inc = QLabel("INCREMENTO")
        lbl_inc.setStyleSheet("font-weight:bold; color:#334155; font-size:12px;")
        bar.addWidget(lbl_inc)

        self.spin_pct = QDoubleSpinBox()
        self.spin_pct.setRange(-50.0, 100.0)
        self.spin_pct.setDecimals(1)
        self.spin_pct.setSingleStep(0.5)
        self.spin_pct.setValue(2.0)
        self.spin_pct.setSuffix(" %")
        self.spin_pct.setFixedWidth(100)
        self.spin_pct.setStyleSheet(
            "QDoubleSpinBox { padding:6px; border:1px solid #CBD5E1; border-radius:6px;"
            " font-size:14px; font-weight:bold; }"
        )
        bar.addWidget(self.spin_pct)

        self.btn_calcular = QPushButton("→ Calcular")
        self.btn_calcular.setFixedSize(120, 40)
        icon_path = ICONS_DIR / "calculator-icon.png"
        if icon_path.exists():
            self.btn_calcular.setIcon(QIcon(str(icon_path)))
        self.btn_calcular.setIconSize(QSize(28, 28))
        self.btn_calcular.setToolTip(
            "Calcula as quotas mensais por fração."
        )
        self.btn_calcular.setStyleSheet(
            "QPushButton { background:#0F766E; color:white; font-size:12px;"
            " font-weight:bold; border:none; border-radius:8px; }"
            "QPushButton:hover { background:#0D9488; }"
            "QPushButton:pressed { background:#115E59; }"
        )
        self.btn_calcular.clicked.connect(self._aplicar_incremento)
        bar.addWidget(self.btn_calcular)

        self.btn_aprovar = QPushButton("Aprovar Quotas")
        self.btn_aprovar.setFixedHeight(40)
        self.btn_aprovar.setEnabled(False)
        self.btn_aprovar.setToolTip(
            "Grava a proposta em corrente/quotas_aprovadas.json.\n"
            "As quotas em fracoes só são actualizadas ao 'Encerrar Ano'."
        )
        self.btn_aprovar.setStyleSheet(
            "QPushButton { background:#1D4ED8; color:white; font-weight:bold;"
            " border:none; border-radius:8px; padding:0 16px; font-size:12px; }"
            "QPushButton:hover { background:#1E40AF; }"
            "QPushButton:disabled { background:#94A3B8; color:#E2E8F0; }"
        )
        self.btn_aprovar.clicked.connect(self._aprovar_quotas)
        bar.addWidget(self.btn_aprovar)
        bar.addStretch()
        left_lay.addLayout(bar)

        nota_esq = QLabel(
            "A coluna Projeção só é preenchida após premir «=». "
            "Quota N e Quota E calculadas com o mesmo critério (total projetado × permilagem ÷ 12)."
        )
        nota_esq.setWordWrap(True)
        nota_esq.setStyleSheet("color:#64748B; font-size:11px; font-style:italic;")
        left_lay.addWidget(nota_esq)

        splitter.addWidget(left)

        # ── Painel direito ───────────────────────────────────────────────────
        right = QFrame()
        right.setObjectName("orcRight")
        right.setStyleSheet(
            "QFrame#orcRight { background:#fff; border:1px solid #D0D5DD; border-radius:8px; }"
        )
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(10, 10, 10, 10)
        right_lay.setSpacing(8)

        lbl_q = QLabel("Quotas mensais projetadas (por fração)")
        lbl_q.setStyleSheet("font-weight:bold; color:#2F5597; font-size:13px;")
        right_lay.addWidget(lbl_q)

        self.tbl_quotas = QTableWidget(0, 5)
        self.tbl_quotas.setHorizontalHeaderLabels(
            ["Fração", "Andar", "Permilagem", "Quota N", "Quota E"]
        )
        self.tbl_quotas.verticalHeader().setVisible(False)
        self.tbl_quotas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_quotas.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl_quotas.setStyleSheet(self._table_css())
        hq = self.tbl_quotas.horizontalHeader()
        hq.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hq.resizeSection(0, 60)
        hq.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hq.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hq.resizeSection(2, 95)
        hq.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hq.resizeSection(3, 80)
        hq.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hq.resizeSection(4, 80)
        hq.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        right_lay.addWidget(self.tbl_quotas, 1)

        formula = QFrame()
        formula.setStyleSheet(
            "QFrame { background:#FEF2F2; border:1px solid #FECACA; border-radius:8px; }"
        )
        fl = QVBoxLayout(formula)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(4)
        t1 = QLabel(
            "<b>Cálculo das quotas mensais (N e E)</b><br>"
            "Quota N = (total projetado quotas normais × permilagem) ÷ 12<br>"
            "Quota E = (total projetado quotas extras × permilagem) ÷ 12"
        )
        t1.setWordWrap(True)
        t1.setStyleSheet("color:#7F1D1D; font-size:11px;")
        fl.addWidget(t1)
        t2 = QLabel(
            "<b>Arredondamento</b><br>"
            "parte decimal ≤ 0,50 → sobe para ,50<br>"
            "parte decimal &gt; 0,50 → sobe para o euro seguinte"
        )
        t2.setWordWrap(True)
        t2.setStyleSheet("color:#7F1D1D; font-size:11px;")
        fl.addWidget(t2)
        right_lay.addWidget(formula)

        nota_dir = QLabel(
            "Valores da tabela de quotas são demonstrativos até gravar em "
            "Configurações → Frações (grava automaticamente ao 'Encerrar Ano')."
        )
        nota_dir.setWordWrap(True)
        nota_dir.setStyleSheet("color:#64748B; font-size:11px; font-style:italic;")
        right_lay.addWidget(nota_dir)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#64748B; font-size:11px; font-style:italic;")
        root.addWidget(self.status)

    @staticmethod
    def _table_css() -> str:
        return f"""
            QTableWidget {{
                gridline-color: #E2E8F0;
                border: 1px solid #E2E8F0;
                background: #fff;
                font-size: 12px;
            }}
            QHeaderView::section {{
                background-color: {_HDR_BG};
                color: {_HDR_FG};
                font-weight: bold;
                padding: 8px 6px;
                border: none;
                border-right: 1px solid #1F4587;
            }}
            QTableWidget::item {{ padding: 4px 8px; }}
        """

    # ── Dados ────────────────────────────────────────────────────────────────
    def set_pasta_dados(self, pasta_dados):
        self.pasta_dados = pasta_dados
        self.carregar()

    def carregar(self):
        if not self.pasta_dados:
            self.status.setText("Sem pasta de dados.")
            return
        try:
            dados = carregar_dados_orcamento(self.pasta_dados)
        except Exception as exc:
            QMessageBox.warning(self, "Orçamento", f"Erro ao carregar dados:\n{exc}")
            return

        self._despesas = dados.get("despesas") or []
        self._qn_corrente = float(dados.get("quotas_normais") or 0)
        self._qe_corrente = float(dados.get("quotas_extras") or 0)
        self._fracoes = dados.get("fracoes") or []

        self._preencher_mapa(proj=None)
        self._preencher_quotas([])  # vazio até calcular
        self._ultimas_quotas = []
        self.btn_aprovar.setEnabled(False)
        prop = estado_proposta_aprovada(self.pasta_dados)
        self.status.setText(
            f"Carregado: {len(self._despesas)} despesa(s), "
            f"{len(self._fracoes)} fração(ões). {prop}"
        )

    def _item(self, texto, *, align=Qt.AlignmentFlag.AlignLeft, bold=False,
              fg=None, bg=None) -> QTableWidgetItem:
        it = QTableWidgetItem(str(texto))
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        if fg:
            it.setForeground(QBrush(QColor(fg)))
        if bg:
            it.setBackground(QBrush(QColor(bg)))
        return it

    def _toggle_style(self, ativo: bool) -> str:
        if ativo:
            return (
                "QToolButton { background:#16A34A; color:white; font-weight:bold;"
                " border:none; border-radius:3px; min-width:16px; max-width:16px;"
                " min-height:16px; max-height:16px; font-size:10px; padding:0; }"
                "QToolButton:hover { background:#15803D; }"
            )
        return (
            "QToolButton { background:#DC2626; color:white; font-weight:bold;"
            " border:none; border-radius:3px; min-width:16px; max-width:16px;"
            " min-height:16px; max-height:16px; font-size:10px; padding:0; }"
            "QToolButton:hover { background:#B91C1C; }"
        )

    def _criar_celula_receita(self, texto: str, tipo: str, bg=None) -> QWidget:
        """Rótulo + caixa de validação (verde = inclui, vermelho = exclui)."""
        cor = bg or "#FFFFFF"
        w = QWidget()
        w.setAutoFillBackground(True)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        w.setStyleSheet(
            f"QWidget {{ background-color: {cor}; border: none; }}"
            f"QLabel {{ background-color: transparent; font-size: 12px; }}"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 0, 4, 0)
        lay.setSpacing(8)
        lbl = QLabel(texto)
        lay.addWidget(lbl)

        btn = QToolButton()
        ativo = self._incluir_qn if tipo == "qn" else self._incluir_qe
        btn.setText("✓" if ativo else "✕")
        btn.setStyleSheet(self._toggle_style(ativo))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(
            "Incluir no cálculo de projeção e quotas"
            if ativo else
            "Excluído do cálculo — clique para incluir"
        )
        btn.clicked.connect(lambda _=False, t=tipo: self._alternar_inclusao(t))
        lay.addWidget(btn)
        lay.addStretch()
        return w

    def _alternar_inclusao(self, tipo: str):
        if tipo == "qn":
            self._incluir_qn = not self._incluir_qn
        else:
            self._incluir_qe = not self._incluir_qe
        # Reaplica projeção se já existia, senão só refresca o mapa
        if getattr(self, "_ultima_proj", None) is not None:
            self._aplicar_incremento()
        else:
            self._preencher_mapa(None)

    def _preencher_mapa(self, proj: dict | None):
        """proj = None → só corrente; senão dict com despesas_proj, qn_proj, qe_proj."""
        self._ultima_proj = proj
        rows: list[tuple] = []

        # Título despesas
        rows.append(("__tit__", "DESPESAS", "", ""))
        despesas_proj = (proj or {}).get("despesas") or []
        mapa_proj = {d["conta"]: d.get("projecao") for d in despesas_proj}

        total_c = 0.0
        total_p = 0.0
        for d in self._despesas:
            conta = d["conta"]
            c = float(d.get("corrente") or 0)
            total_c += c
            p = mapa_proj.get(conta) if proj else None
            if p is not None:
                total_p += float(p)
            rows.append(("desp", conta, c, p))

        rows.append(("__tot__", "Total despesas", total_c, total_p if proj else None))
        rows.append(("__blank__", "", "", ""))

        # Receitas
        rows.append(("__tit__", "RECEITAS", "", ""))
        qn_p = (proj or {}).get("qn") if proj else None
        qe_p = (proj or {}).get("qe") if proj else None
        # Totais de receitas só com as linhas incluídas
        tot_rc = 0.0
        if self._incluir_qn:
            tot_rc += self._qn_corrente
        if self._incluir_qe:
            tot_rc += self._qe_corrente
        tot_rp = None
        if proj is not None:
            tot_rp = 0.0
            if self._incluir_qn:
                tot_rp += float(qn_p or 0)
            if self._incluir_qe:
                tot_rp += float(qe_p or 0)
        rows.append(("rec_qn", "a) Quotas Normais", self._qn_corrente, qn_p))
        rows.append(("rec_qe", "b) Quotas Extras    ", self._qe_corrente, qe_p))
        rows.append(("__tot__", "Total receitas", tot_rc, tot_rp))

        self.tbl_mapa.setRowCount(len(rows))
        for i, (kind, desc, c, p) in enumerate(rows):
            if kind == "__tit__":
                self.tbl_mapa.setItem(i, 0, self._item(desc, bold=True, bg=_TITULO_BG, fg="#1E3A5F"))
                self.tbl_mapa.setItem(i, 1, self._item("", bg=_TITULO_BG))
                self.tbl_mapa.setItem(i, 2, self._item("", bg=_TITULO_BG))
                self.tbl_mapa.setCellWidget(i, 0, None)
                continue
            if kind == "__blank__":
                for col in range(3):
                    self.tbl_mapa.setItem(i, col, self._item(""))
                self.tbl_mapa.setCellWidget(i, 0, None)
                continue

            if kind == "__tot__":
                bg = _TOTAL_BG
            elif i % 2:
                bg = "#FFFFFF"
            else:
                bg = _ROW_ALT
            bold = kind == "__tot__"

            if kind in ("rec_qn", "rec_qe"):
                tipo = "qn" if kind == "rec_qn" else "qe"
                placeholder = self._item("", bg=bg)
                self.tbl_mapa.setItem(i, 0, placeholder)
                self.tbl_mapa.setCellWidget(
                    i, 0, self._criar_celula_receita(desc, tipo, bg=bg)
                )
            else:
                self.tbl_mapa.setCellWidget(i, 0, None)
                self.tbl_mapa.setItem(
                    i, 0, self._item(desc, bold=bold, bg=bg, fg=_OK_COLOR if bold else None)
                )

            c_txt = format_currency(c) if isinstance(c, (int, float)) else ""
            self.tbl_mapa.setItem(
                i, 1,
                self._item(
                    c_txt,
                    align=Qt.AlignmentFlag.AlignRight,
                    bold=bold,
                    bg=bg,
                    fg=_OK_COLOR if bold else None,
                ),
            )
            if p is None:
                p_txt = ""
                p_fg = None
            else:
                p_txt = format_currency(p)
                p_fg = _PROJ_COLOR
            self.tbl_mapa.setItem(
                i, 2,
                self._item(
                    p_txt,
                    align=Qt.AlignmentFlag.AlignRight,
                    bold=bold,
                    bg=bg,
                    fg=p_fg,
                ),
            )
            self.tbl_mapa.setRowHeight(i, 28 if kind.startswith("rec_") else 26)

    def _preencher_quotas(self, quotas: list[dict]):
        n = len(quotas)
        # +1 linha de totais (mensal) se houver dados
        self.tbl_quotas.setRowCount(n + (1 if n else 0))
        soma_n = 0.0
        soma_e = 0.0
        for i, q in enumerate(quotas):
            bg = None if i % 2 else _ROW_ALT
            qn = float(q.get("quota_normal") or 0)
            qe = float(q.get("quota_extra") or 0)
            soma_n += qn
            soma_e += qe
            self.tbl_quotas.setItem(
                i, 0,
                self._item(q.get("fracao", ""), align=Qt.AlignmentFlag.AlignCenter, bg=bg, bold=True),
            )
            self.tbl_quotas.setItem(i, 1, self._item(q.get("andar", ""), bg=bg))
            self.tbl_quotas.setItem(
                i, 2,
                self._item(
                    f"{float(q.get('permilagem') or 0):.3f}",
                    align=Qt.AlignmentFlag.AlignCenter,
                    bg=bg,
                ),
            )
            self.tbl_quotas.setItem(
                i, 3,
                self._item(
                    f"{qn:.2f}",
                    align=Qt.AlignmentFlag.AlignRight,
                    bg=bg,
                    fg=_OK_COLOR,
                    bold=True,
                ),
            )
            self.tbl_quotas.setItem(
                i, 4,
                self._item(
                    f"{qe:.2f}",
                    align=Qt.AlignmentFlag.AlignRight,
                    bg=bg,
                ),
            )
            self.tbl_quotas.setRowHeight(i, 28)

        if n:
            i = n
            bg = _TOTAL_BG
            self.tbl_quotas.setItem(
                i, 0,
                self._item("Total", align=Qt.AlignmentFlag.AlignCenter, bg=bg, bold=True, fg=_OK_COLOR),
            )
            self.tbl_quotas.setItem(
                i, 1,
                self._item("mensal", bg=bg, fg=_OK_COLOR),
            )
            self.tbl_quotas.setItem(
                i, 2,
                self._item("", bg=bg),
            )
            self.tbl_quotas.setItem(
                i, 3,
                self._item(
                    f"{soma_n:.2f}",
                    align=Qt.AlignmentFlag.AlignRight,
                    bg=bg,
                    bold=True,
                    fg=_OK_COLOR,
                ),
            )
            self.tbl_quotas.setItem(
                i, 4,
                self._item(
                    f"{soma_e:.2f}",
                    align=Qt.AlignmentFlag.AlignRight,
                    bg=bg,
                    bold=True,
                    fg=_OK_COLOR,
                ),
            )
            self.tbl_quotas.setRowHeight(i, 30)

    def _aplicar_incremento(self):
        pct = float(self.spin_pct.value())
        desp_proj = projetar_despesas(self._despesas, pct)
        qn_proj = projetar_total_anual(self._qn_corrente, pct) if self._incluir_qn else 0.0
        qe_proj = projetar_total_anual(self._qe_corrente, pct) if self._incluir_qe else 0.0
        # Projeção a zero nas linhas desactivadas (ícone vermelho)
        self._preencher_mapa({
            "despesas": desp_proj,
            "qn": qn_proj,
            "qe": qe_proj,
        })

        quotas = calcular_quotas_por_fracao(
            qn_proj,
            self._fracoes,
            total_extras_projetado=qe_proj,
        )
        self._preencher_quotas(quotas)

        total_receitas_proj = qn_proj + qe_proj
        self._ultimas_quotas = quotas
        self._ultimo_pct = pct
        self._ultimo_qn_proj = qn_proj
        self._ultimo_qe_proj = qe_proj
        self.btn_aprovar.setEnabled(bool(quotas))
        flags = []
        flags.append("N✓" if self._incluir_qn else "N✕")
        flags.append("E✓" if self._incluir_qe else "E✕")
        self.status.setText(
            f"Projeção {pct:.1f} % [{', '.join(flags)}] — "
            f"base quotas {format_currency(total_receitas_proj)} · "
            f"{len(quotas)} fração(ões). Pode aprovar para o próximo exercício."
        )

    def _aprovar_quotas(self):
        if not self._ultimas_quotas:
            QMessageBox.information(
                self, "Aprovar Quotas",
                "Calcule primeiro a projeção com o botão «=»."
            )
            return
        if not self.pasta_dados:
            QMessageBox.warning(self, "Aprovar Quotas", "Pasta de dados não definida.")
            return

        destino_ano = "?"
        try:
            from Commons import obter_ano_exercicio
            from Database import resolver_pasta
            origem = int(obter_ano_exercicio(str(resolver_pasta(self.pasta_dados))))
            destino_ano = origem + 1
        except Exception:
            origem = None

        existente = ler_quotas_aprovadas(self.pasta_dados)
        extra = ""
        if existente:
            extra = (
                f"\n\nJá existe uma proposta "
                f"(aprovada em {existente.get('aprovado_em', '?')}) — será substituída."
            )

        reply = QMessageBox.question(
            self,
            "Aprovar Quotas",
            f"Gravar proposta de quotas para o exercício <b>{destino_ano}</b>?"
            f"<br><br>Ficheiro: <code>corrente/quotas_aprovadas.json</code>"
            f"<br>As quotas em <b>frações</b> só serão actualizadas ao "
            f"<b>'Encerrar Ano'</b>.{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            path = gravar_quotas_aprovadas(
                self._ultimas_quotas,
                incremento_pct=self._ultimo_pct,
                incluir_normais=self._incluir_qn,
                incluir_extras=self._incluir_qe,
                total_normais_proj=self._ultimo_qn_proj,
                total_extras_proj=self._ultimo_qe_proj,
                pasta=self.pasta_dados,
            )
            self.status.setText(estado_proposta_aprovada(self.pasta_dados))
            QMessageBox.information(
                self,
                "Quotas aprovadas",
                f"Proposta gravada em:\n{path}\n\n"
                f"Será aplicada automaticamente ao 'Encerrar Ano' "
                f"(exercício {destino_ano}).",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Não foi possível gravar a proposta:\n{exc}")
