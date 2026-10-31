#!/usr/bin/env python3
"""
Cria versões "mini" de condominio.db — condo42.db — contendo apenas as
tabelas (e views) realmente usadas pelo site web (app.py), com os
respetivos dados copiados.

Processa:
  - o exercício corrente:  corrente/condominio.db         -> export/condo42.db
  - cada exercício passado: historico/YYYY/condominio.db  -> export/YYYY/condo42.db
    (uma pasta YYYY por cada subpasta de historico/ que exista)

Uso (sem argumentos — os caminhos vêm sempre de Commons.py quando possível):
    python3 criar_condo42.py

Coloca este script na mesma pasta que Commons.py e Database.py. Se por
algum motivo não for possível importar Commons.py (dependência em falta,
script fora da pasta do projeto), cai automaticamente para os mesmos
caminhos calculados manualmente (corrente/, historico/, export/ dentro
da pasta deste script).
"""

import re
import sys
import sqlite3
from pathlib import Path

# Pasta onde este script está (serve de base para o fallback manual).
BASE_DIR = Path(__file__).resolve().parent

ANO_RE = re.compile(r"^\d{4}$")


def _resolver_pastas_base():
    """
    Resolve as pastas corrente/historico/export via Commons.py quando
    possível (PASTA_CORRENTE / PASTA_HISTORICO / BASE_DIR), caindo para
    cálculo manual (corrente/, historico/, export/ dentro de BASE_DIR) se
    a importação falhar.
    """
    sys.path.insert(0, str(BASE_DIR))
    try:
        from Commons import PASTA_CORRENTE, PASTA_HISTORICO
        pasta_corrente = Path(PASTA_CORRENTE).resolve()
        pasta_historico = Path(PASTA_HISTORICO).resolve()
        pasta_export = BASE_DIR / "export"
        print(f"ℹ️  Pasta corrente (Commons.PASTA_CORRENTE):   {pasta_corrente}")
        print(f"ℹ️  Pasta historico (Commons.PASTA_HISTORICO): {pasta_historico}")
        print(f"ℹ️  Pasta export:                               {pasta_export.resolve()}")
    except Exception as exc:
        pasta_corrente = (BASE_DIR / "corrente").resolve()
        pasta_historico = (BASE_DIR / "historico").resolve()
        pasta_export = BASE_DIR / "export"
        print(f"ℹ️  Não foi possível importar Commons.py ({exc}); "
              f"a usar caminhos calculados manualmente.")
        print(f"ℹ️  Pasta corrente:  {pasta_corrente}")
        print(f"ℹ️  Pasta historico: {pasta_historico}")
        print(f"ℹ️  Pasta export:    {pasta_export.resolve()}")
    return pasta_corrente, pasta_historico, pasta_export


def _listar_jobs():
    """
    Devolve a lista de pares (origem, destino, rótulo) a processar:
      - corrente/condominio.db         -> export/condo42.db
      - historico/YYYY/condominio.db   -> export/YYYY/condo42.db
        para cada subpasta YYYY de historico/ (ordenadas).
    """
    pasta_corrente, pasta_historico, pasta_export = _resolver_pastas_base()

    jobs = [
        (
            (pasta_corrente / "condominio.db").resolve(),
            (pasta_export / "condo42.db").resolve(),
            "corrente",
        )
    ]

    if pasta_historico.is_dir():
        anos = sorted(
            p.name for p in pasta_historico.iterdir()
            if p.is_dir() and ANO_RE.match(p.name)
        )
        for ano in anos:
            jobs.append(
                (
                    (pasta_historico / ano / "condominio.db").resolve(),
                    (pasta_export / ano / "condo42.db").resolve(),
                    ano,
                )
            )
    else:
        print(f"⚠️  Pasta de histórico não encontrada: {pasta_historico} — a ignorar exercícios passados.")

    return jobs


# Tabelas base lidas diretamente por app.py (funções read_relational_* /
# financial_summary / _ano_exercicio).
TABELAS = [
    "configs",            # _ano_exercicio()
    "movimentos",         # read_relational_movimentos() -> rota /bancos
    "condominos",         # JOINs em receitas_mensais / receitas_resumo
    "receitas_mensais",   # read_relational_receitas() (fallback sem view)
    "receitas_resumo",    # read_relational_receitas() (saldo_ant / saldo)
    "despesas_mensais",   # read_relational_despesas() (fallback sem view)
    "balanco_linhas",     # read_relational_linhas("balanco_linhas")
]

