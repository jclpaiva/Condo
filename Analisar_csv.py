# Analisar_csv.py
# Detecção automática de estrutura de extratos bancários CSV.
# Independente do banco/layout: infere delimitador, cabeçalho e colunas
# a partir da forma dos dados (datas, números, texto), não de um formato fixo.
#
# Integração na aplicação:
#   - Configuracoes_Gui → analyze_and_update(csv, configs_path)
#   - Bancos._detetar_params_importacao → CSVAnalyzer(csv).analyze()
#   - Persistência via bridge Commons.carregar_db / salvar_db → condominio.db

from __future__ import annotations

import os
import re
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from Database import carregar_db, salvar_db

# from Commons import (data API → Database)

# ---------------------------------------------------------------------------
# Padrões reutilizáveis
# ---------------------------------------------------------------------------

_RE_DATE = re.compile(
    r"^\s*("
    r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"          # 28/12/2024, 02-01-25
    r"|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"            # 2024-12-28
    r")(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\s*$"       # opcional HH:MM[:SS]
)

_RE_NUMBER = re.compile(
    r"^\s*[-+]?"
    r"(?:"
    r"\d{1,3}(?:[.\s]\d{3})+,\d{1,2}"             # 1.234,56 / 1 234,56
    r"|\d{1,3}(?:,\d{3})+\.\d{1,2}"               # 1,234.56
    r"|\d+[.,]\d{1,2}"                              # 50,00 / 50.00
    r"|\d+"                                         # inteiro
    r")\s*(?:€|EUR|USD|\$)?\s*$",
    re.IGNORECASE,
)

# Palavras que tipicamente aparecem em cabeçalhos de extratos (multilingue)
_HEADER_TOKENS = {
    "data", "date", "datum",
    "descricao", "descrição", "description", "desc", "historico", "histórico",
    "movimento", "movimiento", "transaction", "lancamento", "lançamento",
    "valor", "amount", "montante", "importo",
    "debito", "débito", "debit", "debeto",
    "credito", "crédito", "credit",
    "saldo", "balance", "saldo disponivel", "saldo disponível",
    "moeda", "currency", "divisa",
    "referencia", "referência", "reference", "ref",
    "operacao", "operação", "operation",
}

# Linhas de metadados / rodapé a ignorar como dados
_META_HINTS = (
    "consultar extrato", "nome empresa", "nif", "intervalo de",
    "tipos de movimento", "saldo contabil", "saldo inicial", "saldo final",
    "saldo anterior", "saldo actual", "saldo atual",
    "total", "subtotal", "página", "pagina", "page ",
    "emitido em", "generated", "copyright",
)


