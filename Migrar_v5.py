#!/usr/bin/env python3
"""
migrar_v5.py
============
Migração one-shot: base de dados V4 → V5

O que faz:
  1. Cria backup automático de condominio.db antes de tocar em nada
  2. Cria a nova tabela 'regras' (V5)
  3. Migra regras_classificacao → regras  (resolvendo conta via contas)
  4. Migra Configs.COND_* → regras        (condóminos com normal/extra)
  5. Migra despesas_mensais: conta_id → conta TEXT
  6. Migra movimentos: conta_id → conta TEXT
  7. Remove REGRA_* e COND_* de Configs
  8. Remove tabelas obsoletas: regras_classificacao, contas
  9. Valida e imprime relatório final

O que NÃO faz:
  - Não toca em condominos, receitas_mensais, receitas_resumo, juros,
    saldos_linhas, balanco_linhas, configs (excepto limpeza de CLASSIFICACAO)

Uso:
  python migrar_v5.py                      # usa ./corrente/condominio.db
  python migrar_v5.py caminho/para/pasta   # pasta com condominio.db
"""

import sqlite3
import shutil
import sys
from datetime import datetime
from pathlib import Path


def main():
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "corrente"
    db    = pasta / "condominio.db"

    if not db.exists():
        sys.exit(f"❌ DB não encontrada: {db}")

    # ── Backup ────────────────────────────────────────────────────────────────
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = pasta / f"condominio_V4_backup_{ts}.db"
    shutil.copy2(db, backup)
    print(f"\n{'='*65}")
    print(f"  MIGRAÇÃO V4 → V5")
    print(f"  DB:     {db}")
    print(f"  Backup: {backup.name}")
    print(f"{'='*65}\n")

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")   # desligar FKs para migração

    try:
        with conn:
            _criar_tabela_regras(conn)
            n_gerais    = _migrar_regras_gerais(conn)
            n_cond      = _migrar_regras_condominos(conn)
            n_desp      = _migrar_despesas_mensais(conn)
            n_mov       = _migrar_movimentos(conn)
            _limpar_configs(conn)
            _remover_tabelas_obsoletas(conn)
            _validar(conn, n_gerais, n_cond)

        print("\n✅  Migração V5 concluída com sucesso.\n")

    except Exception as e:
        print(f"\n❌  Erro — rollback total: {e}")
        import traceback; traceback.print_exc()
        print(f"\n  O backup está em: {backup}")
        sys.exit(1)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────

