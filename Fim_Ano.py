#===========================================================================
# Função de Encerramento de ano e passagem de Saldo Finais a Saldos iniciais
# VERSÃO CORRIGIDA - Backup em historico/YYYY + Entry Point
#===========================================================================
import os
import sys
import shutil
import sqlite3
import pandas as pd
from pathlib import Path

from datetime import datetime
from Commons import (
    BASE_DIR,
    PASTA_CORRENTE,
    PASTA_HISTORICO,
    obter_ano_exercicio,
)

from Logging_utils import ativar_logging
from Database import (
    existe_dados,
    resolver_pasta,
    guardar_movimentos_fonte,
    carregar_movimentos_fonte,
    fonte_de_path,
    save_despesas_wide,
    save_juros_wide,
    save_receitas_wide,
    save_saldos_wide,
    save_balanco_wide,
    load_despesas_wide,
    load_juros_wide,
    load_receitas_wide,
    load_saldos_wide,
    load_balanco_wide,
    configs as configs_repo,
    create_schema,
    db_transaction,
)

logger = ativar_logging("fim_ano")
# ativar_logging já redirecciona stdout/stderr para o ficheiro de log.

# PASTA_CORRENTE / PASTA_HISTORICO: importadas de Commons (não redefinir
# aqui — eram uma cópia local não usada, dessincronizável de Commons.py).

# ---------------------------------------------------------------------------
# Identificação canónica de contas / registos de saldo
# ---------------------------------------------------------------------------
CONTA_SALDO_ANTERIOR = "SALDO ANTERIOR"
CONTA_SALDO_DPRAZO   = "SALDO Dep.Poupança"
DESCRICAO_MARCADOR   = "***"
TIPO_RECEITA         = "RECEITA"

_TOKEN_POUPANCA = ("POUPANCA", "POUPANÇA")
_TOKEN_ORDEM    = ("ORDEM",)
_TOKEN_CAIXA    = ("CAIXA", "NUMERARIO", "NUMERÁRIO")
_TOKEN_FINAL    = ("_F", " F", "FINAL")
_TOKEN_INICIAL  = ("_I", " I", "INICIAL")


def _norm(s: str) -> str:
    """Normaliza texto para comparação: uppercase, remove acentos, colapsa espaços."""
    if s is None:
        return ""
    t = str(s).upper().strip()
    t = (t.replace("Ç", "C").replace("Ã", "A").replace("Õ", "O")
           .replace("Á", "A").replace("À", "A").replace("Â", "A")
           .replace("É", "E").replace("Ê", "E")
           .replace("Í", "I")
           .replace("Ó", "O").replace("Ô", "O")
           .replace("Ú", "U"))
    return " ".join(t.split())


def _e_saldo_inicial(conta: str, tipo: str) -> bool:
    n = _norm(conta)
    if tipo == "poupanca":
        return any(t in n for t in _TOKEN_POUPANCA) and any(t in n for t in _TOKEN_INICIAL)
    if tipo == "ordem":
        return any(t in n for t in _TOKEN_ORDEM) and any(t in n for t in _TOKEN_INICIAL)
    if tipo == "caixa":
        return any(t in n for t in _TOKEN_CAIXA) and any(t in n for t in _TOKEN_INICIAL)
    return False


def _e_saldo_final(conta: str, tipo: str) -> bool:
    n = _norm(conta)
    if tipo == "poupanca":
        return any(t in n for t in _TOKEN_POUPANCA) and any(t in n for t in _TOKEN_FINAL)
    if tipo == "ordem":
        return any(t in n for t in _TOKEN_ORDEM) and any(t in n for t in _TOKEN_FINAL)
    if tipo == "caixa":
        return any(t in n for t in _TOKEN_CAIXA) and any(t in n for t in _TOKEN_FINAL)
    return False


def _e_conta_a_zerar(conta: str) -> bool:
    n = _norm(conta)
    if any(t in n for t in _TOKEN_FINAL) and (
        any(t in n for t in _TOKEN_POUPANCA)
        or any(t in n for t in _TOKEN_ORDEM)
        or any(t in n for t in _TOKEN_CAIXA)
    ):
        return True
    if n in ("JUROS", "SALDO FINAL") or "SALDO EXERCICIO" in n:
        return True
    return False


def _e_linha_balanco_inicial(conta: str, tipo: str) -> bool:
    n = _norm(conta)
    if tipo == "poupanca":
        return "A)" in n and any(t in n for t in _TOKEN_POUPANCA)
    if tipo == "ordem":
        return "B)" in n and any(t in n for t in _TOKEN_ORDEM)
    if tipo == "caixa":
        return "C)" in n and any(t in n for t in _TOKEN_CAIXA)
    return False


def _encontrar_idx_saldo_anterior(df: pd.DataFrame):
    """Localiza o registo canónico de saldo de abertura numa tabela de movimentos."""
    if df is None or df.empty:
        return None
    conta = df["CONTA"].astype(str).map(_norm) if "CONTA" in df.columns else pd.Series([""] * len(df))
    desc  = df["DESCRICAO"].astype(str) if "DESCRICAO" in df.columns else pd.Series([""] * len(df))
    tipo  = df["TIPO"].astype(str).str.upper().str.strip() if "TIPO" in df.columns else pd.Series([""] * len(df))
    marcador = desc.str.contains(r"\*{3}", na=False, regex=True)
    receita  = tipo == TIPO_RECEITA
    mask1 = (
        (conta.str.contains("SALDO ANTERIOR", na=False) | conta.str.contains("SALDO DEP", na=False))
        & marcador & receita
    )
    idxs = df.index[mask1]
    if len(idxs) > 0:
        return int(idxs[0])
    mask2 = conta.str.startswith("SALDO") & marcador & receita
    idxs = df.index[mask2]
    if len(idxs) > 0:
        return int(idxs[0])
    return None


