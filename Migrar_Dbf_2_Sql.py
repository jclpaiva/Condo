#!/usr/bin/env python3
"""
Migrar_Dbf_2_Sql.py

Converte tabelas DBF legadas directamente para o schema relacional
em condominio.db (sem passar por dados.sqlite).

Tabelas DBF suportadas (na pasta indicada):
    Contas.dbf, Condominos.dbf, Configs.dbf,
    Bancos.dbf, Caixa.dbf, DPrazo.dbf,
    ReceitasN.dbf, ReceitasE.dbf, Despesas.dbf,
    Juros.dbf, Saldos.dbf, Balanco.dbf

O ano de exercício usado nas tabelas normalizadas (receitas_mensais,
despesas_mensais, juros, receitas_resumo) é o ANO DA PASTA quando este tem o
formato AAAA (ex.: historico/2024 → 2024); caso contrário usa o valor de
Configs.ANO_EXERCICIO. Nunca é imposto um ano fixo.

Uso:
    python Migrar_Dbf_2_Sql.py --pasta historico/2024 --force
    python Migrar_Dbf_2_Sql.py --pasta corrente          # sem --force não recria

Sem --force, a migração aborta se já existir condominio.db no destino
(protege a base operacional corrente). Com --force, recria-a de raiz.

Os ficheiros .dbf de origem não são apagados.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    from dbfread import DBF
except ImportError:
    print("ERRO: pacote 'dbfread' em falta. Instale com:  pip install dbfread")
    sys.exit(1)

from Database import (
    BASE_DIR,
    PASTA_CORRENTE,
    create_schema,
    db_path,
    ensure_views_and_fts,
    get_connection,
    _to_float,
    _to_int,
    _to_str,
    _normalize_date,
    _letra_from_label,
    ContasRepo,
    CondominosRepo,
    RegrasRepo,
    MovimentosRepo,
    ConfigsRepo,
)

MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
         "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

# Nomes lógicos → ficheiro .dbf esperado
DBF_FILES = {
    "Contas": "Contas.dbf",
    "Condominos": "Condominos.dbf",
    "Configs": "Configs.dbf",
    "Bancos": "Bancos.dbf",
    "Caixa": "Caixa.dbf",
    "DPrazo": "DPrazo.dbf",
    "ReceitasN": "ReceitasN.dbf",
    "ReceitasE": "ReceitasE.dbf",
    "Despesas": "Despesas.dbf",
    "Juros": "Juros.dbf",
    "Saldos": "Saldos.dbf",
    "Balanco": "Balanco.dbf",
}


# ---------------------------------------------------------------------------
# Leitura DBF
# ---------------------------------------------------------------------------

def _dbf_path(pasta: Path, tabela: str) -> Path | None:
    """Localiza o ficheiro .dbf (case-insensitive no nome)."""
    expected = DBF_FILES.get(tabela, f"{tabela}.dbf")
    exact = pasta / expected
    if exact.exists():
        return exact
    # pesquisa case-insensitive
    target = expected.casefold()
    for p in pasta.iterdir():
        if p.is_file() and p.name.casefold() == target:
            return p
    # aceita também sem extensão se existir (stem)
    for p in pasta.iterdir():
        if p.is_file() and p.stem.casefold() == tabela.casefold():
            return p
    return None


def _load_dbf(pasta: Path, tabela: str) -> list[dict[str, Any]] | None:
    """
    Lê um DBF e devolve lista de dicts com chaves em MAIÚSCULAS.
    Retorna None se o ficheiro não existir.
    """
    path = _dbf_path(pasta, tabela)
    if path is None:
        return None
    rows: list[dict[str, Any]] = []
    # Tentativas de encoding comuns em aplicações PT (FoxPro/Clipper)
    last_err: Exception | None = None
    for encoding in ("cp1252", "latin-1", "utf-8", "cp850"):
        try:
            table = DBF(str(path), encoding=encoding, ignore_missing_memofile=True,
                        char_decode_errors="replace")
            for rec in table:
                d = {str(k).upper(): v for k, v in rec.items()}
                rows.append(d)
            return rows
        except Exception as e:
            last_err = e
            rows = []
            continue
    print(f"   ⚠️  Falha ao ler {path.name}: {last_err}")
    return None


def _dbf_disponiveis(pasta: Path) -> set[str]:
    """Conjunto de nomes lógicos de tabelas DBF presentes na pasta."""
    found = set()
    for nome in DBF_FILES:
        if _dbf_path(pasta, nome) is not None:
            found.add(nome)
    return found


def _detectar_ano(pasta: Path, configs_rows: list[dict] | None) -> int:
    """Ano da pasta (AAAA) tem prioridade; caso contrário, Configs.ANO_EXERCICIO."""
    nome = pasta.name.strip()
    if len(nome) == 4 and nome.isdigit():
        return int(nome)
    if configs_rows:
        for r in configs_rows:
            cat = _to_str(r.get("CATEGORIA")).upper()
            chave = _to_str(r.get("CHAVE")).upper()
            if cat == "GERAL" and chave == "ANO_EXERCICIO":
                val = r.get("VALOR")
                if val not in (None, ""):
                    return int(_to_float(val))
    import datetime
    return datetime.date.today().year


# ---------------------------------------------------------------------------
# Contas / Condóminos / Movimentos
# ---------------------------------------------------------------------------

def migrate_contas(pasta: Path) -> dict[str, int]:
    """Migra Contas.dbf → contas. Devolve mapeamento nome → id."""
    print("→ Migrando contas …")
    repo = ContasRepo(pasta)
    mapping: dict[str, int] = {}

    rows = _load_dbf(pasta, "Contas")
    if not rows:
        print("   · Contas.dbf não encontrado – ignorado")
        return mapping

    for r in rows:
        nome = _to_str(r.get("CONTA"))
        tipo = _to_str(r.get("TIPO")).upper()
        if not nome:
            continue
        if tipo not in ("RECEITA", "DESPESA"):
            tipo = "RECEITA" if "REC" in tipo else "DESPESA"
        existing = repo.find_by_nome(nome)
        if existing:
            mapping[nome] = existing["id"]
            if existing["tipo"] != tipo:
                variante = f"{nome} ({tipo})"
                mapping[variante] = repo.ensure(variante, tipo)
            continue
        mapping[nome] = repo.ensure(nome, tipo)

    print(f"   ✓ {len(mapping)} contas")
    return mapping


def migrate_condominos(pasta: Path) -> dict[str, int]:
    """Migra Condominos.dbf → condominos. Devolve mapeamento fracao → id."""
    print("→ Migrando condóminos …")
    repo = CondominosRepo(pasta)
    mapping: dict[str, int] = {}

    rows = _load_dbf(pasta, "Condominos")
    if not rows:
        print("   · Condominos.dbf não encontrado – ignorado")
        return mapping

    for r in rows:
        fracao = _to_str(r.get("FRACAO"))
        nome = _to_str(r.get("NOME"))
        if not fracao or nome.lower() in ("[placeholder]", "placeholder"):
            continue

        check_val = _to_str(r.get("CHECK"))
        admin_val = _to_str(r.get("ADMIN"))
        ativo = 1 if check_val in ("1", ".T.", "T", "t", "True", "true") else 0
        admin = 1 if admin_val in ("1", ".T.", "T", "t", "True", "true") else 0

        data = {
            "fracao": fracao,
            "andar": _to_str(r.get("ANDAR")),
            "nome": nome,
            "morada": _to_str(r.get("MORADA")),
            "cpostal": _to_str(r.get("CPOSTAL")),
            "cidade": _to_str(r.get("CIDADE")),
            "telemovel": _to_str(r.get("TELEMOVEL")),
            "email": _to_str(r.get("EMAIL")),
            "permilagem": _to_float(r.get("PERMILAGEM")),
            "quota_normal": _to_float(r.get("QUOTAN")),
            "quota_extra": _to_float(r.get("QUOTAE")),
            "foto": _to_str(r.get("FOTO")),
            "ativo": ativo,
            "admin": admin,
        }
        mapping[fracao] = repo.upsert(data)

    print(f"   ✓ {len(mapping)} condóminos")
    return mapping


def migrate_movimentos(pasta: Path, contas_map: dict[str, int]) -> None:
    """Migra Bancos/Caixa/DPrazo.dbf → movimentos."""
    print("→ Migrando movimentos …")
    repo = MovimentosRepo(pasta)

    fontes = {"Bancos": "bancos", "Caixa": "caixa", "DPrazo": "dprazo"}

    for tabela, fonte in fontes.items():
        rows = _load_dbf(pasta, tabela)
        if rows is None:
            print(f"   · {tabela}.dbf não existe – ignorada")
            continue
        novos = []
        for r in rows:
            data = _normalize_date(r.get("DATA"))
            descricao = _to_str(r.get("DESCRICAO") or r.get("DESCRICAO_"))
            valor = _to_float(r.get("VALOR"))
            saldo = _to_float(r.get("SALDO"))
            tipo = _to_str(r.get("TIPO")).upper() or None
            if tipo and tipo not in ("RECEITA", "DESPESA"):
                tipo = None
            conta_nome = _to_str(r.get("CONTA"))
            conta_id = contas_map.get(conta_nome)
            observacao = _to_str(r.get("OBSERVACAO"))

            if not data and not descricao:
                continue

            novos.append({
                "data": data or "1970-01-01",
                "descricao": descricao or "***",
                "valor": valor,
                "saldo": saldo,
                "tipo": tipo,
                "conta_id": conta_id,
                "observacao": observacao,
                "origem": "migracao",
                "fonte": fonte,
            })

        n = repo.replace_fonte(fonte, novos)
        print(f"   · {fonte}: {n} movimentos")


# ---------------------------------------------------------------------------
# Configs (inclui CLASSIFICACAO)
# ---------------------------------------------------------------------------

def migrate_configs(pasta: Path) -> list[dict]:
    """Migra Configs.dbf → configs. Devolve as linhas lidas (para detectar ano)."""
    print("→ Migrando configurações (todas as categorias) …")
    repo = ConfigsRepo(pasta)
    rows = _load_dbf(pasta, "Configs")
    if not rows:
        print("   · Configs.dbf não encontrado – ignorado")
        return []

    n = 0
    for r in rows:
        cat = _to_str(r.get("CATEGORIA"))
        chave = _to_str(r.get("CHAVE"))
        if not cat or not chave:
            continue
        repo.set_value(
            categoria=cat,
            chave=chave,
            valor=r.get("VALOR"),
            tipo=_to_str(r.get("TIPO")) or "String",
            descricao=_to_str(r.get("DESCRICAO")),
        )
        n += 1
    print(f"   ✓ {n} configs")
    return rows


def migrate_regras(pasta: Path, contas_map: dict[str, int]) -> None:
    """
    Converte regras de Configs.dbf (REGRA_* + COND_*) para regras_classificacao.

    NOTA: a classificação em runtime já lê directamente a tabela configs.
    Esta função é apenas um enriquecimento opcional (--regras).
    """
    print("→ Migrando regras de classificação (enriquecimento) …")
    repo = RegrasRepo(pasta)

    rows = _load_dbf(pasta, "Configs")
    if not rows:
        print("   · Configs.dbf não encontrado – ignorado")
        return

    configs = {
        _to_str(r.get("CHAVE")): r
        for r in rows
        if _to_str(r.get("CATEGORIA")).upper() == "CLASSIFICACAO"
    }

    for chave, row in configs.items():
        if not chave.startswith("REGRA_") or chave.endswith("_VALOR"):
            continue
        pattern = _to_str(row.get("VALOR"))
        if not pattern:
            continue
        nome = chave.replace("REGRA_", "").replace("_", " ").title()
        valor_key = chave + "_VALOR"
        valor_esp = None
        if valor_key in configs:
            valor_esp = _to_float(configs[valor_key].get("VALOR"))

        conta_id = None
        for cnome, cid in contas_map.items():
            if nome.lower() in cnome.lower() or cnome.lower() in nome.lower():
                conta_id = cid
                break

        try:
            repo.add(
                nome=nome, pattern=pattern, prioridade=50,
                conta_id=conta_id, classe=None, valor_especifico=valor_esp,
            )
        except sqlite3.IntegrityError:
            print(f"   · regra já existe: {nome}")

    print("   ✓ regras migradas")


# ---------------------------------------------------------------------------
# Receitas / Despesas (mensal) + resumo
# ---------------------------------------------------------------------------

def _iter_wide(pasta: Path, tabela: str) -> Iterator[dict[str, Any]]:
    rows = _load_dbf(pasta, tabela)
    if not rows:
        return
    for d in rows:
        yield d


def migrate_receitas(
    pasta: Path,
    condominos_map: dict[str, int],
    ano: int,
) -> None:
    print("→ Migrando receitas mensais …")
    total = 0

    with get_connection(pasta) as conn:
        id_by_fracao = {
            r["fracao"]: r["id"]
            for r in conn.execute("SELECT id, fracao FROM condominos")
        }
        conn.execute("DELETE FROM receitas_mensais WHERE ano = ?", (ano,))
        conn.execute("DELETE FROM receitas_resumo WHERE ano = ?", (ano,))

        nao_mapeadas = []
        for tabela, tipo_quota in (("ReceitasN", "NORMAL"), ("ReceitasE", "EXTRA")):
            for d in _iter_wide(pasta, tabela):
                label = str(d.get("FRACCAO") or "").strip()
                if not label or label.upper() in ("TOTAIS", "TOTAL"):
                    continue
                letra = _letra_from_label(label)
                if not letra or letra not in id_by_fracao:
                    nao_mapeadas.append((tabela, label))
                    continue
                cid = id_by_fracao[letra]
                for col, mes in zip(MESES, range(1, 13)):
                    val = _to_float(d.get(col, 0))
                    if abs(val) < 0.0005:
                        continue
                    conn.execute(
                        """INSERT OR REPLACE INTO receitas_mensais
                           (condominio_id, ano, mes, tipo_quota, valor)
                           VALUES (?,?,?,?,?)""",
                        (cid, ano, mes, tipo_quota, val),
                    )
                    total += 1
                conn.execute(
                    """INSERT OR REPLACE INTO receitas_resumo
                       (condominio_id, ano, tipo_quota, fracao_label, saldo_ant, saldo)
                       VALUES (?,?,?,?,?,?)""",
                    (cid, ano, tipo_quota, label,
                     _to_float(d.get("SALDO_ANT", 0)), _to_float(d.get("SALDO", 0))),
                )
        if nao_mapeadas:
            print(f"   ⚠️ fracções não mapeadas: {nao_mapeadas}")

    print(f"   ✓ {total} valores mensais de receitas")


def migrate_despesas(pasta: Path, contas_map: dict[str, int], ano: int) -> None:
    print("→ Migrando despesas mensais …")
    total = 0

    with get_connection(pasta) as conn:
        conn.execute("DELETE FROM despesas_mensais WHERE ano = ?", (ano,))
        for d in _iter_wide(pasta, "Despesas"):
            nome = str(d.get("DESPESAS") or "").strip()
            if not nome or nome.upper() in ("TOTAIS", "TOTAL"):
                continue
            conta_id = contas_map.get(nome)
            if not conta_id:
                for cnome, cid in contas_map.items():
                    if nome.lower() in cnome.lower() or cnome.lower() in nome.lower():
                        conta_id = cid
                        break
            if not conta_id:
                cur = conn.execute(
                    "INSERT INTO contas (nome, tipo) VALUES (?, 'DESPESA')", (nome,)
                )
                conta_id = cur.lastrowid
                contas_map[nome] = conta_id
            for col, mes in zip(MESES, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO despesas_mensais
                       (conta_id, ano, mes, valor) VALUES (?,?,?,?)""",
                    (conta_id, ano, mes, val),
                )
                total += 1

    print(f"   ✓ {total} valores mensais de despesas")


