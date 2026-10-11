"""
Receitas.py - VERSÃO SIMPLIFICADA (SEM HEURÍSTICAS COMPLEXAS)
Processa receitas de Bancos + Caixa

NOVA LÓGICA:
- Aglutina movimentos de ambos os ficheiros
- Agrupa por FRACÇÃO + MÊS real do pagamento
- Classifica por comparação de valor (Normal/Extra/Ambos)
- Registra no mês correto
- Calcula saldos automaticamente
"""

import os
import re
import sys
import pandas as pd

from collections import defaultdict
from datetime import datetime
from Logging_utils import ativar_logging
from pathlib import Path
from Commons import clean_numeric
from Database import carregar_db, salvar_db

logger = ativar_logging("receitas")

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
# AGLUTINAÇÃO DE MOVIMENTOS
# ====================================================================

def aglutinar_movimentos(bancos_db_path, caixa_db_path, dprazo_db_path=None):
    """
    Aglutina movimentos de Bancos, Caixa e DPrazo.
    Retorna DataFrame com: DATA, TIPO, CONTA, DESCRICAO, VALOR, OBSERVACAO
    """
    
    print(f"\n{'='*80}")
    print("🔄 AGLUTINAÇÃO DE MOVIMENTOS (BANCOS + CAIXA + DPRAZO)")
    print(f"{'='*80}")
    
    df_bancos = pd.DataFrame()
    df_caixa = pd.DataFrame()
    df_dprazo = pd.DataFrame()
    
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

    # Carrega DPrazo (opcional)
    if dprazo_db_path:
        try:
            rows_dprazo, _ = carregar_db(dprazo_db_path)
            df_dprazo = pd.DataFrame(rows_dprazo, dtype=object)
            print(f"  ✅ DPrazo: {len(df_dprazo)} registos")
        except FileNotFoundError:
            print(f"  ⚠️  DPrazo não encontrado")
        except Exception as e:
            print(f"  ❌ Erro ao ler DPrazo: {e}")
        
    # Une ambos
    if df_bancos.empty and df_caixa.empty and df_dprazo.empty:
        print(f"  ❌ ERRO: Nenhum movimento encontrado")
        return pd.DataFrame()
    
    dfs_to_concat = []
    
    if not df_bancos.empty:
        df_bancos = df_bancos[['DATA', 'TIPO', 'CONTA', 'DESCRICAO', 'VALOR', 'OBSERVACAO']].copy()
        dfs_to_concat.append(df_bancos)
    
    if not df_caixa.empty:
        df_caixa = df_caixa[['DATA', 'TIPO', 'CONTA', 'DESCRICAO', 'VALOR', 'OBSERVACAO']].copy()
        dfs_to_concat.append(df_caixa)

    if not df_dprazo.empty:
        df_dprazo = df_dprazo[['DATA', 'TIPO', 'CONTA', 'DESCRICAO', 'VALOR', 'OBSERVACAO']].copy()
        dfs_to_concat.append(df_dprazo)
        
    df_movimentos = pd.concat(dfs_to_concat, ignore_index=True)
    
    print(f"\n  📊 Total aglutinado: {len(df_movimentos)} movimentos")
    
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
# CARREGAR TABELA DE QUOTAS
# ====================================================================

