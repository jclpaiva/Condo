"""
Database.py – Camada de dados 100% SQLite relacional (sem qualquer dependência de DBF)

- Schema tipado, com PRIMARY KEYs, FOREIGN KEYs e índices
- Repositórios simples para CRUD e pesquisas
- Substitui completamente o bridge antigo (carregar_db / salvar_db)
"""

from __future__ import annotations

import sqlite3
import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from contextlib import contextmanager

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

def get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
PASTA_CORRENTE = BASE_DIR / "corrente"
PASTA_HISTORICO = BASE_DIR / "historico"
DB_NAME = "condominio.db"


def db_path(pasta: Path | None = None) -> Path:
    """Caminho do ficheiro de base de dados na pasta indicada (default = corrente)."""
    return (pasta or PASTA_CORRENTE) / DB_NAME


# ---------------------------------------------------------------------------
# Ligação
# ---------------------------------------------------------------------------

@contextmanager
def get_connection(pasta: Path | None = None, *, row_factory: bool = True):
    path = db_path(pasta)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    if row_factory:
        conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = DELETE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema completo
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- ============================================================
--  Núcleo
-- ============================================================

CREATE TABLE IF NOT EXISTS condominos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fracao          TEXT    NOT NULL UNIQUE,          -- A, B, C, D, E, F
    andar           TEXT,
    nome            TEXT    NOT NULL,
    morada          TEXT,
    cpostal         TEXT,
    cidade          TEXT,
    telemovel       TEXT,
    email           TEXT,
    permilagem      REAL    DEFAULT 0,
    quota_normal    REAL    NOT NULL DEFAULT 0,
    quota_extra     REAL    NOT NULL DEFAULT 0,
    foto            TEXT,
    ativo           INTEGER NOT NULL DEFAULT 1,       -- 1 = recebe emails
    admin           INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT
);

-- ============================================================
--  Regras de classificação V5
--  Tabela única: absorve Configs.REGRA_* + COND_* + tabela contas
--  normal/extra preenchidos = regra de condómino
--  normal/extra vazios      = regra geral (despesa/receita)
-- ============================================================

CREATE TABLE IF NOT EXISTS regras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prioridade  INTEGER NOT NULL DEFAULT 100,  -- menor = mais prioritário
    classe      TEXT    NOT NULL CHECK (classe IN ('RECEITA', 'DESPESA')),
    conta       TEXT    NOT NULL,              -- nome da conta contabilística (texto livre)
    pattern     TEXT    NOT NULL,              -- texto a procurar na descrição do CSV
    normal      REAL,                          -- quota normal (só condóminos)
    extra       REAL,                          -- quota extra  (só condóminos)
    ativo       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE (pattern, normal, extra)
);

CREATE INDEX IF NOT EXISTS idx_regras_prioridade ON regras (prioridade);
CREATE INDEX IF NOT EXISTS idx_regras_pattern    ON regras (pattern);
CREATE INDEX IF NOT EXISTS idx_regras_ativo      ON regras (ativo);

-- ============================================================
--  Movimentos (bancos + caixa + depósito a prazo unificados)
-- ============================================================

CREATE TABLE IF NOT EXISTS movimentos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    data            TEXT    NOT NULL,                 -- ISO YYYY-MM-DD
    descricao       TEXT    NOT NULL,
    valor           REAL    NOT NULL,
    saldo           REAL,
    tipo            TEXT    CHECK (tipo IN ('RECEITA', 'DESPESA') OR tipo IS NULL),
    conta           TEXT,                             -- nome da conta (texto livre, sem FK)
    observacao      TEXT,
    origem          TEXT    NOT NULL DEFAULT 'manual', -- 'import_csv' | 'manual' | 'sincronizacao'
    fonte           TEXT    NOT NULL CHECK (fonte IN ('bancos', 'caixa', 'dprazo')),
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mov_data      ON movimentos (data);
CREATE INDEX IF NOT EXISTS idx_mov_conta     ON movimentos (conta);
CREATE INDEX IF NOT EXISTS idx_mov_fonte     ON movimentos (fonte);
CREATE INDEX IF NOT EXISTS idx_mov_tipo      ON movimentos (tipo);
CREATE INDEX IF NOT EXISTS idx_mov_descricao ON movimentos (descricao);

-- ============================================================
--  Receitas mensais (normalizadas – substitui ReceitasN / ReceitasE)
-- ============================================================

CREATE TABLE IF NOT EXISTS receitas_mensais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    condominio_id   INTEGER NOT NULL REFERENCES condominos(id) ON DELETE CASCADE,
    ano             INTEGER NOT NULL,
    mes             INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    tipo_quota      TEXT    NOT NULL,                 -- 'NORMAL' | 'EXTRA' | 'JUROS' | ...
    valor           REAL    NOT NULL DEFAULT 0,
    UNIQUE (condominio_id, ano, mes, tipo_quota)
);

CREATE INDEX IF NOT EXISTS idx_rec_ano_mes ON receitas_mensais (ano, mes);
CREATE INDEX IF NOT EXISTS idx_rec_condo   ON receitas_mensais (condominio_id);

-- ============================================================
--  Despesas mensais (normalizadas)
-- ============================================================

CREATE TABLE IF NOT EXISTS despesas_mensais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conta           TEXT    NOT NULL,                 -- nome da conta (texto livre)
    ano             INTEGER NOT NULL,
    mes             INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    valor           REAL    NOT NULL DEFAULT 0,
    UNIQUE (conta, ano, mes)
);

CREATE INDEX IF NOT EXISTS idx_desp_ano_mes ON despesas_mensais (ano, mes);
CREATE INDEX IF NOT EXISTS idx_desp_conta   ON despesas_mensais (conta);

-- ============================================================
--  Configurações (EAV limpo)
-- ============================================================

CREATE TABLE IF NOT EXISTS configs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria       TEXT    NOT NULL,
    chave           TEXT    NOT NULL,
    valor           TEXT,
    tipo            TEXT,                             -- Number | String | Boolean
    descricao       TEXT,
    UNIQUE (categoria, chave)
);

CREATE INDEX IF NOT EXISTS idx_configs_cat ON configs (categoria);

-- ============================================================
--  Snapshots de saldos / balanço (opcional – para histórico rápido)
-- ============================================================

