"""
Database.py – Camada de dados 100% SQLite relacional (sem qualquer dependência de DBF)

- Schema tipado, com PRIMARY KEYs, FOREIGN KEYs e índices
- Repositórios simples para CRUD e pesquisas
- API canónica SQLite (sem bridge DBF/path-based)
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

# Caminhos: BASE_DIR, PASTA_CORRENTE, PASTA_HISTORICO, DB_NAME, db_path
# são definidos em Commons.py e importados no final deste módulo
# (evita import circular Commons ↔ Database).


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
    # WAL quando o filesystem o suporta; senão DELETE (ex.: alguns mounts de rede)
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode and str(mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.Error:
        try:
            conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.Error:
            pass
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@contextmanager
def db_transaction(pasta: Path | None = None, *, row_factory: bool = True):
    """
    Context manager para uma transação explícita e partilhável.

    Uso típico no encerramento de ano (ou qualquer operação multi-passo):

        with db_transaction(pasta) as conn:
            save_xxx(..., conn=conn)
            guardar_movimentos_fonte(..., conn=conn)
            # commit automático no fim do bloco se não houver exceção
            # rollback automático se ocorrer qualquer exceção
    """
    path = db_path(pasta)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), detect_types=sqlite3.PARSE_DECLTYPES)
    if row_factory:
        conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode and str(mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.Error:
        try:
            conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.Error:
            pass
    try:
        conn.execute("BEGIN")
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
    -- quotas: tabela fracoes (quota_normal / quota_extra) — não aqui
    foto            TEXT,
    ativo           INTEGER NOT NULL DEFAULT 1,       -- 1 = recebe emails
    admin           INTEGER NOT NULL DEFAULT 0,
    cc_numero       TEXT,                             -- Cartão de Cidadão n.º (NIC + check + versão)
    cc_validade     TEXT,                             -- Data validade CC (dd-mm-yyyy)
    nif             TEXT,                             -- NIF (9 dígitos)
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT
);

-- ============================================================
--  Frações (estrutura + quotas mensais — fonte de verdade €)
-- ============================================================

CREATE TABLE IF NOT EXISTS fracoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fracao        TEXT    NOT NULL UNIQUE,
    andar         TEXT    NOT NULL,
    permilagem    REAL    NOT NULL,
    quota_normal  REAL    NOT NULL DEFAULT 0,
    quota_extra   REAL    NOT NULL DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now'))
);

-- ============================================================
--  Regras de classificação V5
--  Tabela única: absorve Configs.REGRA_* + COND_* + tabela contas
--  normal/extra preenchidos = legado regra de condómino (preferir fracoes)
--  normal/extra vazios      = regra geral (despesa/receita)
-- ============================================================

CREATE TABLE IF NOT EXISTS regras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prioridade  INTEGER NOT NULL DEFAULT 100,  -- menor = mais prioritário
    classe      TEXT    NOT NULL CHECK (classe IN ('RECEITA', 'DESPESA')),
    conta       TEXT    NOT NULL,              -- nome da conta contabilística (texto livre)
    pattern     TEXT    NOT NULL,              -- texto a procurar na descrição do CSV
    normal      REAL,                          -- legado (não é fonte de verdade das quotas)
    extra       REAL,                          -- legado
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
    """Cria tabelas em falta (CREATE IF NOT EXISTS). Não migra dados nem DROP de colunas.

    Alterações estruturais V2→V3 (quotas em fracoes, remover de condominos)
    fazem-se com o script ``migrar_2_v3.py``.
    """
    with get_connection(pasta, row_factory=False) as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_condominos_cc_columns(conn)


def _ensure_condominos_cc_columns(conn) -> None:
    """Adiciona cc_numero / cc_validade / nif se a tabela já existia sem elas."""
    try:
        existentes = {
            row[1] for row in conn.execute("PRAGMA table_info(condominos)").fetchall()
        }
    except Exception:
        return
    for col, tipo in (
        ("cc_numero", "TEXT"),
        ("cc_validade", "TEXT"),
        ("nif", "TEXT"),
    ):
        if col not in existentes:
            conn.execute(f"ALTER TABLE condominos ADD COLUMN {col} {tipo}")


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

def _normalizar_admin(val: Any) -> int:
    """Normaliza o campo admin: 1 = atual, -1 = cessante, 0 = outros."""
    if val is True or val in (1, "1", ".T.", "T", "t", "True", "true"):
        return 1
    if val in (-1, "-1"):
        return -1
    try:
        n = int(float(str(val).strip()))
        if n == 1:
            return 1
        if n == -1:
            return -1
    except (ValueError, TypeError):
        pass
    return 0

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

    # Colunas permitidas em INSERT/UPDATE (whitelist contra SQL injection por nomes)
    # quota_* não existem em condominos (fonte = fracoes)
    _ALLOWED_COLS = frozenset({
        "fracao", "andar", "nome", "morada", "cpostal", "cidade",
        "telemovel", "email", "permilagem",
        "foto", "ativo", "admin",
        "cc_numero", "cc_validade", "nif",
    })

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

    def _filter_cols(self, data: dict) -> dict:
        """Mantém apenas chaves conhecidas da tabela condominos."""
        return {k: v for k, v in data.items() if k in self._ALLOWED_COLS}

    def upsert(self, data: dict) -> int:
        """Insere ou actualiza por fracao. Devolve o id.

        ATENÇÃO: só é seguro quando `data["fracao"]` ainda corresponde ao
        condómino certo. Se a fracao de um condómino já existente estiver
        a ser alterada (ex.: estava vazia e passou a ter um valor), esta
        pesquisa por fracao já não encontra o registo antigo e cria-se um
        duplicado. Para editar um condómino já existente, usa
        `update_by_id`, que identifica o registo pelo `id` (estável),
        nunca pela fracao.
        """
        data = self._filter_cols(data)
        if "fracao" not in data:
            raise ValueError("upsert condominos: 'fracao' é obrigatório")
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM condominos WHERE fracao = ?", (data["fracao"],)
            ).fetchone()
            if existing:
                sets = ", ".join(f"{k} = ?" for k in data if k != "fracao")
                if not sets:
                    return existing["id"]
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

    def update_by_id(self, id_: int, data: dict) -> bool:
        """Actualiza um condómino já existente pelo `id` (estável),
        independentemente do valor actual ou novo de `fracao`. É o método
        correcto para gravar edições feitas no ecrã de Condóminos, onde o
        `id` de cada linha é conhecido desde o carregamento."""
        data = self._filter_cols(data)
        if not data:
            return False
        with self._conn() as conn:
            sets = ", ".join(f"{k} = ?" for k in data)
            vals = list(data.values()) + [id_]
            cur = conn.execute(
                f"UPDATE condominos SET {sets}, updated_at = datetime('now') WHERE id = ?",
                vals,
            )
            return cur.rowcount > 0

class FracoesRepo(BaseRepo):
    table = "fracoes"

    _CREATE = """CREATE TABLE IF NOT EXISTS fracoes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        fracao        TEXT    NOT NULL UNIQUE,
        andar         TEXT    NOT NULL,
        permilagem    REAL    NOT NULL,
        quota_normal  REAL    NOT NULL DEFAULT 0,
        quota_extra   REAL    NOT NULL DEFAULT 0,
        created_at    TEXT    DEFAULT (datetime('now'))
    )"""

    def all_ordered(self) -> list[sqlite3.Row]:
        """Todas as frações ordenadas por fração (com quotas se a coluna existir)."""
        with self._conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fracoes)").fetchall()}
            if "quota_normal" in cols:
                sql = (
                    "SELECT id, fracao, andar, permilagem, "
                    "COALESCE(quota_normal,0) AS quota_normal, "
                    "COALESCE(quota_extra,0) AS quota_extra "
                    "FROM fracoes ORDER BY fracao, id"
                )
            else:
                sql = (
                    "SELECT id, fracao, andar, permilagem FROM fracoes "
                    "ORDER BY fracao, id"
                )
            return conn.execute(sql).fetchall()

    def replace_all(self, rows: Sequence[dict]) -> int:
        """Substitui todas as frações (usado pela GUI de Configurações).

        Aceita chaves em minúsculas ou como na grelha (Fração/Andar/Permilagem).
        Preserva quota_normal/extra se vierem no dict; senão 0.
        Devolve o número de registos gravados.
        """
        with self._conn() as conn:
            conn.execute(self._CREATE)
            # garantir colunas em BD antiga ainda não migrada
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fracoes)").fetchall()}
            for col in ("quota_normal", "quota_extra"):
                if col not in cols:
                    try:
                        conn.execute(
                            f"ALTER TABLE fracoes ADD COLUMN {col} REAL NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
            conn.execute("DELETE FROM fracoes")
            vistas: set[str] = set()
            n = 0
            for r in rows:
                fracao = str(r.get("fracao") or r.get("Fração") or "").strip().upper()
                andar = str(r.get("andar") or r.get("Andar") or "").strip()
                if not fracao or not andar or fracao in vistas:
                    continue
                perm = r.get("permilagem")
                if perm is None:
                    perm = r.get("Permilagem")
                try:
                    perm = float(str(perm).replace(",", ".")) if perm not in (None, "") else 0.0
                except ValueError:
                    perm = 0.0
                qn = r.get("quota_normal", r.get("Quota Normal", r.get("QUOTAN", 0)))
                qe = r.get("quota_extra", r.get("Quota Extra", r.get("QUOTAE", 0)))
                try:
                    qn = float(str(qn).replace(",", ".")) if qn not in (None, "") else 0.0
                except ValueError:
                    qn = 0.0
                try:
                    qe = float(str(qe).replace(",", ".")) if qe not in (None, "") else 0.0
                except ValueError:
                    qe = 0.0
                conn.execute(
                    "INSERT INTO fracoes (fracao, andar, permilagem, quota_normal, quota_extra) "
                    "VALUES (?,?,?,?,?)",
                    (fracao, andar, perm, qn, qe),
                )
                vistas.add(fracao)
                n += 1
            return n

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

    _ALLOWED_COLS = frozenset({
        "prioridade", "classe", "conta", "pattern", "normal", "extra", "ativo",
    })

    def _filter_cols(self, data: dict) -> dict:
        return {k: v for k, v in data.items() if k in self._ALLOWED_COLS}

    def upsert(self, data: dict) -> int:
        """Insere ou actualiza por (pattern, normal, extra). Devolve o id."""
        data = self._filter_cols(data)
        if "pattern" not in data:
            raise ValueError("upsert regras: 'pattern' é obrigatório")
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
                if not sets:
                    return existing["id"]
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

    def replace_fonte(self, fonte: str, rows: Sequence[dict], conn=None) -> int:
        """Apaga todos os movimentos de uma fonte e insere os novos.
        Se `conn` for fornecido, usa essa conexão (não faz commit/rollback).
        """
        def _do(c):
            c.execute("DELETE FROM movimentos WHERE fonte = ?", (fonte,))
            if not rows:
                return 0
            cur = c.executemany(
                """
                INSERT INTO movimentos
                    (data, descricao, valor, saldo, tipo, conta, observacao, origem, fonte)
                VALUES
                    (:data, :descricao, :valor, :saldo, :tipo, :conta, :observacao, :origem, :fonte)
                """,
                rows,
            )
            return cur.rowcount
        if conn is not None:
            return _do(conn)
        with self._conn() as c:
            return _do(c)

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
                  tipo: str = "String", descricao: str = "", conn=None) -> None:
        """Grava um valor de configuração.
        Se `conn` for fornecido, usa essa conexão (não faz commit/rollback).
        """
        def _do(c):
            c.execute(
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
        if conn is not None:
            _do(conn)
        else:
            with self._conn() as c:
                _do(c)

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

def fracoes(pasta=None) -> FracoesRepo:
    return FracoesRepo(pasta)

def regras(pasta=None) -> RegrasRepo:
    return RegrasRepo(pasta)

def movimentos(pasta=None) -> MovimentosRepo:
    return MovimentosRepo(pasta)

def configs(pasta=None) -> ConfigsRepo:
    return ConfigsRepo(pasta)

# ---------------------------------------------------------------------------
# API canónica — única interface pública de dados
#
# Contrato:
#   - Argumento principal = pasta de dados (Path | str), NÃO path lógico DBF
#   SQL / repos por baixo — sem bridge DBF/path-based
# ---------------------------------------------------------------------------

_STEMS_LOGICOS = frozenset({
    "configs", "condominio.db", "bancos", "caixa", "dprazo", "condominos",
    "receitasn", "receitase", "despesas", "juros", "saldos", "balanco", "contas",
})

def resolver_pasta(path_or_pasta) -> Path:
    """
    Normaliza qualquer caminho/nome para a pasta de dados que contém condominio.db.

    Aceita: None, "corrente", Path("corrente"), .../corrente/Configs, .../condominio.db
    """
    if path_or_pasta is None:
        return PASTA_CORRENTE
    p = Path(path_or_pasta)
    if p.name.lower() in _STEMS_LOGICOS:
        p = p.parent
    if not p.is_absolute():
        candidate = BASE_DIR / p
        if candidate.exists() or (candidate / DB_NAME).exists():
            return candidate
        # nome lógico de pasta (ex. corrente) mesmo ainda sem ficheiros
        if len(p.parts) == 1:
            return candidate
        return p
    return p

def fracao_de_conta_quota(conta: str) -> str:
    """Remove prefixo 'Quota … - ' da conta; devolve o nome de fracção/andar."""
    import re
    conta = (conta or "").strip()
    base = re.sub(
        r"^(Quota\s*(extra|total)?\s*-\s*)",
        "",
        conta,
        flags=re.IGNORECASE,
    ).strip()
    return base or conta

def is_regra_condomino(
    classe: str | None,
    conta: str | None,
    normal,
    extra,
) -> bool:
    """
    Critério único: regra de quota de condómino.
    RECEITA + normal preenchido + (extra preenchido OU conta sugere quota/fracção).
    """
    if normal is None:
        return False
    if (classe or "").strip().upper() != "RECEITA":
        return False
    conta_l = (conta or "").lower()
    return (
        extra is not None
        or "quota" in conta_l
        or "frac" in conta_l
    )

def quotas_em_vigor(fracao: str, data: str | None = None, pasta=None) -> dict:
    """
    Quotas da fração (fonte: tabela ``fracoes``).

    O parâmetro ``data`` é ignorado (histórico fica em historico/YYYY).
    Aceita letra (A) ou rótulo de andar.
    """
    pasta = resolver_pasta(pasta)
    vazio = {
        "QUOTA_NORMAL": 0.0, "QUOTA_EXTRA": 0.0, "QUOTA_TOTAL": 0.0,
        "FRACAO": (fracao or "").strip().upper(), "VIGENCIA_DE": None,
    }
    if not db_path(pasta).exists():
        return vazio

    fr = (fracao or "").strip().upper()
    if not fr:
        return vazio

    letra_para_label, label_para_letra = _mapas_fracoes_db(pasta)
    if fr not in letra_para_label:
        for lab, let in label_para_letra.items():
            if lab.upper() == fr:
                fr = let
                break

    try:
        with get_connection(pasta) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fracoes)").fetchall()}
            if "quota_normal" not in cols:
                return vazio
            row = conn.execute(
                """
                SELECT fracao, quota_normal, quota_extra
                  FROM fracoes
                 WHERE UPPER(fracao) = ?
                 LIMIT 1
                """,
                (fr,),
            ).fetchone()
    except Exception as exc:
        print(f"⚠️ quotas_em_vigor({fr!r}): {exc}")
        return vazio

    if row is None:
        return vazio
    try:
        qn = float(row["quota_normal"] or 0)
    except (TypeError, ValueError):
        qn = 0.0
    try:
        qe = float(row["quota_extra"] or 0)
    except (TypeError, ValueError):
        qe = 0.0
    return {
        "QUOTA_NORMAL": qn,
        "QUOTA_EXTRA": qe,
        "QUOTA_TOTAL": round(qn + qe, 2),
        "FRACAO": (row["fracao"] or fr).strip().upper(),
        "VIGENCIA_DE": None,
    }


def guardar_quota_fracao(
    fracao: str,
    quota_normal: float,
    quota_extra: float,
    *,
    vigencia_de: str | None = None,
    origem: str = "manual",
    pasta=None,
) -> bool:
    """
    Actualiza quota_normal / quota_extra na tabela ``fracoes``.
    ``vigencia_de`` e ``origem`` são ignorados (API estável para a UI).
    """
    pasta = resolver_pasta(pasta)
    fr = (fracao or "").strip().upper()
    if not fr:
        return False
    try:
        with get_connection(pasta, row_factory=False) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fracoes)").fetchall()}
            if "quota_normal" not in cols:
                print("⚠️ fracoes sem colunas de quota — execute migrar_2_v3.py")
                return False
            cur = conn.execute(
                """
                UPDATE fracoes
                   SET quota_normal = ?, quota_extra = ?
                 WHERE UPPER(fracao) = ?
                """,
                (float(quota_normal or 0), float(quota_extra or 0), fr),
            )
            if cur.rowcount == 0:
                print(f"⚠️ guardar_quota_fracao: fração {fr!r} não existe em fracoes")
                return False
        return True
    except Exception as exc:
        print(f"⚠️ guardar_quota_fracao({fr!r}): {exc}")
        return False


def quotas_por_fracao(pasta=None) -> dict:
    """
    Quotas por rótulo de fracção/andar (chave = andar quando existe).

    Fonte: tabela ``fracoes`` (quota_normal / quota_extra).
    """
    pasta = resolver_pasta(pasta)
    if not db_path(pasta).exists():
        return {}

    out: dict = {}
    letra_para_label, _ = _mapas_fracoes_db(pasta)
    try:
        with get_connection(pasta) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(fracoes)").fetchall()}
            if "quota_normal" not in cols:
                return {}
            rows = conn.execute(
                """
                SELECT fracao, andar, quota_normal, quota_extra
                  FROM fracoes
                 ORDER BY fracao
                """
            ).fetchall()
    except Exception as exc:
        print(f"⚠️ quotas_por_fracao: {exc}")
        return {}

    for r in rows:
        fr = (r["fracao"] or "").strip().upper()
        andar = (r["andar"] or "").strip()
        try:
            qn = float(r["quota_normal"] or 0)
        except (TypeError, ValueError):
            qn = 0.0
        try:
            qe = float(r["quota_extra"] or 0)
        except (TypeError, ValueError):
            qe = 0.0
        vals = {
            "QUOTA_NORMAL": qn,
            "QUOTA_EXTRA": qe,
            "QUOTA_TOTAL": round(qn + qe, 2),
        }
        # Chave canónica = rótulo de andar (como na V2).
        # NÃO indexar pela letra (A, B, …): match_fracao faz substring e
        # "A" casa dentro de "QUOTA", atribuindo todos os pagamentos à fração A.
        if andar:
            out[andar] = vals
        elif fr:
            out[fr] = vals
        elif fr in letra_para_label:
            out[letra_para_label[fr]] = vals
    return out


def condominos_para_categorizacao(pasta=None) -> list[dict]:
    """
    Lista para categorização de extractos (Bancos).

    - **Match (nome no extracto):** padrões da tabela ``regras`` (como antes)
      + nome da ficha ``condominos``.
    - **Valores de quota:** tabela ``fracoes`` via ``quotas_em_vigor``
      (nunca ``regras.normal/extra`` nem colunas de condominos).

    Cada item: PREFIXO, NOME, NOME_ALTERNATIVO, VALOR_NORMAL, VALOR_EXTRA,
               VALOR_TOTAL, CONTA
    """
    pasta = resolver_pasta(pasta)
    if not db_path(pasta).exists():
        return []

    create_schema(pasta)

    try:
        from Commons import remover_acentos
    except ImportError:
        def remover_acentos(t):  # type: ignore
            return t

    def _norm(s: str) -> str:
        s = remover_acentos((s or "").strip()).upper()
        return " ".join(s.split())

    # ── 1. Condóminos + quotas em vigor (fracoes) ─────────────────────
    por_fracao: dict[str, dict] = {}
    por_andar: dict[str, dict] = {}
    try:
        with get_connection(pasta) as conn:
            rows_co = conn.execute(
                """
                SELECT fracao, andar, nome
                FROM condominos
                ORDER BY fracao, id
                """
            ).fetchall()
    except Exception as exc:
        print(f"⚠️ condominos_para_categorizacao (condominos): {exc}")
        rows_co = []

    letra_para_label, label_para_letra = _mapas_fracoes_db(pasta)

    for r in rows_co:
        fracao = (r["fracao"] or "").strip().upper()
        andar = (r["andar"] or "").strip()
        if not andar and fracao in letra_para_label:
            andar = letra_para_label[fracao]
        nome = (r["nome"] or "").strip()
        q = quotas_em_vigor(fracao, pasta=pasta) if fracao else {
            "QUOTA_NORMAL": 0.0, "QUOTA_EXTRA": 0.0,
        }
        qn = float(q.get("QUOTA_NORMAL") or 0)
        qe = float(q.get("QUOTA_EXTRA") or 0)
        if qn <= 0 and qe <= 0:
            print(
                f"  ⚠️ Condómino '{nome or '?'}' (fração {fracao or '?'}) "
                f"sem quotas em fracoes — não será usado na categorização"
            )
            continue

        info = {
            "fracao": fracao,
            "andar": andar,
            "nome": nome,
            "qn": qn,
            "qe": qe,
        }
        if fracao and fracao not in por_fracao:
            por_fracao[fracao] = info
        if andar and andar not in por_andar:
            por_andar[andar] = info
        and_key = _norm(andar).replace(" ", "")
        if and_key:
            por_andar.setdefault(and_key, info)

    if not por_fracao and not por_andar:
        print("  ⚠️ Nenhuma fração com quotas em fracoes")
        return []

    def _resolver_info(conta: str, pattern: str) -> dict | None:
        """Liga conta/padrão da regra à ficha condominos (por fracção/andar)."""
        conta = (conta or "").strip()
        label = fracao_de_conta_quota(conta)
        if label and label in por_andar:
            return por_andar[label]
        if label:
            label_key = _norm_fracao_label(label)
            label_key_compact = label_key.replace(" ", "")
            letra2 = None
            for lbl_norm, letra in label_para_letra.items():
                if lbl_norm == label_key or lbl_norm.replace(" ", "") == label_key_compact:
                    letra2 = letra
                    break
            if letra2 and letra2 in por_fracao:
                return por_fracao[letra2]
        if conta.upper() in por_fracao:
            return por_fracao[conta.upper()]
        if conta in por_andar:
            return por_andar[conta]
        ck = _norm(conta).replace(" ", "")
        if ck in por_andar:
            return por_andar[ck]
        p = _norm(pattern)
        if p:
            for info in por_fracao.values():
                n = _norm(info["nome"])
                if n and (p in n or n in p):
                    return info
        return None

    # ── 2. Match pelos padrões de regras (como antes batia certo) ───────────
    result: list[dict] = []
    vistos_padrao: set[str] = set()
    try:
        with get_connection(pasta) as conn:
            rows_reg = conn.execute(
                """
                SELECT pattern, conta, classe, normal, extra
                FROM regras
                WHERE ativo = 1
                ORDER BY prioridade, id
                """
            ).fetchall()
    except Exception as exc:
        print(f"⚠️ condominos_para_categorizacao (regras): {exc}")
        rows_reg = []

    for r in rows_reg:
        pattern = (r["pattern"] or "").strip()
        conta = (r["conta"] or "").strip()
        if not pattern:
            continue
        if not is_regra_condomino(r["classe"], conta, r["normal"], r["extra"]):
            continue

        info = _resolver_info(conta, pattern)
        if not info:
            print(
                f"  ⚠️ Regra '{pattern}' / conta '{conta}' sem ficha em "
                f"condominos com quotas — ignorada"
            )
            continue

        nome_match = _norm(pattern)
        if not nome_match or nome_match in vistos_padrao:
            continue
        vistos_padrao.add(nome_match)

        qn, qe = info["qn"], info["qe"]
        conta_label = info["andar"] or fracao_de_conta_quota(conta) or conta
        result.append({
            "PREFIXO": info["fracao"] or conta_label,
            "NOME": nome_match,
            "NOME_ALTERNATIVO": _norm(info["nome"]) if info["nome"] else "",
            "VALOR_NORMAL": qn,
            "VALOR_EXTRA": qe,
            "VALOR_TOTAL": round(qn + qe, 2),
            "CONTA": conta_label,
        })
        print(
            f"  ✓ Match '{pattern}' → {conta_label}: "
            f"Normal={qn:.2f} Extra={qe:.2f} (tabela condominos)"
        )

    # ── 3. Condóminos sem regra: match pelo nome da ficha ───────────────────
    for info in por_fracao.values():
        nome_match = _norm(info["nome"])
        if not nome_match or nome_match in vistos_padrao:
            continue
        vistos_padrao.add(nome_match)
        qn, qe = info["qn"], info["qe"]
        conta_label = info["andar"] or info["fracao"]
        result.append({
            "PREFIXO": info["fracao"] or conta_label,
            "NOME": nome_match,
            "NOME_ALTERNATIVO": "",
            "VALOR_NORMAL": qn,
            "VALOR_EXTRA": qe,
            "VALOR_TOTAL": round(qn + qe, 2),
            "CONTA": conta_label,
        })
        print(
            f"  ✓ Match nome ficha '{info['nome']}' → {conta_label}: "
            f"Normal={qn:.2f} Extra={qe:.2f}"
        )

    result.sort(key=lambda x: x.get("NOME", ""))
    return result

def regras_condominos_lista(pasta=None) -> list[dict]:
    """
    Lista para categorização Bancos.

    Match: padrões ``regras`` (+ nome da ficha).
    Valores: tabela ``condominos`` (quota_normal / quota_extra).
    """
    return condominos_para_categorizacao(pasta)

def db_existe(pasta=None) -> bool:
    """True se condominio.db existe na pasta de dados."""
    return db_path(resolver_pasta(pasta)).exists()

def carregar_condominos(pasta=None) -> list[dict]:
    """Lista de condóminos (chaves MAIÚSCULAS legado)."""
    pasta = resolver_pasta(pasta)
    result = _carregar_condominos_relacional(pasta)
    if result is None:
        return []
    rows, _ = result
    return rows

def guardar_condominos(rows_or_df, pasta=None) -> bool:
    """Grava lista/DataFrame de condóminos."""
    pasta = resolver_pasta(pasta)
    if pd is None:
        return False
    if hasattr(rows_or_df, "iterrows"):
        df = rows_or_df
    else:
        df = pd.DataFrame(list(rows_or_df or []), dtype=object)
    return bool(_salvar_condominos_relacional(df, pasta))

def carregar_configs(pasta=None) -> list[dict]:
    """Lista de configs (CATEGORIA, CHAVE, VALOR, TIPO, DESCRICAO)."""
    pasta = resolver_pasta(pasta)
    result = _carregar_configs_relacional(pasta)
    if result is None:
        return []
    rows, _ = result
    return rows

def guardar_configs(rows_or_df, pasta=None) -> bool:
    """Substitui configs a partir de lista/DataFrame."""
    pasta = resolver_pasta(pasta)
    if pd is None:
        return False
    if hasattr(rows_or_df, "iterrows"):
        df = rows_or_df
    else:
        df = pd.DataFrame(list(rows_or_df or []), dtype=object)
    return bool(_salvar_configs_relacional(df, pasta))

def movimentos_dataframe(pasta=None, fontes=None):
    """
    Movimentos de condominio.db como DataFrame (colunas legado MAIÚSCULAS).

    Args:
        pasta: pasta de dados (ou path lógico — resolvido por resolver_pasta)
        fontes: None = todas; ou iterável de fontes
                (aceita 'bancos'/'Bancos', 'caixa', 'dprazo', …)

    Returns:
        pandas.DataFrame com colunas:
        DATA, TIPO, CONTA, DESCRICAO, VALOR, OBSERVACAO, FONTE
        (vazio se não houver dados ou pandas indisponível)
    """
    if pd is None:
        raise ImportError("pandas é necessário para movimentos_dataframe")

    pasta = resolver_pasta(pasta)
    if not db_path(pasta).exists():
        return pd.DataFrame(
            columns=["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "OBSERVACAO", "FONTE"]
        )

    fontes_norm = None
    if fontes is not None:
        fontes_norm = [str(f).strip().lower() for f in fontes if str(f).strip()]

    try:
        with get_connection(pasta) as conn:
            if fontes_norm:
                placeholders = ",".join("?" * len(fontes_norm))
                sql = f"""
                    SELECT data, tipo, conta, descricao, valor, observacao, fonte
                    FROM movimentos
                    WHERE lower(fonte) IN ({placeholders})
                    ORDER BY data, id
                """
                rows = conn.execute(sql, fontes_norm).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT data, tipo, conta, descricao, valor, observacao, fonte
                    FROM movimentos
                    ORDER BY data, id
                    """
                ).fetchall()
    except Exception as exc:
        print(f"⚠️ movimentos_dataframe: {exc}")
        return pd.DataFrame(
            columns=["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "OBSERVACAO", "FONTE"]
        )

    if not rows:
        return pd.DataFrame(
            columns=["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "OBSERVACAO", "FONTE"]
        )

    records = [
        {
            "DATA": r["data"],
            "TIPO": r["tipo"] or "",
            "CONTA": r["conta"] or "",
            "DESCRICAO": r["descricao"] or "",
            "VALOR": r["valor"],
            "OBSERVACAO": r["observacao"] or "",
            "FONTE": r["fonte"] or "",
        }
        for r in rows
    ]
    df = pd.DataFrame(records, dtype=object)
    # Dedup legado (mesmo critério Receitas/Despesas)
    antes = len(df)
    df = df.drop_duplicates(subset=["DATA", "CONTA", "VALOR"], keep="first").reset_index(drop=True)
    if antes > len(df):
        print(f"  🧹 Removidos {antes - len(df)} movimentos duplicados")
    return df

def aglutinar_movimentos(
    bancos_db_path=None,
    caixa_db_path=None,
    dprazo_db_path=None,
    pasta=None,
    fontes=None,
    *,
    verbose: bool = True,
    incluir_fonte: bool = False,
):
    """
    Aglutina movimentos de várias fontes num único DataFrame (API canónica).

    Substitui as cópias locais que existiam em Receitas.py e Despesas.py.

    Resolução da pasta (por ordem de prioridade):
        1. ``pasta``
        2. ``bancos_db_path`` / ``caixa_db_path`` / ``dprazo_db_path`` (paths legados)
        3. pasta corrente

    Fontes:
        - Se ``fontes`` for dado, usa-se tal qual.
        - Senão: bancos + caixa; inclui dprazo se ``dprazo_db_path`` for truthy.

    Returns:
        DataFrame com colunas DATA, TIPO, CONTA, DESCRICAO, VALOR, OBSERVACAO
        (+ FONTE se ``incluir_fonte=True``). DataFrame vazio se não houver dados.
    """
    if pasta is not None:
        pasta_res = resolver_pasta(pasta)
    elif bancos_db_path is not None:
        pasta_res = resolver_pasta(bancos_db_path)
    elif caixa_db_path is not None:
        pasta_res = resolver_pasta(caixa_db_path)
    elif dprazo_db_path is not None:
        pasta_res = resolver_pasta(dprazo_db_path)
    else:
        pasta_res = resolver_pasta(None)

    if fontes is not None:
        fontes_res = list(fontes)
    else:
        fontes_res = ["bancos", "caixa"]
        if dprazo_db_path:
            fontes_res.append("dprazo")

    if verbose:
        print(f"\n{'='*80}")
        print(f"🔄 AGLUTINAÇÃO DE MOVIMENTOS (SQL / {'+'.join(fontes_res)})")
        print(f"{'='*80}")

    df = movimentos_dataframe(pasta_res, fontes=fontes_res)

    if df.empty:
        if verbose:
            print("  ❌ ERRO: Nenhum movimento encontrado")
            print(f"{'='*80}\n")
        return df

    if verbose and "FONTE" in df.columns:
        for fonte, n in df["FONTE"].astype(str).str.lower().value_counts().items():
            print(f"  ✅ {fonte}: {n} registos")
        print(f"\n  📊 Total aglutinado: {len(df)} movimentos únicos")
        print(f"{'='*80}\n")

    cols = ["DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "OBSERVACAO"]
    if incluir_fonte:
        cols.append("FONTE")
    return df[[c for c in cols if c in df.columns]].copy()


_FONTE_POR_STEM = {
    "bancos": "bancos",
    "caixa": "caixa",
    "dprazo": "dprazo",
}

def fonte_de_path(path_or_fonte) -> str:
    """Normaliza 'Bancos' / '.../Caixa' / 'dprazo' → fonte SQL."""
    if path_or_fonte is None:
        return "bancos"
    s = str(path_or_fonte).strip()
    name = Path(s).name
    key = name.casefold()
    if key in _FONTE_POR_STEM:
        return _FONTE_POR_STEM[key]
    # path completo .../Bancos
    stem = Path(s).stem.casefold()
    return _FONTE_POR_STEM.get(stem, key)

def carregar_movimentos_fonte(pasta=None, fonte="bancos") -> list[dict]:
    """
    Movimentos de uma fonte como lista de dicts (chaves MAIÚSCULAS).

    Returns:
        [{DATA, TIPO, CONTA, DESCRICAO, VALOR, SALDO, OBSERVACAO}, ...]
    """
    pasta = resolver_pasta(pasta)
    fonte = fonte_de_path(fonte)
    if not db_path(pasta).exists():
        return []
    try:
        create_schema(pasta)
        rows_rel = MovimentosRepo(pasta).find(fonte=fonte)
    except Exception as exc:
        print(f"⚠️ carregar_movimentos_fonte({fonte}): {exc}")
        return []
    out = []
    for r in rows_rel:
        out.append({
            "DATA": r["data"],
            "TIPO": r["tipo"] or "",
            "CONTA": r["conta"] or "",
            "DESCRICAO": r["descricao"] or "",
            "VALOR": r["valor"],
            "SALDO": r["saldo"],
            "OBSERVACAO": r["observacao"] or "",
        })
    return out

def guardar_movimentos_fonte(rows_or_df, pasta=None, fonte="bancos", conn=None) -> bool:
    """
    Substitui todos os movimentos de uma fonte.

    rows_or_df: list[dict] com chaves MAIÚSCULAS ou DataFrame equivalente.
    Se `conn` for fornecido, usa essa conexão (transação externa).
    """
    pasta = resolver_pasta(pasta)
    fonte = fonte_de_path(fonte)
    try:
        if pd is not None and hasattr(rows_or_df, "iterrows"):
            df = rows_or_df
        else:
            df = pd.DataFrame(list(rows_or_df or []), dtype=object)
        n = sync_movimentos_from_legacy_df(df, fonte, pasta, conn=conn)
        print(f"  ✓ {n} movimentos gravados ({fonte}) em {pasta}")
        return True
    except Exception as exc:
        print(f"⚠️ guardar_movimentos_fonte({fonte}): {exc}")
        import traceback
        traceback.print_exc()
        return False

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
  COALESCE(f.quota_normal, 0) AS quota_normal,
  COALESCE(f.quota_extra, 0) AS quota_extra,
  r.ano,
  COALESCE(SUM(CASE WHEN r.tipo_quota='NORMAL' THEN r.valor END), 0) AS pago_normal,
  COALESCE(SUM(CASE WHEN r.tipo_quota='EXTRA' THEN r.valor END), 0) AS pago_extra,
  COALESCE(SUM(r.valor), 0) AS pago_total
FROM condominos co
LEFT JOIN fracoes f ON UPPER(f.fracao) = UPPER(co.fracao)
LEFT JOIN receitas_mensais r ON r.condominio_id = co.id
GROUP BY co.id, co.fracao, co.nome, f.quota_normal, f.quota_extra, r.ano;
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

def sync_movimentos_from_legacy_df(df, fonte: str, pasta: Path | None = None, conn=None) -> int:
    """
    Sincroniza um DataFrame no formato legado (DATA, DESCRICAO, VALOR, SALDO, TIPO, CONTA, OBSERVACAO)
    para a tabela movimentos de condominio.db (substitui todos os da fonte).
    V5: conta é TEXT directo, sem FK para contas.
    Se `conn` for fornecido, usa essa conexão (não reconstrói FTS dentro da transação externa).
    """
    # Usa símbolos já definidos neste módulo (evita auto-import circular)
    pasta = pasta or PASTA_CORRENTE
    if conn is None:
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

    n = mov_repo.replace_fonte(fonte, rows, conn=conn)
    # Rebuild FTS apenas quando não estamos dentro de uma transação externa
    if conn is not None:
        return n
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

MESES_COLS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
MESES_KEYS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

def _norm_fracao_label(label: str) -> str:
    s = " ".join(str(label or "").upper().replace("º", "º").replace("°", "º").split())
    return s

def mapas_fracoes(pasta=None) -> tuple[dict[str, str], dict[str, str]]:
    """
    API pública: mapas letra↔andar a partir da tabela ``fracoes``.

    Returns:
        (letra_para_label, label_norm_para_letra)
        ex.: ({"A": "R/c Esq.", ...}, {"r/c esq.": "A", ...})
    """
    return _mapas_fracoes_db(pasta)


def _mapas_fracoes_db(pasta=None) -> tuple[dict[str, str], dict[str, str]]:
    """
    Mapas fracao(letra)↔andar(rótulo), construídos a partir da tabela
    'fracoes' — fonte de verdade única, editável em Configurações.

    Substitui o antigo mapeamento fixo no código: uma fracção nova, uma
    letra reatribuída ou um rótulo renomeado ficam automaticamente
    reflectidos em toda a aplicação, sem precisar de tocar em código.

    Returns:
        (letra_para_label, label_norm_para_letra)
    """
    pasta = resolver_pasta(pasta)
    letra_para_label: dict[str, str] = {}
    label_para_letra: dict[str, str] = {}
    try:
        for r in fracoes(pasta).all_ordered():
            letra = str(r["fracao"] or "").strip().upper()
            andar = str(r["andar"] or "").strip()
            if not letra:
                continue
            letra_para_label[letra] = andar or letra
            if andar:
                label_para_letra[_norm_fracao_label(andar)] = letra
    except Exception as exc:
        print(f"⚠️ _mapas_fracoes_db: {exc}")
    return letra_para_label, label_para_letra

def _letra_from_label(label: str, letra_para_label: dict, label_para_letra: dict) -> str | None:
    """
    Converte um rótulo de fracção (ex. 'R/c Esq.') na letra correspondente
    (ex. 'A'), usando os mapas já carregados da tabela 'fracoes'
    (ver ``_mapas_fracoes_db``).
    """
    key = _norm_fracao_label(label)
    if key in label_para_letra:
        return label_para_letra[key]
    # correspondência aproximada: ignora espaços e o símbolo de grau (º/°),
    # para apanhar variantes como '1 Esq.' ou '1° Esq.' vs '1º Esq.'
    key_compact = key.replace(" ", "").replace("º", "")
    for lbl_norm, letra in label_para_letra.items():
        lbl_compact = lbl_norm.replace(" ", "").replace("º", "")
        if lbl_compact and (lbl_compact in key_compact or key_compact in lbl_compact):
            return letra
    # o próprio valor já é uma letra de fracção existente?
    if len(key) == 1 and key in letra_para_label:
        return key
    return None

def ano_exercicio(pasta=None) -> int:
    """Ano do exercício (Configs GERAL/ANO_EXERCICIO). API pública."""
    return _ano_exercicio(resolver_pasta(pasta))

def _ano_exercicio(pasta: Path | None = None) -> int:
    """Ano do exercício a partir de Configs; fallback = ano civil actual."""
    try:
        v = ConfigsRepo(pasta).get_value("GERAL", "ANO_EXERCICIO", None)
        if v is None or str(v).strip() == "":
            return datetime.date.today().year
        return int(float(str(v).replace(",", ".")))
    except Exception:
        return datetime.date.today().year

def save_receitas_wide(df, tipo_quota: str, pasta: Path | None = None, ano: int | None = None, conn=None) -> int:
    """Grava DataFrame largo ReceitasN/E em receitas_mensais + receitas_resumo.
    Se `conn` for fornecido, usa essa conexão (não faz commit/rollback).
    """
    pasta = resolver_pasta(pasta)
    ano = ano or _ano_exercicio(pasta)
    tipo_quota = tipo_quota.upper()
    if tipo_quota not in ("NORMAL", "EXTRA"):
        raise ValueError(tipo_quota)

    letra_para_label, label_para_letra = _mapas_fracoes_db(pasta)

    def _do(c):
        condo_map = {r["fracao"]: r["id"] for r in c.execute("SELECT id, fracao FROM condominos")}
        c.execute(
            "DELETE FROM receitas_mensais WHERE ano = ? AND tipo_quota = ?",
            (ano, tipo_quota),
        )
        c.execute(
            "DELETE FROM receitas_resumo WHERE ano = ? AND tipo_quota = ?",
            (ano, tipo_quota),
        )
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            label = str(d.get("FRACCAO") or "").strip()
            if not label or label.upper() == "TOTAIS":
                continue
            letra = _letra_from_label(label, letra_para_label, label_para_letra)
            if not letra or letra not in condo_map:
                print(f"  ⚠️ Fracção não mapeada: {label!r}")
                continue
            cid = condo_map[letra]
            for col, mes in zip(MESES_COLS, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO receitas_mensais
                       (condominio_id, ano, mes, tipo_quota, valor)
                       VALUES (?,?,?,?,?)""",
                    (cid, ano, mes, tipo_quota, val),
                )
                n += 1
            c.execute(
                """INSERT OR REPLACE INTO receitas_resumo
                   (condominio_id, ano, tipo_quota, fracao_label, saldo_ant, saldo)
                   VALUES (?,?,?,?,?,?)""",
                (cid, ano, tipo_quota, label,
                 _to_float(d.get("SALDO_ANT", 0)), _to_float(d.get("SALDO", 0))),
            )
        return n

    if conn is not None:
        return _do(conn)
    create_schema(pasta)
    ensure_views_and_fts(pasta)
    with get_connection(pasta) as c:
        return _do(c)

def load_receitas_wide(tipo_quota: str, pasta: Path | None = None, ano: int | None = None):
    """Devolve (rows_legado, fields) no formato ReceitasN/E."""
    pasta = resolver_pasta(pasta)
    ensure_views_and_fts(pasta)
    ano = ano or _ano_exercicio(pasta)
    tipo_quota = tipo_quota.upper()
    fields = ["FRACCAO", "SALDO_ANT"] + MESES_COLS + ["TOTAL", "SALDO"]
    letra_para_label, _ = _mapas_fracoes_db(pasta)

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
                     else letra_para_label.get(letra, letra))
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

def save_despesas_wide(df, pasta: Path | None = None, ano: int | None = None, conn=None) -> int:
    """Grava DataFrame largo Despesas em despesas_mensais.
    Se `conn` for fornecido, usa essa conexão (não faz commit/rollback).
    """
    pasta = resolver_pasta(pasta)
    ano = ano or _ano_exercicio(pasta)
    def _do(c):
        c.execute("DELETE FROM despesas_mensais WHERE ano = ?", (ano,))
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
                c.execute(
                    """INSERT OR REPLACE INTO despesas_mensais
                       (conta, ano, mes, valor) VALUES (?,?,?,?)""",
                    (nome, ano, mes, val),
                )
                n += 1
        return n
    if conn is not None:
        return _do(conn)
    create_schema(pasta)
    ensure_views_and_fts(pasta)
    with get_connection(pasta) as c:
        return _do(c)

def load_despesas_wide(pasta: Path | None = None, ano: int | None = None):
    """Devolve (rows_legado, fields) no formato Despesas."""
    pasta = resolver_pasta(pasta)
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

def save_juros_wide(df, pasta: Path | None = None, ano: int | None = None, conn=None) -> int:
    """Grava DataFrame largo Juros. Se `conn` for fornecido, usa essa conexão."""
    pasta = resolver_pasta(pasta)
    ano = ano or _ano_exercicio(pasta)
    def _do(c):
        c.execute("DELETE FROM juros WHERE ano = ?", (ano,))
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            for col, mes in zip(MESES_COLS, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                c.execute(
                    "INSERT OR REPLACE INTO juros (ano, mes, valor) VALUES (?,?,?)",
                    (ano, mes, val),
                )
                n += 1
        return n
    if conn is not None:
        return _do(conn)
    create_schema(pasta)
    with get_connection(pasta) as c:
        return _do(c)

def load_juros_wide(pasta: Path | None = None, ano: int | None = None):
    pasta = resolver_pasta(pasta)
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

def save_linhas_tabela(df, tabela_linhas: str, pasta: Path | None = None, conn=None) -> int:
    """Grava DataFrame com CONTA/TIPO/VALOR numa tabela de linhas ordenadas.
    Se `conn` for fornecido, usa essa conexão (não faz commit/rollback).
    """
    pasta = resolver_pasta(pasta)
    def _do(c):
        c.execute(f"DELETE FROM {tabela_linhas}")
        n = 0
        for ordem, (_, row) in enumerate(df.iterrows()):
            d = {str(k).upper(): row[k] for k in df.columns}
            conta = d.get("CONTA")
            tipo = d.get("TIPO")
            valor = _to_float(d.get("VALOR", 0))
            conta_s = "" if conta is None else str(conta)
            tipo_s = "" if tipo is None else str(tipo)
            c.execute(
                f"INSERT INTO {tabela_linhas} (ordem, conta, tipo, valor) VALUES (?,?,?,?)",
                (ordem, conta_s, tipo_s, valor),
            )
            n += 1
        return n
    if conn is not None:
        return _do(conn)
    create_schema(pasta)
    with get_connection(pasta) as c:
        return _do(c)

def load_linhas_tabela(tabela_linhas: str, pasta: Path | None = None):
    """Devolve (rows legado CONTA/TIPO/VALOR, fields)."""
    pasta = resolver_pasta(pasta)
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

def save_saldos_wide(df, pasta: Path | None = None, conn=None) -> int:
    return save_linhas_tabela(df, "saldos_linhas", pasta, conn=conn)

def load_saldos_wide(pasta: Path | None = None):
    return load_linhas_tabela("saldos_linhas", pasta)

def save_balanco_wide(df, pasta: Path | None = None, conn=None) -> int:
    return save_linhas_tabela(df, "balanco_linhas", pasta, conn=conn)

def load_balanco_wide(pasta: Path | None = None):
    return load_linhas_tabela("balanco_linhas", pasta)

# ===========================================================================
# Utilitários de pasta / backup
# ===========================================================================

def existe_dados(caminho=None) -> bool:
    """True se a pasta (ou parent do path) contém condominio.db."""
    return db_existe(caminho)

def validar_db_existe(caminho=None) -> bool:
    """Alias de db_existe / existe_dados."""
    return db_existe(caminho)

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
# Implementação interna: configs e condóminos (usada pela API canónica)
# ---------------------------------------------------------------------------

def _carregar_configs_relacional(pasta: Path):
    """Lê configs de condominio.db (chaves MAIÚSCULAS)."""
    try:
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows_rel = ConfigsRepo(pasta).all()
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
        print(f"  ℹ️  Leitura configs: {e}")
        return None

def _salvar_configs_relacional(df, pasta: Path) -> bool:
    """Grava configs em condominio.db."""
    try:
        create_schema(pasta)
        rows = []
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            rows.append(d)
        n = ConfigsRepo(pasta).replace_all(rows)
        print(f"  ✓ {n} configs gravadas em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita configs: {e}")
        return False

def _carregar_condominos_relacional(pasta: Path):
    """Lê condóminos de condominio.db (chaves MAIÚSCULAS)."""
    try:
        if not db_path(pasta).exists():
            return None
        create_schema(pasta)
        rows_rel = CondominosRepo(pasta).all()
        out = []
        for r in rows_rel:
            fracao = r["fracao"] or ""
            q = quotas_em_vigor(fracao, pasta=pasta) if fracao else {
                "QUOTA_NORMAL": 0.0, "QUOTA_EXTRA": 0.0,
            }
            out.append({
                "ID": r["id"],
                "NOME": r["nome"] or "",
                "CHECK": bool(r["ativo"]),
                "MORADA": r["morada"] or "",
                "CPOSTAL": r["cpostal"] or "",
                "CIDADE": r["cidade"] or "",
                "TELEMOVEL": r["telemovel"] or "",
                "EMAIL": r["email"] or "",
                "FRACAO": fracao,
                "ANDAR": r["andar"] or "",
                "PERMILAGEM": r["permilagem"] if r["permilagem"] is not None else 0.0,
                # Só leitura: valores vêm de fracoes (não de condominos)
                "QUOTAN": float(q.get("QUOTA_NORMAL") or 0),
                "QUOTAE": float(q.get("QUOTA_EXTRA") or 0),
                "FOTO": r["foto"] or "",
                # admin: 1 = atual, -1 = cessante (ex-admin), 0 = restante
                "ADMIN": int(r["admin"] or 0),
                "CC_NUMERO": str(r["cc_numero"] or "") if "cc_numero" in r.keys() else "",
                "CC_VALIDADE": str(r["cc_validade"] or "") if "cc_validade" in r.keys() else "",
                "NIF": str(r["nif"] or "") if "nif" in r.keys() else "",
            })
        fields = [
            "ID", "NOME", "CHECK", "MORADA", "CPOSTAL", "CIDADE", "TELEMOVEL", "EMAIL",
            "FRACAO", "ANDAR", "PERMILAGEM", "QUOTAN", "QUOTAE", "FOTO", "ADMIN",
            "CC_NUMERO", "CC_VALIDADE", "NIF",
        ]
        return out, fields
    except Exception as e:
        print(f"  ℹ️  Leitura condóminos: {e}")
        return None

def _salvar_condominos_relacional(df, pasta: Path) -> bool:
    """Grava condóminos em condominio.db.

    Regista cada linha pelo `id` (quando já veio da BD, via `update_by_id`
    — estável mesmo que a `fracao` tenha mudado/estivesse vazia). Só usa
    `upsert` (procura por fracao) para linhas genuinamente novas, sem `id`
    — ex.: condóminos criados no ecrã com "Adicionar Condómino".
    """
    try:
        create_schema(pasta)
        repo = CondominosRepo(pasta)
        n = 0
        for _, row in df.iterrows():
            d = {str(k).upper(): row[k] for k in df.columns}
            fracao = str(d.get("FRACAO") or "").strip()
            id_val = d.get("ID")
            tem_id = id_val not in (None, "", "None")
            if not fracao and not tem_id:
                # Linha nova sem fracao e sem id: nada a identificar nem a gravar
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
                "permilagem": _to_float(d.get("PERMILAGEM", 0)),
                # quotas NÃO se gravam em condominos (fonte = fracoes)
                "foto": str(d.get("FOTO") or "").strip(),
                "ativo": 1 if check_val in (True, 1, "1", ".T.", "T", "t", "True") else 0,
                # admin: 1 = atual, -1 = cessante, 0 = outros
                "admin": _normalizar_admin(admin_val),
                "cc_numero": str(d.get("CC_NUMERO") or "").strip(),
                "cc_validade": str(d.get("CC_VALIDADE") or "").strip(),
                "nif": str(d.get("NIF") or "").strip(),
            }
            if tem_id:
                repo.update_by_id(int(id_val), data)
            else:
                if not fracao:
                    continue
                repo.upsert(data)
            n += 1
        print(f"  ✓ {n} condóminos gravados em condominio.db")
        return True
    except Exception as e:
        print(f"  ✗ Escrita condóminos: {e}")
        import traceback
        traceback.print_exc()
        return False

def carregar_contas(pasta_dados):
    """
    Contas distintas a partir da tabela regras.
    Retorna: (lista_receitas, lista_despesas, todas_contas)
    """
    pasta = resolver_pasta(pasta_dados)
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

# ---------------------------------------------------------------------------
# Caminhos (definidos em Commons.py — import no fim para evitar ciclo)
# ---------------------------------------------------------------------------
from Commons import BASE_DIR, PASTA_CORRENTE, PASTA_HISTORICO, DB_NAME, db_path  # noqa: E402

# API canónica pública:
#   resolver_pasta, db_existe, existe_dados, ano_exercicio,
#   quotas_por_fracao, regras_condominos_lista,
#   movimentos_dataframe, aglutinar_movimentos,
#   carregar/guardar_movimentos_fonte,
#   carregar/guardar_condominos, carregar/guardar_configs,
#   load/save_*_wide, carregar_contas, repos (MovimentosRepo, …)