def migrate_juros(pasta: Path, ano: int) -> None:
    print("→ Migrando juros mensais …")
    total = 0
    with get_connection(pasta) as conn:
        conn.execute("DELETE FROM juros WHERE ano = ?", (ano,))
        for d in _iter_wide(pasta, "Juros"):
            for col, mes in zip(MESES, range(1, 13)):
                val = _to_float(d.get(col, 0))
                if abs(val) < 0.0005:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO juros (ano, mes, valor) VALUES (?,?,?)",
                    (ano, mes, val),
                )
                total += 1
    print(f"   ✓ {total} valores de juros")


def migrate_linhas(pasta: Path, tabela_legado: str, tabela_destino: str) -> None:
    """Copia Saldos/Balanco (CONTA, TIPO, VALOR) preservando a ordem."""
    print(f"→ Migrando {tabela_legado} → {tabela_destino} …")
    rows = _load_dbf(pasta, tabela_legado)
    if rows is None:
        print(f"   · {tabela_legado}.dbf não existe – ignorada")
        return
    with get_connection(pasta) as conn:
        conn.execute(f"DELETE FROM {tabela_destino}")
        for ordem, r in enumerate(rows):
            conta = _to_str(r.get("CONTA"))
            tipo = _to_str(r.get("TIPO"))
            valor = _to_float(r.get("VALOR"))
            conn.execute(
                f"INSERT INTO {tabela_destino} (ordem, conta, tipo, valor) VALUES (?,?,?,?)",
                (ordem, conta, tipo, valor),
            )
    print(f"   ✓ {len(rows)} linhas")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def run_migration(pasta: Path, force: bool = False, regras: bool = False) -> None:
    pasta = Path(pasta)
    if not pasta.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {pasta}")

    disponiveis = _dbf_disponiveis(pasta)
    if not disponiveis:
        raise FileNotFoundError(
            f"Nenhum ficheiro .dbf encontrado em {pasta}.\n"
            f"Esperados (pelo menos um): {', '.join(DBF_FILES.values())}"
        )

    print(f"\n{'='*60}")
    print(f"  Migração DBF → condominio.db")
    print(f"  Pasta: {pasta}")
    print(f"  DBFs encontrados: {', '.join(sorted(disponiveis))}")
    print(f"{'='*60}\n")

    dest = db_path(pasta)
    if dest.exists():
        if not force:
            print(f"⚠  {dest} já existe. Use --force para recriar.")
            sys.exit(1)
        dest.unlink()
        print(f"✓ {dest.name} anterior removido (--force)\n")

    create_schema(pasta)
    print("✓ Schema criado\n")

    # Configs primeiro (para detecção de ano e regras)
    configs_rows = migrate_configs(pasta)
    ano = _detectar_ano(pasta, configs_rows)
    print(f"✓ Ano de exercício: {ano}\n")

    contas_map = migrate_contas(pasta)
    condominos_map = migrate_condominos(pasta)
    if regras:
        migrate_regras(pasta, contas_map)
    migrate_movimentos(pasta, contas_map)

    # garantir ANO_EXERCICIO coerente no destino
    cfg = ConfigsRepo(pasta)
    if cfg.get_value("GERAL", "ANO_EXERCICIO", None) in (None, ""):
        cfg.set_value("GERAL", "ANO_EXERCICIO", str(ano), "Number",
                      "Ano de exercício")
        print(f"   · ANO_EXERCICIO ausente no legado → gravado {ano}")

    migrate_receitas(pasta, condominos_map, ano)
    migrate_despesas(pasta, contas_map, ano)
    migrate_juros(pasta, ano)
    migrate_linhas(pasta, "Saldos", "saldos_linhas")
    migrate_linhas(pasta, "Balanco", "balanco_linhas")

    ensure_views_and_fts(pasta)

    print(f"\n{'='*60}")
    print("  Migração concluída com sucesso!")
    print(f"  Destino: {db_path(pasta)}")
    print(f"  Ficheiros .dbf de origem preservados.")
    print(f"{'='*60}\n")

    with get_connection(pasta) as conn:
        for t in ("condominos", "contas", "regras_classificacao", "movimentos",
                  "configs", "receitas_mensais", "receitas_resumo",
                  "despesas_mensais", "juros", "saldos_linhas", "balanco_linhas"):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:25s} {n:5d} registos")


def main():
    parser = argparse.ArgumentParser(
        description="Migração DBF → schema relacional (condominio.db)"
    )
    parser.add_argument("--pasta", default=str(PASTA_CORRENTE),
                        help="Pasta com os ficheiros .dbf (default: corrente)")
    parser.add_argument("--force", action="store_true",
                        help="Recria condominio.db mesmo que já exista")
    parser.add_argument("--regras", action="store_true",
                        help="Migrar também regras_classificacao (enriquecimento)")
    args = parser.parse_args()
    pasta = Path(args.pasta)
    if not pasta.is_absolute():
        pasta = BASE_DIR / pasta
    run_migration(pasta, force=args.force, regras=args.regras)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERRO inesperado: {e}", file=sys.stderr)
        raise