CREATE TABLE IF NOT EXISTS saldos_linhas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem   INTEGER NOT NULL,
    conta   TEXT    NOT NULL DEFAULT '',
    tipo    TEXT    DEFAULT '',
    valor   REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS balanco_linhas (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem   INTEGER NOT NULL,
    conta   TEXT    NOT NULL DEFAULT '',
    tipo    TEXT    DEFAULT '',
    valor   REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS saldos_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conta           TEXT,                             -- nome da conta
    nome            TEXT,                             -- para títulos / totais
    tipo            TEXT,                             -- RECEITA | TITULO | SUBTOTAL | ...
    valor           REAL    NOT NULL DEFAULT 0,
    momento         TEXT    NOT NULL DEFAULT 'final', -- 'inicial' | 'final' | 'exercicio'
    ano             INTEGER,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
--  Juros mensais (mantido simples)
-- ============================================================

CREATE TABLE IF NOT EXISTS receitas_resumo (
    condominio_id   INTEGER NOT NULL REFERENCES condominos(id) ON DELETE CASCADE,
    ano             INTEGER NOT NULL,
    tipo_quota      TEXT    NOT NULL CHECK (tipo_quota IN ('NORMAL', 'EXTRA')),
    fracao_label    TEXT,
    saldo_ant       REAL    DEFAULT 0,
    saldo           REAL    DEFAULT 0,
    PRIMARY KEY (condominio_id, ano, tipo_quota)
);

CREATE TABLE IF NOT EXISTS juros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ano             INTEGER NOT NULL,
    mes             INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    valor           REAL    NOT NULL DEFAULT 0,
    UNIQUE (ano, mes)
);
"""


def create_schema(pasta: Path | None = None) -> None:
    """Cria (ou actualiza) o schema completo."""
    with get_connection(pasta, row_factory=False) as conn:
        conn.executescript(SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Helpers de conversão de tipos
# ---------------------------------------------------------------------------

def _to_float(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(str(val).replace(",", ".")))
    except (ValueError, TypeError):
        return default


def _to_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _normalize_date(val: Any) -> str:
    """Converte várias formas de data para ISO YYYY-MM-DD."""
    if val is None or val == "":
        return ""
    if isinstance(val, datetime.date):
        return val.isoformat()
    s = str(val).strip()
    # já ISO?
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # dd/mm/yyyy ou dd-mm-yyyy
    for sep in ("/", "-"):
        parts = s.split(sep)
        if len(parts) == 3:
            d, m, y = parts
            if len(y) == 4:
                return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s


# ---------------------------------------------------------------------------
# Repositórios básicos (CRUD + find)
# ---------------------------------------------------------------------------

class BaseRepo:
    table: str = ""

    def __init__(self, pasta: Path | None = None):
        self.pasta = pasta

    def _conn(self):
        return get_connection(self.pasta)

    def all(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(f"SELECT * FROM {self.table}").fetchall()

    def get(self, id_: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                f"SELECT * FROM {self.table} WHERE id = ?", (id_,)
            ).fetchone()

    def delete(self, id_: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(f"DELETE FROM {self.table} WHERE id = ?", (id_,))
            return cur.rowcount > 0


class CondominosRepo(BaseRepo):
    table = "condominos"

    def find_by_fracao(self, fracao: str) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM condominos WHERE fracao = ?", (fracao,)
            ).fetchone()

    def find_ativos(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM condominos WHERE ativo = 1 ORDER BY fracao"
            ).fetchall()

    def upsert(self, data: dict) -> int:
        """Insere ou actualiza por fracao. Devolve o id."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM condominos WHERE fracao = ?", (data["fracao"],)
            ).fetchone()
            if existing:
                sets = ", ".join(f"{k} = ?" for k in data if k != "fracao")
                vals = [data[k] for k in data if k != "fracao"] + [data["fracao"]]
                conn.execute(
                    f"UPDATE condominos SET {sets}, updated_at = datetime('now') WHERE fracao = ?",
                    vals,
                )
                return existing["id"]
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            cur = conn.execute(
                f"INSERT INTO condominos ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            return cur.lastrowid


class RegrasRepo(BaseRepo):
    table = "regras"

    def find_ativas(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT *
                FROM regras
                WHERE ativo = 1
                ORDER BY prioridade, id
                """
            ).fetchall()

    def find_condominos(self) -> list[sqlite3.Row]:
        """Regras com normal/extra definidos (condóminos)."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM regras WHERE ativo=1 AND normal IS NOT NULL ORDER BY prioridade"
            ).fetchall()

    def find_gerais(self) -> list[sqlite3.Row]:
        """Regras sem normal/extra (despesas/receitas gerais)."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM regras WHERE ativo=1 AND normal IS NULL ORDER BY prioridade"
            ).fetchall()

    def upsert(self, data: dict) -> int:
        """Insere ou actualiza por (pattern, normal, extra). Devolve o id."""
        with self._conn() as conn:
            existing = conn.execute(
                """SELECT id FROM regras
                   WHERE pattern=?
                   AND (normal IS ? OR normal=?)
                   AND (extra  IS ? OR extra=?)""",
                (data["pattern"],
                 data.get("normal"), data.get("normal"),
                 data.get("extra"),  data.get("extra")),
            ).fetchone()
            if existing:
                sets = ", ".join(f"{k}=?" for k in data if k != "pattern")
                vals = [data[k] for k in data if k != "pattern"] + [existing["id"]]
                conn.execute(f"UPDATE regras SET {sets} WHERE id=?", vals)
                return existing["id"]
            cols = ", ".join(data.keys())
            ph   = ", ".join("?" * len(data))
            cur  = conn.execute(f"INSERT INTO regras ({cols}) VALUES ({ph})",
                                list(data.values()))
            return cur.lastrowid

    def replace_all(self, rows: Sequence[dict]) -> int:
        """Substitui todas as regras activas (usado pela GUI de Regras)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM regras")
            n = 0
            for r in rows:
                pattern = str(r.get("pattern") or r.get("Pattern") or "").strip()
                conta   = str(r.get("conta")   or r.get("Conta")   or "").strip()
                classe  = str(r.get("classe")  or r.get("Classe")  or "DESPESA").strip().upper()
                if not pattern or not conta:
                    continue
                if classe not in ("RECEITA", "DESPESA"):
                    classe = "DESPESA"
                prio   = int(r.get("prioridade") or r.get("Prioridade") or 100)
                normal = r.get("normal") or r.get("Normal")
                extra  = r.get("extra")  or r.get("Extra")
                normal = float(normal) if normal not in (None, "") else None
                extra  = float(extra)  if extra  not in (None, "") else None
                conn.execute(
                    """INSERT INTO regras (prioridade, classe, conta, pattern, normal, extra)
                       VALUES (?,?,?,?,?,?)""",
                    (prio, classe, conta, pattern, normal, extra),
                )
                n += 1
            return n

    def contas_unicas(self) -> list[str]:
        """Lista de nomes de contas distintos (para combos na GUI)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT conta FROM regras WHERE ativo=1 ORDER BY conta"
            ).fetchall()
            return [r["conta"] for r in rows]


class MovimentosRepo(BaseRepo):
    table = "movimentos"

    def find(
        self,
        *,
        fonte: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
        conta: str | None = None,
        tipo: str | None = None,
        descricao_like: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[Any] = []
        if fonte:
            clauses.append("m.fonte = ?")
            params.append(fonte)
        if data_de:
            clauses.append("m.data >= ?")
            params.append(data_de)
        if data_ate:
            clauses.append("m.data <= ?")
            params.append(data_ate)
        if conta is not None:
            clauses.append("m.conta = ?")
            params.append(conta)
        if tipo:
            # BUGFIX: "tipo" sem qualificador era ambíguo (existe em
            # movimentos.tipo E em contas.tipo, por causa do LEFT JOIN),
            # o que fazia esta pesquisa falhar sempre com
            # "sqlite3.OperationalError: ambiguous column name: tipo".
            clauses.append("m.tipo = ?")
            params.append(tipo)
        if descricao_like:
            clauses.append("m.descricao LIKE ?")
            params.append(f"%{descricao_like}%")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT m.*
            FROM movimentos m
            {where}
            ORDER BY m.data, m.id
        """
        if limit:
            sql += f" LIMIT {int(limit)}"

        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

    def insert_many(self, rows: Sequence[dict]) -> int:
        if not rows:
            return 0
        with self._conn() as conn:
            cur = conn.executemany(
                """
                INSERT INTO movimentos
                    (data, descricao, valor, saldo, tipo, conta, observacao, origem, fonte)
                VALUES
                    (:data, :descricao, :valor, :saldo, :tipo, :conta, :observacao, :origem, :fonte)
                """,
                rows,
            )
            return cur.rowcount

    def replace_fonte(self, fonte: str, rows: Sequence[dict]) -> int:
        """Apaga todos os movimentos de uma fonte e insere os novos (útil na reimportação)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM movimentos WHERE fonte = ?", (fonte,))
            if not rows:
                return 0
            cur = conn.executemany(
                """
                INSERT INTO movimentos
                    (data, descricao, valor, saldo, tipo, conta, observacao, origem, fonte)
                VALUES
                    (:data, :descricao, :valor, :saldo, :tipo, :conta, :observacao, :origem, :fonte)
                """,
                rows,
            )
            return cur.rowcount


class ConfigsRepo(BaseRepo):
    table = "configs"

    def get_value(self, categoria: str, chave: str, default: Any = None) -> Any:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT valor, tipo FROM configs WHERE categoria = ? AND chave = ?",
                (categoria, chave),
            ).fetchone()
            if not row:
                return default
            val = row["valor"]
            t = (row["tipo"] or "").lower()
            if t == "number":
                return _to_float(val)
            if t == "boolean":
                return str(val).lower() in ("1", "true", "yes", "sim")
            return val

    def set_value(self, categoria: str, chave: str, valor: Any,
                  tipo: str = "String", descricao: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO configs (categoria, chave, valor, tipo, descricao)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(categoria, chave) DO UPDATE SET
                    valor = excluded.valor,
                    tipo = excluded.tipo,
                    descricao = excluded.descricao
                """,
                (categoria, chave, str(valor) if valor is not None else None, tipo, descricao),
            )

    def all_by_categoria(self, categoria: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM configs WHERE categoria = ? ORDER BY chave",
                (categoria,),
            ).fetchall()

    def all(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM configs ORDER BY categoria, chave"
            ).fetchall()

    def replace_all(self, rows: Sequence[dict]) -> int:
        """Substitui todas as configs (útil quando a GUI grava a tabela completa)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM configs")
            n = 0
            for r in rows:
                cat = str(r.get("categoria") or r.get("CATEGORIA") or "").strip()
                chave = str(r.get("chave") or r.get("CHAVE") or "").strip()
                if not cat or not chave:
                    continue
                valor = r.get("valor", r.get("VALOR"))
                tipo = str(r.get("tipo") or r.get("TIPO") or "String")
                desc = str(r.get("descricao") or r.get("DESCRICAO") or "")
                conn.execute(
                    """INSERT INTO configs (categoria, chave, valor, tipo, descricao)
                       VALUES (?,?,?,?,?)""",
                    (cat, chave, None if valor is None else str(valor), tipo, desc),
                )
                n += 1
            return n


# Atalhos de conveniência
def condominos(pasta=None) -> CondominosRepo:
    return CondominosRepo(pasta)

def regras(pasta=None) -> RegrasRepo:
    return RegrasRepo(pasta)

def movimentos(pasta=None) -> MovimentosRepo:
    return MovimentosRepo(pasta)

def configs(pasta=None) -> ConfigsRepo:
    return ConfigsRepo(pasta)


# ---------------------------------------------------------------------------
# Views / FTS / pesquisas avançadas
# ---------------------------------------------------------------------------

VIEWS_SQL = """
CREATE VIEW IF NOT EXISTS v_movimentos AS
SELECT m.id, m.data, m.descricao, m.valor, m.saldo, m.tipo,
       m.conta, m.observacao, m.origem, m.fonte, m.created_at