def _norm(s: str) -> str:
    return (
        str(s or "")
        .strip()
        .casefold()
        .replace("á", "a").replace("à", "a").replace("ã", "a").replace("â", "a")
        .replace("é", "e").replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o").replace("ô", "o").replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _is_date(v: str) -> bool:
    return bool(v and _RE_DATE.match(v.strip()))


def _is_number(v: str) -> bool:
    if not v or not v.strip():
        return False
    s = v.strip()
    if _is_date(s):
        return False
    return bool(_RE_NUMBER.match(s))


def _looks_meta(line: str) -> bool:
    low = _norm(line)
    return any(h in low for h in _META_HINTS)


# ===========================================================================
# Analisador
# ===========================================================================

class CSVAnalyzer:
    """Infere automaticamente a estrutura de um extrato bancário CSV."""

    DELIMITERS = [";", ",", "\t", "|"]

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        self.encoding: str | None = None
        self.lines: list[str] = []
        self.delimiter: str | None = None
        self.header_index: int | None = None
        self.header_fields: list[str] = []
        self.data_start_row: int | None = None  # 0-based index da 1ª linha de dados
        self.total_columns: int = 0
        self.sample_rows: list[list[str]] = []  # campos já partidos

    # ------------------------------------------------------------------
    # 1. Encoding + carga
    # ------------------------------------------------------------------
    def detect_encoding(self) -> str:
        candidates = ["utf-8-sig", "cp1252", "latin-1", "utf-8", "cp850", "iso-8859-1"]
        for enc in candidates:
            try:
                with open(self.file_path, "r", encoding=enc, errors="strict") as f:
                    for _ in range(80):
                        if not f.readline():
                            break
                self.encoding = enc
                return enc
            except (UnicodeDecodeError, UnicodeError):
                continue
        self.encoding = "cp1252"
        return self.encoding

    def load_file(self) -> bool:
        if not self.encoding:
            self.detect_encoding()
        try:
            with open(self.file_path, "r", encoding=self.encoding, errors="replace") as f:
                self.lines = [ln.rstrip("\n\r") for ln in f]
            return bool(self.lines)
        except OSError as e:
            print(f"  ✗ Erro ao ler ficheiro: {e}")
            return False

    # ------------------------------------------------------------------
    # 2. Partição de linhas
    # ------------------------------------------------------------------
    @staticmethod
    def _split(line: str, delim: str) -> list[str]:
        parts = line.split(delim)
        while parts and not parts[-1].strip():
            parts.pop()
        return [p.strip() for p in parts]

    # ------------------------------------------------------------------
    # 3. Detecção de delimitador
    # ------------------------------------------------------------------
    def _score_delimiter(self, delim: str) -> tuple[float, int, float]:
        counts: list[int] = []
        for ln in self.lines:
            if not ln.strip() or _looks_meta(ln):
                continue
            n = len(self._split(ln, delim))
            if n >= 2:
                counts.append(n)
        if len(counts) < 3:
            return 0.0, 0, 0.0
        modal, freq = Counter(counts).most_common(1)[0]
        if modal < 3:
            return 0.0, modal, 0.0
        consist = freq / len(counts)
        score = modal * consist * min(len(counts), 40)
        return score, modal, consist

    def detect_delimiter(self) -> str | None:
        best_d, best_s, best_cols = None, -1.0, 0
        print("\n  🔍 A testar delimitadores…")
        for d in self.DELIMITERS:
            score, cols, consist = self._score_delimiter(d)
            print(f"    {d!r:>6} → cols≈{cols:2d}  consist={consist:.0%}  score={score:.1f}")
            if score > best_s:
                best_s, best_d, best_cols = score, d, cols
        if best_d is None:
            return None
        self.delimiter = best_d
        self.total_columns = best_cols
        print(f"  ✓ Delimitador escolhido: {best_d!r}  ({best_cols} colunas)")
        return best_d

    # ------------------------------------------------------------------
    # 4. Classificação linha a linha
    # ------------------------------------------------------------------
    def _row_profile(self, fields: list[str]) -> dict[str, Any]:
        n = len(fields)
        if n == 0:
            return {"kind": "empty", "n": 0, "dates": 0, "nums": 0, "texts": 0,
                    "header_hits": 0, "empty": 0}
        dates = sum(1 for f in fields if _is_date(f))
        nums = sum(1 for f in fields if _is_number(f))
        empties = sum(1 for f in fields if not f)
        texts = n - dates - nums - empties
        hits = 0
        for f in fields:
            tok = _norm(f)
            if not tok:
                continue
            if tok in _HEADER_TOKENS:
                hits += 1
                continue
            for ht in _HEADER_TOKENS:
                if ht in tok or tok in ht:
                    hits += 1
                    break
        return {
            "kind": "row",
            "n": n,
            "dates": dates,
            "nums": nums,
            "texts": texts,
            "header_hits": hits,
            "empty": empties,
        }

    def _is_data_row(self, profile: dict, expected_cols: int) -> bool:
        if profile["n"] < max(3, expected_cols - 1):
            return False
        if expected_cols and abs(profile["n"] - expected_cols) > 1:
            if profile["n"] < expected_cols - 1:
                return False
        return profile["dates"] >= 1 and profile["nums"] >= 1

    def _is_header_row(self, profile: dict, expected_cols: int) -> bool:
        if profile["n"] < 3:
            return False
        if expected_cols and profile["n"] < expected_cols - 1:
            return False
        if profile["header_hits"] >= 2 and profile["dates"] == 0 and profile["nums"] <= 1:
            return True
        if (
            profile["dates"] == 0
            and profile["nums"] == 0
            and profile["texts"] >= 3
            and expected_cols
            and abs(profile["n"] - expected_cols) <= 1
        ):
            return True
        return False

    # ------------------------------------------------------------------
    # 5. Localizar cabeçalho e início dos dados
    # ------------------------------------------------------------------
    def find_structure(self) -> bool:
        assert self.delimiter
        expected = self.total_columns

        profiles: list[tuple[int, list[str], dict]] = []
        for i, ln in enumerate(self.lines):
            if not ln.strip():
                continue
            if _looks_meta(ln) and i < 30:
                fields = self._split(ln, self.delimiter)
                p = self._row_profile(fields)
                if not self._is_header_row(p, expected):
                    continue
            fields = self._split(ln, self.delimiter)
            p = self._row_profile(fields)
            profiles.append((i, fields, p))

        if not profiles:
            print("  ✗ Nenhuma linha útil encontrada")
            return False

        data_flags = [self._is_data_row(p, expected) for _, _, p in profiles]
        header_flags = [self._is_header_row(p, expected) for _, _, p in profiles]

        data_start_pos = None
        for i in range(len(profiles)):
            if data_flags[i]:
                run = 0
                for j in range(i, min(i + 5, len(profiles))):
                    if data_flags[j]:
                        run += 1
                    else:
                        break
                if run >= 2 or (run >= 1 and i == len(profiles) - 1):
                    data_start_pos = i
                    break

        if data_start_pos is None:
            for i, flag in enumerate(data_flags):
                if flag:
                    data_start_pos = i
                    break

        if data_start_pos is None:
            print("  ✗ Não foram encontradas linhas de movimentos")
            return False

        data_line_index = profiles[data_start_pos][0]
        self.data_start_row = data_line_index

        header_pos = None
        for i in range(data_start_pos - 1, -1, -1):
            if header_flags[i]:
                header_pos = i
                break
            _, fields, p = profiles[i]
            if p["n"] >= max(3, expected - 1) and p["dates"] == 0 and p["nums"] <= 1:
                header_pos = i
                break

        if header_pos is not None:
            self.header_index = profiles[header_pos][0]
            fields = profiles[header_pos][1]
        else:
            self.header_index = None
            fields = [f"Col{k}" for k in range(expected)]

        data_ncols = [
            profiles[i][2]["n"]
            for i in range(data_start_pos, min(data_start_pos + 30, len(profiles)))
            if data_flags[i]
        ]
        if data_ncols:
            modal_cols = Counter(data_ncols).most_common(1)[0][0]
            self.total_columns = modal_cols

        if len(fields) < self.total_columns:
            fields = fields + [f"Col{k}" for k in range(len(fields), self.total_columns)]
        else:
            fields = fields[: self.total_columns]
        self.header_fields = fields

        self.sample_rows = []
        for i in range(data_start_pos, len(profiles)):
            if not data_flags[i]:
                if i > data_start_pos + 2 and not any(data_flags[i:i + 3]):
                    break
                continue
            row = profiles[i][1]
            if len(row) < self.total_columns:
                row = row + [""] * (self.total_columns - len(row))
            else:
                row = row[: self.total_columns]
            self.sample_rows.append(row)
            if len(self.sample_rows) >= 40:
                break

        hdr_label = (
            f"linha {self.header_index + 1}"
            if self.header_index is not None
            else "— (sintético)"
        )
        print(f"  ✓ Cabeçalho: {hdr_label}")
        print(f"  ✓ Dados a partir da linha {self.data_start_row + 1}")
        print(f"  ✓ Colunas: {self.total_columns}  →  {self.header_fields}")
        print(f"  ✓ Amostras de dados: {len(self.sample_rows)}")
        return bool(self.sample_rows)

    # ------------------------------------------------------------------
    # 6. Identificação das colunas críticas
    # ------------------------------------------------------------------
    def _col_stats(self, col: int) -> dict[str, float]:
        vals = [r[col] for r in self.sample_rows if col < len(r)]
        n = len(vals) or 1
        dates = sum(1 for v in vals if _is_date(v))
        nums = sum(1 for v in vals if _is_number(v))
        empty = sum(1 for v in vals if not (v or "").strip())
        texts = n - dates - nums - empty
        avg_len = sum(len((v or "").strip()) for v in vals) / n
        uniq = len({(v or "").strip() for v in vals if (v or "").strip()})
        return {
            "date_rate": dates / n,
            "num_rate": nums / n,
            "text_rate": max(0, texts) / n,
            "empty_rate": empty / n,
            "avg_len": avg_len,
            "uniq": uniq,
            "n": n,
        }

    def _header_bias(self, col: int) -> dict[str, float]:
        name = _norm(self.header_fields[col] if col < len(self.header_fields) else "")
        bias = {"date": 0.0, "desc": 0.0, "valor": 0.0, "saldo": 0.0}
        if not name:
            return bias
        if any(k in name for k in ("data", "date", "datum")):
            bias["date"] += 0.15
        if any(k in name for k in ("desc", "histor", "memo", "narrat", "detalhe", "texto")):
            bias["desc"] += 0.15
        if any(k in name for k in ("saldo", "balance")):
            bias["saldo"] += 0.2
        if any(k in name for k in (
            "valor", "amount", "montante", "movimento", "debit", "credit",
            "debito", "credito", "quantia", "importo",
        )):
            if "data" not in name:
                bias["valor"] += 0.12
        return bias

    def identify_columns(self) -> dict[str, int] | None:
        print("\n  🎯 A identificar colunas (pela forma dos dados)…")
        if not self.sample_rows or self.total_columns < 3:
            return None

        stats = [self._col_stats(c) for c in range(self.total_columns)]
        biases = [self._header_bias(c) for c in range(self.total_columns)]

        for c, s in enumerate(stats):
            ghost = " 👻" if s["empty_rate"] > 0.9 else ""
            print(
                f"    Col {c}: date={s['date_rate']:.0%} num={s['num_rate']:.0%} "
                f"text={s['text_rate']:.0%} empty={s['empty_rate']:.0%} "
                f"len={s['avg_len']:.0f}  '{self.header_fields[c]}'{ghost}"
            )

        used: set[int] = set()

        def score_date(c: int) -> float:
            s, b = stats[c], biases[c]
            if s["empty_rate"] > 0.85:
                return -1
            return s["date_rate"] * 2.0 + b["date"] - s["empty_rate"]

        col_data = max(range(self.total_columns), key=score_date)
        if stats[col_data]["date_rate"] < 0.4:
            candidates = [c for c in range(self.total_columns) if stats[c]["date_rate"] >= 0.3]
            col_data = candidates[0] if candidates else 0
        used.add(col_data)

        def score_saldo(c: int) -> float:
            if c in used:
                return -1e9
            s, b = stats[c], biases[c]
            if s["empty_rate"] > 0.7 or s["num_rate"] < 0.5:
                return -1e9
            return s["num_rate"] + b["saldo"] + (c / max(1, self.total_columns)) * 0.3

        col_saldo = max(range(self.total_columns), key=score_saldo)
        if col_saldo in used or stats[col_saldo]["num_rate"] < 0.5:
            nums = [
                c for c in range(self.total_columns)
                if c not in used and stats[c]["num_rate"] >= 0.5 and stats[c]["empty_rate"] < 0.7
            ]
            col_saldo = nums[-1] if nums else self.total_columns - 1
        used.add(col_saldo)

        def score_valor(c: int) -> float:
            if c in used:
                return -1e9
            s, b = stats[c], biases[c]
            if s["empty_rate"] > 0.85 or s["num_rate"] < 0.4:
                return -1e9
            variety = min(1.0, s["uniq"] / max(1, s["n"]))
            return s["num_rate"] + b["valor"] + variety * 0.4 - abs(c - col_saldo) * 0.01

        col_valor = max(range(self.total_columns), key=score_valor)
        if col_valor in used or stats[col_valor]["num_rate"] < 0.4:
            nums = [
                c for c in range(self.total_columns)
                if c not in used and stats[c]["num_rate"] >= 0.4 and stats[c]["empty_rate"] < 0.85
            ]
            left = [c for c in nums if c < col_saldo]
            col_valor = (left[-1] if left else (nums[0] if nums else max(0, col_saldo - 1)))
        used.add(col_valor)

        def score_desc(c: int) -> float:
            if c in used:
                return -1e9
            s, b = stats[c], biases[c]
            if s["empty_rate"] > 0.9:
                return -1e9
            return s["text_rate"] * 1.5 + min(s["avg_len"], 40) / 40 + b["desc"]

        col_desc = max(range(self.total_columns), key=score_desc)
        if col_desc in used:
            rest = [c for c in range(self.total_columns) if c not in used]
            col_desc = rest[0] if rest else 1
        used.add(col_desc)

        result = {
            "col_data": int(col_data),
            "col_descricao": int(col_desc),
            "col_valor": int(col_valor),
            "col_saldo": int(col_saldo),
        }

        if len(set(result.values())) < 4:
            print(f"  ✗ Índices em conflito: {result}")
            return None

        print("\n  ✓ Colunas escolhidas:")
        for k, idx in result.items():
            print(f"    {k.replace('col_', '').upper():<12} = {idx:2d}  '{self.header_fields[idx]}'")
        return result

    # ------------------------------------------------------------------
    # 7. Formato numérico
    # ------------------------------------------------------------------
    def detect_number_format(self) -> tuple[str, str]:
        """Devolve (separador_decimal, separador_milhares). Default PT: (',', '.')"""
        comma_dec = dot_dec = 0
        for row in self.sample_rows:
            for v in row:
                if not _is_number(v):
                    continue
                s = v.strip()
                lc, ld = s.rfind(","), s.rfind(".")
                if lc > ld and re.search(r",\d{1,2}\s*$", s):
                    comma_dec += 1
                elif ld > lc and re.search(r"\.\d{1,2}\s*$", s):
                    dot_dec += 1
        if dot_dec > comma_dec:
            return ".", ","
        return ",", "."

    # ------------------------------------------------------------------
    # 8. Pipeline
    # ------------------------------------------------------------------
    def analyze(self) -> dict[str, Any] | None:
        """
        Executa a análise completa.

        Devolve dict com as chaves esperadas por Bancos.py / Configuracoes_Gui:
            COL_DATA, COL_DESCRICAO, COL_VALOR, COL_SALDO (int, 0-based)
            CSV_DELIMITER, CSV_DECIMAL, CSV_THOUSANDS (str)
            CSV_FIRST_ROW (int, 1-based), TOTAL_COLUMNS (int)
            CSV_AUTO_DETECT = 'False'
        """
        print(f"\n🔍 ANALISANDO CSV: {self.file_path}")
        print("-" * 72)

        if not self.load_file():
            return None
        print(f"  • Encoding: {self.encoding}   linhas: {len(self.lines)}")

        if not self.detect_delimiter():
            print("  ✗ Delimitador não detetado")
            return None

        if not self.find_structure():
            print("\n  Primeiras 12 linhas:")
            for i, ln in enumerate(self.lines[:12], 1):
                print(f"    {i:2d}: {ln[:110]}")
            return None

        cols = self.identify_columns()
        if not cols:
            return None

        dec, thou = self.detect_number_format()

        # Tipos alinhados com o que Bancos.carregar_parametros_importacao /
        # _detetar_params_importacao esperam (ints nos índices e contagens).
        params = {
            "COL_DATA": int(cols["col_data"]),
            "COL_DESCRICAO": int(cols["col_descricao"]),
            "COL_VALOR": int(cols["col_valor"]),
            "COL_SALDO": int(cols["col_saldo"]),
            "CSV_AUTO_DETECT": "False",
            "CSV_DECIMAL": str(dec),
            "CSV_DELIMITER": str(self.delimiter),
            "CSV_FIRST_ROW": int(self.data_start_row) + 1,  # 1-based
            "CSV_THOUSANDS": str(thou),
            "TOTAL_COLUMNS": int(self.total_columns),
        }

        print("\n  ✓ Parâmetros finais:")
        for k, v in params.items():
            print(f"    • {k:<18} = {v!r}")
        print("-" * 72)
        return params


# ===========================================================================
# Persistência em Configs (via bridge → condominio.db)
# ===========================================================================

def _resolver_configs_path(configs_path: str | Path) -> Path:
    """
    Normaliza o caminho lógico de Configs para o bridge.
    Aceita:
      - Path/str absoluto ou relativo para .../Configs
      - pasta de dados (usa Configs dentro dela)
      - apenas o nome 'Configs'
    """
    p = Path(configs_path)
    if p.is_dir():
        return p / "Configs"
    # se vier só o nome sem pasta, o bridge resolve via PASTA_CORRENTE no parent
    return p


def update_configs_db(parameters: dict, configs_path: str | Path = "Configs") -> bool:
    """
    Grava os parâmetros de IMPORTACAO em Configs (condominio.db),
    preservando GERAL, CLASSIFICACAO e restantes categorias.
    """
    print("\n💾 ATUALIZANDO CONFIGS…")
    print("-" * 72)

    type_map = {
        "COL_DATA": ("Number", "Indice col. DATA"),
        "COL_DESCRICAO": ("Number", "Indice col. DESC"),
        "COL_VALOR": ("Number", "Indice col. VALOR"),
        "COL_SALDO": ("Number", "Indice col. SALDO"),
        "CSV_AUTO_DETECT": ("String", "Deve ser sempre False"),
        "CSV_DECIMAL": ("String", "Separador decimal"),
        "CSV_DELIMITER": ("String", "Delimitador CSV"),
        "CSV_FIRST_ROW": ("Number", "1 linha dados no CSV"),
        "CSV_THOUSANDS": ("String", "Separador milhares"),
        "TOTAL_COLUMNS": ("Number", "Total de colunas no CSV"),
    }

    try:
        configs_path = _resolver_configs_path(configs_path)
        rows, _ = carregar_db(configs_path)
        novas = set(parameters.keys())
        rows = [
            r for r in rows
            if not (
                str(r.get("CATEGORIA", "")).strip().upper() == "IMPORTACAO"
                and str(r.get("CHAVE", "")).strip() in novas
            )
        ]
        for key, val in parameters.items():
            tipo, desc = type_map.get(key, ("String", "Parâmetro CSV"))
            rows.append({
                "CATEGORIA": "IMPORTACAO",
                "CHAVE": key,
                "VALOR": str(val),
                "TIPO": tipo,
                "DESCRICAO": desc,
            })
            print(f"  ✓ {key:<18} = {val}")

        df = pd.DataFrame(rows, dtype=object)
        ok = salvar_db(df, str(configs_path), None)
        if not ok:
            raise RuntimeError("salvar_db falhou para Configs")
        print(f"  ✓ {len(parameters)} parâmetros IMPORTACAO gravados em condominio.db")
        print("-" * 72)
        return True
    except Exception as e:
        print(f"  ✗ Erro ao atualizar Configs: {e}")
        traceback.print_exc()
        return False


# Alias legado (caso algum caller antigo use este nome)
update_configs_db = update_configs_db


def analyze_and_update(
    csv_path: str | Path,
    configs_path: str | Path = "Configs",
) -> tuple[bool, str, dict | None]:
    """
    Analisa o CSV e atualiza Configs.

    API estável usada por Configuracoes_Gui:
        success, message, params = analyze_and_update(csv_path, configs_path)
    """
    csv_path = str(csv_path)
    if not os.path.exists(csv_path):
        msg = f"Ficheiro não encontrado: {csv_path}"
        print(f"\n✗ {msg}")
        return False, msg, None

    print("\n" + "=" * 72)
    print(f"🔎 VERIFICAÇÃO AUTOMÁTICA — {os.path.basename(csv_path)}")
    print("=" * 72)

    analyzer = CSVAnalyzer(csv_path)
    params = analyzer.analyze()
    if params is None:
        msg = "Não foi possível detetar a estrutura automaticamente"
        print(f"\n✗ {msg}")
        return False, msg, None

    if update_configs_db(params, configs_path):
        msg = "CONFIGS ATUALIZADO COM SUCESSO"
        print(f"\n✅ {msg}")
        return True, msg, params

    # Mesmo se a gravação falhar, devolve os params para a GUI os mostrar
    msg = "FALHA AO ATUALIZAR CONFIGS (parâmetros detetados disponíveis)"
    print(f"\n✗ {msg}")
    return False, msg, params


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python Analisar_csv.py <ficheiro.csv> [Configs] [--dry-run]")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if a not in ("--dry-run", "-n")]
    dry = "--dry-run" in sys.argv or "-n" in sys.argv

    csv_file = args[0]
    if not os.path.isabs(csv_file):
        csv_file = os.path.join(os.getcwd(), csv_file)
    cfg = args[1] if len(args) > 1 else "Configs"

    if dry:
        p = CSVAnalyzer(csv_file).analyze()
        sys.exit(0 if p else 1)

    ok, _, _ = analyze_and_update(csv_file, cfg)
    sys.exit(0 if ok else 1)
