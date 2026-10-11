#===========================================================================
# Balanço do Exercício
#===========================================================================
import sys
import pandas as pd
import unicodedata  # Para normalização de texto nos cálculos

from datetime import datetime
from Logging_utils import ativar_logging
from Commons import (
    BASE_DIR,
    clean_numeric,
    obter_ano_exercicio,
    calcular_numero_admin,
)
from Database import carregar_db, salvar_db

logger = ativar_logging("Balanco")

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
# PARTE 1: CARREGAR DADOS DOS MÓDULOS
# ====================================================================
# a
def carregar_despesas(despesas_db='Despesas'):
    try:
        rows, _ = carregar_db(despesas_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            return []
        despesas = []
        for _, row in df.iterrows():
            conta = str(row['DESPESAS']).strip()
            if conta.upper() == 'TOTAIS':
                continue
            valor = clean_numeric(row.get('TOTAL', 0))
            if valor > 0.01:
                despesas.append({'conta': conta, 'valor': valor})
        return despesas
    except Exception as e:
        print(f"ERRO ao carregar despesas: {e}")
        return []
#b
def carregar_quotas_normais(receitas_n_db='ReceitasN'):
    try:
        rows, _ = carregar_db(receitas_n_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            return 0.0
        totais = df[df['FRACCAO'].astype(str).str.strip().str.upper() == 'TOTAIS']
        if totais.empty:
            return 0.0
        return clean_numeric(totais.iloc[0].get('TOTAL', 0))
    except Exception as e:
        print(f"ERRO ao carregar quotas normais: {e}")
        return 0.0
#c
def carregar_quotas_extras(receitas_e_db='ReceitasE'):
    try:
        rows, _ = carregar_db(receitas_e_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            return 0.0
        totais = df[df['FRACCAO'].astype(str).str.strip().str.upper() == 'TOTAIS']
        if totais.empty:
            return 0.0
        return clean_numeric(totais.iloc[0].get('TOTAL', 0))
    except Exception as e:
        print(f"ERRO ao carregar quotas extras: {e}")
        return 0.0
#d                            
def carregar_juros(juros_db='Juros'):
    """
    Soma o valor total de juros a partir da tabela Juros (condominio.db).
    Se existir uma linha "TOTAIS" (várias contas geradoras de juros), usa-a.
    Caso contrário (apenas uma conta gera juros, gerar_receitas_juros não
    escreve linha TOTAIS), soma o TOTAL de todas as linhas existentes.
    """
    try:
        rows, _ = carregar_db(juros_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            print("  ⚠️  Juros está vazio")
            return 0.0
        primeira_coluna = df.columns[0]
        rotulo = df[primeira_coluna].astype(str).str.strip().str.upper()
        totais = df[rotulo == 'TOTAIS']
        if not totais.empty:
            valor = clean_numeric(totais.iloc[0].get('TOTAL', 0))
        elif 'TOTAL' in df.columns:
            valor = sum(clean_numeric(v) for v in df['TOTAL'])
        else:
            print(f"  ⚠️  Coluna TOTAL não encontrada em {juros_db}")
            return 0.0
        print(f"  ✓ Juros carregados de {juros_db}: {valor:.2f}")
        return valor
    except Exception as e:
        print(f"  ❌ ERRO ao carregar juros de {juros_db}: {e}")
        return 0.0

#e
def obter_saldos_iniciais(saldos_db='Saldos'):
    try:
        rows, _ = carregar_db(saldos_db)
        df = pd.DataFrame(rows, dtype=object)
        if df.empty:
            print(f"  ⚠️  {saldos_db} vazio")
            return {'deposito_poupanca': 0.0, 'deposito_ordem': 0.0, 'numerario_caixa': 0.0}
            
        def obter_valor(pattern):
            mascara = df['CONTA'].str.upper().str.contains(pattern, na=False)
            if mascara.any():
                return clean_numeric(df[mascara].iloc[0]['VALOR'])
            return 0.0

        deposito_poupanca = obter_valor('POUPANÇA_I') or obter_valor('POUPANCA_I')
        deposito_ordem = obter_valor('ORDEM_I')
        numerario_caixa = obter_valor('CAIXA_I')

        return {
            'deposito_poupanca': deposito_poupanca,
            'deposito_ordem': deposito_ordem,
            'numerario_caixa': numerario_caixa
        }
    except FileNotFoundError:
        print(f"  ⚠️  Ficheiro {saldos_db} não encontrado. Usando valores 0.")
        return {'deposito_poupanca': 0.0, 'deposito_ordem': 0.0, 'numerario_caixa': 0.0}
    except Exception as e:
        print(f"  ❌ Erro ao ler {saldos_db}: {e}")
        return {'deposito_poupanca': 0.0, 'deposito_ordem': 0.0, 'numerario_caixa': 0.0}

# ====================================================================
# PARTE 2: GERAR BALANÇO CONSOLIDADO
# ====================================================================
#a
def gerar_balanco(
    despesas_db='Despesas',
    receitas_n_db='ReceitasN',
    receitas_e_db='ReceitasE',
    saldos_db='Saldos',
    juros_db='Juros',
    output_db='Balanco',
    bancos_db='Bancos',
    caixa_db='Caixa',
):
    print("\n" + "="*80)
    print("📊 GERAÇÃO DE BALANÇO ANUAL CONSOLIDADO")
    print("="*80)
    
    # Calcula o número da administração logo no início
    global numero_admin
    numero_admin = calcular_numero_admin()
    
    # Carrega dados
    print("\nPASSO 1: Carregando dados dos módulos...")
    despesas = carregar_despesas(despesas_db)
    quotas_normais = carregar_quotas_normais(receitas_n_db)
    quotas_extras = carregar_quotas_extras(receitas_e_db)

    # Os juros devem ser carregados da tabela Juros
    juros = carregar_juros(juros_db)
    saldos_iniciais = obter_saldos_iniciais(saldos_db)
    
    print(f"  ✓ Despesas: {len(despesas)} contas")
    print(f"  ✓ Quotas Normais: {quotas_normais:.2f}")
    print(f"  ✓ Quotas Extras: {quotas_extras:.2f}")
    print(f"  ✓ Juros: {juros:.2f}")
    print(f"  ✓ Saldo Poupança (Inicial): {saldos_iniciais['deposito_poupanca']:.2f}")
    print(f"  ✓ Saldo Ordem (Inicial): {saldos_iniciais['deposito_ordem']:.2f}")
    print(f"  ✓ Saldo Numerário (Inicial): {saldos_iniciais['numerario_caixa']:.2f}")
    
    # Calcula totais baseados em receitas e despesas
    print("\nPASSO 2: Calculando totais baseados em receitas e despesas...")
    total_despesas = sum(d['valor'] for d in despesas)
    total_receitas = quotas_normais + quotas_extras + juros
    saldo_adm_inicial = (saldos_iniciais['deposito_poupanca'] + 
                         saldos_iniciais['deposito_ordem'] + 
                         saldos_iniciais['numerario_caixa'])
    
    saldo_exercicio_rec = total_receitas - total_despesas
    saldo_final_rec = (saldo_adm_inicial + total_receitas) - total_despesas
    
    print(f"  • Total Despesas: {total_despesas:.2f}")
    print(f"  • Total Receitas: {total_receitas:.2f}")
    print(f"  • Saldo Inicial : {saldo_adm_inicial:.2f}")
    print(f"  • Saldo Exercício (receitas-despesas): {saldo_exercicio_rec:.2f}")
    print(f"  • Saldo Final (saldoIn+receitas-despesas): {saldo_final_rec:.2f}")
    
    # Calcula saldos finais baseados em movimentos (parte da rotina transferida)
    print("\nPASSO 3: Calculando saldos finais baseados em movimentos...")
    initial_poup = saldos_iniciais['deposito_poupanca']

    # BUGFIX: `carregar_db` era chamado aqui com os nomes fixos 'Bancos'
    # e 'Caixa' (em vez dos parâmetros `bancos_db`/`caixa_db`, que nem
    # sequer existiam antes desta correção). Como estes nomes não têm
    # componente de pasta, resolviam sempre para a PASTA_CORRENTE global,
    # ignorando por completo a pasta em que despesas_db/receitas_n_db/etc.
    # realmente estavam — ver nota mais detalhada em processar_balanco().
    rows_bancos, _ = carregar_db(bancos_db)
    df_bancos = pd.DataFrame(rows_bancos, dtype=object)
    
    patterns_dep = ['REGRA_DEP_POUPANCA', 'DEP POUPANCA']
    patterns_lev = ['REGRA_LEV_POUPANCA', 'LEV POUPANCA']
    mascara_dep = df_bancos['DESCRICAO'].str.upper().str.contains('|'.join(patterns_dep), na=False)
    mascara_lev = df_bancos['DESCRICAO'].str.upper().str.contains('|'.join(patterns_lev), na=False)
    sum_dep = sum(clean_numeric(v) for v in df_bancos.loc[mascara_dep, 'VALOR']) if 'VALOR' in df_bancos.columns else 0.0
    sum_lev = sum(clean_numeric(v) for v in df_bancos.loc[mascara_lev, 'VALOR']) if 'VALOR' in df_bancos.columns else 0.0
    total_mov_poup = sum_dep - sum_lev
    deposito_poup_f = initial_poup + total_mov_poup
    
    ultimo_saldo_bancos = clean_numeric(df_bancos.iloc[-1]['SALDO']) if not df_bancos.empty else 0.0
    
    rows_caixa, _ = carregar_db(caixa_db)
    df_caixa = pd.DataFrame(rows_caixa, dtype=object)
    ultimo_saldo_caixa = clean_numeric(df_caixa.iloc[-1]['SALDO']) if not df_caixa.empty else 0.0
    
    sum_f = deposito_poup_f + ultimo_saldo_bancos + ultimo_saldo_caixa
    sum_i = saldos_iniciais['deposito_poupanca'] + saldos_iniciais['deposito_ordem'] + saldos_iniciais['numerario_caixa']
    saldo_exercicio_mov = sum_f - sum_i
    saldo_final_mov = sum_f
    
    print(f"  • Depósito Poupança.F: {deposito_poup_f:.2f}")
    print(f"  • Depósito Ordem.F: {ultimo_saldo_bancos:.2f}")
    print(f"  • Numerário Caixa.F: {ultimo_saldo_caixa:.2f}")
    print(f"  • Saldo do Exercício (movimentos): {saldo_exercicio_mov:.2f}")
    print(f"  • Saldo Final (movimentos): {saldo_final_mov:.2f}")
    
    # Validação de consistência
    diferenca_exercicio = abs(saldo_exercicio_rec - saldo_exercicio_mov)
    diferenca_final = abs(saldo_final_rec - saldo_final_mov)
    if diferenca_exercicio > 0.01 or diferenca_final > 0.01:
        print(f"\n  ⚠️  AVISO: Divergência entre cálculos!")
        print(f"     Saldo Exercício (receitas vs movimentos): {saldo_exercicio_rec:.2f} vs {saldo_exercicio_mov:.2f} (dif: {diferenca_exercicio:.2f})")
        print(f"     Saldo Final (receitas vs movimentos): {saldo_final_rec:.2f} vs {saldo_final_mov:.2f} (dif: {diferenca_final:.2f})")
    
    # Usar valores de movimentos para maior precisão
    saldo_exercicio = saldo_exercicio_mov
    saldo_final = saldo_final_mov
    
    total_debitos = total_despesas + saldo_final
    total_creditos = saldo_adm_inicial + total_receitas
    
    print(f"\n  • Saldo do Exercício (final): {saldo_exercicio:.2f}")
    print(f"  • Saldo Final (final): {saldo_final:.2f}")
    print(f"  • TOTAL DÉBITOS (Esquerda): {total_debitos:.2f}")
    print(f"  • TOTAL CRÉDITOS (Direita): {total_creditos:.2f}")
    
    diferenca = abs(total_debitos - total_creditos)
    if diferenca > 0.01:
        print(f"\n  ⚠️  ERRO: Débitos ≠ Créditos! Diferença: {diferenca:.2f}")
    else:
        print(f"\n  ✓ Validação OK: Débitos = Créditos ({total_debitos:.2f})")
    
    # PASSO 4: Montando estrutura do balanço (EXATAMENTE COMO NA IMAGEM)
    print("\nPASSO 4: Montando estrutura do balanço...")
    registos = []

    # ===================== LADO ESQUERDO =====================

    # Todas as despesas carregadas do Despesas
    registos.append({'CONTA': 'DESPESAS ANO CORRENTE', 'TIPO': 'TITULO', 'VALOR': 0.0})
    
    # Cria lista com despesas ( até + 8 linhas em branco se contas despesas for menor )
    despesas_completas = (
        [{'CONTA': desp['conta'], 'TIPO': 'DESPESA', 'VALOR': desp['valor']} for desp in despesas]
        + [{'CONTA': '', 'TIPO': '', 'VALOR': 0.0}] * max(0, 8 - len(despesas))
    )

    registos.extend(despesas_completas)

    registos.append({'CONTA': '', 'TIPO': '', 'VALOR': 0.0})  # linha em branco
    registos.append({'CONTA': 'Total despesas (TD)', 'TIPO': 'SUBTOTAL', 'VALOR': total_despesas})

    registos.append({'CONTA': '', 'TIPO': '', 'VALOR': 0.0})  # linha em branco
    registos.append({'CONTA': 'Saldo Final', 'TIPO': 'SALDO', 'VALOR': saldo_final})
    registos.append({'CONTA': 'TOTAL', 'TIPO': 'TOTAL', 'VALOR': total_debitos})

    # Separador interno (não será impresso, apenas para a função exibir_balanco dividir as colunas)
    registos.append({'CONTA': '--- LADO DIREITO ---', 'TIPO': 'SEPARADOR', 'VALOR': 0.0})

    # ===================== LADO DIREITO =====================

    registos.append({'CONTA': 'SALDO ADMINISTRAÇÃO ANTERIOR', 'TIPO': 'TITULO', 'VALOR': 0.0})
    registos.append({'CONTA': 'a) Depósito Poupança', 'TIPO': 'RECEITA', 'VALOR': saldos_iniciais['deposito_poupanca']})
    registos.append({'CONTA': 'b) Depósito Ordem', 'TIPO': 'RECEITA', 'VALOR': saldos_iniciais['deposito_ordem']})
    registos.append({'CONTA': 'c) Numerário Caixa', 'TIPO': 'RECEITA', 'VALOR': saldos_iniciais['numerario_caixa']})
    registos.append({'CONTA': 'Total saldo anterior (TSA)', 'TIPO': 'SUBTOTAL', 'VALOR': saldo_adm_inicial})

    registos.append({'CONTA': '', 'TIPO': '', 'VALOR': 0.0})  # linha em branco
    registos.append({'CONTA': 'RECEITAS ANO CORRENTE', 'TIPO': 'TITULO', 'VALOR': 0.0})
    registos.append({'CONTA': 'a) Quotas Normais', 'TIPO': 'RECEITA', 'VALOR': quotas_normais})
    registos.append({'CONTA': 'b) Quotas Extras', 'TIPO': 'RECEITA', 'VALOR': quotas_extras})
    registos.append({'CONTA': 'c) Juros', 'TIPO': 'RECEITA', 'VALOR': juros})
    registos.append({'CONTA': 'Total receitas (TR)', 'TIPO': 'SUBTOTAL', 'VALOR': total_receitas})

    registos.append({'CONTA': '', 'TIPO': '', 'VALOR': 0.0})  # linha em branco
    registos.append({'CONTA': '', 'TIPO': '', 'VALOR': 0.0})  # linha em branco
    registos.append({'CONTA': 'TOTAL', 'TIPO': 'TOTAL', 'VALOR': total_creditos})
    
    # Salva em Balanco (condominio.db) pelo bridge de compatibilidade.
    field_specs = (
        'CONTA C(50); '
        'TIPO C(10); '
        'VALOR N(10,2) '
    )

    df_balanco = pd.DataFrame(registos)
    if 'CONTA' in df_balanco.columns:
        df_balanco['CONTA'] = df_balanco['CONTA'].astype(str).str[:50]
    if 'TIPO' in df_balanco.columns:
        df_balanco['TIPO'] = df_balanco['TIPO'].astype(str).str[:10]
    if 'VALOR' in df_balanco.columns:
        df_balanco['VALOR'] = pd.to_numeric(df_balanco['VALOR'], errors='coerce').fillna(0.0)

    ok = salvar_db(df_balanco[['CONTA', 'TIPO', 'VALOR']], output_db, field_specs)
    if ok:
        print(f"  ✓ {len(registos)} registos salvos em {output_db}")
    else:
        print(f"  ⚠️ Falha ao gravar {output_db}")
    
    return {
        'total_despesas': total_despesas,
        'total_receitas': total_receitas,
        'saldo_adm_inicial': saldo_adm_inicial,
        'saldo_exercicio': saldo_exercicio,
        'saldo_final': saldo_final,
        'total_debitos': total_debitos,
        'total_creditos': total_creditos
    }

# ====================================================================
# PARTE 3: EXIBIR BALANÇO NO ECRÃ
# ====================================================================
def exibir_balanco(balanco_db='Balanco'):
    print("\n" + "="*120)
    print(f"BALANÇO DA {numero_admin}ª ADMINISTRAÇÃO".center(120))
    print("="*120)
    print(f"{'DÉBITOS (ESQUERDA)':<60}{'CRÉDITOS (DIREITA)':<60}")
    print("-" * 120)
    
    try:
        rows, _ = carregar_db(balanco_db)
        df = pd.DataFrame(rows, dtype=object)
        
        # Divide em lados
        separador_idx = df[df['CONTA'] == '--- LADO DIREITO ---'].index
        if not separador_idx.empty:
            sep = separador_idx[0]
            df_esquerda = df.iloc[:sep].reset_index(drop=True)
            df_direita = df.iloc[sep+1:].reset_index(drop=True)
        else:
            df_esquerda = df
            df_direita = pd.DataFrame()
        
        max_linhas = max(len(df_esquerda), len(df_direita))
        
        for i in range(max_linhas):
            linha_esq = ""
            linha_dir = ""
            
            # Lado esquerdo (DÉBITOS)
            if i < len(df_esquerda):
                row = df_esquerda.iloc[i]
                conta = str(row['CONTA']).strip()
                valor = clean_numeric(row['VALOR'])
                
                if conta == '--- LADO DIREITO ---':
                    continue  # ignora separador
                
                if valor > 0.01 or 'Total' in conta or 'Saldo Final' in conta or 'TOTAL' in conta:
                    linha_esq = f"{conta:<45} {valor:>12.2f}"
                else:
                    linha_esq = conta  # apenas título ou linha em branco
            
            # Lado direito (CRÉDITOS)
            if i < len(df_direita):
                row = df_direita.iloc[i]
                conta = str(row['CONTA']).strip()
                valor = clean_numeric(row['VALOR'])
                
                if valor > 0.01 or 'Total' in conta or 'TOTAL' in conta:
                    linha_dir = f"{conta:<45} {valor:>12.2f}"
                else:
                    linha_dir = conta  # título ou linha em branco
            
            # Imprime as duas colunas
            print(f"{linha_esq:<60}{linha_dir:<60}")
        
        print("=" * 120)
        
    except Exception as e:
        print(f"ERRO ao exibir balanço: {e}")

    
# ====================================================================
# PARTE 4: ATUALIZAR SALDOS FINAIS NO FICHEIRO SALDOS
# ====================================================================

def atualizar_saldos_finais(saldos_db='Saldos', bancos_db='Bancos', caixa_db='Caixa',
                             juros_db='Juros', dprazo_db='DPrazo'):
    """
    Atualiza os saldos finais na tabela Saldos com base nos movimentos.
    
    Alteração:
    - Mantém a mesma lógica de classificação por padrões em DESCRICAO
    - Depósito Poupança_F vem do último saldo em DPrazo
    - Depósito Ordem_F vem do último saldo em Bancos
    - Numerário Caixa_F vem do último saldo em Caixa
    
    Também grava:
    - JUROS (tabela Juros → Saldos.Juros)
    - SALDO_EXERCICIO
    - SALDO_FINAL
    """
    print("\n" + "="*80)
    print("💾 ATUALIZAÇÃO DE SALDOS FINAIS (COM SALDO EXERCÍCIO E FINAL)")
    print("="*80)
    
    try:
        # ============================================================
        # 1. CARREGAR SALDOS INICIAIS
        # ============================================================

        saldos_iniciais = obter_saldos_iniciais(saldos_db)
        initial_poup = saldos_iniciais['deposito_poupanca']
        # BUGFIX: 'Juros' estava fixo (não era parâmetro), tal como
        # 'DPrazo' um pouco abaixo — ambos ignoravam a pasta de trabalho
        # pretendida e liam sempre da PASTA_CORRENTE global. Passaram a
        # parâmetros (juros_db / dprazo_db) tal como saldos_db/
        # bancos_db/caixa_db já eram.
        juros_valor = carregar_juros(juros_db)
        
        print("\nPASSO 1: Carregando saldos iniciais...")
        print(f"  ✓ Depósito Poupança (Inicial): {initial_poup:.2f}")
        print(f"  ✓ Depósito Ordem (Inicial): {saldos_iniciais['deposito_ordem']:.2f}")
        print(f"  ✓ Numerário Caixa (Inicial): {saldos_iniciais['numerario_caixa']:.2f}")
        print(f"  ✓ Juros (para gravação em Saldos): {juros_valor:.2f}")       
        
        # ============================================================
        # 2. CALCULAR DEPÓSITO POUPANÇA FINAL A PARTIR DE DPrazo
        # ============================================================
        print("\nPASSO 2: Calculando Depósito Poupança Final a partir de DPrazo...")
        try:
            rows_dprazo, _ = carregar_db(dprazo_db)
            df_dprazo = pd.DataFrame(rows_dprazo, dtype=object)
            
            if df_dprazo.empty:
                print("  ⚠️  DPrazo vazio → Poupança_F = 0.00")
                deposito_poup_f = 0.0
            else:
                coluna_descricao = 'DESCRICAO'

                if coluna_descricao not in df_dprazo.columns:
                    print(f"  ❌ Coluna '{coluna_descricao}' não existe em DPrazo!")
                    print(f"  Colunas disponíveis: {list(df_dprazo.columns)}")
                    deposito_poup_f = 0.0
                else:
                    desc_upper = df_dprazo[coluna_descricao].astype(str).str.upper().str.strip()

                    # Padrões – podes alargar se necessário
                    patterns_dep = ['REGRA_DEP_POUPANCA', 'DEPOSITO POUPANCA', 'DEP POUPANCA', 'CREDITO POUPANCA']
                    patterns_lev = ['REGRA_LEV_POUPANCA', 'LEVANTAMENTO POUPANCA', 'LEV POUPANCA', 'RESGATE POUPANCA']

                    mascara_dep = desc_upper.str.contains('|'.join(p.upper() for p in patterns_dep), na=False)
                    mascara_lev = desc_upper.str.contains('|'.join(p.upper() for p in patterns_lev), na=False)

                    # Incluir JUROS da conta Poupança em DPrazo
                    mascara_juros = desc_upper.str.contains('JUROS', na=False)
                    
                    # TODOS os movimentos de poupança (depósitos + juros + levantamentos)
                    sum_dep = df_dprazo.loc[mascara_dep, 'VALOR'].apply(clean_numeric).sum()
                    sum_juros_poupanca = df_dprazo.loc[mascara_juros, 'VALOR'].apply(clean_numeric).sum()
                    sum_lev = df_dprazo.loc[mascara_lev, 'VALOR'].apply(clean_numeric).sum()

                    # Total de movimentos = depósitos + juros + levantamentos (já negativos)
                    total_mov_poup = sum_dep + sum_juros_poupanca + sum_lev
                    deposito_poup_f = initial_poup + total_mov_poup

                    print(f"  • Soma depósitos encontrados: +{sum_dep:.2f}")
                    print(f"  • Soma juros encontrados: +{sum_juros_poupanca:.2f}")
                    print(f"  • Soma levantamentos encontrados: {sum_lev:.2f}")
                    print(f"  • Movimento líquido poupança: {total_mov_poup:.2f}")
                    print(f"  ✓ Depósito Poupança_F calculado: {deposito_poup_f:.2f}")
                    print(f"  (baseado em {mascara_dep.sum()} depósitos, {mascara_juros.sum()} juros e {mascara_lev.sum()} levantamentos)")
                    
                    # Opcional: mostrar data do último movimento relevante
                    if 'DATA' in df_dprazo.columns and not df_dprazo.empty:
                        ultima_data = df_dprazo.iloc[-1]['DATA']
                        print(f"      (último movimento em: {ultima_data})")
        
        except FileNotFoundError:
            print("  ⚠️  Ficheiro DPrazo não encontrado → usando 0.00")
            deposito_poup_f = 0.0
        except Exception as e:
            print(f"  ❌ Erro ao processar DPrazo: {e} → usando 0.00")
            deposito_poup_f = 0.0
        
        # ============================================================
        # 3. OBTER DEPÓSITO ORDEM FINAL (mantém-se)
        # ============================================================
        print("\nPASSO 3: Obtendo Depósito Ordem Final...")
        rows_bancos, _ = carregar_db(bancos_db)
        df_bancos = pd.DataFrame(rows_bancos, dtype=object)
        deposito_ordem_f = clean_numeric(df_bancos.iloc[-1]['SALDO']) if not df_bancos.empty else 0.0
        print(f"  ✓ Depósito Ordem Final: {deposito_ordem_f:.2f}")
        
        # ============================================================
        # 4. OBTER NUMERÁRIO CAIXA FINAL (mantém-se)
        # ============================================================
        print("\nPASSO 4: Obtendo Numerário Caixa Final...")
        rows_caixa, _ = carregar_db(caixa_db)
        df_caixa = pd.DataFrame(rows_caixa, dtype=object)
        numerario_caixa_f = clean_numeric(df_caixa.iloc[-1]['SALDO']) if not df_caixa.empty else 0.0
        print(f"  ✓ Numerário Caixa Final: {numerario_caixa_f:.2f}")
        
        # ============================================================
        # 5. CALCULAR SALDO EXERCÍCIO E SALDO FINAL
        # ============================================================
        print("\nPASSO 5: Calculando Saldo Exercício e Saldo Final...")
        
        soma_iniciais = (saldos_iniciais['deposito_poupanca'] + 
                         saldos_iniciais['deposito_ordem'] + 
                         saldos_iniciais['numerario_caixa'])
        
        soma_finais = deposito_poup_f + deposito_ordem_f + numerario_caixa_f
        
        saldo_exercicio = soma_finais - soma_iniciais
        saldo_final = soma_finais
        
        print(f"  • Soma Saldos Iniciais: {soma_iniciais:.2f}")
        print(f"  • Soma Saldos Finais: {soma_finais:.2f}")
        print(f"  ✓ Saldo Exercício: {saldo_exercicio:.2f}")
        print(f"  ✓ Saldo Final: {saldo_final:.2f}")
        
        # ============================================================
        # 6. ATUALIZAR FICHEIRO SALDOS
        # ============================================================
        print("\nPASSO 6: Atualizando tabela Saldos...")

        # Leitura via bridge e gravação via bridge consistente.
        rows_saldos, _ = carregar_db(saldos_db)
        df_saldos = pd.DataFrame(rows_saldos, dtype=object)
        for idx, row in df_saldos.iterrows():
            c = str(row.get('CONTA', '')).strip().upper()
            if 'POUPANÇA_F' in c or 'POUPANCA_F' in c:
                df_saldos.at[idx, 'VALOR'] = round(deposito_poup_f, 2)
                print(f"  ✓ Gravado POUPANÇA_F: {deposito_poup_f:.2f}")
            elif 'ORDEM_F' in c:
                df_saldos.at[idx, 'VALOR'] = round(deposito_ordem_f, 2)
                print(f"  ✓ Gravado ORDEM_F: {deposito_ordem_f:.2f}")
            elif 'CAIXA_F' in c or 'NUMERARIO_CAIXA_F' in c:
                df_saldos.at[idx, 'VALOR'] = round(numerario_caixa_f, 2)
                print(f"  ✓ Gravado CAIXA_F: {numerario_caixa_f:.2f}")
            elif 'EXERCICIO' in c or 'EXERCÍCIO' in c:
                df_saldos.at[idx, 'VALOR'] = round(saldo_exercicio, 2)
            elif 'SALDO FINAL' in c:
                df_saldos.at[idx, 'VALOR'] = round(saldo_final, 2)
            elif c == 'JUROS':
                df_saldos.at[idx, 'VALOR'] = round(juros_valor, 2)
                print(f"  ✓ Juros gravados em Saldos: {juros_valor:.2f}")

        specs_saldos = 'CONTA C(50);DESCRICAO C(50);TIPO C(10);VALOR N(10,2);SALDO N(10,2);OBSERVACAO C(30)'
        if not salvar_db(df_saldos, saldos_db, specs_saldos):
            raise RuntimeError('salvar_db falhou para Saldos')
        
        # ============================================================
        # 7. RESUMO FINAL
        # ============================================================
        print("\n" + "="*80)
        print("✅ SALDOS FINAIS ATUALIZADOS COM SUCESSO")
        print("="*80)
        print(f"\nResumo dos Saldos:")
        print(f"  • Depósito Poupança_F:  {deposito_poup_f:>12.2f} €   ← calculado de DPrazo")
        print(f"  • Depósito Ordem_F:     {deposito_ordem_f:>12.2f} €")
        print(f"  • Numerário Caixa_F:    {numerario_caixa_f:>12.2f} €")
        print(f"  ────────────────────────────────────")
        print(f"  • SALDO EXERCÍCIO:      {saldo_exercicio:>12.2f} €")
        print(f"  • SALDO FINAL:          {saldo_final:>12.2f} €")
        print("="*80 + "\n")
        
        return {
            'deposito_poupanca_f': deposito_poup_f,
            'deposito_ordem_f': deposito_ordem_f,
            'numerario_caixa_f': numerario_caixa_f,
            'saldo_exercicio': saldo_exercicio,
            'saldo_final': saldo_final
        }
        
    except FileNotFoundError as e:
        print(f"  ❌ Erro: Ficheiro não encontrado - {e}")
        return None
    except Exception as e:
        print(f"  ❌ Erro ao atualizar saldos finais: {e}")
        import traceback
        traceback.print_exc()
        return None

# ====================================================================
# PARTE 5: EXPORTA BALANÇO PARA EXCEL
# ====================================================================
def exportar_balanco_excel(balanco_db='Balanco', output_excel='Balanco.xlsx'):
    try:
        rows, _ = carregar_db(balanco_db)
        df = pd.DataFrame(rows, dtype=object)
        
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Balanco', index=False)
            
            workbook = writer.book
            worksheet = writer.sheets['Balanco']
            
            worksheet.column_dimensions['A'].width = 50
            worksheet.column_dimensions['B'].width = 15
            worksheet.column_dimensions['C'].width = 15
            worksheet.column_dimensions['D'].width = 50
        
        print(f"✓ Balanço exportado para {output_excel}")
        
    except Exception as e:
        print(f"ERRO ao exportar para Excel: {e}")

# ====================================================================
# PARTE 6: PROCESSAR_BALANCO
# ====================================================================
def processar_balanco(
    despesas_db='Despesas',
    receitas_n_db='ReceitasN',
    receitas_e_db='ReceitasE',
    saldos_db='Saldos',
    juros_db='Juros',
    balanco_db='Balanco',
    exportar_excel=False,
    bancos_db='Bancos',
    caixa_db='Caixa',
):
    """
    Processo principal de geração do balanço.
    """

    # BUGFIX: 'Bancos' aqui também estava fixo em vez de usar o
    # parâmetro bancos_db (agora aceite). Sem pasta explícita, resolvia
    # sempre para a PASTA_CORRENTE global.
    ano_exercicio = obter_ano_exercicio(bancos_db)

    # Continua com o processo normal
    resultados = gerar_balanco(despesas_db, receitas_n_db, receitas_e_db,
                               saldos_db, juros_db, balanco_db,
                               bancos_db=bancos_db, caixa_db=caixa_db)
    
    exibir_balanco(balanco_db)
    
    if exportar_excel:
        exportar_balanco_excel(balanco_db)
    
    admin_str = f"{numero_admin}ª Administração" if 'numero_admin' in globals() else "Administração"

    return {
        'total_receitas': resultados['total_receitas'],
        'total_despesas': resultados['total_despesas'],
        'saldo_exercicio': resultados['saldo_exercicio'],
        'ano_exercicio': ano_exercicio  # ✅ NOVO: Retorna também o ano
    }

# ====================================================================
# EXECUTAR
# ====================================================================

if __name__ == "__main__":
    try:
        # Processar balanço
        processar_balanco(
            despesas_db='Despesas',
            receitas_n_db='ReceitasN',
            receitas_e_db='ReceitasE',
            saldos_db='Saldos',
            balanco_db='Balanco',
            exportar_excel=False
        )
        
        # Atualizar saldos finais
        atualizar_saldos_finais(
            saldos_db='Saldos',
            bancos_db='Bancos',
            caixa_db='Caixa'
        )
        
    except Exception as e:
        print(f"\nERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()