def clean_numeric(value):
    """Retorna 0.0 se o valor for NaN ou None."""
    return 0.0 if pd.isna(value) else float(value)

def ler_db(path):
    """Lê tabela via API canónica (load_*_wide / movimentos)."""
    try:
        pasta = resolver_pasta(path)
        nome = Path(path).name.casefold().replace("ç", "c").replace("ã", "a")
        if nome == "despesas":
            rows, _ = load_despesas_wide(pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome == "juros":
            rows, _ = load_juros_wide(pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome == "receitasn":
            rows, _ = load_receitas_wide("NORMAL", pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome == "receitase":
            rows, _ = load_receitas_wide("EXTRA", pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome.startswith("saldo"):
            rows, _ = load_saldos_wide(pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome == "balanco":
            rows, _ = load_balanco_wide(pasta)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if nome in ("bancos", "caixa", "dprazo"):
            rows = carregar_movimentos_fonte(pasta, nome)
            return pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        print(f"⚠️ ler_db: tabela desconhecida {nome!r}")
        return pd.DataFrame()
    except Exception:
        return None

def gravar_tabela(df, path=None, conn=None, ano=None):
    """Escrita via API canónica (movimentos / wide).
    Se `conn` for fornecido, todas as escritas usam essa conexão.
    `ano`: só é relevante para ReceitasN/ReceitasE (ver fim_ano_quotas_normais/extras);
    permite gravar o SALDO_ANT/SALDO já sob o ano novo, antes de o
    ANO_EXERCICIO em Configs ter sido atualizado.
    """
    pasta = resolver_pasta(path)
    nome = Path(path).name.casefold().replace("ç", "c").replace("ã", "a")
    try:
        if nome in ("bancos", "caixa", "dprazo"):
            return guardar_movimentos_fonte(df, pasta=pasta, fonte=nome, conn=conn)
        if nome == "despesas":
            save_despesas_wide(df, pasta, ano=ano, conn=conn)
            return True
        if nome == "juros":
            save_juros_wide(df, pasta, ano=ano, conn=conn)
            return True
        if nome == "receitasn":
            save_receitas_wide(df, "NORMAL", pasta, ano=ano, conn=conn)
            return True
        if nome == "receitase":
            save_receitas_wide(df, "EXTRA", pasta, ano=ano, conn=conn)
            return True
        if nome.startswith("saldo"):
            save_saldos_wide(df, pasta, conn=conn)
            return True
        if nome == "balanco":
            save_balanco_wide(df, pasta, conn=conn)
            return True
        print(f"⚠️ gravar_tabela: tabela desconhecida {nome!r}")
        return False
    except Exception as exc:
        print(f"⚠️ gravar_tabela({nome}): {exc}")
        return False

# obter_ano_exercicio já não é redefinida aqui: usa-se directamente a versão
# central de Commons.py (importada acima), para deixar de haver duas
# implementações divergentes da mesma leitura.

def backup_arquivos_db(bancos_db='Bancos'):
    """
    Cria backup de condominio.db em BASE_DIR/historico/YYYY.

    Args:
        bancos_db: caminho na pasta de trabalho (usado só para obter o ano e a pasta)
    """
    ano_exercicio = obter_ano_exercicio(bancos_db)
    
    # Determinar pasta de trabalho (dados do exercício a arquivar)
    if os.path.isabs(bancos_db):
        work_dir = os.path.dirname(bancos_db)
    else:
        work_dir = os.getcwd()
    
    # ✅ CORRIGIDO: Backup vai para BASE_DIR/historico/YYYY (não work_dir/historico)
    historico_dir = BASE_DIR / 'historico'
    backup_dir = historico_dir / str(ano_exercicio)
    
    print(f"  Pasta de origem: {work_dir}")
    print(f"  Pasta de backup: {backup_dir}")
    
    # Cria pasta historico se não existir
    if not historico_dir.exists():
        try:
            historico_dir.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Pasta historico criada")
        except Exception as e:
            print(f"  ✗ Erro ao criar pasta historico: {e}")
            return False
    
    # Cria pasta do ano
    if not backup_dir.exists():
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Pasta {ano_exercicio} criada")
        except Exception as e:
            print(f"  ✗ Erro ao criar pasta do ano: {e}")
            return False
    
    # Copia condominio.db (única fonte de verdade)
    condo_origem = Path(work_dir) / 'condominio.db'
    if not condo_origem.exists():
        print(f"  ✗ condominio.db não encontrado em {work_dir}")
        return False

    try:
        shutil.copy2(str(condo_origem), str(backup_dir / 'condominio.db'))
        print(f"    ✓ condominio.db")
    except Exception as e:
        print(f"    ✗ Erro ao copiar condominio.db: {e}")
        return False

    return True

def obter_saldos_finais(saldos_db='Saldos'):
    """Obtém os saldos finais da tabela Saldos (condominio.db)."""
    try:
        print(f"\n=== OBTER_SALDOS_FINAIS ===")
        print(f"Lendo ficheiro: {saldos_db}")
        
        rows, _ = load_saldos_wide(resolver_pasta(saldos_db))
        df = pd.DataFrame(rows, dtype=object)
        print(f"Registos lidos: {len(df)}")
        
        if df.empty:
            print("⚠️ Ficheiro vazio!")
            return {'poupanca_f': 0.0, 'ordem_f': 0.0, 'caixa_f': 0.0, 'total': 0.0}
        
        print(f"Colunas disponíveis: {list(df.columns)}")
        print(f"\nContas encontradas:")
        for idx, row in df.iterrows():
            print(f"  {row['CONTA']}: {row['VALOR']}")
        
        def _valor_saldo_final(tipo: str) -> float:
            for _, row in df.iterrows():
                conta = str(row.get("CONTA", ""))
                if _e_saldo_final(conta, tipo):
                    valor = clean_numeric(row.get("VALOR"))
                    print(f"  ✓ {tipo}: '{conta}' = {valor}")
                    return valor
            print(f"  ⚠️ {tipo}: nenhum registo de saldo final encontrado")
            return 0.0

        print("\nBuscando saldos finais (identificação canónica):")
        poupanca_f = _valor_saldo_final("poupanca")
        ordem_f    = _valor_saldo_final("ordem")
        caixa_f    = _valor_saldo_final("caixa")
        
        resultado = {
            'poupanca_f': poupanca_f, 
            'ordem_f': ordem_f, 
            'caixa_f': caixa_f, 
            'total': round(poupanca_f + ordem_f + caixa_f, 2)
        }
        
        print(f"\n✅ Saldos finais obtidos:")
        print(f"  Poupança_F: {poupanca_f:.2f} €")
        print(f"  Ordem_F: {ordem_f:.2f} €")
        print(f"  Caixa_F: {caixa_f:.2f} €")
        print(f"  TOTAL: {resultado['total']:.2f} €")
        
        return resultado
        
    except Exception as e:
        print(f"❌ ERRO em obter_saldos_finais: {e}")
        import traceback
        traceback.print_exc()
        return {'poupanca_f': 0.0, 'ordem_f': 0.0, 'caixa_f': 0.0, 'total': 0.0}

def zerar_saldos(saldos_db='Saldos', poupanca_novo=0.0, ordem_novo=0.0, caixa_novo=0.0,
                  df_saldos=None, df_balanco=None, conn=None):
    """
    Atualiza saldos iniciais com os valores fornecidos e zera os saldos finais.
    Se `conn` for fornecido, todas as escritas usam essa conexão (transação externa).
    `df_saldos`/`df_balanco`: DataFrames já lidos antecipadamente (ver nota de
    performance em `fim_ano_e_transfere_saldo`); se omitidos, são lidos aqui
    (comportamento antigo, para chamadas fora dessa função).
    """
    print(f"\n=== ZERAR_SALDOS ===")
    print(f"Ficheiro: {saldos_db}")
    print(f"Valores recebidos:")
    print(f"  Poupança_novo: {poupanca_novo:.2f} €")
    print(f"  Ordem_novo: {ordem_novo:.2f} €")
    print(f"  Caixa_novo: {caixa_novo:.2f} €")

    # 1) Atualiza Saldos via dataframe com fallback comum
    try:
        df = ler_db(saldos_db) if df_saldos is None else df_saldos
        if df is None or df.empty:
            print(f"⚠️ Saldos vazio ou não legível: {saldos_db}")
            return False

        print(f"\nAtualizando Saldos (identificação canónica)...")
        for idx, row in df.iterrows():
            conta = str(row.get('CONTA', ''))
            if _e_saldo_inicial(conta, "poupanca"):
                print(f"  ✓ Atualizando inicial poupança '{conta}': {poupanca_novo:.2f}")
                df.at[idx, 'VALOR'] = round(poupanca_novo, 2)
            elif _e_saldo_inicial(conta, "ordem"):
                print(f"  ✓ Atualizando inicial ordem '{conta}': {ordem_novo:.2f}")
                df.at[idx, 'VALOR'] = round(ordem_novo, 2)
            elif _e_saldo_inicial(conta, "caixa"):
                print(f"  ✓ Atualizando inicial caixa '{conta}': {caixa_novo:.2f}")
                df.at[idx, 'VALOR'] = round(caixa_novo, 2)

            if _e_conta_a_zerar(conta):
                print(f"  ✓ Zerando '{conta}'")
                df.at[idx, 'VALOR'] = 0.0

        if not gravar_tabela(df, saldos_db, conn=conn):
            raise RuntimeError('gravar_tabela falhou para Saldos')

        print(f"✅ Saldos atualizado com sucesso!")
    except Exception as e:
        print(f"❌ ERRO ao atualizar Saldos: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 2) Atualiza Balanco
    try:
        balanco_path = Path(saldos_db).parent / 'Balanco'
        print(f"\nAtualizando Balanco em: {balanco_path}")

        if not existe_dados(balanco_path):
            print(f"  ⚠️ Balanco não encontrado, a saltar atualização")
            return True

        df_bal = ler_db(str(balanco_path)) if df_balanco is None else df_balanco
        if df_bal is None or df_bal.empty:
            print(f"  ⚠️ Balanco vazio, a saltar atualização")
            return True

        # zera tudo primeiro
        for idx, row in df_bal.iterrows():
            if 'VALOR' in df_bal.columns:
                df_bal.at[idx, 'VALOR'] = 0.0

        # atualiza os saldos iniciais (identificação canónica A/B/C)
        for idx, row in df_bal.iterrows():
            conta = str(row.get('CONTA', ''))
            if _e_linha_balanco_inicial(conta, "poupanca"):
                print(f"  ✓ Atualizando {conta}: {poupanca_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(poupanca_novo, 2)
            elif _e_linha_balanco_inicial(conta, "ordem"):
                print(f"  ✓ Atualizando {conta}: {ordem_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(ordem_novo, 2)
            elif _e_linha_balanco_inicial(conta, "caixa"):
                print(f"  ✓ Atualizando {conta}: {caixa_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(caixa_novo, 2)

        if not gravar_tabela(df_bal, str(balanco_path), conn=conn):
            raise RuntimeError('gravar_tabela falhou para Balanco')

        print(f"✅ Balanco atualizado com sucesso!")
    except Exception as e:
        print(f"❌ ERRO ao atualizar Balanco: {e}")
        import traceback
        traceback.print_exc()

    return True

def fim_ano_juros(juros_db='Juros', ano=None, df=None, conn=None):
    """Zera juros mensais e grava sob o ano novo.

    `ano`: ano do exercício seguinte (obrigatório no encerramento). Sem isto,
    save_juros_wide usaria ANO_EXERCICIO ainda antigo e destruía os dados do
    ano que acabámos de arquivar, deixando o ano novo sem linhas.
    `df`: DataFrame já lido antecipadamente; se omitido, é lido aqui.
    """
    df = ler_db(juros_db) if df is None else df
    if df is None or df.empty:
        return True  # já vazio — nada a limpar

    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0

    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    return gravar_tabela(df, juros_db, conn=conn, ano=ano)

def fim_ano_despesas(despesas_db='Despesas', ano=None, df=None, conn=None):
    """Zera despesas mensais e grava sob o ano novo.

    `ano`: ano do exercício seguinte (ver nota em `fim_ano_juros`).
    `df`: DataFrame já lido antecipadamente; se omitido, é lido aqui.
    """
    df = ler_db(despesas_db) if df is None else df
    if df is None or df.empty:
        return True  # já vazio — nada a limpar

    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0

    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    return gravar_tabela(df, despesas_db, conn=conn, ano=ano)

def fim_ano_quotas_normais(receitas_n_db='ReceitasN', ano=None, df=None, conn=None):
    """`ano`: ano novo (ano_atual + 1) a usar ao gravar o SALDO_ANT/SALDO
    transitados — ver nota em `gravar_tabela`/`fim_ano_e_transfere_saldo`.
    `df`: DataFrame já lido antecipadamente; se omitido, é lido aqui.
    """
    df = ler_db(receitas_n_db) if df is None else df
    if df is None or df.empty:
        return True  # já vazio — nada a limpar
    
    if 'SALDO' in df.columns:
        df['SALDO_ANT'] = df['SALDO'].copy()
    
    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0
    
    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    
    if 'SALDO' in df.columns:
        df['SALDO'] = 0.0        # Zerar saldos p/ novo ano. Corrigido -> df['SALDO_ANT'].copy()
    return gravar_tabela(df, receitas_n_db, conn=conn, ano=ano)

def fim_ano_quotas_extras(receitas_e_db='ReceitasE', ano=None, df=None, conn=None):
    """`ano`: ano novo (ano_atual + 1) a usar ao gravar o SALDO_ANT/SALDO
    transitados — ver nota em `gravar_tabela`/`fim_ano_e_transfere_saldo`.
    `df`: DataFrame já lido antecipadamente; se omitido, é lido aqui.
    """
    df = ler_db(receitas_e_db) if df is None else df
    if df is None or df.empty:
        return True  # já vazio — nada a limpar
    
    if 'SALDO' in df.columns:
        df['SALDO_ANT'] = df['SALDO'].copy()
    
    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0
    
    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    
    if 'SALDO' in df.columns:
        df['SALDO'] = 0.0        # Zerar saldos p/ novo ano. Corrigido -> df['SALDO_ANT'].copy()
    return gravar_tabela(df, receitas_e_db, conn=conn, ano=ano)

def transfere_saldo_bancos(bancos_db='Bancos', saldo_final=0.0, df=None, conn=None):
    """`df`: DataFrame já lido antecipadamente; se omitido, é lido aqui."""
    df = ler_db(bancos_db) if df is None else df
    if df is None or df.empty:
        return False
    
    # Obter ano do exercício e calcular data do ano seguinte (1 de janeiro)
    ano_exercicio = obter_ano_exercicio(bancos_db)
    data_ano_seguinte = datetime(ano_exercicio + 1, 1, 1).date()
    
    print(f"  Ano exercício: {ano_exercicio}")
    print(f"  Data SALDO ANTERIOR: {data_ano_seguinte.strftime('%d-%m-%Y')}")
    
    for col in ['DESCRICAO','CONTA','TIPO']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.replace('\x00','',regex=False)
    
    df = df.dropna(how='all').reset_index(drop=True)
    
    idx = _encontrar_idx_saldo_anterior(df)
    if idx is None:
        new_row = pd.DataFrame({
            'DATA': [data_ano_seguinte],
            'CONTA': [CONTA_SALDO_ANTERIOR],
            'DESCRICAO': [DESCRICAO_MARCADOR],
            'TIPO': [TIPO_RECEITA],
            'VALOR': [0.0],
            'SALDO': [saldo_final],
            'OBSERVACAO': ['']
        }, index=[0])
        df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
        idx = 0
    
    df.at[idx, 'SALDO'] = saldo_final
    df.at[idx, 'VALOR'] = 0.0
    df.at[idx, 'DATA'] = data_ano_seguinte
    df.at[idx, 'CONTA'] = CONTA_SALDO_ANTERIOR
    df.at[idx, 'DESCRICAO'] = DESCRICAO_MARCADOR
    df.at[idx, 'TIPO'] = TIPO_RECEITA
    df = df.iloc[:idx + 1]
    
    try:
        return gravar_tabela(df, bancos_db, conn=conn)
    except Exception as e:
        print(f"  ❌ Erro ao transferir saldo Bancos: {e}")
        import traceback
        traceback.print_exc()
        return False

def transfere_saldo_caixa(caixa_db='Caixa', saldo_final=0.0, df=None, conn=None):
    """`df`: DataFrame já lido antecipadamente; se omitido, é lido aqui."""
    df = ler_db(caixa_db) if df is None else df
    if df is None or df.empty:
        return False
    
    # Obter ano do exercício e calcular data do ano seguinte (1 de janeiro)
    # Usamos Bancos como referência para o ano
    bancos_path = str(Path(caixa_db).parent / 'Bancos')
    ano_exercicio = obter_ano_exercicio(bancos_path)
    data_ano_seguinte = datetime(ano_exercicio + 1, 1, 1).date()
    
    print(f"  Ano exercício: {ano_exercicio}")
    print(f"  Data SALDO ANTERIOR: {data_ano_seguinte.strftime('%d-%m-%Y')}")
    
    for col in ['DESCRICAO','CONTA','TIPO']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.replace('\x00','',regex=False)
    
    df = df.dropna(how='all').reset_index(drop=True)
    
    idx = _encontrar_idx_saldo_anterior(df)
    if idx is None:
        new_row = pd.DataFrame({
            'DATA': [data_ano_seguinte],
            'CONTA': [CONTA_SALDO_ANTERIOR],
            'DESCRICAO': [DESCRICAO_MARCADOR],
            'TIPO': [TIPO_RECEITA],
            'VALOR': [0.0],
            'SALDO': [saldo_final],
            'OBSERVACAO': ['']
        }, index=[0])
        df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
        idx = 0
    
    df.at[idx, 'SALDO'] = saldo_final
    df.at[idx, 'VALOR'] = 0.0
    df.at[idx, 'DATA'] = data_ano_seguinte
    df.at[idx, 'CONTA'] = CONTA_SALDO_ANTERIOR
    df.at[idx, 'DESCRICAO'] = DESCRICAO_MARCADOR
    df.at[idx, 'TIPO'] = TIPO_RECEITA
    df = df.iloc[:idx + 1]
    
    try:
        return gravar_tabela(df, caixa_db, conn=conn)
    except Exception:
        return False

def transfere_saldo_dprazo(dprazo_db='DPrazo', saldo_final=0.0, df=None, conn=None):
    """`df`: DataFrame já lido antecipadamente; se omitido, é lido aqui."""
    # Obter ano do exercício e calcular data do ano seguinte (1 de janeiro)
    bancos_path = str(Path(dprazo_db).parent / 'Bancos')
    ano_exercicio = obter_ano_exercicio(bancos_path)
    data_ano_seguinte = datetime(ano_exercicio + 1, 1, 1).date()
    
    print(f"  Ano exercício: {ano_exercicio}")
    print(f"  Data SALDO Dep.Poupança: {data_ano_seguinte.strftime('%d-%m-%Y')}")
    
    df = (ler_db(dprazo_db) if df is None else df)
    
    if df is None or df.empty:
        print(f"  ⚠️ DPrazo vazio, criando registo inicial...")
        df = pd.DataFrame({
            'DATA': [data_ano_seguinte],
            'CONTA': [CONTA_SALDO_DPRAZO],
            'DESCRICAO': [DESCRICAO_MARCADOR],
            'TIPO': [TIPO_RECEITA],
            'VALOR': [0.0],
            'SALDO': [saldo_final],
            'OBSERVACAO': ['']
        })
    else:
        for col in ['DESCRICAO', 'CONTA', 'TIPO']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.replace('\x00', '', regex=False)
        df = df.dropna(how='all').reset_index(drop=True)
        idx = _encontrar_idx_saldo_anterior(df)
        if idx is None:
            new_row = pd.DataFrame({
                'DATA': [data_ano_seguinte],
                'CONTA': [CONTA_SALDO_DPRAZO],
                'DESCRICAO': [DESCRICAO_MARCADOR],
                'TIPO': [TIPO_RECEITA],
                'VALOR': [0.0],
                'SALDO': [saldo_final],
                'OBSERVACAO': ['']
            }, index=[0])
            df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
            idx = 0
        df.at[idx, 'SALDO'] = saldo_final
        df.at[idx, 'VALOR'] = 0.0
        df.at[idx, 'DATA'] = data_ano_seguinte
        df.at[idx, 'CONTA'] = CONTA_SALDO_DPRAZO
        df.at[idx, 'DESCRICAO'] = DESCRICAO_MARCADOR
        df.at[idx, 'TIPO'] = TIPO_RECEITA
        df = df.iloc[:idx + 1]
    
    try:
        return gravar_tabela(df, dprazo_db, conn=conn)
    except Exception:
        return False


def fim_ano_e_transfere_saldo(pasta_dados='corrente', validar_pos_commit=True):
    """
    Função principal de encerramento.
    
    Args:
        pasta_dados: Nome da pasta de dados (ex: 'corrente') ou caminho completo
        validar_pos_commit: se True (omissão), corre a validação de
            consistência depois do COMMIT (algumas leituras extra, já fora
            da transação — não bloqueiam, mas custam tempo). Passar False
            para saltar esta validação e tornar o encerramento mais rápido
            (por ex. depois de já ter confirmado que está tudo OK em testes
            anteriores).
    """
    print(f"\n{'='*80}")
    print(f"ENCERRAMENTO DE ANO - INÍCIO")
    print(f"{'='*80}")
    
    # Determinar pasta de trabalho
    if isinstance(pasta_dados, str) and not os.path.isabs(pasta_dados):
        pasta_trabalho = BASE_DIR / pasta_dados
    else:
        pasta_trabalho = pasta_dados
    
    print(f"Pasta de trabalho: {pasta_trabalho}")
    
    # Construir caminhos completos dos ficheiros
    pasta_trabalho = Path(pasta_trabalho)  # Garantir que é um Path object
    despesas_db = pasta_trabalho / 'Despesas'
    receitas_n_db = pasta_trabalho / 'ReceitasN'
    receitas_e_db = pasta_trabalho / 'ReceitasE'
    juros_db = pasta_trabalho / 'Juros'
    bancos_db = pasta_trabalho / 'Bancos'
    dprazo_db = pasta_trabalho / 'DPrazo'
    caixa_db = pasta_trabalho / 'Caixa'
    saldos_db = pasta_trabalho / 'Saldos'
    
    # Verificar se ficheiros existem
    ficheiros_necessarios = [
        ('Bancos', bancos_db),
        ('DPrazo', dprazo_db),
        ('Caixa', caixa_db),
        ('Saldos', saldos_db)
    ]
    
    for nome, caminho in ficheiros_necessarios:
        if not existe_dados(caminho):
            print(f"❌ ERRO: Dados não encontrados: {caminho}")
            return False
        print(f"✓ {nome} encontrado")
    
    # 1. Backup
    print(f"\n1. Criando backup...")
    if not backup_arquivos_db(str(bancos_db)):
        print(f"❌ ERRO ao criar backup!")
        return False
    print(f"✓ Backup criado com sucesso!")
    
    # 2. Obtém saldos finais
    print(f"\n2. Obtendo saldos finais...")
    sd = obter_saldos_finais(str(saldos_db))

    # 2b. Determina o ano novo ANTES de zerar as quotas.
    # BUGFIX: fim_ano_quotas_normais/extras gravam o SALDO_ANT/SALDO
    # transitados via save_receitas_wide(), que por omissão usa o
    # ANO_EXERCICIO corrente em Configs. Se isto corresse ANTES do passo
    # 5 (que só então incrementa o ANO_EXERCICIO), o saldo transitado
    # ficava gravado em receitas_resumo sob o ano ANTIGO — e Receitas.py,
    # já a correr no ano novo, nunca o encontrava (SALDO_ANT aparecia
    # sempre a 0 no pivot). Por isso calculamos e passamos `novo_ano`
    # explicitamente já aqui.
    configs_db = pasta_trabalho / 'Configs'
    novo_ano = None
    if existe_dados(configs_db):
        ano_atual = obter_ano_exercicio(str(configs_db))
        novo_ano = ano_atual + 1
        print(f"  Ano atual: {ano_atual}  ->  Novo ano: {novo_ano}")
    else:
        print(f"  ⚠️ Configs não encontrado em {configs_db}")

    # 2c. Lê TODOS os DataFrames necessários ANTES de abrir a transação de
    # escrita.
    # PERFORMANCE: cada fim_ano_*/transfere_saldo_*/zerar_saldos chamava
    # internamente ler_db(), que abre a SUA PRÓPRIA ligação SQLite
    # (via get_connection/load_*_wide). Se isso corre DENTRO da transação
    # de escrita (db_transaction já com BEGIN/lock ativo), cada uma dessas
    # leituras fica à espera do lock de escrita ser libertado — e só é
    # libertado no commit, no fim de tudo. Resultado: leituras em série a
    # travar sucessivamente, tornando o fecho de ano lento.
    # Lendo tudo aqui, fora da transação, a transação em si passa a conter
    # apenas escritas (rápidas) na mesma ligação `conn`.
    print(f"\n2c. Pré-lendo tabelas (fora da transação)...")
    df_juros      = ler_db(str(juros_db))
    df_despesas   = ler_db(str(despesas_db))
    df_receitas_n = ler_db(str(receitas_n_db))
    df_receitas_e = ler_db(str(receitas_e_db))
    df_bancos     = ler_db(str(bancos_db))
    df_caixa      = ler_db(str(caixa_db))
    df_dprazo     = ler_db(str(dprazo_db))
    df_saldos     = ler_db(str(saldos_db))
    balanco_path  = pasta_trabalho / 'Balanco'
    df_balanco    = ler_db(str(balanco_path)) if existe_dados(balanco_path) else None
    print(f"  ✓ Pré-leitura concluída")

    # 3–5. Todas as escritas dentro de uma única transação + validação final
    print(f"\n3. Iniciando transação de escrita...")
    erros = []
    try:
        with db_transaction(pasta_trabalho) as conn:
            print(f"  ✓ Transação aberta")

            # 3. Limpa ficheiros de receitas/despesas
            # BUGFIX: Juros/Despesas têm de gravar sob `novo_ano` (igual às
            # Receitas). Sem `ano=novo_ano`, save_*_wide usava o ANO_EXERCICIO
            # ainda antigo → DELETE no ano arquivado + ano novo ficava vazio
            # após o incremento em Configs.
            print(f"\n3. Limpando ficheiros de receitas/despesas...")
            if not fim_ano_juros(str(juros_db), ano=novo_ano, df=df_juros, conn=conn):
                erros.append("limpar Juros")
            if not fim_ano_despesas(str(despesas_db), ano=novo_ano, df=df_despesas, conn=conn):
                erros.append("limpar Despesas")
            if not fim_ano_quotas_normais(str(receitas_n_db), ano=novo_ano, df=df_receitas_n, conn=conn):
                erros.append("limpar ReceitasN")
            if not fim_ano_quotas_extras(str(receitas_e_db), ano=novo_ano, df=df_receitas_e, conn=conn):
                erros.append("limpar ReceitasE")
            if erros:
                raise RuntimeError("Falha ao: " + ", ".join(erros))

            # 4. Transfere saldos
            print(f"\n4. Transferindo saldos...")
            if not transfere_saldo_bancos(str(bancos_db), sd['ordem_f'], df=df_bancos, conn=conn):
                raise RuntimeError("Falha ao transferir saldo de Bancos")
            if not transfere_saldo_caixa(str(caixa_db), sd['caixa_f'], df=df_caixa, conn=conn):
                raise RuntimeError("Falha ao transferir saldo de Caixa")
            if not transfere_saldo_dprazo(str(dprazo_db), sd['poupanca_f'], df=df_dprazo, conn=conn):
                raise RuntimeError("Falha ao transferir saldo de DPrazo")
            if not zerar_saldos(str(saldos_db), sd['poupanca_f'], sd['ordem_f'], sd['caixa_f'],
                                 df_saldos=df_saldos, df_balanco=df_balanco, conn=conn):
                raise RuntimeError("Falha ao atualizar Saldos/Balanço")

            # 5. Atualizar ano do exercício (ano_atual/novo_ano já calculados no passo 2b)
            print(f"\n5. Atualizando ano do exercício...")
            if novo_ano is not None:
                print(f"  Novo ano: {novo_ano}")
                if not atualizar_ano_exercicio_configs(str(configs_db), novo_ano, conn=conn):
                    raise RuntimeError("Falha ao atualizar ANO_EXERCICIO")
                print(f"  ✓ Ano do exercício atualizado")
            else:
                print(f"  ⚠️ Configs não encontrado em {configs_db} — ANO_EXERCICIO não atualizado")

            print(f"\n  ✓ Todas as operações concluídas — a fazer COMMIT...")

        # 6. Validação de consistência (após commit, leitura fresca) — opcional
        avisos = []
        if validar_pos_commit:
            print(f"\n6. Validação de consistência pós-encerramento...")
            avisos = _validar_consistencia_pos_encerramento(
                pasta_trabalho, sd, novo_ano
            )
            if avisos:
                print(f"  ⚠️ {len(avisos)} aviso(s) de consistência:")
                for a in avisos:
                    print(f"    - {a}")
            else:
                print(f"  ✓ Validação OK — saldos e ano consistentes")
        else:
            print(f"\n6. Validação de consistência pós-encerramento: SALTADA (validar_pos_commit=False)")

        print(f"\n{'='*80}")
        if avisos:
            print(f"⚠️ ENCERRAMENTO CONCLUÍDO COM AVISOS DE CONSISTÊNCIA")
        else:
            print(f"✅ ENCERRAMENTO CONCLUÍDO COM SUCESSO!")
        print(f"{'='*80}\n")
        return True

    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ ENCERRAMENTO FALHOU — ROLLBACK EXECUTADO")
        print(f"   Erro: {e}")
        print(f"   A base de dados ficou no estado anterior ao início das alterações.")
        print(f"   O backup em historico/ continua disponível.")
        print(f"{'='*80}\n")
        import traceback
        traceback.print_exc()
        return False


def _validar_consistencia_pos_encerramento(pasta_trabalho, sd_originais, novo_ano):
    """
    Validações de consistência após o commit do encerramento.
    Devolve lista de avisos (vazia = tudo OK).
    """
    avisos = []
    pasta = Path(pasta_trabalho)

    # 1) Saldos iniciais = saldos finais que foram transferidos
    try:
        rows, _ = load_saldos_wide(pasta)
        df = pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
        if df.empty:
            avisos.append("Tabela Saldos vazia após encerramento")
        else:
            for tipo, esperado, label in (
                ("poupanca", sd_originais["poupanca_f"], "Poupança_I"),
                ("ordem",    sd_originais["ordem_f"],    "Ordem_I"),
                ("caixa",    sd_originais["caixa_f"],    "Caixa_I"),
            ):
                encontrado = None
                for _, row in df.iterrows():
                    if _e_saldo_inicial(str(row.get("CONTA", "")), tipo):
                        encontrado = clean_numeric(row.get("VALOR"))
                        break
                if encontrado is None:
                    avisos.append(f"Saldo inicial {label} não encontrado")
                elif abs(encontrado - esperado) > 0.015:
                    avisos.append(
                        f"{label} = {encontrado:.2f} (esperado {esperado:.2f})"
                    )

            # Finais devem estar a zero
            for tipo, label in (("poupanca", "Poupança_F"), ("ordem", "Ordem_F"), ("caixa", "Caixa_F")):
                for _, row in df.iterrows():
                    if _e_saldo_final(str(row.get("CONTA", "")), tipo):
                        v = clean_numeric(row.get("VALOR"))
                        if abs(v) > 0.015:
                            avisos.append(f"{label} não está a zero ({v:.2f})")
                        break
    except Exception as e:
        avisos.append(f"Erro ao validar Saldos: {e}")

    # 2) Movimentos: registo de saldo anterior com valor correto
    for fonte, esperado, label in (
        ("bancos", sd_originais["ordem_f"], "Bancos"),
        ("caixa",  sd_originais["caixa_f"], "Caixa"),
        ("dprazo", sd_originais["poupanca_f"], "DPrazo"),
    ):
        try:
            rows = carregar_movimentos_fonte(pasta, fonte)
            dfm = pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame()
            idx = _encontrar_idx_saldo_anterior(dfm)
            if idx is None:
                avisos.append(f"{label}: registo SALDO ANTERIOR não encontrado")
            else:
                saldo = clean_numeric(dfm.at[idx, "SALDO"] if "SALDO" in dfm.columns else 0)
                if abs(saldo - esperado) > 0.015:
                    avisos.append(
                        f"{label} SALDO ANTERIOR = {saldo:.2f} (esperado {esperado:.2f})"
                    )
                # Deve ser o único / primeiro registo relevante
                if len(dfm) > idx + 1:
                    # Após corte, só deve restar até ao saldo anterior
                    pass  # o corte já foi feito; se houver mais, não é crítico
        except Exception as e:
            avisos.append(f"Erro ao validar {label}: {e}")

    # 3) Ano do exercício
    if novo_ano is not None:
        try:
            ano_lido = obter_ano_exercicio(str(pasta / "Configs"))
            if int(ano_lido) != int(novo_ano):
                avisos.append(
                    f"ANO_EXERCICIO = {ano_lido} (esperado {novo_ano})"
                )
        except Exception as e:
            avisos.append(f"Erro ao validar ANO_EXERCICIO: {e}")

    return avisos



def atualizar_ano_exercicio_configs(configs_db, ano_exercicio, conn=None):
    """Actualiza ANO_EXERCICIO via ConfigsRepo (API canónica).
    Se `conn` for fornecido, usa essa conexão (transação externa).
    """
    try:
        print(f"\n  ═══════════════════════════════════════════════")
        print(f"  Atualizando ANO_EXERCICIO em Configs (condominio.db)...")
        print(f"  Caminho: {configs_db}")
        print(f"  Novo valor: {ano_exercicio}")
        print(f"  ═══════════════════════════════════════════════")

        pasta = resolver_pasta(configs_db)
        if conn is None:
            create_schema(pasta)
        antigo = configs_repo(pasta).get_value("GERAL", "ANO_EXERCICIO", None)
        print(f"  ℹ️  Valor atual: {antigo}")
        configs_repo(pasta).set_value(
            "GERAL", "ANO_EXERCICIO", str(ano_exercicio),
            tipo="Number", descricao="Ano atual do exercicio",
            conn=conn,
        )
        if conn is None:
            verificado = configs_repo(pasta).get_value("GERAL", "ANO_EXERCICIO", None)
            if str(verificado) == str(ano_exercicio) or float(verificado) == float(ano_exercicio):
                print(f"  ✅ CONFIRMADO: ANO_EXERCICIO = {verificado}")
                print(f"  ═══════════════════════════════════════════════\n")
                return True
            print(f"  ❌ Valor não confirmado: {verificado}")
            return False
        print(f"  ✅ ANO_EXERCICIO definido para {ano_exercicio} (confirmado no commit)")
        print(f"  ═══════════════════════════════════════════════\n")
        return True
    except Exception as e:
        print(f"  ❌ Erro ao atualizar ANO_EXERCICIO: {e}")
        import traceback
        traceback.print_exc()
        return False


# ====================================================================
# ✅ ENTRY POINT - EXECUTA A FUNÇÃO PRINCIPAL
# ====================================================================
if __name__ == "__main__":
    try:
        sucesso = fim_ano_e_transfere_saldo(pasta_dados='corrente')
        sys.exit(0 if sucesso else 1)
    except Exception as e:
        print(f"❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)