FROM movimentos m;

CREATE VIEW IF NOT EXISTS v_receitas_pivot AS
SELECT
  co.fracao, co.nome AS condominio, r.ano, r.tipo_quota,
  SUM(CASE WHEN r.mes=1 THEN r.valor ELSE 0 END) AS jan,
  SUM(CASE WHEN r.mes=2 THEN r.valor ELSE 0 END) AS fev,
  SUM(CASE WHEN r.mes=3 THEN r.valor ELSE 0 END) AS mar,
  SUM(CASE WHEN r.mes=4 THEN r.valor ELSE 0 END) AS abr,
  SUM(CASE WHEN r.mes=5 THEN r.valor ELSE 0 END) AS mai,
  SUM(CASE WHEN r.mes=6 THEN r.valor ELSE 0 END) AS jun,
  SUM(CASE WHEN r.mes=7 THEN r.valor ELSE 0 END) AS jul,
  SUM(CASE WHEN r.mes=8 THEN r.valor ELSE 0 END) AS ago,
  SUM(CASE WHEN r.mes=9 THEN r.valor ELSE 0 END) AS "set",
  SUM(CASE WHEN r.mes=10 THEN r.valor ELSE 0 END) AS out,
  SUM(CASE WHEN r.mes=11 THEN r.valor ELSE 0 END) AS nov,
  SUM(CASE WHEN r.mes=12 THEN r.valor ELSE 0 END) AS dez,
  SUM(r.valor) AS total,
  COALESCE(MAX(rr.saldo_ant), 0) AS saldo_ant,
  COALESCE(MAX(rr.saldo), 0) AS saldo
FROM receitas_mensais r
JOIN condominos co ON co.id = r.condominio_id
LEFT JOIN receitas_resumo rr
  ON rr.condominio_id = r.condominio_id
 AND rr.ano = r.ano
 AND rr.tipo_quota = r.tipo_quota
GROUP BY co.fracao, co.nome, r.ano, r.tipo_quota;

CREATE VIEW IF NOT EXISTS v_despesas_pivot AS
SELECT
  d.conta, d.ano,
  SUM(CASE WHEN d.mes=1 THEN d.valor ELSE 0 END) AS jan,
  SUM(CASE WHEN d.mes=2 THEN d.valor ELSE 0 END) AS fev,
  SUM(CASE WHEN d.mes=3 THEN d.valor ELSE 0 END) AS mar,
  SUM(CASE WHEN d.mes=4 THEN d.valor ELSE 0 END) AS abr,
  SUM(CASE WHEN d.mes=5 THEN d.valor ELSE 0 END) AS mai,
  SUM(CASE WHEN d.mes=6 THEN d.valor ELSE 0 END) AS jun,
  SUM(CASE WHEN d.mes=7 THEN d.valor ELSE 0 END) AS jul,
  SUM(CASE WHEN d.mes=8 THEN d.valor ELSE 0 END) AS ago,
  SUM(CASE WHEN d.mes=9 THEN d.valor ELSE 0 END) AS "set",
  SUM(CASE WHEN d.mes=10 THEN d.valor ELSE 0 END) AS out,
  SUM(CASE WHEN d.mes=11 THEN d.valor ELSE 0 END) AS nov,
  SUM(CASE WHEN d.mes=12 THEN d.valor ELSE 0 END) AS dez,
  SUM(d.valor) AS total
