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
from Commons import clean_numeric, db_path
from Database import (
    load_receitas_wide, load_juros_wide,
    save_receitas_wide, save_juros_wide, resolver_pasta,
    aglutinar_movimentos,
)

logger = ativar_logging("receitas")
# ativar_logging já redirecciona stdout/stderr para o ficheiro de log.

# ====================================================================
# CARREGAR TABELA DE QUOTAS
# ====================================================================

def carregar_tabela_quotas(pasta_ou_path=None):
    """
    Carrega quotas dos condóminos via API canónica (Database.quotas_por_fracao).

    Args:
        pasta_ou_path: pasta de dados, ou path legado (.../Configs). None = corrente.

    Returns:
        dict[fracao_nome] -> {QUOTA_NORMAL, QUOTA_EXTRA, QUOTA_TOTAL}
    """
    from Database import quotas_por_fracao

    tabela_quotas = quotas_por_fracao(pasta_ou_path)

    print(f"✅ {len(tabela_quotas)} fracções carregadas (de regras):")
    for fracao, valores in tabela_quotas.items():
        print(
            f"  - {fracao}: Normal={valores['QUOTA_NORMAL']:.2f}, "
            f"Extra={valores['QUOTA_EXTRA']:.2f}"
        )

    return tabela_quotas


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
        except Exception:
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
        
        # CLASSIFICAÇÃO POR VALOR — matemática partilhada (Quotas.py v1.01)
        from Quotas import repartir_para_mapas
        print(f"\n  🔍 {fracao} | Mês {mes} | Total: {total_mes:.2f}")
        pn, pe, label = repartir_para_mapas(total_mes, qn, qe, tol=eps)
        mapa_normal[fracao][mes] = pn
        mapa_extra[fracao][mes] = pe
        print(f"      ✅ {label}")
    
    print(f"\n{'='*80}")
    print("✅ PROCESSAMENTO CONCLUÍDO")
    print(f"{'='*80}\n")
    
    return mapa_normal, mapa_extra


def match_fracao(texto, tabela_quotas):
    """Match de fracção por substring (preferência pelo rótulo mais longo)."""
    texto_limpo = limpar_texto(texto)
    if not texto_limpo:
        return None

    # Ordenar por comprimento desc. evita que "A" case dentro de "QUOTA"
    candidatos = []
    for fracao_nome in tabela_quotas.keys():
        fracao_limpa = limpar_texto(fracao_nome)
        if not fracao_limpa:
            continue
        if fracao_limpa in texto_limpo:
            candidatos.append((len(fracao_limpa), fracao_nome))
    if not candidatos:
        return None
    candidatos.sort(key=lambda x: (-x[0], x[1]))
    return candidatos[0][1]


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

# Fallback estático só se a tabela fracoes estiver vazia / BD inacessível.
_MAPA_LETRA_LABEL_FALLBACK = {
    "A": "R/c Esq.", "B": "R/c Dto.", "C": "1º Esq.",
    "D": "1º Dto.", "E": "2º Esq.", "F": "2º Dto.",
}


def _mapa_letra_label(pasta=None) -> dict[str, str]:
    """Mapa letra→andar canónico (tabela fracoes via Database.mapas_fracoes)."""
    try:
        from Database import mapas_fracoes
        letra_para_label, _ = mapas_fracoes(pasta)
        if letra_para_label:
            return letra_para_label
    except Exception:
        pass
    return dict(_MAPA_LETRA_LABEL_FALLBACK)


def _norm_label(label: str, pasta=None) -> str:
    """Normaliza letra (A-F) ou rótulo para o rótulo canónico da fracção."""
    label = str(label or "").strip()
    if not label:
        return ""
    mapa = _mapa_letra_label(pasta)
    if len(label) == 1 and label.upper() in mapa:
        return mapa[label.upper()]
    return label


def _carregar_saldos_anteriores(output_path, tipo_quota) -> dict:
    """
    Obtém SALDO_ANT por fracção a partir de:
      1. receitas_resumo (SQLite)
      2. Tabela plana atual via load_receitas_wide (só valores != 0)

    Nunca grava/propaga zeros vindos de uma regeneração anterior.
    """
    resultado = {}
    pasta = Path(output_path).parent

    # --- 1) receitas_resumo (SQLite) ---
    try:
        from Database import get_connection, ConfigsRepo
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

    # --- 3) Tabela plana atual (SQL) – só valores não-zero ---
    try:
        rows, _ = load_receitas_wide("NORMAL" if "NORMAL" in str(tipo_quota).upper() else "EXTRA", resolver_pasta(output_path))
        for registo in rows:
            fracao = _norm_label(registo.get("FRAÇÃO", ""))
            if not fracao or fracao.upper() == "TOTAIS":
                continue
            val = clean_numeric(registo.get("SALDO_ANT", 0.0))
            if abs(val) > 0.0005:
                resultado[fracao] = val
        if resultado:
            print(f"  ✓ SALDO ANTERIOR lido da tabela plana: {len(resultado)} fracções")
    except Exception as e:
        print(f"  ⚠️  Leitura tabela plana SALDO_ANT: {e}")

    if not resultado:
        print("  ⚠️  Nenhum SALDO ANTERIOR encontrado em receitas_resumo / tabela plana")
    return resultado


