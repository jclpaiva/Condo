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
    # ✅ CORRIGIDO
    obter_ano_exercicio,
)

from Logging_utils import ativar_logging
from Database import carregar_db, salvar_db, existe_dados

logger = ativar_logging("Fim_Ano")

class PrintToLogger:
    def write(self, msg):
        msg = msg.rstrip()
        if msg:
            logger.info(msg)

    def flush(self):
        pass

sys.stdout = PrintToLogger()
sys.stderr = PrintToLogger()

PASTA_CORRENTE = BASE_DIR / "corrente"
PASTA_HISTORICO = BASE_DIR / "historico"

def clean_numeric(value):
    """Retorna 0.0 se o valor for NaN ou None."""
    return 0.0 if pd.isna(value) else float(value)

def ler_db(path):
    try:
        rows, _ = carregar_db(path)
        return pd.DataFrame(rows, dtype=object)
    except Exception:
        return None
        
def salvar_db(df, path, field_specs):
    """
    Delegação explícita para o bridge central de compatibilidade.
    Mantém a API local do módulo; a escrita vai para condominio.db.
    """
    return salvar_db_compat(df, path, field_specs)

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
        
        rows, _ = carregar_db(saldos_db)
        df = pd.DataFrame(rows, dtype=object)
        print(f"Registos lidos: {len(df)}")
        
        if df.empty:
            print("⚠️ Ficheiro vazio!")
            return {'poupanca_f': 0.0, 'ordem_f': 0.0, 'caixa_f': 0.0, 'total': 0.0}
        
        print(f"Colunas disponíveis: {list(df.columns)}")
        print(f"\nContas encontradas:")
        for idx, row in df.iterrows():
            print(f"  {row['CONTA']}: {row['VALOR']}")
        
        def obter_valor(*patterns):
            """Procura CONTA que contenha algum dos padrões (case-insensitive)."""
            conta_up = df['CONTA'].astype(str).str.upper()
            for pattern in patterns:
                pat = pattern.upper()
                mascara = conta_up.str.contains(pat, na=False, regex=False)
                if mascara.any():
                    valor = clean_numeric(df[mascara].iloc[0]['VALOR'])
                    print(f"  Padrão '{pattern}' encontrado em '{df[mascara].iloc[0]['CONTA']}': {valor}")
                    return valor
            print(f"  Padrões {patterns} NÃO encontrados")
            return 0.0

        print("\nBuscando saldos finais:")
        # Nomes reais: "Depósito Poupança_F", "Depósito Ordem_F", "Numerário Caixa_F"
        poupanca_f = obter_valor('POUPANÇA_F', 'POUPANCA_F', 'POUPANÇA F', 'POUPANCA F')
        ordem_f = obter_valor('ORDEM_F', 'ORDEM F', 'DEPÓSITO ORDEM_F', 'DEPOSITO ORDEM_F')
        caixa_f = obter_valor('CAIXA_F', 'CAIXA F', 'NUMERÁRIO CAIXA_F', 'NUMERARIO CAIXA_F')
        
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