FROM despesas_mensais d
GROUP BY d.conta, d.ano;

CREATE VIEW IF NOT EXISTS v_saldos_por_fonte AS
SELECT fonte, tipo, COUNT(*) AS n_movimentos,
       ROUND(SUM(valor), 2) AS total_valor, MAX(data) AS ultima_data
FROM movimentos
GROUP BY fonte, tipo;

CREATE VIEW IF NOT EXISTS v_quotas_por_condomino AS
SELECT
  co.id AS condominio_id, co.fracao, co.nome,
  co.quota_normal, co.quota_extra, r.ano,
  COALESCE(SUM(CASE WHEN r.tipo_quota='NORMAL' THEN r.valor END), 0) AS pago_normal,
  COALESCE(SUM(CASE WHEN r.tipo_quota='EXTRA' THEN r.valor END), 0) AS pago_extra,
  COALESCE(SUM(r.valor), 0) AS pago_total
FROM condominos co
LEFT JOIN receitas_mensais r ON r.condominio_id = co.id
GROUP BY co.id, co.fracao, co.nome, co.quota_normal, co.quota_extra, r.ano;
"""


def ensure_views_and_fts(pasta: Path | None = None) -> None:
    """Cria views e índice FTS5 (idempotente)."""
    with get_connection(pasta, row_factory=False) as conn:
        for view in (
            "v_receitas_pivot",
            "v_despesas_pivot",
            "v_movimentos",
            "v_quotas_por_condomino",
            "v_saldos_por_fonte",
        ):
            try:
                conn.execute(f"DROP VIEW IF EXISTS {view}")
            except Exception:
                pass
        for stmt in VIEWS_SQL.split(";"):
            s = stmt.strip()
            if s:
                try:
                    conn.execute(s)
                except Exception:
                    pass
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS movimentos_fts USING fts5(
                    descricao,
                    content='movimentos',
                    content_rowid='id',
                    tokenize='unicode61'
                )
            """)
        except Exception:
            pass