def carregar_tabela_quotas(configs_db_path):
    """Carrega quotas dos condóminos de Configs (condominio.db)."""
    
    try:
        rows, _ = carregar_db(configs_db_path)
        df_configs = pd.DataFrame(rows, dtype=object)
    except Exception as e:
        print(f"ERRO ao ler Configs: {e}")
        return {}
    
    # Nota: valores de CATEGORIA/CHAVE podem vir com espaços; normalizar
    # (strip + upper) antes de comparar.
    categoria_normalizada = df_configs.get('CATEGORIA', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    df_cond = df_configs[categoria_normalizada == 'CLASSIFICACAO'].copy()
    
    prefixos = set()
    dict_valores = {}
    
    for _, row in df_cond.iterrows():
        chave = str(row['CHAVE']).strip()
        valor = str(row['VALOR']).strip()
        
        if chave.startswith('COND_'):
            dict_valores[chave] = valor
            if chave.endswith('_NOME'):
                prefixos.add(chave[:-5])
    
    tabela_quotas = {}
    
    for prefixo in sorted(prefixos):
        chave_conta = f"{prefixo}_CONTA"
        fracao_nome = dict_valores.get(chave_conta, extrair_nome_fracao(prefixo))
        
        try:
            quota_normal = float(dict_valores.get(f"{prefixo}_NORMAL", "0").replace(',', '.'))
        except:
            quota_normal = 0.0
        
        try:
            quota_extra = float(dict_valores.get(f"{prefixo}_EXTRA", "0").replace(',', '.'))
        except:
            quota_extra = 0.0
        
        quota_total = quota_normal + quota_extra
        
        tabela_quotas[fracao_nome] = {
            'QUOTA_NORMAL': quota_normal,
            'QUOTA_EXTRA': quota_extra,
            'QUOTA_TOTAL': quota_total
        }
    
    print(f"✅ {len(tabela_quotas)} fracções carregadas:")
    for fracao, valores in tabela_quotas.items():
        print(f"  - {fracao}: Normal={valores['QUOTA_NORMAL']:.2f}, Extra={valores['QUOTA_EXTRA']:.2f}")
    
    return tabela_quotas


def extrair_nome_fracao(prefixo):
    """Extrai nome da fracção do prefixo"""
    nome = prefixo.replace('COND_', '').replace('_A', '').replace('_B', '')
    
    mapeamento = {
        'RC_DTO': 'R/c Dto.',
        'RC_ESQ': 'R/c Esq.',
        '1DTO': '1º Dto.',
        '1ESQ': '1º Esq.',
        '2DTO': '2º Dto.',
        '2ESQ': '2º Esq.'
    }
    
    return mapeamento.get(nome, f"{nome}.")


# ====================================================================
# PROCESSAR RECEITAS (LÓGICA SIMPLIFICADA)
# ====================================================================

def processar_receitas_simplificado(df_movimentos, tabela_quotas, eps=0.5):
    """
    LÓGICA SIMPLIFICADA:
    1. Filtra receitas de quotas
    2. Agrupa por FRACÇÃO + MÊS (soma todos os pagamentos do mesmo mês)
    3. Classifica por valor: Normal / Extra / Ambos
    4. Registra no mês correto
    
    Retorna: (mapa_normal, mapa_extra)
    """
    
    print(f"\n{'='*80}")
    print("📊 PROCESSAMENTO SIMPLIFICADO DE RECEITAS")
    print(f"{'='*80}")
    
    # Filtra receitas de quotas
    df_receitas = df_movimentos[
        (df_movimentos['TIPO'].str.upper().str.strip() == 'RECEITA') &
        (df_movimentos['CONTA'].str.upper().str.contains('QUOTA', na=False))
    ].copy()
    
    print(f"  ✅ {len(df_receitas)} receitas de quotas encontradas")
    
    if df_receitas.empty:
        return {}, {}
    
    # Mapas de saída
    mapa_normal = {}
    mapa_extra = {}
    
    # Agrupa por FRACÇÃO + MÊS
    grupos_mes = defaultdict(lambda: {'valores': [], 'total': 0.0})
    
    for _, row in df_receitas.iterrows():
        # Identifica fracção
        conta_txt = str(row['CONTA']).strip()
        fracao = match_fracao(conta_txt, tabela_quotas)
        
        if not fracao:
            if '-' in conta_txt:
                fracao = match_fracao(conta_txt.split('-', 1)[1].strip(), tabela_quotas)
        
        if not fracao:
            print(f"  ⚠️  Fracção não identificada: {conta_txt}")
            continue
        
        # Extrai mês
        try:
            if isinstance(row['DATA'], datetime):
                mes = row['DATA'].month
            else:
                mes = pd.to_datetime(row['DATA']).month
        except:
            print(f"  ⚠️  Data inválida: {row['DATA']}")
            continue
        
        valor = clean_numeric(row['VALOR'])
        if valor <= 0:
            continue
        
        # Agrupa por fracção|mês
        chave = f"{fracao}|{mes}"
        grupos_mes[chave]['valores'].append(valor)
        grupos_mes[chave]['total'] += valor
    
    print(f"\n  📋 {len(grupos_mes)} grupos (fracção|mês) identificados")
    
    # Processa cada grupo
    for chave, dados in grupos_mes.items():
        fracao, mes_str = chave.split('|')
        mes = int(mes_str)
        total_mes = round(dados['total'], 2)
        
        quotas = tabela_quotas.get(fracao)
        if not quotas:
            continue
        
        qn = quotas['QUOTA_NORMAL']
        qe = quotas['QUOTA_EXTRA']
        qt = quotas['QUOTA_TOTAL']
        
        # Inicializa mapas
        if fracao not in mapa_normal:
            mapa_normal[fracao] = {m: 0.0 for m in range(1, 13)}
        if fracao not in mapa_extra:
            mapa_extra[fracao] = {m: 0.0 for m in range(1, 13)}
        
        # CLASSIFICAÇÃO POR VALOR
        print(f"\n  🔍 {fracao} | Mês {mes} | Total: {total_mes:.2f}")
        
        # Caso 1: Valor ≈ Quota Normal
        if abs(total_mes - qn) <= eps:
            mapa_normal[fracao][mes] = total_mes
            print(f"      ✅ Classificado como NORMAL ({qn:.2f})")
        
        # Caso 2: Valor ≈ Quota Extra
        elif abs(total_mes - qe) <= eps:
            mapa_extra[fracao][mes] = total_mes
            print(f"      ✅ Classificado como EXTRA ({qe:.2f})")
        
        # Caso 3: Valor ≈ Quota Total (Normal + Extra)
        elif abs(total_mes - qt) <= eps:
            mapa_normal[fracao][mes] = qn
            mapa_extra[fracao][mes] = qe
            print(f"      ✅ Classificado como TOTAL ({qt:.2f}) = Normal + Extra")
        
        # Caso 4: Múltiplos de quotas (2x, 3x, etc.)
        elif qt > eps:
            n_multiplo = round(total_mes / qt)
            if n_multiplo >= 2 and abs(total_mes - n_multiplo * qt) <= eps:
                # Distribui proporcionalmente
                mapa_normal[fracao][mes] = qn * n_multiplo
                mapa_extra[fracao][mes] = qe * n_multiplo
                print(f"      ✅ Classificado como {n_multiplo}x TOTAL = {n_multiplo}x Normal + {n_multiplo}x Extra")
            else:
                # Decomposição proporcional
                if qt > 0:
                    proporcao_normal = qn / qt
                    proporcao_extra = qe / qt
                    
                    mapa_normal[fracao][mes] = round(total_mes * proporcao_normal, 2)
                    mapa_extra[fracao][mes] = round(total_mes * proporcao_extra, 2)
                    print(f"      ⚙️  Decomposição proporcional: N={mapa_normal[fracao][mes]:.2f}, E={mapa_extra[fracao][mes]:.2f}")
        
        # Caso 5: Valor não reconhecido → tenta proporção
        else:
            if qt > 0:
                proporcao_normal = qn / qt
                proporcao_extra = qe / qt
                
                mapa_normal[fracao][mes] = round(total_mes * proporcao_normal, 2)
                mapa_extra[fracao][mes] = round(total_mes * proporcao_extra, 2)
                print(f"      ⚠️  Valor não reconhecido → Proporção: N={mapa_normal[fracao][mes]:.2f}, E={mapa_extra[fracao][mes]:.2f}")
    
    print(f"\n{'='*80}")
    print("✅ PROCESSAMENTO CONCLUÍDO")
    print(f"{'='*80}\n")
    
    return mapa_normal, mapa_extra


def match_fracao(texto, tabela_quotas):
    """Match de fracção por substring"""
    texto_limpo = limpar_texto(texto)
    
    for fracao_nome in tabela_quotas.keys():
        fracao_limpa = limpar_texto(fracao_nome)
        if fracao_limpa in texto_limpo:
            return fracao_nome
    
    return None


def limpar_texto(texto):
    """Limpa texto para comparação"""
    if not texto:
        return ""
    
    texto = str(texto).upper()
    
    for char in ['.', ',', ';', ':', '-', '/', '\\', '(', ')', '[', ']', '"', "'"]:
        texto = texto.replace(char, ' ')
    
    return re.sub(r'\s+', ' ', texto).strip()



# ====================================================================
# SALDO ANTERIOR – fontes (por prioridade)
# ====================================================================

_MAPA_LETRA_LABEL = {
    "A": "R/c Esq.", "B": "R/c Dto.", "C": "1º Esq.",
    "D": "1º Dto.", "E": "2º Esq.", "F": "2º Dto.",
}
_MAPA_LABEL_LETRA = {v: k for k, v in _MAPA_LETRA_LABEL.items()}


def _norm_label(label: str) -> str:
    """Normaliza letra (A-F) ou rótulo para o rótulo canónico da fracção."""
    label = str(label or "").strip()
    if not label:
        return ""
    if len(label) == 1 and label.upper() in _MAPA_LETRA_LABEL:
        return _MAPA_LETRA_LABEL[label.upper()]
    return label


def _carregar_saldos_anteriores(output_path, tipo_quota) -> dict:
    """
    Obtém SALDO_ANT por fracção a partir de:
      1. receitas_resumo (SQLite)
      2. Tabela plana atual via bridge (só valores != 0)

    Nunca grava/propaga zeros vindos de uma regeneração anterior.
    """
    resultado = {}
    pasta = Path(output_path).parent

    # --- 1) receitas_resumo (SQLite) ---
    try:
        from Database import get_connection, db_path, ConfigsRepo
        if db_path(pasta).exists():
            tipo_sql = "NORMAL" if "NORMAL" in str(tipo_quota).upper() else "EXTRA"
            try:
                ano = int(ConfigsRepo(pasta).get_value("GERAL", "ANO_EXERCICIO", 0) or 0)
            except Exception:
                ano = 0
            with get_connection(pasta) as conn:
                sql = """
                    SELECT COALESCE(NULLIF(TRIM(rr.fracao_label), ''), c.fracao),
                           rr.saldo_ant
                    FROM receitas_resumo rr
                    JOIN condominos c ON c.id = rr.condominio_id
                    WHERE UPPER(TRIM(rr.tipo_quota)) = ?
                """
                params = [tipo_sql]
                if ano:
                    sql += " AND rr.ano = ?"
                    params.append(ano)
                for label, sa in conn.execute(sql, params):
                    fracao = _norm_label(label)
                    if not fracao:
                        continue
                    val = clean_numeric(sa)
                    if abs(val) > 0.0005:
                        resultado[fracao] = val
            if resultado:
                print(f"  ✓ SALDO_ANT lido de receitas_resumo: {len(resultado)} fracções")
                return resultado
    except Exception as e:
        print(f"  ⚠️  Leitura receitas_resumo SALDO_ANT: {e}")

    # --- 3) Tabela plana atual (bridge) – só valores não-zero ---
    try:
        rows, _ = carregar_db(str(output_path))
        for registo in rows:
            fracao = _norm_label(registo.get("FRACCAO", ""))
            if not fracao or fracao.upper() == "TOTAIS":
                continue
            val = clean_numeric(registo.get("SALDO_ANT", 0.0))
            if abs(val) > 0.0005:
                resultado[fracao] = val
        if resultado:
            print(f"  ✓ SALDO_ANT lido da tabela plana: {len(resultado)} fracções")
    except Exception as e:
        print(f"  ⚠️  Leitura tabela plana SALDO_ANT: {e}")

    if not resultado:
        print("  ⚠️  Nenhum SALDO_ANT encontrado em receitas_resumo / tabela plana")
    return resultado


# ====================================================================
# GERAR RECEITAS (SQLite via bridge)
# ====================================================================

def gerar_db_receitas(tabela_quotas, mapa, output_path, tipo_quota, titulo):
    """Gera tabela de receitas (Normal ou Extra) em condominio.db via bridge."""
    
    print(f"\n{'='*80}")
    print(f"💾 GERANDO: {titulo}")
    print(f"{'='*80}")

    saldos_anteriores = _carregar_saldos_anteriores(output_path, tipo_quota)
    
    field_specs = (
        'FRACCAO C(30); SALDO_ANT N(10,2); '
        'JAN N(10,2); FEV N(10,2); MAR N(10,2); '
        'ABR N(10,2); MAI N(10,2); JUN N(10,2); '
        'JUL N(10,2); AGO N(10,2); SET N(10,2); '
        'OUT N(10,2); NOV N(10,2); DEZ N(10,2); '
        'TOTAL N(10,2); SALDO N(10,2)'
    )

    rows = []
    total_saldo_ant = 0.0
    totais_mensais = [0.0] * 12
    total_anual_geral = 0.0
    total_saldo_final = 0.0
    
    for fracao in sorted(tabela_quotas.keys()):
        quotas = tabela_quotas[fracao]
        quota_anual = quotas[tipo_quota] * 12
        
        valores_mes = mapa.get(fracao, {m: 0.0 for m in range(1, 13)})
        
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
        
        total_pago = sum([jan, fev, mar, abr, mai, jun, jul, ago, set_val, out, nov, dez])
        
        saldo_anterior = saldos_anteriores.get(fracao, 0.0)
        
        # SALDO = (Quota_Anual - Total_Pago) × -1 + Saldo_Anterior
        saldo_final = (quota_anual - total_pago) * -1 + saldo_anterior
        
        total_saldo_ant += saldo_anterior
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
        total_anual_geral += total_pago
        total_saldo_final += saldo_final
        
        rows.append({
            'FRACCAO': fracao[:30],
            'SALDO_ANT': saldo_anterior,
            'JAN': jan, 'FEV': fev, 'MAR': mar,
            'ABR': abr, 'MAI': mai, 'JUN': jun,
            'JUL': jul, 'AGO': ago, 'SET': set_val,
            'OUT': out, 'NOV': nov, 'DEZ': dez,
            'TOTAL': total_pago,
            'SALDO': saldo_final
        })
        
        print(f"  ✅ {fracao}: Pago={total_pago:.2f}, Saldo={saldo_final:.2f}")
    
    rows.append({
        'FRACCAO': 'TOTAIS',
        'SALDO_ANT': total_saldo_ant,
        'JAN': totais_mensais[0], 'FEV': totais_mensais[1], 'MAR': totais_mensais[2],
        'ABR': totais_mensais[3], 'MAI': totais_mensais[4], 'JUN': totais_mensais[5],
        'JUL': totais_mensais[6], 'AGO': totais_mensais[7], 'SET': totais_mensais[8],
        'OUT': totais_mensais[9], 'NOV': totais_mensais[10], 'DEZ': totais_mensais[11],
        'TOTAL': total_anual_geral,
        'SALDO': total_saldo_final
    })
    
    print(f"\n  📊 TOTAIS: Pago={total_anual_geral:.2f}, Saldo={total_saldo_final:.2f}")

    df = pd.DataFrame(rows, dtype=object)
    ok = salvar_db(df, output_path, field_specs)
    print(f"  ✅ Gravado: {output_path}\n") if ok else print(f"  ⚠️ Falha ao gravar: {output_path}\n")

    # Sincronizar SALDO / SALDO_ANT para receitas_resumo
    # IMPORTANTE: nunca sobrescrever saldo_ant não-zero com zero
    try:
        from Database import get_connection, db_path, ConfigsRepo
        pasta = Path(output_path).parent
        if ok and db_path(pasta).exists():
            tipo_sql = "NORMAL" if "NORMAL" in str(tipo_quota).upper() else "EXTRA"
            try:
                ano = int(ConfigsRepo(pasta).get_value("GERAL", "ANO_EXERCICIO", 0) or 0)
            except Exception:
                ano = 0
            if not ano:
                import datetime
                ano = datetime.date.today().year
            with get_connection(pasta) as conn:
                id_by_fracao = {
                    str(r[0]): r[1]
                    for r in conn.execute("SELECT fracao, id FROM condominos")
                }
                for row in rows:
                    label = str(row.get("FRACCAO", "")).strip()
                    if not label or label.upper() == "TOTAIS":
                        continue
                    letra = _MAPA_LABEL_LETRA.get(label, label)
                    cid = id_by_fracao.get(letra)
                    if not cid:
                        continue
                    sa = float(row.get("SALDO_ANT", 0) or 0)
                    sf = float(row.get("SALDO", 0) or 0)
                    # Preservar saldo_ant existente se o novo for zero
                    conn.execute(
                        """INSERT INTO receitas_resumo
                           (condominio_id, ano, tipo_quota, fracao_label, saldo_ant, saldo)
                           VALUES (?,?,?,?,?,?)
                           ON CONFLICT(condominio_id, ano, tipo_quota) DO UPDATE SET
                             fracao_label = excluded.fracao_label,
                             saldo_ant = CASE
                               WHEN excluded.saldo_ant = 0
                                    AND receitas_resumo.saldo_ant != 0
                               THEN receitas_resumo.saldo_ant
                               ELSE excluded.saldo_ant
                             END,
                             saldo = excluded.saldo""",
                        (cid, ano, tipo_sql, label, sa, sf),
                    )
            print(f"  ✓ receitas_resumo sincronizado ({tipo_sql}, ano={ano})")
    except Exception as e:
        print(f"  ⚠️  Sync receitas_resumo: {e}")


# ====================================================================
# GERAR JUROS
# ====================================================================

def gerar_receitas_juros(df_movimentos, juros_db='Juros'):
    """Gera Juros a partir do DataFrame aglutinado, via o bridge de salvar_db do auxílio comum."""
    
    print(f"\n{'='*80}")
    print("💰 GERANDO RECEITAS DE JUROS")
    print(f"{'='*80}")
    
    if df_movimentos.empty:
        print("⚠️  DataFrame vazio")
        return
    
    df_juros = df_movimentos[
        (df_movimentos['TIPO'].str.upper().str.strip() == 'RECEITA') &
        (df_movimentos['CONTA'].str.upper().str.contains('JUROS', na=False))
    ].copy()
    
    print(f"  ✅ {len(df_juros)} registos de juros")
    
    if df_juros.empty:
        print("  ⚠️  Nenhum registo de juros")
        return
    
    juros_por_conta = {}
    
    for _, row in df_juros.iterrows():
        conta = str(row['CONTA']).strip()
        valor = clean_numeric(row['VALOR'])
        
        try:
            mes = row['DATA'].month if hasattr(row['DATA'], 'month') else pd.to_datetime(row['DATA']).month
        except:
            continue
        
        if conta not in juros_por_conta:
            juros_por_conta[conta] = {m: 0.0 for m in range(1, 13)}
        
        juros_por_conta[conta][mes] += round(valor, 2)
    
    field_specs = (
        'JUROS C(30); '
        'JAN N(10,2); FEV N(10,2); MAR N(10,2); '
        'ABR N(10,2); MAI N(10,2); JUN N(10,2); '
        'JUL N(10,2); AGO N(10,2); SET N(10,2); '
        'OUT N(10,2); NOV N(10,2); DEZ N(10,2); '
        'TOTAL N(10,2)'
    )

    rows = []
    for conta, meses in sorted(juros_por_conta.items()):
        total = sum(meses.values())
        rows.append({
            'JUROS': conta[:30],
            'JAN': meses[1], 'FEV': meses[2], 'MAR': meses[3],
            'ABR': meses[4], 'MAI': meses[5], 'JUN': meses[6],
            'JUL': meses[7], 'AGO': meses[8], 'SET': meses[9],
            'OUT': meses[10], 'NOV': meses[11], 'DEZ': meses[12],
            'TOTAL': total
        })
        
        print(f"  ✅ {conta}: {total:.2f}")
    
    if len(juros_por_conta) > 1:
        totais_mensais = [sum(juros_por_conta[c][m] for c in juros_por_conta) for m in range(1, 13)]
        rows.append({
            'JUROS': 'TOTAIS',
            'JAN': totais_mensais[0], 'FEV': totais_mensais[1], 'MAR': totais_mensais[2],
            'ABR': totais_mensais[3], 'MAI': totais_mensais[4], 'JUN': totais_mensais[5],
            'JUL': totais_mensais[6], 'AGO': totais_mensais[7], 'SET': totais_mensais[8],
            'OUT': totais_mensais[9], 'NOV': totais_mensais[10], 'DEZ': totais_mensais[11],
            'TOTAL': sum(totais_mensais)
        })
    
    df = pd.DataFrame(rows, dtype=object)
    ok = salvar_db(df, juros_db, field_specs)
    print(f"  ✅ Gravado: {juros_db}\n") if ok else print(f"  ⚠️ Falha ao gravar: {juros_db}\n")


# ====================================================================
# PROCESSO PRINCIPAL
# ====================================================================

def processar_receitas(configs_db='Configs',
                       bancos_db='Bancos',
                       caixa_db='Caixa',
                       dprazo_db='DPrazo',
                       receitas_n='ReceitasN',
                       receitas_e='ReceitasE',
                       juros_db='Juros',
                       eps_tolerance=0.5):
    """Processo principal - VERSÃO SIMPLIFICADA"""
    
    print("\n" + "="*80)
    print("🔄 PROCESSAMENTO DE RECEITAS - VERSÃO SIMPLIFICADA")
    print("="*80 + "\n")
    
    # 1. Carregar quotas
    print("PASSO 1: Carregando tabela de quotas...")
    tabela_quotas = carregar_tabela_quotas(configs_db)
    
    if not tabela_quotas:
        print("❌ Tabela de quotas vazia")
        return
    
    # 2. Aglutinar movimentos
    print("\nPASSO 2: Aglutinando Bancos + Caixa...")
    df_movimentos = aglutinar_movimentos(bancos_db, caixa_db, dprazo_db)
    
    if df_movimentos.empty:
        print("❌ Nenhum movimento")
        return
    
    # 3. Processar receitas
    print("\nPASSO 3: Processando receitas...")
    mapa_normal, mapa_extra = processar_receitas_simplificado(df_movimentos, tabela_quotas, eps_tolerance)
    
    # 4. Gerar tabelas de receitas (SQLite)
    print("\nPASSO 4: Gerando tabelas de receitas...")
    gerar_db_receitas(tabela_quotas, mapa_normal, receitas_n, 'QUOTA_NORMAL', 'QUOTAS NORMAIS')
    gerar_db_receitas(tabela_quotas, mapa_extra, receitas_e, 'QUOTA_EXTRA', 'QUOTAS EXTRAS')

    # 5. Gerar Juros
    print("\nPASSO 5: Gerando Juros...")
    gerar_receitas_juros(df_movimentos, juros_db)

    # 6. Exibir resultados
    print("\nPASSO 6: Exibindo mapas de receitas...")
    exibir_mapas(receitas_n, receitas_e)

    print("\n" + "="*80)
    print("✅ PROCESSAMENTO CONCLUÍDO COM SUCESSO! (VERSÃO SIMPLIFICADA)")
    print("="*80 + "\n")


def exibir_mapas(receitas_n_path, receitas_e_path):
    """Exibe os mapas de receitas formatados via o leitor de compatibilidade do projeto."""
    print("\n" + "="*120)
    print("MAPAS DE RECEITAS - VISUALIZAÇÃO")
    print("="*120)

    # Quotas Normais
    print("\n📊 QUOTAS NORMAIS")
    print("-"*120)
    try:
        rows_n, _ = carregar_db(receitas_n_path)
        df_n = pd.DataFrame(rows_n, dtype=object)
        pd.set_option('display.float_format', '{:.2f}'.format)
        print(df_n.to_string(index=False))
    except Exception as e:
        print(f"ERRO ao exibir {receitas_n_path}: {e}")

    # Quotas Extras
    print("\n📊 QUOTAS EXTRAS")
    print("-"*120)
    try:
        rows_e, _ = carregar_db(receitas_e_path)
        df_e = pd.DataFrame(rows_e, dtype=object)
        print(df_e.to_string(index=False))
    except Exception as e:
        print(f"ERRO ao exibir {receitas_e_path}: {e}")

    print("\n" + "="*120)


def main(pasta_trabalho=None):
    """
    Função principal para processar receitas.
    - Usa pasta_trabalho como diretório de trabalho (se None, usa current dir).
    - Processa dados e gera ReceitasN, ReceitasE e Juros.
    """
    if pasta_trabalho is None:
        pasta_trabalho = Path.cwd()
    else:
        pasta_trabalho = Path(pasta_trabalho)

    if not pasta_trabalho.exists():
        raise FileNotFoundError(f"Pasta de trabalho não existe: {pasta_trabalho}")

    # Muda para o diretório de trabalho temporariamente
    original_cwd = os.getcwd()
    os.chdir(str(pasta_trabalho))

    try:
        # BUGFIX (arquitetural): nomes simples confiavam no os.chdir()
        # acima, que deixou de ter efeito na resolução de caminhos do
        # back-end SQLite (ver nota equivalente em Balanco_Gui.py). Usar
        # caminhos completos a partir de pasta_trabalho corrige isso.
        processar_receitas(
            configs_db=str(pasta_trabalho / 'Configs'),
            bancos_db=str(pasta_trabalho / 'Bancos'),
            caixa_db=str(pasta_trabalho / 'Caixa'),
            dprazo_db=str(pasta_trabalho / 'DPrazo'),
            receitas_n=str(pasta_trabalho / 'ReceitasN'),
            receitas_e=str(pasta_trabalho / 'ReceitasE'),
            juros_db=str(pasta_trabalho / 'Juros'),
            eps_tolerance=0.5  # Tolerância para comparações
        )
    except Exception as e:
        print(f"❌ Erro ao processar receitas: {e}")
        raise  # Propaga erro para o GUI
    finally:
        # Volta ao diretório original
        os.chdir(original_cwd)


# ====================================================================
# EXECUTAR
# ====================================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()