#!/usr/bin/env python3
"""
import_regras.py
Importa regras.xlsx para a tabela `regras` de condominio.db.

Uso:
  python import_regras.py [caminho/para/condominio.db] [caminho/para/regras.xlsx]

Se omitidos:
  - DB  → ./corrente/condominio.db  (ou pasta do script / corrente)
  - XLSX → regras.xlsx ao lado do script
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    print("❌ pandas é necessário: pip install pandas openpyxl")
    sys.exit(1)


def find_default_db() -> Path:
    """Procura condominio.db em locais habituais."""
    candidates = [
        Path.cwd() / "corrente" / "condominio.db",
        Path.cwd() / "condominio.db",
        Path(__file__).resolve().parent / "corrente" / "condominio.db",
        Path(__file__).resolve().parent.parent / "corrente" / "condominio.db",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

def find_default_xlsx() -> Path:
    """Procura regras.xlsx em locais habituais."""
    candidates = [
        Path.cwd() / "corrente" / "regras.xlsx",
        Path.cwd() / "regras.xlsx",
        Path(__file__).resolve().parent / "corrente" / "cregras.xlsx",
        Path(__file__).resolve().parent.parent / "attachments" / "regras.xlsx",
        Path(__file__).resolve().parent.parent / "corrente" / "regras.xlsx",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

#def find_default_xlsx() -> Path:
#    candidates = [
#        Path.cwd() / "regras.xlsx",
#        Path(__file__).resolve().parent / "regras.xlsx",
#        Path(__file__).resolve().parent.parent / "attachments" / "regras.xlsx",
#        Path("/home/workdir/attachments/regras.xlsx"),
#    ]
#    for c in candidates:
#        if c.exists():
#            return c
#    return candidates[0]


def _to_float_or_none(val) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _to_int(val, default: int = 100) -> int:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return int(float(str(val).replace(",", ".")))
    except (ValueError, TypeError):
        return default


def import_regras(db_path: Path, xlsx_path: Path, *, limpar: bool = True) -> int:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Ficheiro Excel não encontrado: {xlsx_path}")

    df = pd.read_excel(xlsx_path, engine="openpyxl")
    colmap = {}
    for c in df.columns:
        key = str(c).strip().upper()
        if key in ("PRIORIDADE", "PRIO"):
            colmap[c] = "prioridade"
        elif key in ("CLASSE",):
            colmap[c] = "classe"
        elif key in ("CONTA",):
            colmap[c] = "conta"
        elif key in ("PATTERN", "PATHERN", "PADRAO", "PADRÃO"):
            colmap[c] = "pattern"
        elif key in ("NORMAL",):
            colmap[c] = "normal"
        elif key in ("EXTRA",):
            colmap[c] = "extra"
    df = df.rename(columns=colmap)

    required = {"prioridade", "classe", "conta", "pattern"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colunas em falta no Excel: {missing}. Colunas: {list(df.columns)}")

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inseridas = 0
    ignoradas = 0

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regras (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                prioridade  INTEGER NOT NULL DEFAULT 100,
                classe      TEXT    NOT NULL CHECK (classe IN ('RECEITA', 'DESPESA')),
                conta       TEXT    NOT NULL,
                pattern     TEXT    NOT NULL,
                normal      REAL,
                extra       REAL,
                ativo       INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE (pattern, normal, extra)
            )
        """)

        if limpar:
            n_del = conn.execute("DELETE FROM regras").rowcount
            print(f"🗑  Apagadas {n_del} regra(s) existentes.")

        for i, row in df.iterrows():
            pattern = str(row.get("pattern") or "").strip()
            conta = str(row.get("conta") or "").strip()
            classe = str(row.get("classe") or "DESPESA").strip().upper()
            if not pattern or not conta:
                print(f"  ⚠ Linha {i+2}: pattern ou conta vazios — ignorada")
                ignoradas += 1
                continue
            if classe not in ("RECEITA", "DESPESA"):
                classe = "DESPESA"

            prio = _to_int(row.get("prioridade"), 100)
            normal = _to_float_or_none(row.get("normal") if "normal" in df.columns else None)
            extra = _to_float_or_none(row.get("extra") if "extra" in df.columns else None)

            try:
                conn.execute(
                    """
                    INSERT INTO regras
                        (prioridade, classe, conta, pattern, normal, extra, ativo, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (prio, classe, conta, pattern, normal, extra, now),
                )
                inseridas += 1
                n_str = f" normal={normal}" if normal is not None else ""
                e_str = f" extra={extra}" if extra is not None else ""
                print(f"  ✓ [{prio:3d}] {classe:7s} | {conta:25s} | {pattern}{n_str}{e_str}")
            except sqlite3.IntegrityError as e:
                print(f"  ⚠ Linha {i+2} ({pattern}): {e} — ignorada")
                ignoradas += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"\n✅ {inseridas} regra(s) inserida(s), {ignoradas} ignorada(s).")
    print(f"   DB: {db_path.resolve()}")
    return inseridas


def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else find_default_db()
    xlsx = Path(sys.argv[2]) if len(sys.argv) > 2 else find_default_xlsx()

    print(f"📂 Excel : {xlsx}")
    print(f"📂 DB    : {db}")
    print("-" * 60)

    n = import_regras(db, xlsx, limpar=True)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) AS n FROM regras").fetchone()["n"]
    gerais = conn.execute(
        "SELECT COUNT(*) AS n FROM regras WHERE normal IS NULL AND extra IS NULL"
    ).fetchone()["n"]
    condo = total - gerais
    print(f"\n📊 Na DB: {total} regras no total "
          f"({gerais} gerais, {condo} de condómino/quota).")
    print("\nPrimeiras 5:")
    for r in conn.execute(
        "SELECT id, prioridade, classe, conta, pattern, normal, extra, ativo "
        "FROM regras ORDER BY classe, prioridade, id LIMIT 5"
    ):
        print(f"  id={r['id']} prio={r['prioridade']} {r['classe']} "
              f"{r['conta']!r} pat={r['pattern']!r} "
              f"n={r['normal']} e={r['extra']} ativo={r['ativo']}")
    conn.close()
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())