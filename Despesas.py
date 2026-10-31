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
from Database import (
    resolver_pasta,
    save_despesas_wide,
    load_despesas_wide,
    aglutinar_movimentos,
)

logger = ativar_logging("despesas")
# ativar_logging já redirecciona stdout/stderr para o ficheiro de log.

# ====================================================================
# AGREGAR DESPESAS POR CONTA E MÊS
# ====================================================================
def agregar_despesas_por_mes(df_movimentos):
    """
    Agrega despesas por CONTA e MÊS, somando valores positivos e negativos.
    O valor final por conta/mês é o absoluto da soma.

    Inclui:
    - todas as linhas com TIPO = DESPESA
    - e a conta "MANUTENCAO CGD" mesmo que o extracto bancário a tenha
      classificado como RECEITA (é a comissão de manutenção da conta,
      debitada pelo banco ao condomínio — é sempre DESPESA)
    """

    df_despesas = df_movimentos[
        (
            df_movimentos['TIPO'].str.upper().str.strip() == 'DESPESA'
        ) |
        (
            (df_movimentos['CONTA'].str.upper().str.strip() == 'MANUTENCAO CGD')
        )
    ].copy()

    print(f"  → {len(df_despesas)} despesas encontradas para processar")
    if df_despesas.empty:
        print("AVISO: Nenhuma despesa encontrada")
        return {}

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
        except Exception:
            continue

        conta = str(row['CONTA']).strip()
        if not conta:
            continue

        valor = clean_numeric(row['VALOR'])
        dados_agregados[conta][mes] += valor
        contas_com_valor.add(conta)

    for conta in dados_agregados:
        for mes in dados_agregados[conta]:
            dados_agregados[conta][mes] = abs(dados_agregados[conta][mes])

    print(f"  → Agregação concluída: {len(contas_com_valor)} contas com despesas")
    return dados_agregados


# ====================================================================
# GERAR TABELA DE DESPESAS
# ====================================================================
def gerar_tabela_despesas(dados_agregados, output_db_path=None, pasta=None):
    """
    Gera tabela de despesas em condominio.db via save_despesas_wide (SQL).

    output_db_path: path legado (.../Despesas) — usado só para resolver a pasta.
    pasta: pasta de dados explícita (preferida).
    """
    if not dados_agregados:
        print("AVISO: Nenhum dado para gerar tabela de despesas")
        return

    if pasta is not None:
        pasta_res = resolver_pasta(pasta)
    elif output_db_path is not None:
        pasta_res = resolver_pasta(output_db_path)
    else:
        pasta_res = resolver_pasta(None)

    contas_ordenadas = sorted(dados_agregados.keys())
    print(f"  → Gerando tabela com {len(contas_ordenadas)} contas")

    rows = []
    totais_mensais = [0.0] * 12

    for conta in contas_ordenadas:
        valores_mes = dados_agregados[conta]
        vals = [float(valores_mes.get(m, 0.0) or 0.0) for m in range(1, 13)]
        total_anual = sum(vals)
        for i, v in enumerate(vals):
            totais_mensais[i] += v
        rows.append({
            "DESPESAS": conta[:50],
            "JAN": vals[0], "FEV": vals[1], "MAR": vals[2],
            "ABR": vals[3], "MAI": vals[4], "JUN": vals[5],
            "JUL": vals[6], "AGO": vals[7], "SET": vals[8],
            "OUT": vals[9], "NOV": vals[10], "DEZ": vals[11],
            "TOTAL": total_anual,
        })
        print(f"  ✓ {conta}: Total anual = {total_anual:.2f}")

    total_geral = sum(totais_mensais)
    rows.append({
        "DESPESAS": "TOTAIS",
        "JAN": totais_mensais[0], "FEV": totais_mensais[1], "MAR": totais_mensais[2],
        "ABR": totais_mensais[3], "MAI": totais_mensais[4], "JUN": totais_mensais[5],
        "JUL": totais_mensais[6], "AGO": totais_mensais[7], "SET": totais_mensais[8],
        "OUT": totais_mensais[9], "NOV": totais_mensais[10], "DEZ": totais_mensais[11],
        "TOTAL": total_geral,
    })
    print(f"\n  ✓ TOTAIS: {total_geral:.2f}")

    df = pd.DataFrame(rows, dtype=object)
    n = save_despesas_wide(df, pasta_res)
    print(f"\nTabela de despesas gravada em {pasta_res} ({n} células/linhas via SQL)")
    print(f"Total de registos: {len(contas_ordenadas) + 1} (incluindo TOTAIS)")


# ====================================================================
# VISUALIZAÇÃO (PIVOT TABLE NO TERMINAL)
# ====================================================================

def exibir_pivot_table(despesas_db_path=None, pasta=None):
    """Exibe a tabela de despesas (load_despesas_wide)."""
    try:
        pasta_res = resolver_pasta(pasta if pasta is not None else despesas_db_path)
        rows, _ = load_despesas_wide(pasta_res)
        df = pd.DataFrame(rows, dtype=object)

        if df.empty:
            print("AVISO: Despesas está vazio")
            return

        print("\n" + "=" * 120)
        print("TABELA DE DESPESAS - PIVOT TABLE")
        print("=" * 120)

        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 120)
        pd.set_option("display.float_format", "{:.2f}".format)

        print(df.to_string(index=False))
        print("=" * 120)

        if "TOTAL" in df.columns and len(df) > 1:
            linha_totais = df[df["DESPESAS"].astype(str).str.strip().str.upper() == "TOTAIS"]
            if not linha_totais.empty:
                total_geral = clean_numeric(linha_totais["TOTAL"].iloc[0])
                print(f"\n>>> TOTAL GERAL DE DESPESAS: {total_geral:.2f} €")
                meses = [
                    "JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                    "JUL", "AGO", "SET", "OUT", "NOV", "DEZ",
                ]
                valores_mensais = [
                    clean_numeric(linha_totais[mes].iloc[0])
                    for mes in meses if mes in linha_totais.columns
                ]
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
        rows, _ = load_despesas_wide(resolver_pasta(despesas_db_path))
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
                       exportar_excel=False,
                       pasta=None):
    """
    Processo principal de despesas.

    Preferir ``pasta=``. Os argumentos ``bancos_db`` / ``caixa_db`` /
    ``despesas_db`` são **legado de compatibilidade** (só para
    ``resolver_pasta``); dados em ``condominio.db``.
    """
    print("\n" + "=" * 80)
    print("PROCESSAMENTO DE DESPESAS (SQL / API canónica)")
    print("=" * 80 + "\n")

    if pasta is not None:
        pasta_res = resolver_pasta(pasta)
    else:
        pasta_res = resolver_pasta(bancos_db)

    print("PASSO 1: Aglutinando movimentos (bancos+caixa)...")
    df_movimentos = aglutinar_movimentos(pasta=pasta_res)
    if df_movimentos.empty:
        print("ERRO: Não foi possível carregar movimentos")
        return

    print("\nPASSO 2: Agregando despesas por conta e mês...")
    dados_agregados = agregar_despesas_por_mes(df_movimentos)
    if not dados_agregados:
        print("AVISO: Nenhuma despesa para processar")
        return

    print("\nPASSO 3: Gerando tabela de despesas...")
    gerar_tabela_despesas(dados_agregados, despesas_db, pasta=pasta_res)

    print("\nPASSO 4: Exibindo resultado...")
    exibir_pivot_table(despesas_db, pasta=pasta_res)

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
        # back-end SQLite (resolver_pasta resolve nomes sem pasta sempre para a
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