# Views que o app.py tenta usar primeiro (com fallback às tabelas acima
# caso não existam) — ambas dependem só das tabelas já listadas.
VIEWS = [
    "v_receitas_pivot",
    "v_despesas_pivot",
]


def criar_mini_bd(origem_path: Path, destino_path: Path) -> None:
    if not origem_path.exists():
        raise FileNotFoundError(
            f"Base de dados de origem não encontrada: {origem_path}"
        )

    destino_path.parent.mkdir(parents=True, exist_ok=True)
    if destino_path.exists():
        destino_path.unlink()  # começa sempre do zero

    src_conn = sqlite3.connect(str(origem_path))
    dst_conn = sqlite3.connect(str(destino_path))

    cur = src_conn.cursor()

    # 1) Recriar o esquema das tabelas (CREATE TABLE original, tal como está
    #    em condominio.db, para manter tipos, defaults e UNIQUE/CHECK).
    tabelas_copiadas = []
    for tabela in TABELAS:
        row = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (tabela,),
        ).fetchone()
        if row is None:
            print(f"⚠️  Tabela '{tabela}' não existe em {origem_path} — a ignorar.")
            continue
        dst_conn.execute(row[0])
        tabelas_copiadas.append(tabela)

    dst_conn.commit()

    # 2) Copiar os dados, usando ATTACH para fazer INSERT...SELECT direto
    #    entre as duas bases de dados (mais rápido e simples que ler linha a
    #    linha em Python).
    dst_conn.execute("ATTACH DATABASE ? AS origem", (str(origem_path),))
    try:
        for tabela in tabelas_copiadas:
            dst_conn.execute(f"INSERT INTO main.{tabela} SELECT * FROM origem.{tabela}")
        dst_conn.commit()
    finally:
        dst_conn.execute("DETACH DATABASE origem")

    # 3) Recriar as views usadas pelo app.py (ficam "vazias" de dados
    #    próprios — uma view não tem dados, calcula-os a partir das tabelas
    #    já copiadas acima).
    views_copiadas = []
    for view in VIEWS:
        row = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
            (view,),
        ).fetchone()
        if row is None:
            print(f"⚠️  View '{view}' não existe em {origem_path} — a ignorar.")
            continue
        dst_conn.execute(row[0])
        views_copiadas.append(view)

    dst_conn.commit()
    src_conn.close()
    dst_conn.close()

    print(f"✅ {destino_path} criado com sucesso.")
    print(f"   Tabelas copiadas: {', '.join(tabelas_copiadas)}")
    print(f"   Views recriadas:  {', '.join(views_copiadas)}")



def main() -> tuple[bool, str]:
    """
    Exporta condominio.db → condo42.db (corrente + históricos).

    Returns:
        (sucesso_global, mensagem_para_UI)
    """
    jobs = _listar_jobs()
    if not jobs:
        return False, "Nenhum exercício encontrado para exportar."

    sucesso: list[str] = []
    falhas: list[str] = []
    detalhes: list[str] = []

    for origem_path, destino_path, rotulo in jobs:
        print(f"\n--- {rotulo} ---")
        if not Path(origem_path).is_file():
            msg = f"{rotulo}: origem inexistente ({origem_path})"
            print(f"⚠️  {msg}")
            falhas.append(rotulo)
            detalhes.append(f"✗ {msg}")
            continue
        try:
            criar_mini_bd(origem_path, destino_path)
            sucesso.append(rotulo)
            #detalhes.append(f"✓ {rotulo} → {destino_path}")
        except Exception as exc:
            print(f"❌ Falhou '{rotulo}' ({origem_path}): {exc}")
            falhas.append(rotulo)
            #detalhes.append(f"✗ {rotulo}: {exc}")

    print("\n==== Resumo ====")
    print(f"✅ Concluídos ({len(sucesso)}): {', '.join(sucesso) if sucesso else '—'}")
    print(f"❌ Falhados   ({len(falhas)}): {', '.join(falhas) if falhas else '—'}")

    resumo = (
        f"<br><b>✅ Exportação P/Condo42Web concluída</b><br><br>"
        f"Pastas: {', '.join(sucesso)}"
    )
    return (len(falhas) == 0 and len(sucesso) > 0), resumo


if __name__ == "__main__":
    ok, msg = main()
    print(msg)
    if not ok:
        sys.exit(1)
