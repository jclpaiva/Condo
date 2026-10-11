"""
Despesas.py - Script para processamento de despesas
Funcionalidades:
- Processa dados de despesas (ex.: de Bancos ou outros)
- Gera Despesas com pivot de contas x meses
- Calcula totais
"""

import os
import sys
import pandas as pd

from collections import defaultdict
from datetime import datetime
from Logging_utils import ativar_logging
from pathlib import Path
from Commons import clean_numeric
from Database import carregar_db, salvar_db

logger = ativar_logging("despesas")

class PrintToLogger:
    def write(self, msg):
        msg = msg.rstrip()
        if msg:
            logger.info(msg)

    def flush(self):
        pass

sys.stdout = PrintToLogger()
sys.stderr = PrintToLogger()

# ====================================================================
# AGLUTINAÇÃO DE MOVIMENTOS (BANCOS + CAIXA)
# ====================================================================
def aglutinar_movimentos(bancos_db_path, caixa_db_path):
    """
    Aglutina movimentos de Bancos e Caixa.
    Retorna DataFrame com: DATA, TIPO, CONTA, VALOR, DESCRICAO, OBSERVACAO
    """
    print(f"\n{'='*80}")
    print("🔄 AGLUTINAÇÃO DE MOVIMENTOS (BANCOS + CAIXA)")
    print(f"{'='*80}")
    df_bancos = pd.DataFrame()
    df_caixa = pd.DataFrame()

    # Carrega Bancos
    try:
        rows_bancos, _ = carregar_db(bancos_db_path)
        df_bancos = pd.DataFrame(rows_bancos, dtype=object)
        print(f"  ✅ Bancos: {len(df_bancos)} registos")
    except FileNotFoundError:
        print(f"  ⚠️  Bancos não encontrado")
    except Exception as e:
        print(f"  ❌ Erro ao ler Bancos: {e}")

    # Carrega Caixa
    try:
        rows_caixa, _ = carregar_db(caixa_db_path)
        df_caixa = pd.DataFrame(rows_caixa, dtype=object)
        print(f"  ✅ Caixa: {len(df_caixa)} registos")
    except FileNotFoundError:
        print(f"  ⚠️  Caixa não encontrado")
    except Exception as e:
        print(f"  ❌ Erro ao ler Caixa: {e}")

    # Une ambos
    if df_bancos.empty and df_caixa.empty:
        print(f"  ❌ ERRO: Nenhum movimento encontrado")
        return pd.DataFrame()

    dfs_to_concat = []
    if not df_bancos.empty:
        # Garantir que todas as colunas necessárias existem
        for col in ['DESCRICAO', 'OBSERVACAO']:
            if col not in df_bancos.columns:
                df_bancos[col] = ""
        df_bancos = df_bancos[['DATA', 'TIPO', 'CONTA', 'DESCRICAO', 'VALOR', 'OBSERVACAO']].copy()
        dfs_to_concat.append(df_bancos)

    if not df_caixa.empty:
        for col in ['DESCRICAO', 'OBSERVACAO']:
            if col not in df_caixa.columns:
                df_caixa[col] = ""
        df_caixa = df_caixa[['DATA', 'TIPO', 'CONTA', 'DESCRICAO', 'VALOR', 'OBSERVACAO']].copy()
        dfs_to_concat.append(df_caixa)

    df_movimentos = pd.concat(dfs_to_concat, ignore_index=True)
    print(f"\n📊 Total aglutinado: {len(df_movimentos)} movimentos")

    # Remove duplicados
    antes = len(df_movimentos)
    df_movimentos = df_movimentos.drop_duplicates(
        subset=['DATA', 'CONTA', 'VALOR'],
        keep='first'
    ).reset_index(drop=True)
    if antes > len(df_movimentos):
        print(f"  🧹 Removidos {antes - len(df_movimentos)} duplicados")

    # Ordena por data
    df_movimentos = df_movimentos.sort_values('DATA').reset_index(drop=True)
    print(f"  ✅ DataFrame final: {len(df_movimentos)} movimentos únicos")
    print(f"{'='*80}\n")
    return df_movimentos

# ====================================================================
# AGREGAR DESPESAS POR CONTA E MÊS
# ====================================================================
#def agregar_despesas_por_mes(df_movimentos):
#    """
#    Agrega despesas por CONTA e MÊS, replicando a lógica do VBA.
#    Aceita DataFrame já aglutinado (Bancos + Caixa).
#    """
    # Filtra apenas DESPESAS
    #df_despesas = df_movimentos[df_movimentos['TIPO'].str.upper().str.strip() == 'DESPESA'].copy()
    
