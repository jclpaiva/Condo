#!/usr/bin/env python3
"""
Migrar_fracoes.py
Garante que a tabela `fracoes` existe em condominio.db (cria-a se não
existir, usando a estrutura do ficheiro Excel) e, de qualquer forma,
apaga TODOS os registos existentes e copia para lá, do zero, todos
os registos do Excel.

Aceita .xlsx (Excel 2007+) e .xls (Excel 97/2003).

Uso:
  python Migrar_fracoes.py [caminho/para/fracoes.xlsx|.xls] [caminho/para/condominio.db]

Se omitidos, o programa pergunta interativamente (com valor por defeito):
  - Excel → fracoes.xlsx / fracoes.xls em locais habituais
  - DB    → ./corrente/condominio.db  (ou pasta do script / corrente)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    print("❌ pandas é necessário: pip install pandas openpyxl xlrd")
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
    """Procura fracoes.xlsx / fracoes.xls em locais habituais."""
    candidates = [
        Path.cwd() / "import" / "fracoes.xlsx",
        Path.cwd() / "import" / "fracoes.xls",
        Path.cwd() / "fracoes.xlsx",
        Path.cwd() / "fracoes.xls",
        Path(__file__).resolve().parent / "import" / "fracoes.xlsx",
        Path(__file__).resolve().parent / "import" / "fracoes.xls",
        Path(__file__).resolve().parent / "fracoes.xlsx",
        Path(__file__).resolve().parent / "fracoes.xls",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def table_exists(conn: sqlite3.Connection, nome: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)
    ).fetchone()
    return row is not None


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


def read_excel(path: Path) -> "pd.DataFrame":
    """Lê .xlsx (openpyxl) ou .xls (xlrd)."""
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        try:
            return pd.read_excel(path, engine="openpyxl")
        except ImportError:
            raise ImportError(
                "Para ler .xlsx é necessário openpyxl: pip install openpyxl"
            ) from None
    if suffix == ".xls":
        try:
            return pd.read_excel(path, engine="xlrd")
        except ImportError:
            raise ImportError(
                "Para ler .xls é necessário xlrd: pip install xlrd"
            ) from None
    raise ValueError(
        f"Formato não suportado: {suffix!r}. Use .xlsx ou .xls"
    )


def import_fracoes(db_path: Path, xlsx_path: Path) -> int:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Ficheiro Excel não encontrado: {xlsx_path}")

    df = read_excel(xlsx_path)
    colmap = {}
    for c in df.columns:
        key = str(c).strip().upper()
        if key in ("FRACAO", "FRAÇÃO", "FRACTION"):
            colmap[c] = "fracao"
        elif key in ("ANDAR", "PISO"):
            colmap[c] = "andar"
        elif key in ("PERMILAGEM", "PERMILAGEM (‰)", "PERMIL", "‰"):
            colmap[c] = "permilagem"
    df = df.rename(columns=colmap)

    required = {"fracao", "andar", "permilagem"}
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

        havia_tabela = table_exists(conn, "fracoes")
        n_del = 0
        if havia_tabela:
            n_del = conn.execute("SELECT COUNT(*) FROM fracoes").fetchone()[0]

        # Apaga e recria sempre a tabela do zero, mesmo que já existisse
        # com um esquema antigo (ex. sem a coluna permilagem) — assim
        # o esquema fica sempre atualizado, nunca "preso" a uma versão antiga.
        conn.execute("DROP TABLE IF EXISTS fracoes")
        conn.execute("""
            CREATE TABLE fracoes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fracao      TEXT    NOT NULL,
                andar       TEXT    NOT NULL,
                permilagem  REAL    NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        if havia_tabela:
            print(f"🗑  Tabela 'fracoes' já existia — apagados {n_del} registo(s) e recriada.")
        else:
            print("🆕 Tabela 'fracoes' não existia — criada agora.")

        for i, row in df.iterrows():
            fracao = str(row.get("fracao") or "").strip()
            andar = str(row.get("andar") or "").strip()
            permilagem = _to_float_or_none(row.get("permilagem"))
            if not fracao or not andar or permilagem is None:
                print(f"  ⚠ Linha {i+2}: fracao, andar ou permilagem vazios/inválidos — ignorada")
                ignoradas += 1
                continue

            try:
                conn.execute(
                    """
                    INSERT INTO fracoes (fracao, andar, permilagem, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (fracao, andar, permilagem, now),
                )
                inseridas += 1
                print(f"  ✓ {fracao:10s} | {andar:10s} | permilagem={permilagem}")
            except sqlite3.IntegrityError as e:
                print(f"  ⚠ Linha {i+2} ({fracao}): {e} — ignorada")
                ignoradas += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"\n✅ {inseridas} fração/frações inserida(s), {ignoradas} ignorada(s).")
    print(f"   DB: {db_path.resolve()}")
    return inseridas


def ask_path(pergunta: str, default: Path) -> Path:
    """Pergunta um caminho ao utilizador, mostrando o valor por defeito.
    Se o utilizador apenas carregar Enter, usa o valor por defeito."""
    resposta = input(f"{pergunta} [{default}]: ").strip()
    return Path(resposta) if resposta else default


def main():
    # Os caminhos também podem continuar a ser passados na linha de
    # comando; se não forem, pergunta-se interativamente ao utilizador.
    if len(sys.argv) > 2:
        xlsx = Path(sys.argv[1])
        db = Path(sys.argv[2])
    else:
        xlsx = ask_path("Caminho do Excel a importar (.xlsx ou .xls)", find_default_xlsx())
        db = ask_path("Caminho do file a atualizar", find_default_db())

    print("-" * 60)
    print(f"📂 Excel : {xlsx}")
    print(f"📂 DB    : {db}")
    print("-" * 60)

    n = import_fracoes(db, xlsx)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) AS n FROM fracoes").fetchone()["n"]
    soma = conn.execute("SELECT COALESCE(SUM(permilagem), 0) AS s FROM fracoes").fetchone()["s"]
    print(f"\n📊 Na DB: {total} fração/frações no total. Soma das permilagens: {soma:g}")
    print("\nPrimeiras 5:")
    for r in conn.execute(
        "SELECT id, fracao, andar, permilagem FROM fracoes ORDER BY id LIMIT 5"
    ):
        print(f"  id={r['id']} fracao={r['fracao']!r} andar={r['andar']!r} permilagem={r['permilagem']}")
    conn.close()
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