def zerar_saldos(saldos_db='Saldos', poupanca_novo=0.0, ordem_novo=0.0, caixa_novo=0.0):
    """
    Atualiza saldos iniciais com os valores fornecidos e zera os saldos finais.
    Usa o bridge de compatibilidade do projeto: tenta SQLite sempre que o
    base de dados condominio.db existe na pasta de trabalho.
    """
    print(f"\n=== ZERAR_SALDOS ===")
    print(f"Ficheiro: {saldos_db}")
    print(f"Valores recebidos:")
    print(f"  Poupança_novo: {poupanca_novo:.2f} €")
    print(f"  Ordem_novo: {ordem_novo:.2f} €")
    print(f"  Caixa_novo: {caixa_novo:.2f} €")

    # 1) Atualiza Saldos via dataframe com fallback comum
    try:
        df = ler_db(saldos_db)
        if df is None or df.empty:
            print(f"⚠️ Saldos vazio ou não legível: {saldos_db}")
            return False

        print(f"\nAtualizando Saldos...")
        for idx, row in df.iterrows():
            conta = str(row.get('CONTA', '')).strip().upper()
            if 'POUPANCA_I' in conta or 'POUPANÇA_I' in conta:
                print(f"  ✓ Atualizando {conta}: {poupanca_novo:.2f}")
                df.at[idx, 'VALOR'] = round(poupanca_novo, 2)
            elif 'ORDEM_I' in conta:
                print(f"  ✓ Atualizando {conta}: {ordem_novo:.2f}")
                df.at[idx, 'VALOR'] = round(ordem_novo, 2)
            elif 'CAIXA_I' in conta or 'NUMERARIO_I' in conta:
                print(f"  ✓ Atualizando {conta}: {caixa_novo:.2f}")
                df.at[idx, 'VALOR'] = round(caixa_novo, 2)

            if 'POUPANCA_F' in conta or 'POUPANÇA_F' in conta or 'ORDEM_F' in conta or 'CAIXA_F' in conta:
                print(f"  ✓ Zerando {conta}")
                df.at[idx, 'VALOR'] = 0.0

            if conta == 'JUROS' or 'SALDO EXERCICIO' in conta or 'SALDO EXERCÍCIO' in conta or conta == 'SALDO FINAL':
                print(f"  ✓ Zerando {conta}")
                df.at[idx, 'VALOR'] = 0.0

        specs = 'CONTA C(50);DESCRICAO C(50);TIPO C(10);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(30)'
        if not salvar_db(df, saldos_db, specs):
            raise RuntimeError('salvar_db falhou para Saldos')

        print(f"✅ Saldos atualizado com sucesso!")
    except Exception as e:
        print(f"❌ ERRO ao atualizar Saldos: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 2) Atualiza Balanco com o mesmo bridge
    try:
        balanco_path = Path(saldos_db).parent / 'Balanco'
        print(f"\nAtualizando Balanco em: {balanco_path}")

        if not existe_dados(balanco_path):
            print(f"  ⚠️ Balanco não encontrado, a saltar atualização")
            return True

        df_bal = ler_db(str(balanco_path))
        if df_bal is None or df_bal.empty:
            print(f"  ⚠️ Balanco vazio, a saltar atualização")
            return True

        # zera tudo primeiro
        for idx, row in df_bal.iterrows():
            if 'VALOR' in df_bal.columns:
                df_bal.at[idx, 'VALOR'] = 0.0

        # atualiza os saldos iniciais
        for idx, row in df_bal.iterrows():
            conta = str(row.get('CONTA', '')).strip().upper().replace('Ç','C').replace('Ã','A')
            if 'A)' in conta and 'POUPAN' in conta:
                print(f"  ✓ Atualizando {row.get('CONTA')}: {poupanca_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(poupanca_novo, 2)
            elif 'B)' in conta and 'ORDEM' in conta:
                print(f"  ✓ Atualizando {row.get('CONTA')}: {ordem_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(ordem_novo, 2)
            elif 'C)' in conta and ('CAIXA' in conta or 'NUMERARIO' in conta):
                print(f"  ✓ Atualizando {row.get('CONTA')}: {caixa_novo:.2f}")
                df_bal.at[idx, 'VALOR'] = round(caixa_novo, 2)

        specs_bal = 'CONTA C(50);DESCRICAO C(50);TIPO C(10);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(30)'
        if not salvar_db(df_bal, str(balanco_path), specs_bal):
            raise RuntimeError('salvar_db falhou para Balanco')

        print(f"✅ Balanco atualizado com sucesso!")
    except Exception as e:
        print(f"❌ ERRO ao atualizar Balanco: {e}")
        import traceback
        traceback.print_exc()

    return True

def fim_ano_juros(juros_db='Juros'):
    df = ler_db(juros_db)
    if df is None or df.empty:
        return True  # já vazio — nada a limpar
    
    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0
    
    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    
    specs = 'JUROS C(50);JAN N(10,2);FEV N(10,2);MAR N(10,2);ABR N(10,2);MAI N(10,2);JUN N(10,2);JUL N(10,2);AGO N(10,2);SET N(10,2);OUT N(10,2);NOV N(10,2);DEZ N(10,2);TOTAL N(10,2)'
    return salvar_db(df, juros_db, specs)

def fim_ano_despesas(despesas_db='Despesas'):
    df = ler_db(despesas_db)
    if df is None or df.empty:
        return True  # já vazio — nada a limpar
    
    meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    for mes in meses:
        if mes in df.columns:
            df[mes] = 0.0
    
    if 'TOTAL' in df.columns:
        df['TOTAL'] = 0.0
    
    specs = 'DESPESAS C(50);JAN N(10,2);FEV N(10,2);MAR N(10,2);ABR N(10,2);MAI N(10,2);JUN N(10,2);JUL N(10,2);AGO N(10,2);SET N(10,2);OUT N(10,2);NOV N(10,2);DEZ N(10,2);TOTAL N(10,2)'
    return salvar_db(df, despesas_db, specs)

def fim_ano_quotas_normais(receitas_n_db='ReceitasN'):
    df = ler_db(receitas_n_db)
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
        df['SALDO'] = df['SALDO_ANT'].copy()
    
    specs = 'FRACCAO C(30);SALDO_ANT N(10,2);JAN N(10,2);FEV N(10,2);MAR N(10,2);ABR N(10,2);MAI N(10,2);JUN N(10,2);JUL N(10,2);AGO N(10,2);SET N(10,2);OUT N(10,2);NOV N(10,2);DEZ N(10,2);TOTAL N(10,2);SALDO N(10,2)'
    return salvar_db(df, receitas_n_db, specs)

def fim_ano_quotas_extras(receitas_e_db='ReceitasE'):
    df = ler_db(receitas_e_db)
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
        df['SALDO'] = df['SALDO_ANT'].copy()
    
    specs = 'FRACCAO C(30);SALDO_ANT N(10,2);JAN N(10,2);FEV N(10,2);MAR N(10,2);ABR N(10,2);MAI N(10,2);JUN N(10,2);JUL N(10,2);AGO N(10,2);SET N(10,2);OUT N(10,2);NOV N(10,2);DEZ N(10,2);TOTAL N(10,2);SALDO N(10,2)'
    return salvar_db(df, receitas_e_db, specs)

def transfere_saldo_bancos(bancos_db='Bancos', saldo_final=0.0):
    df = ler_db(bancos_db)
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
    
    idx_saldo = df[(df['CONTA'].str.upper().str.contains('SALDO ANTERIOR',na=False))&
                   (df['DESCRICAO'].str.contains(r'\*{3}',na=False))&
                   (df['TIPO'].str.upper()=='RECEITA')].index
    
    if not idx_saldo.empty:
        idx = idx_saldo[0]
    else:
        new_row = pd.DataFrame({
            'DATA':[data_ano_seguinte],
            'CONTA':['SALDO ANTERIOR'],
            'DESCRICAO':['***'],
            'TIPO':['RECEITA'],
            'VALOR':[0.0],
            'SALDO':[saldo_final],
            'OBSERVACAO':['']
        }, index=[0])
        df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
        idx = 0
    
    df.at[idx,'SALDO'] = saldo_final
    df.at[idx,'VALOR'] = 0.0
    df.at[idx,'DATA'] = data_ano_seguinte  # Atualizar também se já existir
    df = df.iloc[:idx+1]
    
    try:
        specs = 'DATA D;TIPO C(10);CONTA C(30);DESCRICAO C(30);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(32)'
        return salvar_db(df, bancos_db, specs)
    except Exception as e:
        print(f"  ❌ Erro ao transferir saldo Bancos: {e}")
        import traceback
        traceback.print_exc()
        return False

def transfere_saldo_caixa(caixa_db='Caixa', saldo_final=0.0):
    df = ler_db(caixa_db)
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
    
    idx_saldo = df[(df['CONTA'].str.upper().str.contains('SALDO ANTERIOR',na=False))&
                   (df['DESCRICAO'].str.contains(r'\*{3}',na=False))&
                   (df['TIPO'].str.upper()=='RECEITA')].index
    
    if not idx_saldo.empty:
        idx = idx_saldo[0]
    else:
        new_row = pd.DataFrame({
            'DATA':[data_ano_seguinte],
            'CONTA':['SALDO ANTERIOR'],
            'DESCRICAO':['***'],
            'TIPO':['RECEITA'],
            'VALOR':[0.0],
            'SALDO':[saldo_final],
            'OBSERVACAO':['']
        }, index=[0])
        df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
        idx = 0
    
    df.at[idx,'SALDO'] = saldo_final
    df.at[idx,'VALOR'] = 0.0
    df.at[idx,'DATA'] = data_ano_seguinte  # Atualizar também se já existir
    df = df.iloc[:idx+1]
    
    try:
        specs = 'DATA D;TIPO C(10);CONTA C(30);DESCRICAO C(30);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(30)'
        return salvar_db(df, caixa_db, specs)
    except:
        return False

def transfere_saldo_dprazo(dprazo_db='DPrazo', saldo_final=0.0):
    # Obter ano do exercício e calcular data do ano seguinte (1 de janeiro)
    bancos_path = str(Path(dprazo_db).parent / 'Bancos')
    ano_exercicio = obter_ano_exercicio(bancos_path)
    data_ano_seguinte = datetime(ano_exercicio + 1, 1, 1).date()
    
    print(f"  Ano exercício: {ano_exercicio}")
    print(f"  Data SALDO Dep.Poupança: {data_ano_seguinte.strftime('%d-%m-%Y')}")
    
    df = ler_db(dprazo_db)
    
    # ✅ CORRIGIDO: Se ficheiro vazio ou None, criar DataFrame novo com registo inicial
    if df is None or df.empty:
        print(f"  ⚠️ DPrazo vazio, criando registo inicial...")
        df = pd.DataFrame({
            'DATA': [data_ano_seguinte],
            'CONTA': ['SALDO Dep.Poupança'],
            'DESCRICAO': ['***'],
            'TIPO': ['RECEITA'],
            'VALOR': [0.0],
            'SALDO': [saldo_final],
            'OBSERVACAO': ['']
        })
    else:
        # Ficheiro tem dados, processar normalmente
        for col in ['DESCRICAO','CONTA','TIPO']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.replace('\x00','',regex=False)
        
        df = df.dropna(how='all').reset_index(drop=True)
        
        idx_saldo = df[(df['CONTA'].str.upper().str.contains('SALDO ANTERIOR',na=False))&
                       (df['DESCRICAO'].str.contains(r'\*{3}',na=False))&
                       (df['TIPO'].str.upper()=='RECEITA')].index
        
        if not idx_saldo.empty:
            idx = idx_saldo[0]
        else:
            new_row = pd.DataFrame({
                'DATA':[data_ano_seguinte],
                'CONTA':['SALDO Dep.Poupança'],
                'DESCRICAO':['***'],
                'TIPO':['RECEITA'],
                'VALOR':[0.0],
                'SALDO':[saldo_final],
                'OBSERVACAO':['']
            }, index=[0])
            df = pd.concat([new_row, df.iloc[0:]]).reset_index(drop=True)
            idx = 0
        
        df.at[idx,'SALDO'] = saldo_final
        df.at[idx,'VALOR'] = 0.0
        df.at[idx,'DATA'] = data_ano_seguinte
        df = df.iloc[:idx+1]
    
    try:
        specs = 'DATA D;TIPO C(10);CONTA C(30);DESCRICAO C(30);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(30)'
        return salvar_db(df, dprazo_db, specs)
    except:
        return False


def fim_ano_e_transfere_saldo(pasta_dados='corrente'):
    """
    Função principal de encerramento.
    
    Args:
        pasta_dados: Nome da pasta de dados (ex: 'corrente') ou caminho completo
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
    
    # 3. Limpa ficheiros
    print(f"\n3. Limpando ficheiros de receitas/despesas...")
    suc = fim_ano_juros(str(juros_db))
    suc &= fim_ano_despesas(str(despesas_db))
    suc &= fim_ano_quotas_normais(str(receitas_n_db))
    suc &= fim_ano_quotas_extras(str(receitas_e_db))
    
    if not suc:
        print(f"⚠️ Aviso: Alguns ficheiros podem não ter sido limpos")
    
    # 4. Transfere saldos
    print(f"\n4. Transferindo saldos...")
    suc &= transfere_saldo_bancos(str(bancos_db), sd['ordem_f'])
    suc &= transfere_saldo_caixa(str(caixa_db), sd['caixa_f'])
    suc &= transfere_saldo_dprazo(str(dprazo_db), sd['poupanca_f'])
    suc &= zerar_saldos(str(saldos_db), sd['poupanca_f'], sd['ordem_f'], sd['caixa_f'])
    
    # 5. Atualizar ano do exercício no Configs (APÓS todas as transferências!)
    print(f"\n5. Atualizando ano do exercício...")
    configs_db = pasta_trabalho / 'Configs'
    if existe_dados(configs_db):
        # Obter ano atual ANTES da atualização
        ano_atual = obter_ano_exercicio(str(configs_db))
        novo_ano = ano_atual + 1
        print(f"  Ano atual: {ano_atual}")
        print(f"  Novo ano: {novo_ano}")
        if atualizar_ano_exercicio_configs(str(configs_db), novo_ano):
            print(f"  ✓ Ano do exercício atualizado com sucesso!")
        else:
            print(f"  ⚠️ Aviso: Erro ao atualizar ano do exercício")
            suc = False
    else:
        print(f"  ⚠️ Configs não encontrado em {configs_db}")
    
    
    print(f"\n{'='*80}")
    if suc:
        print(f"✅ ENCERRAMENTO CONCLUÍDO COM SUCESSO!")
    else:
        print(f"⚠️ ENCERRAMENTO CONCLUÍDO COM AVISOS")
    print(f"{'='*80}\n")
    
    return suc

def atualizar_ano_exercicio_configs(configs_db, ano_exercicio):
    """
    Atualiza ANO_EXERCICIO em condominio.db.configs (via bridge carregar/salvar).
    """
    try:
        print(f"\n  ═══════════════════════════════════════════════")
        print(f"  Atualizando ANO_EXERCICIO em Configs (condominio.db)...")
        print(f"  Caminho: {configs_db}")
        print(f"  Novo valor: {ano_exercicio}")
        print(f"  ═══════════════════════════════════════════════")

        # Preferir API relacional directa
        try:
            from Database import configs as cfg_repo, create_schema
            pasta = Path(configs_db).parent
            create_schema(pasta)
            antigo = cfg_repo(pasta).get_value("GERAL", "ANO_EXERCICIO", None)
            print(f"  ℹ️  Valor atual: {antigo}")
            cfg_repo(pasta).set_value(
                "GERAL", "ANO_EXERCICIO", str(ano_exercicio),
                tipo="Number", descricao="Ano atual do exercicio",
            )
            verificado = cfg_repo(pasta).get_value("GERAL", "ANO_EXERCICIO", None)
            if str(verificado) == str(ano_exercicio) or float(verificado) == float(ano_exercicio):
                print(f"  ✅ CONFIRMADO: ANO_EXERCICIO = {verificado}")
                print(f"  ═══════════════════════════════════════════════\n")
                return True
            print(f"  ❌ Valor não confirmado: {verificado}")
            return False
        except Exception as exc:
            print(f"  ⚠️ API configs falhou ({exc}); a tentar bridge carregar/salvar...")

        rows, _ = carregar_db(configs_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            df = pd.DataFrame([{
                'CATEGORIA': 'GERAL',
                'CHAVE': 'ANO_EXERCICIO',
                'VALOR': str(ano_exercicio),
                'TIPO': 'Number',
                'DESCRICAO': 'Ano atual do exercicio'
            }])
        else:
            if 'CATEGORIA' not in df.columns:
                df.columns = [c.upper() for c in df.columns]
            mask = df['CATEGORIA'].astype(str).str.strip().str.upper().eq('GERAL') & \
                   df['CHAVE'].astype(str).str.strip().str.upper().eq('ANO_EXERCICIO')
            if mask.any():
                valor_antigo = str(df.loc[mask, 'VALOR'].iloc[0]).strip()
                print(f"  ℹ️  Valor atual: {valor_antigo}")
                df.loc[mask, 'VALOR'] = str(ano_exercicio)
            else:
                df = pd.concat([df, pd.DataFrame([{
                    'CATEGORIA': 'GERAL',
                    'CHAVE': 'ANO_EXERCICIO',
                    'VALOR': str(ano_exercicio),
                    'TIPO': 'Number',
                    'DESCRICAO': 'Ano atual do exercicio'
                }])], ignore_index=True)

        ok = salvar_db_compat(df, configs_db, None)
        if not ok:
            raise RuntimeError('salvar_db falhou para Configs')

        rows_check, _ = carregar_db(configs_db)
        df_check = pd.DataFrame(rows_check, dtype=object)
        mask_check = df_check['CATEGORIA'].astype(str).str.strip().str.upper().eq('GERAL') & \
                     df_check['CHAVE'].astype(str).str.strip().str.upper().eq('ANO_EXERCICIO')
        if mask_check.any():
            valor_verificado = str(df_check.loc[mask_check, 'VALOR'].iloc[0]).strip()
            if valor_verificado == str(ano_exercicio):
                print(f"  ✅ CONFIRMADO: ANO_EXERCICIO = {valor_verificado}")
                print(f"  ═══════════════════════════════════════════════\n")
                return True
            print(f"  ❌ Esperado {ano_exercicio}, encontrado {valor_verificado}")
            return False
        print(f"  ❌ ANO_EXERCICIO não encontrado após gravação")
        return False

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