#    df_despesas = df_movimentos[
#        (df_movimentos['TIPO'].str.upper().str.strip() == 'DESPESA') &
#        (~df_movimentos['CONTA'].str.upper().str.contains('DEPÓSITO|DEPOSITO|SALDO ANTERIOR', na=False)) &
#        (~df_movimentos['DESCRICAO'].str.upper().str.contains('DEPÓSITO|DEPOSITO|ENTRADA|CRÉDITO|SALDO INICIAL', na=False)) &
#        (df_movimentos['VALOR'] < 0)  # opcional: garante que é saída (valor negativo)
#    ].copy()
       

#    print(f"DEBUG: {len(df_despesas)} despesas encontradas para processar")
#    if df_despesas.empty:
#        print("AVISO: Nenhuma despesa encontrada")
#        return {}
    
#    Dicionário: {Conta: {mes: valor}}
#    dados_agregados = defaultdict(lambda: defaultdict(float))
#    contas_com_valor = set()
#    for _, row in df_despesas.iterrows():
#      if pd.isna(row['DATA']):
#            continue
#        try:
#            if isinstance(row['DATA'], datetime):
#                mes = row['DATA'].month
#            else:
#                mes = pd.to_datetime(row['DATA']).month
#        except:
#            continue

#      c   onta = str(row['CONTA']).strip()
#      if   not conta or conta == '':
#            continue

#        valor = abs(clean_numeric(row['VALOR']))
#        dados_agregados[conta][mes] += valor
#        contas_com_valor.add(conta)

#    print(f"DEBUG: Agregação concluída. {len(contas_com_valor)} contas com despesas")
#    return dados_agregados


# ====================================================================
# AGREGAR DESPESAS POR CONTA E MÊS (com soma de positivos e negativos)
# ====================================================================
def agregar_despesas_por_mes(df_movimentos):
    """
    Agrega despesas por CONTA e MÊS, somando valores positivos e negativos.
    O valor final por conta/mês será sempre positivo (valor absoluto da soma).
    # Filtra:
    # - todas as DESPESAS
    # - e também as RECEITAS da conta "Manutencao Cgd"
    """

    df_despesas = df_movimentos[
        (
            df_movimentos['TIPO'].str.upper().str.strip() == 'DESPESA'
        ) |
        (
            (df_movimentos['TIPO'].str.upper().str.strip() == 'RECEITA') &
            (df_movimentos['CONTA'].str.upper().str.strip() == 'MANUTENCAO CGD')
        )
    ].copy()
    
    print(f"DEBUG: {len(df_despesas)} despesas encontradas para processar")
    if df_despesas.empty:
        print("AVISO: Nenhuma despesa encontrada")
        return {}
   
    # Dicionário: {Conta: {mes: valor}}
    dados_agregados = defaultdict(lambda: defaultdict(float))
    contas_com_valor = set()

    for _, row in df_despesas.iterrows():
        if pd.isna(row['DATA']):
            continue
            
        try:
            if isinstance(row['DATA'], datetime):
                mes = row['DATA'].month
            else:
                mes = pd.to_datetime(row['DATA']).month
        except:
            continue
            
        conta = str(row['CONTA']).strip()
        if not conta or conta == '':
            continue
            
        valor = clean_numeric(row['VALOR']) if 'clean_numeric' in globals() else row['VALOR']
        
        # Soma com sinal (positivo e negativo)
        dados_agregados[conta][mes] += valor
        contas_com_valor.add(conta)

    # Torna todos os valores finais positivos (absoluto da soma)
    for conta in dados_agregados:
        for mes in dados_agregados[conta]:
            dados_agregados[conta][mes] = abs(dados_agregados[conta][mes])

    print(f"DEBUG: Agregação concluída. {len(contas_com_valor)} contas com despesas")
    return dados_agregados


