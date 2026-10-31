#!/usr/bin/env python3
"""
Migração: adiciona campos de identificação à tabela `condominos`.

Campos:
  - cc_numero   TEXT  — Cartão de Cidadão n.º
                        Formato: NNNNNNNNN D LLD
                        (9 dígitos NIC + espaço + dígito de controlo + espaço
                         + 2 letras de versão + 1 dígito)
                        Ex.: "123456789 0 ZZ0"
  - cc_validade TEXT  — Data de validade do CC (dd-mm-yyyy)
  - nif         TEXT  — NIF (9 dígitos)

Uso:
    python3 migrar_cc_nif.py [caminho/para/condominio.db]

Se não for passado caminho, usa a BD em anexos (ou a de Commons se disponível).
O script é idempotente: só adiciona colunas que ainda não existam.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Colunas a adicionar: (nome, tipo SQL, comentário)
NOVAS_COLUNAS = [
    (
        "cc_numero",
        "TEXT",
        "Cartão de Cidadão n.º (NIC 9 dígitos + check + versão 3 chars)",
    ),
    (
        "cc_validade",
        "TEXT",
        "Data de validade do CC (dd-mm-yyyy)",
    ),
    (
        "nif",
        "TEXT",
        "NIF (9 dígitos)",
    ),
]


def _colunas_existentes(conn: sqlite3.Connection, tabela: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return {row[1] for row in cur.fetchall()}


def migrar(db_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Base de dados não encontrada: {db_path}")

    print(f"BD: {db_path.resolve()}")
    conn = sqlite3.connect(str(db_path))
    try:
        existentes = _colunas_existentes(conn, "condominos")
        print(f"Colunas atuais em condominos: {sorted(existentes)}")

        adicionadas = []
        for nome, tipo, comentario in NOVAS_COLUNAS:
            if nome in existentes:
                print(f"  ✓  {nome} já existe — ignorado")
                continue
            sql = f"ALTER TABLE condominos ADD COLUMN {nome} {tipo}"
            conn.execute(sql)
            adicionadas.append(nome)
            print(f"  +  {nome} {tipo}  ({comentario})")

        conn.commit()

        if adicionadas:
            print(f"\nMigração concluída. Colunas adicionadas: {', '.join(adicionadas)}")
        else:
            print("\nNada a fazer — todas as colunas já existiam.")

        # Confirmação final
        finais = _colunas_existentes(conn, "condominos")
        print(f"Colunas finais: {sorted(finais)}")
    finally:
        conn.close()


def _resolver_db_default() -> Path:
    """Tenta Commons; senão usa anexos / pasta corrente."""
    base = Path(__file__).resolve().parent
    candidatos = [
        base / "attachments" / "condominio.db",
        Path("/home/workdir/attachments/condominio.db"),
        base / "corrente" / "condominio.db",
        base / "condominio.db",
    ]
    try:
        sys.path.insert(0, str(base))
        from Commons import db_path, PASTA_CORRENTE  # type: ignore

        p = db_path(PASTA_CORRENTE)
        if p and Path(p).exists():
            return Path(p)
    except Exception:
        pass

    for c in candidatos:
        if c.exists():
            return c
    # fallback: primeiro candidato (para mensagens de erro claras)
    return candidatos[0]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        caminho = Path(sys.argv[1])
    else:
        caminho = _resolver_db_default()

    try:
        migrar(caminho)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
