#!/usr/bin/env python3
"""
migrar_2_v3.py — Migração estrutural V2 → V3 (quotas nas frações)

Altera a base de dados **V2** (schema antigo):
  1. Adiciona ``quota_normal`` e ``quota_extra`` à tabela ``fracoes``
  2. Copia os valores de ``condominos.quota_*`` → ``fracoes`` (match por letra)
  3. Remove ``quota_normal`` e ``quota_extra`` de ``condominos``
  4. Remove a tabela ``quotas_fracao`` se existir (experiência anterior)
  5. Recria a view ``v_quotas_por_condomino``

Uso:
  python migrar_2_v3.py
  python migrar_2_v3.py caminho/para/condominio.db
  python migrar_2_v3.py corrente          # pasta de dados

Por defeito: corrente/condominio.db junto a este script.
Faz backup automático: condominio.db.bak_v2_antes_v3
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "corrente" / "condominio.db"


def _resolver_db(arg: str | None) -> Path:
    if not arg:
        return DEFAULT_DB
    p = Path(arg)
    if p.is_dir():
        cand = p / "condominio.db"
        if cand.is_file():
            return cand
        raise SystemExit(f"Não encontrei condominio.db em {p}")
    if p.is_file():
        return p
    # pasta lógica relativa ao projecto
    cand = ROOT / arg / "condominio.db"
    if cand.is_file():
        return cand
    raise SystemExit(f"BD não encontrada: {arg}")


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrar(db_path: Path) -> None:
    if not db_path.is_file():
        raise SystemExit(f"Ficheiro inexistente: {db_path}")

    bak = db_path.with_suffix(db_path.suffix + ".bak_v2_antes_v3")
    if not bak.exists():
        shutil.copy2(db_path, bak)
        print(f"  ✓ Backup: {bak.name}")
    else:
        print(f"  ℹ️  Backup já existia: {bak.name}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # ── 1. Colunas de quota em fracoes ────────────────────────────────
        fcols = _cols(conn, "fracoes")
        for col in ("quota_normal", "quota_extra"):
            if col not in fcols:
                conn.execute(
                    f"ALTER TABLE fracoes ADD COLUMN {col} REAL NOT NULL DEFAULT 0"
                )
                print(f"  ✓ fracoes: adicionada coluna {col}")
            else:
                print(f"  ℹ️  fracoes.{col} já existe")

        # ── 2. Copiar de condominos → fracoes ─────────────────────────────
        ccols = _cols(conn, "condominos")
        if "quota_normal" in ccols and "quota_extra" in ccols:
            rows = conn.execute(
                """
                SELECT fracao, quota_normal, quota_extra
                  FROM condominos
                 WHERE fracao IS NOT NULL AND TRIM(fracao) != ''
                """
            ).fetchall()
            n = 0
            for r in rows:
                fr = (r["fracao"] or "").strip().upper()
                if not fr:
                    continue
                qn = float(r["quota_normal"] or 0)
                qe = float(r["quota_extra"] or 0)
                cur = conn.execute(
                    """
                    UPDATE fracoes
                       SET quota_normal = ?, quota_extra = ?
                     WHERE UPPER(fracao) = ?
                    """,
                    (qn, qe, fr),
                )
                if cur.rowcount:
                    n += 1
                    print(f"    {fr}: N={qn:.2f}  E={qe:.2f}")
                else:
                    print(f"  ⚠ Fração {fr} em condominos sem linha em fracoes — ignorada")
            print(f"  ✓ Copiados valores para {n} fração(ões)")
        else:
            print("  ℹ️  condominos já sem quota_* — nada a copiar")

        # ── 3. Remover quota_* de condominos ──────────────────────────────
        ccols = _cols(conn, "condominos")
        if "quota_normal" in ccols or "quota_extra" in ccols:
            try:
                conn.execute("DROP VIEW IF EXISTS v_quotas_por_condomino")
            except Exception:
                pass
            for col in ("quota_normal", "quota_extra"):
                if col in ccols:
                    try:
                        conn.execute(f"ALTER TABLE condominos DROP COLUMN {col}")
                        print(f"  ✓ condominos: removida coluna {col}")
                    except Exception as exc:
                        print(f"  ✗ DROP condominos.{col}: {exc}")
        else:
            print("  ℹ️  condominos já sem colunas de quota")

        # ── 4. Remover quotas_fracao se existir ───────────────────────────
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "quotas_fracao" in tables:
            conn.execute("DROP TABLE quotas_fracao")
            print("  ✓ tabela quotas_fracao removida")

        # ── 5. View actualizada ───────────────────────────────────────────
        conn.execute("DROP VIEW IF EXISTS v_quotas_por_condomino")
        conn.execute(
            """
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
            GROUP BY co.id, co.fracao, co.nome, f.quota_normal, f.quota_extra, r.ano
            """
        )
        print("  ✓ view v_quotas_por_condomino recriada")

        conn.commit()
        print(f"\n✅ Migração V2→V3 concluída: {db_path}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    db = _resolver_db(argv[1] if len(argv) > 1 else None)
    print(f"A migrar: {db}")
    migrar(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