def search_movimentos_fts(query: str, pasta: Path | None = None, limit: int = 50) -> list:
    """Pesquisa full-text nas descrições dos movimentos."""
    ensure_views_and_fts(pasta)
    with get_connection(pasta) as conn:
        try:
            return conn.execute(
                """
                SELECT m.*
                FROM movimentos_fts f
                JOIN movimentos m ON m.id = f.rowid
                WHERE movimentos_fts MATCH ?
                ORDER BY m.data DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except Exception as e:
            print(f"⚠️ FTS search falhou ({e}); fallback LIKE")
            return conn.execute(
                """
                SELECT m.*
                FROM movimentos m
                WHERE m.descricao LIKE ?
                ORDER BY m.data DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()


def sync_movimentos_from_legacy_df(df, fonte: str, pasta: Path | None = None) -> int:
    """
    Sincroniza um DataFrame no formato legado (DATA, DESCRICAO, VALOR, SALDO, TIPO, CONTA, OBSERVACAO)
    para a tabela movimentos de condominio.db (substitui todos os da fonte).
    V5: conta é TEXT directo, sem FK para contas.
    """
    from Database import MovimentosRepo, _normalize_date, _to_float, _to_str

    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    ensure_views_and_fts(pasta)
    mov_repo = MovimentosRepo(pasta)

    rows = []
    for _, r in df.iterrows():
        conta = _to_str(r.get("CONTA", r.get("conta", "")))
        tipo = _to_str(r.get("TIPO", r.get("tipo", ""))).upper() or None
        if tipo and tipo not in ("RECEITA", "DESPESA"):
            tipo = None

        rows.append({
            "data": _normalize_date(r.get("DATA", r.get("data", ""))) or "1970-01-01",
            "descricao": _to_str(r.get("DESCRICAO", r.get("descricao", ""))) or "***",
            "valor": _to_float(r.get("VALOR", r.get("valor", 0))),
            "saldo": _to_float(r.get("SALDO", r.get("saldo", 0))),
            "tipo": tipo,
            "conta": conta or None,
            "observacao": _to_str(r.get("OBSERVACAO", r.get("observacao", ""))),
            "origem": "sync_legacy",
            "fonte": fonte,
        })

    n = mov_repo.replace_fonte(fonte, rows)
    # Rebuild FTS for this fonte
    try:
        with get_connection(pasta, row_factory=False) as conn:
            # BUGFIX: "DELETE FROM movimentos_fts" (sem WHERE) não é a forma
            # suportada de limpar uma tabela FTS5 de "external content"
            # (content='movimentos'). Isso fazia a transacção falhar sempre
            # com "database disk image is malformed" (erro interno do
            # pager/cache do sqlite3, não corrupção persistente — ao reabrir
            # a ligação os dados de `movimentos` continuavam intactos), e a
            # excepção era engolida pelo except silencioso abaixo. Resultado
            # prático: o índice de pesquisa nunca era reconstruído e
            # `search_movimentos_fts` ficava sempre a devolver zero
            # resultados (ou resultados desactualizados). O comando correcto
            # para limpar/reconstruir uma tabela FTS5 externa é o comando
            # especial 'delete-all'.
            conn.execute("INSERT INTO movimentos_fts(movimentos_fts) VALUES ('delete-all')")
            conn.execute("INSERT INTO movimentos_fts(rowid, descricao) SELECT id, descricao FROM movimentos")
    except Exception as e:
        print(f"  ⚠️ Reconstrução do índice FTS falhou: {e}")
    return n


class ReceitasRepo(BaseRepo):
    table = "receitas_mensais"

    def pivot(self, ano: int | None = None) -> list:
        with self._conn() as conn:
            if ano:
                return conn.execute(
                    "SELECT * FROM v_receitas_pivot WHERE ano = ? ORDER BY fracao, tipo_quota",
                    (ano,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM v_receitas_pivot ORDER BY ano, fracao, tipo_quota"
            ).fetchall()

    def por_condominio(self, condominio_id: int, ano: int) -> list:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT mes, tipo_quota, valor
                FROM receitas_mensais
                WHERE condominio_id = ? AND ano = ?
                ORDER BY mes, tipo_quota
                """,
                (condominio_id, ano),
            ).fetchall()


class DespesasRepo(BaseRepo):
    table = "despesas_mensais"

    def pivot(self, ano: int | None = None) -> list:
        with self._conn() as conn:
            if ano:
                return conn.execute(
                    "SELECT * FROM v_despesas_pivot WHERE ano = ? ORDER BY conta",
                    (ano,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM v_despesas_pivot ORDER BY ano, conta"
            ).fetchall()


def receitas(pasta=None) -> ReceitasRepo:
    return ReceitasRepo(pasta)

def despesas(pasta=None) -> DespesasRepo:
    return DespesasRepo(pasta)




# ---------------------------------------------------------------------------
# Pivot largo (compatibilidade ReceitasN/E, Despesas, Juros)
# ---------------------------------------------------------------------------

MAPA_FRACAO_PARA_LETRA = {
    "R/C ESQ.": "A", "R/C DTO.": "B",
    "1º ESQ.": "C", "1 ESQ.": "C", "1° ESQ.": "C",
    "1º DTO.": "D", "1 DTO.": "D", "1° DTO.": "D",
    "2º ESQ.": "E", "2 ESQ.": "E", "2° ESQ.": "E",
    "2º DTO.": "F", "2 DTO.": "F", "2° DTO.": "F",
}
MAPA_LETRA_PARA_LABEL = {
    "A": "R/c Esq.", "B": "R/c Dto.",
    "C": "1º Esq.", "D": "1º Dto.",
    "E": "2º Esq.", "F": "2º Dto.",
}
MESES_COLS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
MESES_KEYS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _norm_fracao_label(label: str) -> str:
    s = " ".join(str(label or "").upper().replace("º", "º").replace("°", "º").split())
    return s


def _letra_from_label(label: str) -> str | None:
    key = _norm_fracao_label(label)
    if key in MAPA_FRACAO_PARA_LETRA:
        return MAPA_FRACAO_PARA_LETRA[key]
    # fuzzy
    for k, v in MAPA_FRACAO_PARA_LETRA.items():
        if k.replace(" ", "") in key.replace(" ", "") or key.replace(" ", "") in k.replace(" ", ""):
            return v
    # already a letter?
    if len(key) == 1 and key in "ABCDEF":
        return key
    return None


def _ano_exercicio(pasta: Path | None = None) -> int:
    try:
        v = ConfigsRepo(pasta).get_value("GERAL", "ANO_EXERCICIO", 2026)
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return 2026


def save_receitas_wide(df, tipo_quota: str, pasta: Path | None = None, ano: int | None = None) -> int:
    """Grava DataFrame largo ReceitasN/E em receitas_mensais + receitas_resumo."""
    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    ensure_views_and_fts(pasta)
    ano = ano or _ano_exercicio(pasta)
    tipo_quota = tipo_quota.upper()
    if tipo_quota not in ("NORMAL", "EXTRA"):
        raise ValueError(tipo_quota)

    with get_connection(pasta) as conn:
        condo_map = {r["fracao"]: r["id"] for r in conn.execute("SELECT id, fracao FROM condominos")}
        conn.execute(
            "DELETE FROM receitas_mensais WHERE ano = ? AND tipo_quota = ?",
            (ano, tipo_quota),
        )
        conn.execute(
            "DELETE FROM receitas_resumo WHERE ano = ? AND tipo_quota = ?",
            (ano, tipo_quota),
        )
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            label = str(d.get("FRACCAO") or "").strip()
            if not label or label.upper() == "TOTAIS":
                continue
            letra = _letra_from_label(label)
            if not letra or letra not in condo_map:
                print(f"  ⚠️ Fracção não mapeada: {label!r}")
                continue
            cid = condo_map[letra]
            for col, mes in zip(MESES_COLS, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO receitas_mensais
                       (condominio_id, ano, mes, tipo_quota, valor)
                       VALUES (?,?,?,?,?)""",
                    (cid, ano, mes, tipo_quota, val),
                )
                n += 1
            conn.execute(
                """INSERT OR REPLACE INTO receitas_resumo
                   (condominio_id, ano, tipo_quota, fracao_label, saldo_ant, saldo)
                   VALUES (?,?,?,?,?,?)""",
                (cid, ano, tipo_quota, label,
                 _to_float(d.get("SALDO_ANT", 0)), _to_float(d.get("SALDO", 0))),
            )
        return n


def load_receitas_wide(tipo_quota: str, pasta: Path | None = None, ano: int | None = None):
    """Devolve (rows_legado, fields) no formato ReceitasN/E."""
    pasta = pasta or PASTA_CORRENTE
    ensure_views_and_fts(pasta)
    ano = ano or _ano_exercicio(pasta)
    tipo_quota = tipo_quota.upper()
    fields = ["FRACCAO", "SALDO_ANT"] + MESES_COLS + ["TOTAL", "SALDO"]

    with get_connection(pasta) as conn:
        pivots = conn.execute(
            """SELECT * FROM v_receitas_pivot
               WHERE ano = ? AND UPPER(tipo_quota) = ?
               ORDER BY fracao""",
            (ano, tipo_quota),
        ).fetchall()
        resumos = {
            r["condominio_id"]: r
            for r in conn.execute(
                """SELECT * FROM receitas_resumo
                   WHERE ano = ? AND UPPER(tipo_quota) = ?""",
                (ano, tipo_quota),
            ).fetchall()
        }
        # map fracao letter -> condominio id
        id_by_fracao = {
            r["fracao"]: r["id"]
            for r in conn.execute("SELECT id, fracao FROM condominos")
        }

        rows = []
        totals = {c: 0.0 for c in MESES_COLS}
        totals["TOTAL"] = 0.0
        totals["SALDO_ANT"] = 0.0
        totals["SALDO"] = 0.0

        # BUGFIX: iterar apenas sobre `pivots` (derivado de v_receitas_pivot,
        # que faz JOIN/GROUP BY em cima de receitas_mensais) fazia
        # desaparecer por completo qualquer fracção sem NENHUM valor mensal
        # não-nulo — mesmo que tivesse um SALDO_ANT/SALDO válido em
        # receitas_resumo. Isto acontece sempre a seguir a um fim-de-ano
        # (fim_ano_quotas_normais/extras zera os 12 meses e só transporta o
        # saldo para SALDO_ANT): a fracção ficava invisível na grelha até à
        # primeira quota paga no novo ano, escondendo o saldo transitado.
        # Reproduzido e confirmado com teste. Corrigido: percorre a união
        # das fracções com pivot E das fracções com receitas_resumo.
        pivots_by_fracao = {str(p["fracao"] or ""): p for p in pivots}
        fracao_by_id = {v: k for k, v in id_by_fracao.items()}
        fracoes_com_resumo = {
            fracao_by_id[cid] for cid in resumos if cid in fracao_by_id
        }
        todas_fracoes = sorted(set(pivots_by_fracao) | fracoes_com_resumo)

        for letra in todas_fracoes:
            p = pivots_by_fracao.get(letra)
            cid = id_by_fracao.get(letra)
            res = resumos.get(cid) if cid else None
            label = (res["fracao_label"] if res and res["fracao_label"]
                     else MAPA_LETRA_PARA_LABEL.get(letra, letra))
            row = {"FRACCAO": label}
            total = 0.0
            for mk, col in zip(MESES_KEYS, MESES_COLS):
                val = _to_float(p[mk] if p is not None and mk in p.keys() else 0)
                row[col] = val
                totals[col] += val
                total += val
            row["TOTAL"] = _to_float(p["total"] if p is not None and "total" in p.keys() else total)
            row["SALDO_ANT"] = _to_float(res["saldo_ant"]) if res else 0.0
            row["SALDO"] = _to_float(res["saldo"]) if res else 0.0
            totals["TOTAL"] += row["TOTAL"]
            totals["SALDO_ANT"] += row["SALDO_ANT"]
            totals["SALDO"] += row["SALDO"]
            rows.append(row)

        if rows:
            tot = {"FRACCAO": "TOTAIS"}
            tot.update(totals)
            rows.append(tot)

        return rows, fields


def save_despesas_wide(df, pasta: Path | None = None, ano: int | None = None) -> int:
    """Grava DataFrame largo Despesas em despesas_mensais."""
    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    ensure_views_and_fts(pasta)
    ano = ano or _ano_exercicio(pasta)

    with get_connection(pasta) as conn:
        conn.execute("DELETE FROM despesas_mensais WHERE ano = ?", (ano,))
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            nome = str(d.get("DESPESAS") or "").strip()
            if not nome or nome.upper() == "TOTAIS":
                continue
            for col, mes in zip(MESES_COLS, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO despesas_mensais
                       (conta, ano, mes, valor) VALUES (?,?,?,?)""",
                    (nome, ano, mes, val),
                )
                n += 1
        return n


def load_despesas_wide(pasta: Path | None = None, ano: int | None = None):
    """Devolve (rows_legado, fields) no formato Despesas."""
    pasta = pasta or PASTA_CORRENTE
    ensure_views_and_fts(pasta)
    ano = ano or _ano_exercicio(pasta)
    fields = ["DESPESAS"] + MESES_COLS + ["TOTAL"]

    with get_connection(pasta) as conn:
        pivots = conn.execute(
            "SELECT * FROM v_despesas_pivot WHERE ano = ? ORDER BY conta",
            (ano,),
        ).fetchall()
        rows = []
        totals = {c: 0.0 for c in MESES_COLS}
        totals["TOTAL"] = 0.0
        for p in pivots:
            row = {"DESPESAS": str(p["conta"] or "")}
            total = 0.0
            for mk, col in zip(MESES_KEYS, MESES_COLS):
                val = _to_float(p[mk] if mk in p.keys() else 0)
                row[col] = val
                totals[col] += val
                total += val
            row["TOTAL"] = _to_float(p["total"] if "total" in p.keys() else total)
            totals["TOTAL"] += row["TOTAL"]
            rows.append(row)
        if rows:
            tot = {"DESPESAS": "TOTAIS"}
            tot.update(totals)
            rows.append(tot)
        return rows, fields


def save_juros_wide(df, pasta: Path | None = None, ano: int | None = None) -> int:
    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    ano = ano or _ano_exercicio(pasta)
    with get_connection(pasta) as conn:
        conn.execute("DELETE FROM juros WHERE ano = ?", (ano,))
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            for col, mes in zip(MESES_COLS, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO juros (ano, mes, valor) VALUES (?,?,?)",
                    (ano, mes, val),
                )
                n += 1
        return n


def load_juros_wide(pasta: Path | None = None, ano: int | None = None):
    pasta = pasta or PASTA_CORRENTE
    ano = ano or _ano_exercicio(pasta)
    fields = ["JUROS"] + MESES_COLS + ["TOTAL"]
    with get_connection(pasta) as conn:
        vals = {r["mes"]: _to_float(r["valor"])
                for r in conn.execute("SELECT mes, valor FROM juros WHERE ano = ?", (ano,))}
        if not vals:
            return [], fields
        row = {"JUROS": "Juros"}
        total = 0.0
        for col, mes in zip(MESES_COLS, range(1, 13)):
            v = vals.get(mes, 0.0)
            row[col] = v
            total += v
        row["TOTAL"] = total
        return [row], fields


# ---------------------------------------------------------------------------
# Saldos / Balanço (linhas ordenadas — fidelidade total ao formato legado)
# ---------------------------------------------------------------------------

def save_linhas_tabela(df, tabela_linhas: str, pasta: Path | None = None) -> int:
    """Grava DataFrame com CONTA/TIPO/VALOR numa tabela de linhas ordenadas."""
    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    with get_connection(pasta) as conn:
        conn.execute(f"DELETE FROM {tabela_linhas}")
        n = 0
        for ordem, (_, row) in enumerate(df.iterrows()):
            d = {str(k).upper(): row[k] for k in df.columns}
            conta = d.get("CONTA")
            tipo = d.get("TIPO")
            valor = _to_float(d.get("VALOR", 0))
            conta_s = "" if conta is None else str(conta)
            tipo_s = "" if tipo is None else str(tipo)
            conn.execute(
                f"INSERT INTO {tabela_linhas} (ordem, conta, tipo, valor) VALUES (?,?,?,?)",
                (ordem, conta_s, tipo_s, valor),
            )
            n += 1
        return n


def load_linhas_tabela(tabela_linhas: str, pasta: Path | None = None):
    """Devolve (rows legado CONTA/TIPO/VALOR, fields)."""
    pasta = pasta or PASTA_CORRENTE
    create_schema(pasta)
    fields = ["CONTA", "TIPO", "VALOR"]
    with get_connection(pasta) as conn:
        # tabela pode ainda não existir em DBs antigos
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (tabela_linhas,),
        ).fetchone()
        if not exists:
            return [], fields
        rows_db = conn.execute(
            f"SELECT conta, tipo, valor FROM {tabela_linhas} ORDER BY ordem, id"
        ).fetchall()
        out = []
        for r in rows_db:
            out.append({
                "CONTA": r["conta"] if r["conta"] is not None else "",
                "TIPO": r["tipo"] if r["tipo"] is not None else "",
                "VALOR": r["valor"] if r["valor"] is not None else 0.0,
            })
        return out, fields


def save_saldos_wide(df, pasta: Path | None = None) -> int:
    return save_linhas_tabela(df, "saldos_linhas", pasta)


def load_saldos_wide(pasta: Path | None = None):
    return load_linhas_tabela("saldos_linhas", pasta)


def save_balanco_wide(df, pasta: Path | None = None) -> int:
    return save_linhas_tabela(df, "balanco_linhas", pasta)


def load_balanco_wide(pasta: Path | None = None):
    return load_linhas_tabela("balanco_linhas", pasta)


# ===========================================================================
# API de compatibilidade wide / path-based (ex-Commons bridge)
# ---------------------------------------------------------------------------
# carregar_db / salvar_db / existe_dados / carregar_contas
# Leitura e escrita exclusivas em condominio.db.
# O "path" lógico (.../ReceitasN, .../Bancos) só identifica a tabela (stem)
# e a pasta de dados (parent).
# ===========================================================================


def existe_dados(caminho) -> bool:
    """True se a pasta (ou parent do path lógico) contém condominio.db."""
    p = Path(caminho)
    if (p.parent / "condominio.db").exists():
        return True
    if p.is_dir() and (p / "condominio.db").exists():
        return True
    return False


def validar_db_existe(caminho) -> bool:
    """Alias de existe_dados."""
    return existe_dados(caminho)


def criar_backup_db(origem, destino) -> bool:
    """Copia um ficheiro de dados (backup simples)."""
    try:
        import shutil
        shutil.copy2(origem, destino)
        return True
    except Exception as e:
        print(f"❌ Erro ao criar backup: {e}")
        return False

# ---------------------------------------------------------------------------
# Camada de dados 100% relacional (condominio.db)
# ---------------------------------------------------------------------------


# Tabelas cujo storage canónico é condominio.db (fase actual da migração)
_TABELAS_MOVIMENTOS = {"Bancos": "bancos", "Caixa": "caixa", "DPrazo": "dprazo"}
_TABELAS_RELACIONAIS_ONLY = set(_TABELAS_MOVIMENTOS) | {"Configs", "Condominos", "ReceitasN", "ReceitasE", "Despesas", "Juros", "Saldos", "Balanco"}


def _normalizar_nome_tabela(stem: str) -> str:
    """Unifica variantes (ex.: Balanço → Balanco)."""
    s = (stem or "").strip()
    key = s.casefold().replace("ç", "c").replace("ã", "a")
    if key in ("balanco", "balanço"):
        return "Balanco"
    if key.startswith("saldo"):
        return "Saldos"
    return s


def _pasta_dados_de(path: Path) -> Path:

    """Pasta de dados a partir de um path lógico (.../Bancos)."""
    path = Path(path)
    parent = path.parent
    if parent.name and parent != path:
        return parent
    return PASTA_CORRENTE


def _carregar_movimentos_relacional(table: str, pasta: Path):
    """Lê movimentos de condominio.db no formato legado (chaves MAIÚSCULAS)."""
    fonte = _TABELAS_MOVIMENTOS.get(table)
    if not fonte:
        return None
    try:
        from Database import movimentos as mov_repo, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows_rel = mov_repo(pasta).find(fonte=fonte)
        if not rows_rel:
            return [], ["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "SALDO", "OBSERVACAO"]
        out = []
        for r in rows_rel:
            out.append({
                "DATA": r["data"],
                "TIPO": r["tipo"] or "",
                # DEPOIS
                "CONTA": r["conta"] or "",              #"CONTA": r["conta_nome"] if "conta_nome" in r.keys() else "", (corrigido)
                "DESCRICAO": r["descricao"] or "",
                "VALOR": r["valor"],
                "SALDO": r["saldo"],
                "OBSERVACAO": r["observacao"] or "",
            })
        fields = ["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "SALDO", "OBSERVACAO"]
        return out, fields
    except Exception as e:
        print(f"  ℹ️  Leitura relacional {table}: {e}")
        return None


def _carregar_configs_relacional(pasta: Path):
    """Lê configs de condominio.db no formato legado."""
    try:
        from Database import configs as cfg_repo, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows_rel = cfg_repo(pasta).all()
        out = []
        for r in rows_rel:
            out.append({
                "CATEGORIA": r["categoria"],
                "CHAVE": r["chave"],
                "VALOR": r["valor"],
                "TIPO": r["tipo"] or "String",
                "DESCRICAO": r["descricao"] or "",
            })
        fields = ["CATEGORIA", "CHAVE", "VALOR", "TIPO", "DESCRICAO"]
        return out, fields
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Configs: {e}")
        return None


def _salvar_movimentos_relacional(df, table: str, pasta: Path) -> bool:
    """Grava movimentos em condominio.db."""
    fonte = _TABELAS_MOVIMENTOS.get(table)
    if not fonte:
        return False
    try:
        from Database import sync_movimentos_from_legacy_df
        n = sync_movimentos_from_legacy_df(df, fonte, pasta)
        print(f"  ✓ {n} movimentos gravados em condominio.db ({fonte})")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional {table}: {e}")
        return False


def _salvar_configs_relacional(df, pasta: Path) -> bool:
    """Grava configs APENAS em condominio.db."""
    try:
        from Database import configs as cfg_repo, create_schema
        create_schema(pasta)
        rows = []
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            rows.append(d)
        n = cfg_repo(pasta).replace_all(rows)
        print(f"  ✓ {n} configs gravadas em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Configs: {e}")
        return False


# _carregar_contas_relacional removida na V5 (tabela contas eliminada)


def _carregar_condominos_relacional(pasta: Path):
    """Lê condóminos de condominio.db no formato legado (NOME, CHECK, ...)."""
    try:
        from Database import condominos as condominos_repo, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows_rel = condominos_repo(pasta).all()
        out = []
        for r in rows_rel:
            out.append({
                "NOME": r["nome"] or "",
                "CHECK": bool(r["ativo"]),
                "MORADA": r["morada"] or "",
                "CPOSTAL": r["cpostal"] or "",
                "CIDADE": r["cidade"] or "",
                "TELEMOVEL": r["telemovel"] or "",
                "EMAIL": r["email"] or "",
                "FRACAO": r["fracao"] or "",
                "ANDAR": r["andar"] or "",
                "PERMILAGEM": r["permilagem"] if r["permilagem"] is not None else 0.0,
                "QUOTAN": r["quota_normal"] if r["quota_normal"] is not None else 0.0,
                "QUOTAE": r["quota_extra"] if r["quota_extra"] is not None else 0.0,
                "FOTO": r["foto"] or "",
                "ADMIN": bool(r["admin"]),
            })
        fields = ["NOME", "CHECK", "MORADA", "CPOSTAL", "CIDADE", "TELEMOVEL", "EMAIL",
                  "FRACAO", "ANDAR", "PERMILAGEM", "QUOTAN", "QUOTAE", "FOTO", "ADMIN"]
        return out, fields
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Condominos: {e}")
        return None


def _salvar_condominos_relacional(df, pasta: Path) -> bool:
    """Grava condóminos APENAS em condominio.db (upsert por fracção, preserva id/FKs)."""
    try:
        from Database import condominos as condominos_repo, create_schema, _to_float as _to_float_rel
        create_schema(pasta)
        repo = condominos_repo(pasta)
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            fracao = str(d.get("FRACAO") or "").strip()
            if not fracao:
                continue
            check_val = d.get("CHECK")
            admin_val = d.get("ADMIN")
            data = {
                "fracao": fracao,
                "nome": str(d.get("NOME") or "").strip(),
                "morada": str(d.get("MORADA") or "").strip(),
                "cpostal": str(d.get("CPOSTAL") or "").strip(),
                "cidade": str(d.get("CIDADE") or "").strip(),
                "telemovel": str(d.get("TELEMOVEL") or "").strip(),
                "email": str(d.get("EMAIL") or "").strip(),
                "andar": str(d.get("ANDAR") or "").strip(),
                "permilagem": _to_float_rel(d.get("PERMILAGEM", 0)),
                "quota_normal": _to_float_rel(d.get("QUOTAN", 0)),
                "quota_extra": _to_float_rel(d.get("QUOTAE", 0)),
                "foto": str(d.get("FOTO") or "").strip(),
                # CHECK/ADMIN podem chegar como bool, 1/0, ".T."/".F." ou "T"/"F"
                # consoante a origem (grelha da GUI ou bridge legado).
                "ativo": 1 if check_val in (True, 1, "1", ".T.", "T", "t", "True") else 0,
                "admin": 1 if admin_val in (True, 1, "1", ".T.", "T", "t", "True") else 0,
            }
            repo.upsert(data)
            n += 1
        print(f"  ✓ {n} condóminos gravados em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Condominos: {e}")
        import traceback; traceback.print_exc()
        return False


# _salvar_contas_relacional removida na V5 (tabela contas eliminada)


def _carregar_receitas_relacional(table: str, pasta: Path):
    tipo = "NORMAL" if table == "ReceitasN" else "EXTRA"
    try:
        from Database import load_receitas_wide, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows, fields = load_receitas_wide(tipo, pasta)
        return rows, fields
    except Exception as e:
        print(f"  ℹ️  Leitura relacional {table}: {e}")
        return None


def _salvar_receitas_relacional(df, table: str, pasta: Path) -> bool:
    tipo = "NORMAL" if table == "ReceitasN" else "EXTRA"
    try:
        from Database import save_receitas_wide, create_schema
        create_schema(pasta)
        n = save_receitas_wide(df, tipo, pasta)
        print(f"  ✓ {n} valores mensais ({tipo}) gravados em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional {table}: {e}")
        import traceback; traceback.print_exc()
        return False


def _carregar_despesas_relacional(pasta: Path):
    try:
        from Database import load_despesas_wide, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        return load_despesas_wide(pasta)
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Despesas: {e}")
        return None


def _salvar_despesas_relacional(df, pasta: Path) -> bool:
    try:
        from Database import save_despesas_wide, create_schema
        create_schema(pasta)
        n = save_despesas_wide(df, pasta)
        print(f"  ✓ {n} valores mensais de despesas gravados em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Despesas: {e}")
        import traceback; traceback.print_exc()
        return False


def _carregar_juros_relacional(pasta: Path):
    try:
        from Database import load_juros_wide, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        return load_juros_wide(pasta)
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Juros: {e}")
        return None


def _salvar_juros_relacional(df, pasta: Path) -> bool:
    try:
        from Database import save_juros_wide, create_schema
        create_schema(pasta)
        n = save_juros_wide(df, pasta)
        print(f"  ✓ {n} valores de juros gravados em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Juros: {e}")
        return False


def _carregar_saldos_relacional(pasta: Path):
    try:
        from Database import load_saldos_wide, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        return load_saldos_wide(pasta)
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Saldos: {e}")
        return None


def _salvar_saldos_relacional(df, pasta: Path) -> bool:
    try:
        from Database import save_saldos_wide, create_schema
        create_schema(pasta)
        n = save_saldos_wide(df, pasta)
        print(f"  ✓ {n} linhas de Saldos gravadas em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Saldos: {e}")
        import traceback; traceback.print_exc()
        return False


def _carregar_balanco_relacional(pasta: Path):
    try:
        from Database import load_balanco_wide, db_path, create_schema
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        return load_balanco_wide(pasta)
    except Exception as e:
        print(f"  ℹ️  Leitura relacional Balanco: {e}")
        return None


def _salvar_balanco_relacional(df, pasta: Path) -> bool:
    try:
        from Database import save_balanco_wide, create_schema
        create_schema(pasta)
        n = save_balanco_wide(df, pasta)
        print(f"  ✓ {n} linhas de Balanço gravadas em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita relacional Balanco: {e}")
        import traceback; traceback.print_exc()
        return False


def carregar_db(path):
    """
    Leitura exclusiva de condominio.db (API de compatibilidade).

    - Bancos / Caixa / DPrazo → condominio.db.movimentos
    - Configs → condominio.db.configs
    - Contas → condominio.db.contas
    - Condominos, ReceitasN/E, Despesas, Juros, Saldos, Balanco → tabelas relacionais

    O argumento `path` só serve para obter o nome lógico da tabela (stem)
    e a pasta de dados (parent). Apenas condominio.db é utilizado.

    Retorna: (lista_de_dicts_com_chaves_MAIUSCULAS, lista_de_campos)
    """
    path = Path(path)
    table = _normalizar_nome_tabela(path.stem)
    pasta = _pasta_dados_de(path)

    if table in _TABELAS_MOVIMENTOS:
        result = _carregar_movimentos_relacional(table, pasta)
        if result is not None:
            return result
    elif table == "Configs":
        result = _carregar_configs_relacional(pasta)
        if result is not None:
            return result
    # tabela Contas eliminada na V5
    elif table == "Condominos":
        result = _carregar_condominos_relacional(pasta)
        if result is not None:
            return result
    elif table in ("ReceitasN", "ReceitasE"):
        result = _carregar_receitas_relacional(table, pasta)
        if result is not None:
            return result
    elif table == "Despesas":
        result = _carregar_despesas_relacional(pasta)
        if result is not None:
            return result
    elif table == "Juros":
        result = _carregar_juros_relacional(pasta)
        if result is not None:
            return result
    elif table == "Saldos":
        result = _carregar_saldos_relacional(pasta)
        if result is not None:
            return result
    elif table == "Balanco":
        result = _carregar_balanco_relacional(pasta)
        if result is not None:
            return result
    else:
        print(f"  ⚠️ Tabela desconhecida para leitura: {table}")

    return [], []


def salvar_db(df, path, field_specs=None):
    """
    Escrita exclusiva em condominio.db (API de compatibilidade).

    - Bancos / Caixa / DPrazo → condominio.db.movimentos
    - Configs, Contas, Condominos, ReceitasN/E, Despesas, Juros, Saldos, Balanco
      → tabelas relacionais correspondentes

    O argumento `path` só serve para obter o nome lógico da tabela (stem)
    e a pasta de dados (parent). Apenas condominio.db é utilizado.
    `field_specs` é ignorado (mantido por compatibilidade de assinatura).
    """
    path = Path(path)
    table = _normalizar_nome_tabela(path.stem)
    pasta = _pasta_dados_de(path)

    if table in _TABELAS_MOVIMENTOS:
        return _salvar_movimentos_relacional(df, table, pasta)

    if table == "Configs":
        return _salvar_configs_relacional(df, pasta)

    if table == "Contas":
        return _salvar_contas_relacional(df, pasta)

    if table == "Condominos":
        return _salvar_condominos_relacional(df, pasta)

    if table in ("ReceitasN", "ReceitasE"):
        return _salvar_receitas_relacional(df, table, pasta)

    if table == "Despesas":
        return _salvar_despesas_relacional(df, pasta)

    if table == "Juros":
        return _salvar_juros_relacional(df, pasta)

    if table == "Saldos":
        return _salvar_saldos_relacional(df, pasta)

    if table == "Balanco":
        return _salvar_balanco_relacional(df, pasta)

    print(f"  ⚠️ Tabela desconhecida para escrita: {table}")
    return False



def carregar_contas(pasta_dados):
    """
    V5: contas vêm directamente da tabela regras (campo conta, distinto).
    Retorna: (lista_receitas, lista_despesas, todas_contas)
    """
    if isinstance(pasta_dados, str):
        pasta = Path(pasta_dados)
    else:
        pasta = Path(pasta_dados)

    receitas, despesas, todas = [], [], []
    try:
        repo = RegrasRepo(pasta)
        for r in repo.find_ativas():
            conta = str(r["conta"] or "").strip()
            classe = str(r["classe"] or "").strip().upper()
            if not conta or conta in todas:
                continue
            todas.append(conta)
            if classe == "RECEITA":
                receitas.append(conta)
            else:
                despesas.append(conta)
    except Exception as exc:
        print(f"⚠️ Erro ao carregar contas de regras: {exc}")
    return receitas, despesas, todas


# --- Aliases canónicos ---
load_table = carregar_db
save_table = salvar_db
has_data = existe_dados