# ====================================================================
# GERAR TABELA DE DESPESAS
# ====================================================================
def gerar_tabela_despesas(dados_agregados, output_db_path):
    """
    Gera tabela de despesas em SQLite.
    """
    
    if not dados_agregados:
        print("AVISO: Nenhum dado para gerar tabela de despesas")
        return
    
    contas_ordenadas = sorted(dados_agregados.keys())
    print(f"DEBUG: Gerando tabela com {len(contas_ordenadas)} contas")

    field_specs = (
        'DESPESAS C(30); '
        'JAN N(10,2); FEV N(10,2); MAR N(10,2); '
        'ABR N(10,2); MAI N(10,2); JUN N(10,2); '
        'JUL N(10,2); AGO N(10,2); SET N(10,2); '
        'OUT N(10,2); NOV N(10,2); DEZ N(10,2); '
        'TOTAL N(10,2)'
    )

    rows = []
    totais_mensais = [0.0] * 12
    
    for conta in contas_ordenadas:
        valores_mes = dados_agregados[conta]
        jan = valores_mes.get(1, 0.0)
        fev = valores_mes.get(2, 0.0)
        mar = valores_mes.get(3, 0.0)
        abr = valores_mes.get(4, 0.0)
        mai = valores_mes.get(5, 0.0)
        jun = valores_mes.get(6, 0.0)
        jul = valores_mes.get(7, 0.0)
        ago = valores_mes.get(8, 0.0)
        set_val = valores_mes.get(9, 0.0)
        out = valores_mes.get(10, 0.0)
        nov = valores_mes.get(11, 0.0)
        dez = valores_mes.get(12, 0.0)
        total_anual = jan + fev + mar + abr + mai + jun + jul + ago + set_val + out + nov + dez
        
        totais_mensais[0] += jan
        totais_mensais[1] += fev
        totais_mensais[2] += mar
        totais_mensais[3] += abr
        totais_mensais[4] += mai
        totais_mensais[5] += jun
        totais_mensais[6] += jul
        totais_mensais[7] += ago
        totais_mensais[8] += set_val
        totais_mensais[9] += out
        totais_mensais[10] += nov
        totais_mensais[11] += dez
        
        rows.append({
            'DESPESAS': conta[:50],
            'JAN': jan,
            'FEV': fev,
            'MAR': mar,
            'ABR': abr,
            'MAI': mai,
            'JUN': jun,
            'JUL': jul,
            'AGO': ago,
            'SET': set_val,
            'OUT': out,
            'NOV': nov,
            'DEZ': dez,
            'TOTAL': total_anual
        })
        print(f"  ✓ {conta}: Total anual = {total_anual:.2f}")
    
    total_geral = sum(totais_mensais)
    rows.append({
        'DESPESAS': 'TOTAIS',
        'JAN': totais_mensais[0],
        'FEV': totais_mensais[1],
        'MAR': totais_mensais[2],
        'ABR': totais_mensais[3],
        'MAI': totais_mensais[4],
        'JUN': totais_mensais[5],
        'JUL': totais_mensais[6],
        'AGO': totais_mensais[7],
        'SET': totais_mensais[8],
        'OUT': totais_mensais[9],
        'NOV': totais_mensais[10],
        'DEZ': totais_mensais[11],
        'TOTAL': total_geral
    })
    print(f"\n  ✓ TOTAIS: {total_geral:.2f}")

    df = pd.DataFrame(rows, dtype=object)
    ok = salvar_db(df, output_db_path, field_specs)
    print(f"\nTabela de despesas gravada em {output_db_path}") if ok else print(f"\nFalha ao gravar {output_db_path}")
    print(f"Total de registos: {len(contas_ordenadas) + 1} (incluindo TOTAIS)")


# ====================================================================
# VISUALIZAÇÃO (PIVOT TABLE NO TERMINAL)
# ====================================================================

def exibir_pivot_table(despesas_db_path):
    """
    Exibe a tabela de despesas formatada como pivot table no terminal.
    Leitura pela compatibilidade comum: `carregar_db` + DataFrame.
    """
    try:
        rows, _ = carregar_db(despesas_db_path)
        df = pd.DataFrame(rows, dtype=object)
        
        if df.empty:
            print("AVISO: Despesas está vazio")
            return
        
        print("\n" + "="*120)
        print("TABELA DE DESPESAS - PIVOT TABLE")
        print("="*120)
        
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 120)
        pd.set_option('display.float_format', '{:.2f}'.format)
        
        print(df.to_string(index=False))
        
        print("="*120)
        
        if 'TOTAL' in df.columns and len(df) > 1:
            linha_totais = df[df['DESPESAS'].astype(str).str.strip().str.upper() == 'TOTAIS']
            if not linha_totais.empty:
                total_geral = clean_numeric(linha_totais['TOTAL'].iloc[0])
                print(f"\n>>> TOTAL GERAL DE DESPESAS: {total_geral:.2f} €")
                
                meses = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 
                        'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
                valores_mensais = [clean_numeric(linha_totais[mes].iloc[0]) for mes in meses if mes in linha_totais.columns]
                if valores_mensais:
                    mes_max = meses[valores_mensais.index(max(valores_mensais))]
                    valor_max = max(valores_mensais)
                    print(f">>> MÊS COM MAIOR DESPESA: {mes_max} ({valor_max:.2f} €)")
        
        print("\n")
        
    except Exception as e:
        print(f"ERRO ao exibir pivot table: {e}")