# ====================================================================
# GERAR RECEITAS (SQL)
# ====================================================================

def gerar_db_receitas(tabela_quotas, mapa, output_path, tipo_quota, titulo):
    """Gera tabela de receitas (Normal ou Extra) em condominio.db via save_receitas_wide."""
    
    print(f"\n{'='*80}")
    print(f"💾 GERANDO: {titulo}")
    print(f"{'='*80}")

    saldos_anteriores = _carregar_saldos_anteriores(output_path, tipo_quota)
    
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
    from Database import save_receitas_wide, resolver_pasta
    pasta = resolver_pasta(output_path)
    tipo_sql = "NORMAL" if "NORMAL" in str(tipo_quota).upper() else "EXTRA"
    save_receitas_wide(df, tipo_sql, pasta)
    ok = True
    print(f"  ✅ Gravado (SQL wide): {pasta} / {tipo_sql}\n")

    # Sincronizar SALDO / SALDO_ANT para receitas_resumo
    # IMPORTANTE: nunca sobrescrever saldo_ant não-zero com zero
    try:
        from Database import get_connection, ConfigsRepo
        pasta = Path(output_path).parent if output_path else pasta
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
                _, label_para_letra = (None, {})
                try:
                    from Database import mapas_fracoes
                    _, label_para_letra = mapas_fracoes(pasta)
                except Exception:
                    label_para_letra = {
                        v.lower(): k
                        for k, v in _MAPA_LETRA_LABEL_FALLBACK.items()
                    }
                for row in rows:
                    label = str(row.get("FRACCAO", "")).strip()
                    if not label or label.upper() == "TOTAIS":
                        continue
                    letra = (
                        label_para_letra.get(label.lower())
                        or label_para_letra.get(label)
                        or (label if len(label) == 1 else label)
                    )
                    # Fallback estático invertido
                    if letra == label and len(label) > 1:
                        inv = {v: k for k, v in _MAPA_LETRA_LABEL_FALLBACK.items()}
                        letra = inv.get(label, label)
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
    """Gera Juros a partir do DataFrame aglutinado, via save_juros_wide."""
    
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
        except Exception:
            continue
        
        if conta not in juros_por_conta:
            juros_por_conta[conta] = {m: 0.0 for m in range(1, 13)}
        
        juros_por_conta[conta][mes] += round(valor, 2)
    
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
    from Database import save_juros_wide, resolver_pasta
    pasta = resolver_pasta(juros_db)
    save_juros_wide(df, pasta)
    print(f"  ✅ Gravado (SQL juros): {pasta}\n")


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
                       eps_tolerance=None,
                       pasta=None):
    """Processo principal — quotas e movimentos via API canónica.

    Preferir ``pasta=``. Os argumentos ``*_db`` (Configs, Bancos, …) são
    **legado de compatibilidade**: só servem para ``resolver_pasta``; tudo
    é lido/gravado em ``condominio.db`` na pasta resolvida.

    ``eps_tolerance``: se None, lê Configs QUOTAS/EPS_TOLERANCE (default 0.5).
    """
    from Database import resolver_pasta, ConfigsRepo

    print("\n" + "=" * 80)
    print("🔄 PROCESSAMENTO DE RECEITAS (SQL / API canónica)")
    print("=" * 80 + "\n")

    pasta_res = resolver_pasta(pasta if pasta is not None else bancos_db)

    # Tolerância a partir de Configs (QUOTAS / EPS_TOLERANCE)
    if eps_tolerance is None:
        try:
            raw = ConfigsRepo(pasta_res).get_value("QUOTAS", "EPS_TOLERANCE", 0.5)
            eps_tolerance = float(str(raw).replace(",", "."))
        except Exception:
            eps_tolerance = 0.5
    print(f"  • EPS_TOLERANCE = {eps_tolerance}")

    # 1. Carregar quotas
    print("PASSO 1: Carregando tabela de quotas...")
    tabela_quotas = carregar_tabela_quotas(pasta_res)

    if not tabela_quotas:
        print("❌ Tabela de quotas vazia")
        return

    # 2. Aglutinar movimentos
    print("\nPASSO 2: Aglutinando movimentos (bancos+caixa+dprazo)...")
    df_movimentos = aglutinar_movimentos(
        bancos_db, caixa_db, dprazo_db, pasta=pasta_res
    )
    
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
        rows_n, _ = load_receitas_wide("NORMAL", resolver_pasta(receitas_n_path))
        df_n = pd.DataFrame(rows_n, dtype=object)
        pd.set_option('display.float_format', '{:.2f}'.format)
        print(df_n.to_string(index=False))
    except Exception as e:
        print(f"ERRO ao exibir {receitas_n_path}: {e}")

    # Quotas Extras
    print("\n📊 QUOTAS EXTRAS")
    print("-"*120)
    try:
        rows_e, _ = load_receitas_wide("EXTRA", resolver_pasta(receitas_e_path))
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
            # eps_tolerance=None → lê QUOTAS/EPS_TOLERANCE das Configs
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