def _criar_tabela_regras(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regras (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            prioridade  INTEGER NOT NULL DEFAULT 100,
            classe      TEXT    NOT NULL CHECK (classe IN ('RECEITA','DESPESA')),
            conta       TEXT    NOT NULL,
            pattern     TEXT    NOT NULL,
            normal      REAL,
            extra       REAL,
            ativo       INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    DEFAULT (datetime('now')),
            UNIQUE (pattern, normal, extra)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_regras_prioridade ON regras (prioridade)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_regras_pattern    ON regras (pattern)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_regras_ativo      ON regras (ativo)")
    print("  ✓ Tabela 'regras' criada")


def _migrar_regras_gerais(conn) -> int:
    """Migra regras_classificacao → regras (regras gerais sem condóminos)."""
    # Verificar se a tabela existe
    existe = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='regras_classificacao'"
    ).fetchone()
    if not existe:
        print("  ─ regras_classificacao não existe — nada a migrar")
        return 0

    rows = conn.execute("""
        SELECT r.pattern, r.prioridade, r.classe, r.valor_especifico,
               c.nome AS conta_nome
        FROM regras_classificacao r
        LEFT JOIN contas c ON c.id = r.conta_id
        WHERE r.ativo = 1
        ORDER BY r.prioridade
    """).fetchall()

    n = 0
    for r in rows:
        conta   = r["conta_nome"] or r["pattern"]
        classe  = r["classe"] or "DESPESA"
        pattern = r["pattern"]
        prio    = r["prioridade"] or 100
        # valor_especifico mapeia para normal (regras gerais sem condómino)
        normal  = r["valor_especifico"]

        conn.execute("""
            INSERT OR IGNORE INTO regras (prioridade, classe, conta, pattern, normal)
            VALUES (?,?,?,?,?)
        """, (prio, classe, conta, pattern, normal))
        if conn.execute("SELECT changes()").fetchone()[0]:
            n += 1
            v = f" (normal={normal})" if normal is not None else ""
            print(f"  ✓ [GERAL] prio={prio:3d} | {conta:28s} | '{pattern}'{v}")

    print(f"\n  → {n} regras gerais migradas\n")
    return n


def _migrar_regras_condominos(conn) -> int:
    """Migra Configs.COND_* → regras (regras de condóminos com normal/extra)."""
    rows = conn.execute("""
        SELECT chave, valor FROM configs
        WHERE categoria='CLASSIFICACAO' AND chave LIKE 'COND_%'
        ORDER BY chave
    """).fetchall()

    if not rows:
        print("  ─ Sem COND_* em Configs — nada a migrar")
        return 0

    # Agrupar por prefixo (ex: COND_A → {NOME, NORMAL, EXTRA, TOTAL})
    condos: dict[str, dict] = {}
    for r in rows:
        chave = r["chave"]       # ex: COND_A_NOME
        valor = r["valor"] or ""
        partes = chave.split("_")  # ['COND', 'A', 'NOME']
        if len(partes) < 3:
            continue
        prefixo = "_".join(partes[:2])   # COND_A
        campo   = "_".join(partes[2:])   # NOME | NORMAL | EXTRA | TOTAL | PATHERN
        condos.setdefault(prefixo, {})[campo] = valor

    n = 0
    prio = 10  # condóminos têm prioridade alta
    for prefixo, dados in sorted(condos.items()):
        nome    = dados.get("NOME", "").strip()
        pattern = (dados.get("PATHERN") or dados.get("PATTERN") or nome).strip()
        normal_s = dados.get("NORMAL", "").strip()
        extra_s  = dados.get("EXTRA",  "").strip()

        if not pattern:
            print(f"  ⚠️  {prefixo}: sem pattern — ignorado")
            continue

        normal = float(normal_s.replace(",", ".")) if normal_s else None
        extra  = float(extra_s.replace(",", "."))  if extra_s  else None

        # Conta = prefixo da fracção legível  ex: "Quota - R/c Esq."
        # obtém da tabela condominos se possível
        fracao = prefixo.replace("COND_", "")   # "A", "B", etc.
        row_c  = conn.execute(
            "SELECT andar FROM condominos WHERE fracao=?", (fracao,)
        ).fetchone()
        andar = row_c["andar"] if row_c else fracao
        conta = f"Quota - {andar}"

        conn.execute("""
            INSERT OR IGNORE INTO regras
                (prioridade, classe, conta, pattern, normal, extra)
            VALUES (?,?,?,?,?,?)
        """, (prio, "RECEITA", conta, pattern, normal, extra))
        if conn.execute("SELECT changes()").fetchone()[0]:
            n += 1
            print(f"  ✓ [COND]  prio={prio:3d} | {conta:28s} | '{pattern}'"
                  f" normal={normal} extra={extra}")
            prio += 10

    print(f"\n  → {n} regras de condóminos migradas\n")
    return n


def _migrar_despesas_mensais(conn) -> int:
    """despesas_mensais: conta_id → conta TEXT (in-place via tabela temp)."""
    existe = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='despesas_mensais'"
    ).fetchone()
    if not existe:
        print("  ─ despesas_mensais não existe")
        return 0

    # Verificar se já tem coluna conta (já migrada)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(despesas_mensais)")]
    if "conta" in cols and "conta_id" not in cols:
        print("  ─ despesas_mensais já migrada")
        return 0

    rows = conn.execute("""
        SELECT d.id, d.ano, d.mes, d.valor,
               c.nome AS conta_nome
        FROM despesas_mensais d
        LEFT JOIN contas c ON c.id = d.conta_id
    """).fetchall()

    for v in ("v_despesas_pivot", "v_receitas_pivot",
               "v_movimentos", "v_quotas_por_condomino", "v_saldos_por_fonte"):
        conn.execute(f"DROP VIEW IF EXISTS {v}")
    conn.execute("DROP TABLE IF EXISTS despesas_mensais_old")
    conn.execute("ALTER TABLE despesas_mensais RENAME TO despesas_mensais_old")
    conn.execute("""
        CREATE TABLE despesas_mensais (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            conta TEXT    NOT NULL,
            ano   INTEGER NOT NULL,
            mes   INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
            valor REAL    NOT NULL DEFAULT 0,
            UNIQUE (conta, ano, mes)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_desp_ano_mes ON despesas_mensais (ano, mes)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_desp_conta   ON despesas_mensais (conta)")

    n = 0
    for r in rows:
        conta = r["conta_nome"] or "Desconhecida"
        conn.execute(
            "INSERT OR REPLACE INTO despesas_mensais (conta, ano, mes, valor) VALUES (?,?,?,?)",
            (conta, r["ano"], r["mes"], r["valor"])
        )
        n += 1

    conn.execute("DROP TABLE despesas_mensais_old")
    print(f"  ✓ despesas_mensais migrada: {n} linhas (conta_id → conta TEXT)")
    return n


def _migrar_movimentos(conn) -> int:
    """movimentos: conta_id INTEGER → conta TEXT (in-place via tabela temp)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(movimentos)")]
    if "conta" in cols and "conta_id" not in cols:
        print("  ─ movimentos já migrada")
        return 0

    rows = conn.execute("""
        SELECT m.id, m.data, m.descricao, m.valor, m.saldo,
               m.tipo, m.observacao, m.origem, m.fonte,
               c.nome AS conta_nome
        FROM movimentos m
        LEFT JOIN contas c ON c.id = m.conta_id
    """).fetchall()

    conn.execute("DROP TABLE IF EXISTS movimentos_old")

    # Remover views que dependem de movimentos antes de renomear
    for v in ("v_movimentos", "v_saldos_por_fonte", "v_despesas_pivot",
               "v_receitas_pivot", "v_quotas_por_condomino"):
        conn.execute(f"DROP VIEW IF EXISTS {v}")

    # Remover FTS antes de renomear (caso exista)
    conn.execute("DROP TABLE IF EXISTS movimentos_fts")
    conn.execute("DROP TABLE IF EXISTS movimentos_fts_config")
    conn.execute("DROP TABLE IF EXISTS movimentos_fts_data")
    conn.execute("DROP TABLE IF EXISTS movimentos_fts_docsize")
    conn.execute("DROP TABLE IF EXISTS movimentos_fts_idx")

    conn.execute("ALTER TABLE movimentos RENAME TO movimentos_old")
    conn.execute("""
        CREATE TABLE movimentos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            data        TEXT    NOT NULL,
            descricao   TEXT    NOT NULL,
            valor       REAL    NOT NULL,
            saldo       REAL,
            tipo        TEXT    CHECK (tipo IN ('RECEITA','DESPESA') OR tipo IS NULL),
            conta       TEXT,
            observacao  TEXT,
            origem      TEXT    NOT NULL DEFAULT 'manual',
            fonte       TEXT    NOT NULL CHECK (fonte IN ('bancos','caixa','dprazo')),
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_data      ON movimentos (data)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_conta     ON movimentos (conta)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_fonte     ON movimentos (fonte)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_tipo      ON movimentos (tipo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_descricao ON movimentos (descricao)")

    n = 0
    for r in rows:
        conta = r["conta_nome"] or None
        conn.execute("""
            INSERT INTO movimentos
                (id, data, descricao, valor, saldo, tipo, conta,
                 observacao, origem, fonte)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (r["id"], r["data"], r["descricao"], r["valor"], r["saldo"],
              r["tipo"], conta, r["observacao"], r["origem"], r["fonte"]))
        n += 1

    conn.execute("DROP TABLE movimentos_old")

    # Recriar FTS
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS movimentos_fts USING fts5(
            descricao,
            content='movimentos',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    conn.execute("INSERT INTO movimentos_fts(movimentos_fts) VALUES ('delete-all')")
    conn.execute("INSERT INTO movimentos_fts(rowid, descricao) SELECT id, descricao FROM movimentos")

    print(f"  ✓ movimentos migrada: {n} linhas (conta_id → conta TEXT)")
    return n


def _limpar_configs(conn):
    """Remove REGRA_* e COND_* de Configs.CLASSIFICACAO."""
    cur = conn.execute("""
        DELETE FROM configs
        WHERE categoria='CLASSIFICACAO'
          AND (chave LIKE 'REGRA_%' OR chave LIKE 'COND_%')
    """)
    print(f"  ✓ Configs: {cur.rowcount} entradas REGRA_*/COND_* removidas")


def _remover_tabelas_obsoletas(conn):
    """Remove regras_classificacao e contas."""
    conn.execute("DROP TABLE IF EXISTS regras_classificacao")
    conn.execute("DROP TABLE IF EXISTS contas")
    print("  ✓ Tabelas obsoletas removidas: regras_classificacao, contas")


def _validar(conn, n_gerais, n_cond):
    print(f"\n{'─'*55}")
    n_regras = conn.execute("SELECT COUNT(*) FROM regras WHERE ativo=1").fetchone()[0]
    n_mov    = conn.execute("SELECT COUNT(*) FROM movimentos").fetchone()[0]
    n_desp   = conn.execute("SELECT COUNT(*) FROM despesas_mensais").fetchone()[0]
    n_cfg    = conn.execute(
        "SELECT COUNT(*) FROM configs WHERE categoria='CLASSIFICACAO'"
    ).fetchone()[0]
    tem_contas = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='contas'"
    ).fetchone()
    tem_rc = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='regras_classificacao'"
    ).fetchone()

    print(f"  Regras activas:         {n_regras}  ({n_gerais} gerais + {n_cond} condóminos)")
    print(f"  Movimentos:             {n_mov}")
    print(f"  Despesas mensais:       {n_desp}")
    print(f"  Configs CLASSIFICACAO:  {n_cfg}  (deve ser 0 após limpeza)")
    print(f"  Tabela 'contas':        {'❌ ainda existe!' if tem_contas else '✅ removida'}")
    print(f"  Tabela 'regras_class.': {'❌ ainda existe!' if tem_rc    else '✅ removida'}")

    print(f"\n  Regras na DB:")
    for r in conn.execute("SELECT prioridade, classe, conta, pattern, normal, extra FROM regras WHERE ativo=1 ORDER BY prioridade"):
        v = f" N={r['normal']}" if r['normal'] is not None else ""
        v += f" E={r['extra']}" if r['extra'] is not None else ""
        print(f"    prio={r['prioridade']:3d} | {r['classe']:7s} | {r['conta']:28s} | '{r['pattern']}'{v}")


if __name__ == "__main__":
    main()