# ====================================================================
# EXPORTAR PARA EXCEL (OPCIONAL - PARA VALIDAÇÃO)
# ====================================================================

def exportar_para_excel(despesas_db_path, output_excel_path='despesas_validacao.xlsx'):
    """
    Exporta despesas para Excel para validação visual.
    """
    try:
        rows, _ = carregar_db(despesas_db_path)
        df = pd.DataFrame(rows, dtype=object)

        if df.empty:
            print("AVISO: Nenhum dado para exportar")
            return

        with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Despesas', index=False)

            workbook = writer.book
            worksheet = writer.sheets['Despesas']

            worksheet.column_dimensions['A'].width = 30
            for col in ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']:
                worksheet.column_dimensions[col].width = 12

        print(f"✓ Dados exportados para {output_excel_path}")

    except Exception as e:
        print(f"ERRO ao exportar para Excel: {e}")


# ====================================================================
# PROCESSO PRINCIPAL
# ====================================================================
def processar_despesas(bancos_db='Bancos',
                       caixa_db='Caixa',
                       despesas_db='Despesas',
                       exportar_excel=False):
    """
    Processo principal que replica GerarTabelaDespesas() do VBA.
    Usa movimentos aglutinados de Bancos + Caixa.
    """
    print("\n" + "="*80)
    print("PROCESSAMENTO DE DESPESAS - Versão Python (COM AGLUTINAÇÃO)")
    print("="*80 + "\n")

    # PASSO 1: Aglutinar movimentos
    print("PASSO 1: Aglutinando movimentos de Bancos + Caixa...")
    df_movimentos = aglutinar_movimentos(bancos_db, caixa_db)
    if df_movimentos.empty:
        print("ERRO: Não foi possível carregar movimentos")
        return

    # PASSO 2: Agregar despesas
    print("\nPASSO 2: Agregando despesas por conta e mês...")
    dados_agregados = agregar_despesas_por_mes(df_movimentos)
    if not dados_agregados:
        print("AVISO: Nenhuma despesa para processar")
        return

    # PASSO 3: Gerar tabela
    print("\nPASSO 3: Gerando tabela de despesas...")
    gerar_tabela_despesas(dados_agregados, despesas_db)

    # PASSO 4: Exibir resultado
    print("\nPASSO 4: Exibindo resultado...")
    exibir_pivot_table(despesas_db)

    # PASSO 5 (Opcional): Exportar para Excel
    if exportar_excel:
        print("\nPASSO 5: Exportando para Excel (validação)...")
        exportar_para_excel(despesas_db)

    print("\n" + "="*80)
    print("PROCESSO CONCLUÍDO COM SUCESSO!")
    print("="*80 + "\n")

# ====================================================================
# MAIN
# ====================================================================
def main(pasta_trabalho=None, exportar_excel=False):
    """
    Função principal para processar despesas.
    - Usa pasta_trabalho como diretório de trabalho.
    - Processa dados de Bancos + Caixa e gera Despesas.
    """
    if pasta_trabalho is None:
        pasta_trabalho = Path.cwd()
    else:
        pasta_trabalho = Path(pasta_trabalho)

    if not pasta_trabalho.exists():
        raise FileNotFoundError(f"Pasta de trabalho não existe: {pasta_trabalho}")

    original_cwd = os.getcwd()
    os.chdir(str(pasta_trabalho))

    try:
        # BUGFIX (arquitetural): nomes simples confiavam no os.chdir()
        # acima, que deixou de ter efeito na resolução de caminhos do
        # back-end SQLite (o bridge resolve nomes sem pasta sempre para a
        # PASTA_CORRENTE global — ver nota em Balanco_Gui.py). Usar
        # caminhos completos a partir de pasta_trabalho corrige isso.
        processar_despesas(
            bancos_db=str(pasta_trabalho / 'Bancos'),
            caixa_db=str(pasta_trabalho / 'Caixa'),
            despesas_db=str(pasta_trabalho / 'Despesas'),
            exportar_excel=exportar_excel
        )
    except Exception as e:
        print(f"❌ Erro ao processar despesas: {e}")
        raise
    finally:
        os.chdir(original_cwd)

# ====================================================================
# EXECUTAR
# ====================================================================
if __name__ == "__main__":
    try:
        # Processa despesas (idêntico a chamar GerarTabelaDespesas no VBA)
        main(exportar_excel=True)  # Gera Excel para validação em modo standalone
    except Exception as e:
        print(f"\nERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()