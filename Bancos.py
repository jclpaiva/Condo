import os
import re
import sys
import pandas as pd

from pathlib import Path
from datetime import date
from datetime import datetime
from Logging_utils import ativar_logging
from Database import (
    existe_dados,
    resolver_pasta,
    guardar_movimentos_fonte,
    carregar_movimentos_fonte,
    carregar_configs,
    fonte_de_path,
)

# Importações compartilhadas
from Commons import (
    BASE_DIR,
    IMPORT_DIR,
    PASTA_CORRENTE,
    db_path,
    clean_numeric,
    remover_acentos,
)

logger = ativar_logging("bancos")


# ====================================================================
# PARTE 1: CARREGAR CONFIGURAÇÕES E REGRAS (VERSÃO MELHORADA)
# ====================================================================

def carregar_configuracoes_e_regras(config_db_path):
    """
    Carrega configurações e dados para classificação do extracto.

    - configs    : parâmetros IMPORTACAO / GERAL / FORMATACAO
    - condominos : quotas e nomes a partir da tabela ``condominos``
                   (``quota_normal`` / ``quota_extra`` — não adivinha valores)
    - regras     : regras gerais (despesas/receitas não-quota) da tabela ``regras``
    """
    from Database import (
        get_connection,
        resolver_pasta,
        condominos_para_categorizacao,
        is_regra_condomino,
    )

    pasta = resolver_pasta(config_db_path)

    # ── 1. Configs (tudo excepto CLASSIFICACAO) ───────────────────────────────
    configs = {}
    try:
        rows = carregar_configs(config_db_path if config_db_path else pasta)
        for row in rows:
            if str(row.get("CATEGORIA", "")).strip() == "CLASSIFICACAO":
                continue
            chave = str(row.get("CHAVE", "")).strip()
            valor_raw = str(row.get("VALOR", "")).strip()
            tipo = str(row.get("TIPO", "")).strip()
            if tipo == "Number":
                try:
                    configs[chave] = float(valor_raw.replace(",", "."))
                    if chave == "CSV_FIRST_ROW":
                        configs[chave] = int(configs[chave])
                except ValueError:
                    configs[chave] = valor_raw
            else:
                configs[chave] = valor_raw
    except Exception as e:
        print(f"Erro ao ler Configs: {e}")

    # ── 2. Condóminos + quotas (tabela condominos) ────────────────────────────
    print("\n📋 Quotas lidas da tabela condominos:")
    condominos = condominos_para_categorizacao(pasta)

    # ── 3. Regras gerais (não-quota: limpeza, EDP, …) ─────────────────────────
    regras_gerais = []
    try:
        if not db_path(pasta).exists():
            print("⚠️  condominio.db não encontrada — sem regras gerais")
            return configs, condominos, regras_gerais

        with get_connection(pasta) as conn:
            rows_reg = conn.execute(
                "SELECT * FROM regras WHERE ativo=1 ORDER BY prioridade, id"
            ).fetchall()

        for r in rows_reg:
            pattern = (r["pattern"] or "").strip()
            conta = (r["conta"] or "").strip()
            classe = (r["classe"] or "DESPESA").strip().upper()
            prio = int(r["prioridade"] or 100)
            normal = r["normal"]
            extra = r["extra"]

            if not pattern:
                continue
            # Regras de quota de condómino: valores vêm de condominos, não daqui
            if is_regra_condomino(classe, conta, normal, extra):
                continue

            if normal is not None:
                regras_gerais.append({
                    "CHAVE_CONFIG": f"REG_{conta}",
                    "PATTERN": pattern,
                    "CLASSE": classe,
                    "CONTA": conta,
                    "PRIORIDADE": prio,
                    "USA_VALOR": True,
                    "VALOR_ESPECIFICO": float(normal),
                })
            else:
                regras_gerais.append({
                    "CHAVE_CONFIG": f"REG_{conta}",
                    "PATTERN": pattern,
                    "CLASSE": classe,
                    "CONTA": conta,
                    "PRIORIDADE": prio,
                    "USA_VALOR": False,
                    "VALOR_ESPECIFICO": None,
                })

        regras_gerais.sort(key=lambda x: x.get("PRIORIDADE", 100))

    except Exception as e:
        print(f"Erro ao carregar tabela regras: {e}")

    print(f"-> Condóminos com quotas para classificar: {len(condominos)}")
    print(f"-> Regras gerais (não-quota): {len(regras_gerais)}")

    if "CSV_FIRST_ROW" not in configs:
        print("AVISO: 'CSV_FIRST_ROW' não encontrada em Configs.")

    return configs, condominos, regras_gerais


# ====================================================================
# PARTE 2: LÓGICA DE CATEGORIZAÇÃO
# ====================================================================
# Matemática de quotas: módulo partilhado Quotas.py (v1.01)
from Quotas import classificar_valor_quota  # noqa: E402


def aplicar_regras_categorizacao(df_dados, condominos, regras_gerais):
    if df_dados.empty:
        return df_dados
    
    df_dados = df_dados.copy()
    df_dados['DESCRICAO_LIMPA'] = (
        df_dados['DESCRICAO'].astype(str)
        .apply(remover_acentos)
        .str.upper()
        .str.replace(r'[.,;:\-—–/\()\[\]"\'ºª]', ' ', regex=True)
        .str.strip()
        .str.replace(r'\s+', ' ', regex=True)
    )
    
    df_dados['TIPO'] = ''
    df_dados['CONTA'] = ''
    df_dados['OBSERVACAO'] = ''
    
    # 1. APLICAR REGRAS DE CONDÓMINOS
    for cond in condominos:
        mascara_nome = df_dados['DESCRICAO_LIMPA'].str.contains(cond['NOME'], case=False, na=False, regex=False)
        
        if cond['NOME_ALTERNATIVO']:
            mascara_alt = df_dados['DESCRICAO_LIMPA'].str.contains(cond['NOME_ALTERNATIVO'], case=False, na=False, regex=False)
            mascara_nome = mascara_nome | mascara_alt
        
        mascara_final = mascara_nome & (df_dados['TIPO'] == '')
        
        if mascara_final.any():
            df_dados.loc[mascara_final, 'TIPO'] = 'RECEITA'
            
            for idx in df_dados[mascara_final].index:
                valor = abs(clean_numeric(df_dados.loc[idx, 'VALOR']))
                v_norm = float(cond.get('VALOR_NORMAL') or 0)
                v_extra = float(cond.get('VALOR_EXTRA') or 0)
                conta_base = cond['CONTA']
                conta, obs = classificar_valor_quota(valor, v_norm, v_extra, conta_base)
                df_dados.loc[idx, 'CONTA'] = conta
                df_dados.loc[idx, 'OBSERVACAO'] = obs
    
    # 2. APLICAR REGRAS GERAIS
    if regras_gerais:
        print(f"\n→ Aplicando {len(regras_gerais)} regras gerais...")

    for regra in regras_gerais:
        pattern = regra['PATTERN'].upper().strip()
        if not pattern:
            print(f"  AVISO: Regra {regra['CHAVE_CONFIG']} tem pattern vazio")
            continue
        
        pattern = remover_acentos(pattern)
        pattern_limpo = re.sub(r'[.,;:\-—–/\()\[\]"\'ºª]', ' ', pattern)
        pattern_limpo = re.sub(r'\s+', ' ', pattern_limpo).strip()
        
        mascara = (df_dados['TIPO'] == '') & df_dados['DESCRICAO_LIMPA'].str.contains(pattern_limpo, case=False, na=False, regex=False)
        
        if regra['USA_VALOR'] and regra['VALOR_ESPECIFICO'] is not None:
            mascara_valor = df_dados['VALOR'].apply(lambda v: abs(clean_numeric(v) - regra['VALOR_ESPECIFICO']) < 0.01)
            mascara = mascara & mascara_valor
        
        if mascara.any():
            if regra['CLASSE']:
                df_dados.loc[mascara, 'TIPO'] = regra['CLASSE']
                print(f"  ✓ {int(mascara.sum())}× '{regra['PATTERN']}' → {regra['CLASSE']} / {regra.get('CONTA', '')}")
            else:
                for idx in df_dados[mascara].index:
                    valor = clean_numeric(df_dados.loc[idx, 'VALOR'])
                    if valor < 0:
                        df_dados.loc[idx, 'TIPO'] = 'DESPESA'
                    elif valor > 0:
                        df_dados.loc[idx, 'TIPO'] = 'RECEITA'
                    else:
                        df_dados.loc[idx, 'TIPO'] = ''
            
            df_dados.loc[mascara, 'CONTA'] = regra['CONTA']
            df_dados.loc[mascara, 'OBSERVACAO'] = ''
    
    # 3. CLASSIFICAÇÃO PADRÃO
    mascara_nao_classificados = (df_dados['TIPO'] == '')
    for idx in df_dados[mascara_nao_classificados].index:
        valor = clean_numeric(df_dados.loc[idx, 'VALOR'])
        if valor < 0:
            df_dados.loc[idx, 'TIPO'] = 'DESPESA'
        elif valor > 0:
            df_dados.loc[idx, 'TIPO'] = 'RECEITA'
    
    df_dados = df_dados.drop(columns=['DESCRICAO_LIMPA'])
    
    return df_dados


# ====================================================================
# PARTE 3: IMPORTAÇÃO CSV 100% PARAMETRIZADA VIA CONFIGS
# ====================================================================

def carregar_parametros_importacao(configs):
    parametros_obrigatorios = {
        'TOTAL_COLUMNS': {'tipo': 'Number', 'descricao': 'Total de colunas no CSV'},
        'CSV_FIRST_ROW': {'tipo': 'Number', 'descricao': 'Primeira linha com dados (não header)'},
        'CSV_DELIMITER': {'tipo': 'String', 'descricao': 'Delimitador de colunas (ex: ;)'},
        'CSV_DECIMAL': {'tipo': 'String', 'descricao': 'Separador decimal (ex: ,)'},
        'CSV_THOUSANDS': {'tipo': 'String', 'descricao': 'Separador de milhares (ex: .)'},
        'COL_DATA': {'tipo': 'Number', 'descricao': 'Índice da coluna DATA (0-based)'},
        'COL_DESCRICAO': {'tipo': 'Number', 'descricao': 'Índice da coluna DESCRIÇÃO'},
        'COL_VALOR': {'tipo': 'Number', 'descricao': 'Índice da coluna VALOR'},
        'COL_SALDO': {'tipo': 'Number', 'descricao': 'Índice da coluna SALDO'}
    }
    
    parametros_opcionais = {
        'CSV_AUTO_DETECT': 'False',
        # Código de página do extracto (Configs.COD_PAGINA = cp1252 / ANSI)
        'COD_PAGINA': 'cp1252',
    }
    
    params = {}
    erros = []
    
    print("\n📋 CARREGANDO PARÂMETROS DE CONFIGS...")
    print("─" * 80)
    
    for chave, info in parametros_obrigatorios.items():
        valor = configs.get(chave)
        
        if valor is None:
            erros.append({
                'chave': chave,
                'tipo': info['tipo'],
                'descricao': info['descricao']
            })
            print(f"  ❌ {chave:<20} - NÃO ENCONTRADO")
        else:
            param_name = chave.lower()
            params[param_name] = valor
            print(f"  ✓  {chave:<20} = {valor}")
    
    for chave, valor_padrao in parametros_opcionais.items():
        valor = configs.get(chave, valor_padrao)
        param_name = chave.lower()
        
        if chave == 'CSV_AUTO_DETECT':
            params[param_name] = str(valor).upper() in ('TRUE', '1', 'SIM')
        elif chave == 'COD_PAGINA':
            # Normaliza aliases comuns (ANSI, Windows-1252, etc.) para o nome usado pelo Python
            aliases = {
                'ansi': 'cp1252',
                'windows-1252': 'cp1252',
                'win1252': 'cp1252',
                'latin1': 'latin-1',
                'iso8859-1': 'latin-1',
                'iso-8859-1': 'latin-1',
                'utf8': 'utf-8',
            }
            enc = str(valor or valor_padrao).strip().lower()
            params['cod_pagina'] = aliases.get(enc, enc) or 'cp1252'
        else:
            params[param_name] = valor
        
        origem = "Configs" if configs.get(chave) is not None else "valor padrão"
        shown = params.get(param_name, valor)
        print(f"  ℹ️  {chave:<20} = {shown} ({origem})")
    
    print("─" * 80)
    
    if erros:
        msg_erro = "\n❌ Parâmetros obrigatórios em falta."
        return None, msg_erro
    
    return params, None


# ====================================================================
# FUNÇÃO PRINCIPAL DE IMPORTAÇÃO
# ====================================================================

def _ler_movimentos_csv(csv_path, params):
    """
    Lê o CSV e extrai as colunas DATA, DESCRICAO, VALOR e SALDO de acordo com
    os parâmetros de importação. Levanta exceção se o ficheiro não corresponder
    ao layout configurado (ex.: o banco alterou o formato).

    Codificação: sempre a definida em Configs.COD_PAGINA (default cp1252).
    """
    print("\n📖 LENDO FICHEIRO CSV...")

    # Encoding: sempre o configurado em Configs.COD_PAGINA
    encoding = params['cod_pagina']
    print(f"  ✓ Encoding (Configs COD_PAGINA): {encoding}")

    if params.get('csv_auto_detect'):
        print("  • Modo: Detecção automática do header")
        with open(csv_path, 'r', encoding=encoding, errors='replace') as f:
            lines = f.readlines()
            data_start_line = None

            for i, line in enumerate(lines):
                if line.strip().startswith('Data mov.'):
                    data_start_line = i + 1
                    print(f"  ✓ Header encontrado na linha {i+1}")
                    break

            if data_start_line is None:
                raise ValueError("Header 'Data mov.' não encontrado")

            total_skiprows = data_start_line
    else:
        print("  • Modo: Linha fixa (configurada em CSV_FIRST_ROW)")
        total_skiprows = int(params['csv_first_row']) - 1
        print(f"  ✓ Saltando {total_skiprows} linhas")

    try:
        df_csv = pd.read_csv(
            csv_path,
            sep=params['csv_delimiter'],
            skiprows=total_skiprows,
            header=None,
            encoding=encoding,
            decimal=params['csv_decimal'],
            thousands=params['csv_thousands'] or None,
            keep_default_na=False,
        )
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Não foi possível ler o CSV com o encoding configurado "
            f"(COD_PAGINA='{encoding}'). Verifica o valor em Configs. Erro: {e}"
        )

    df_csv = df_csv.dropna(how='all')
    print(f"  ✓ {len(df_csv)} linhas lidas do CSV")
    print(f"  ✓ {df_csv.shape[1]} colunas encontradas")

    print("\n📋 EXTRAINDO COLUNAS...")

    colunas_indices = [
        int(params['col_data']),
        int(params['col_descricao']),
        int(params['col_valor']),
        int(params['col_saldo'])
    ]

    max_col = max(colunas_indices)
    if df_csv.shape[1] <= max_col:
        raise ValueError(
            f"Layout do CSV não corresponde aos parâmetros guardados ("
            f"delimitador '{params['csv_delimiter']}'): ficheiro com "
            f"{df_csv.shape[1]} coluna(s), mas pediu-se a coluna {max_col}."
        )

    df_dados = df_csv.iloc[:, colunas_indices].copy()
    df_dados.columns = ['DATA', 'DESCRICAO', 'VALOR', 'SALDO']
    print("  ✓ Colunas extraídas com sucesso")
    return df_dados


def _detetar_params_importacao(csv_path, cod_pagina):
    """
    Deteta automaticamente o formato do CSV (mesma lógica do 'Analisar CSV' em
    Configurações) e devolve os parâmetros no formato usado pela importação.
    Serve de rede de segurança quando os parâmetros guardados em Configs já não
    correspondem ao ficheiro (o banco alterou o layout).

    O encoding usado é sempre o 'cod_pagina' já carregado de Configs.COD_PAGINA
    — nunca se tenta adivinhar a codificação a partir do ficheiro.
    """
    try:
        from Analisar_csv import CSVAnalyzer
        detetados = CSVAnalyzer(csv_path, encoding=cod_pagina).analyze()
    except Exception as e:
        print(f"  ✖ Deteção automática falhou: {e}")
        return None

    if not detetados:
        return None

    try:
        return {
            'csv_auto_detect': False,
            'total_columns': int(detetados['TOTAL_COLUMNS']),
            'csv_first_row': int(detetados['CSV_FIRST_ROW']),
            'csv_delimiter': detetados['CSV_DELIMITER'],
            'csv_decimal': detetados['CSV_DECIMAL'],
            'csv_thousands': detetados['CSV_THOUSANDS'],
            'col_data': int(detetados['COL_DATA']),
            'col_descricao': int(detetados['COL_DESCRICAO']),
            'col_valor': int(detetados['COL_VALOR']),
            'col_saldo': int(detetados['COL_SALDO']),
            'cod_pagina': cod_pagina,
        }
    except Exception as e:
        print(f"  ✖ Parâmetros detetados inválidos: {e}")
        return None


def importar_e_processar_bancos(csv_path, configs, output_db_path, condominos, regras_gerais):
    print("\n" + "="*80)
    print("🔥 IMPORTAÇÃO DE MOVIMENTOS BANCÁRIOS")
    print("="*80)
    
    params, erro = carregar_parametros_importacao(configs)
    
    if erro:
        print(erro)
        raise ValueError("Parâmetros obrigatórios em falta em Configs")

    try:
        df_dados = _ler_movimentos_csv(csv_path, params)
    except Exception as e:
        # Auto-adaptação: o layout do ficheiro mudou em relação ao que está
        # gravado em Configs. Deteta o formato real e reutiliza-o nesta
        # importação (os parâmetros guardados não são alterados).
        print(f"  ✖ Leitura com os parâmetros de Configs falhou: {e}")
        print("  🔎 A detetar automaticamente o formato do ficheiro (fallback)...")
        params_det = _detetar_params_importacao(csv_path, params['cod_pagina'])
        if not params_det:
            print("  ✖ Não foi possível detetar automaticamente o formato do CSV.")
            raise
        params.update(params_det)
        print("  ✓ Formato detetado automaticamente (usado apenas nesta importação).")
        print("    💡 Corra 'Analisar CSV' em Configurações para gravar o novo formato.")
        df_dados = _ler_movimentos_csv(csv_path, params)
    
    print("\n🔄 CONVERTENDO TIPOS DE DADOS...")
    
    df_dados['DESCRICAO'] = df_dados['DESCRICAO'].astype(str).str.strip().str.replace('"', '')
    df_dados['VALOR'] = pd.to_numeric(df_dados['VALOR'], errors='coerce')
    df_dados['SALDO'] = pd.to_numeric(df_dados['SALDO'], errors='coerce')
    df_dados['DATA'] = pd.to_datetime(df_dados['DATA'], errors='coerce', dayfirst=True)
    
    linhas_antes = len(df_dados)
    df_dados = df_dados.dropna(subset=['DATA'])
    linhas_depois = len(df_dados)
    
    if linhas_antes > linhas_depois:
        print(f"  ⚠️  {linhas_antes - linhas_depois} linhas ignoradas (data inválida)")
    
    print(f"  ✓ {linhas_depois} movimentos válidos")
    
    print("\n🏷️  APLICANDO REGRAS DE CATEGORIZAÇÃO...")
    df_dados = aplicar_regras_categorizacao(df_dados, condominos, regras_gerais)
    print(f"  ✓ Categorização concluída")
    
    print("\n⚙️  PREPARANDO DADOS FINAIS...")
    
    df_dados = df_dados.iloc[::-1].reset_index(drop=True)
    
    if not df_dados.empty:
        primeiro_registo = df_dados.iloc[0]
        ano_corrente = primeiro_registo['DATA'].year
        data_saldo_anterior = pd.to_datetime(f'01-01-{ano_corrente}', format='%d-%m-%Y')
        
        saldo_final_primeiro = clean_numeric(primeiro_registo['SALDO'])
        valor_primeiro = clean_numeric(primeiro_registo['VALOR'])
        saldo_anterior = saldo_final_primeiro - valor_primeiro
        
        print(f"  • Ano dos movimentos: {ano_corrente}")
        print(f"  • Saldo anterior calculado: {saldo_anterior:.2f} €")
    else:
        saldo_anterior = 0.0
        data_saldo_anterior = pd.to_datetime('01-01-1900', format='%d-%m-%Y')
        print(f"  ⚠️  Nenhum movimento encontrado")

    registo_saldo_inicial = pd.DataFrame([{
        'DATA': data_saldo_anterior,
        'DESCRICAO': '***',
        'VALOR': 0.0,
        'SALDO': saldo_anterior,
        'TIPO': 'RECEITA',
        'CONTA': 'SALDO ANTERIOR',
        'OBSERVACAO': ''
    }])
    
    df_final = pd.concat([registo_saldo_inicial, df_dados], ignore_index=True)
    
    df_final['VALOR'] = df_final['VALOR'].fillna(0.0)
    df_final['SALDO'] = df_final['SALDO'].fillna(0.0)
    df_final['OBSERVACAO'] = df_final['OBSERVACAO'].fillna('')
    df_final['TIPO'] = df_final['TIPO'].fillna('')
    df_final['CONTA'] = df_final['CONTA'].fillna('')
    
    print(f"  ✓ {len(df_final)} registos preparados")
    
    # =================================================================
    # GRAVAÇÃO — RECRIAÇÃO COMPLETA DO FICHEIRO VIA BRIDGE COMPATÍVEL
    # =================================================================
    print("\n💾 GRAVANDO MOVIMENTOS BANCÁRIOS (SQL / API canónica)...")

    try:
        pasta = resolver_pasta(output_db_path)
        ok = guardar_movimentos_fonte(df_final, pasta=pasta, fonte="bancos")
        if not ok:
            raise RuntimeError('guardar_movimentos_fonte falhou para Bancos')

        print("\n🔄 SINCRONIZANDO MOVIMENTOS DE POUPANÇA PARA DPRAZO...")
        try:
            sincronizar_poupanca_dprazo(output_db_path, 'DPrazo')
        except Exception as e:
            print(f"  ⚠️  Aviso: Falha na sincronização de poupança (continuando): {e}")
            import traceback
            traceback.print_exc()

        print(f"  ✓ {len(df_final)} registos gravados com sucesso")

    except Exception as e:
        print(f"  ❌ Erro crítico ao gravar movimentos bancários: {e}")
        import traceback
        traceback.print_exc()
        raise

    print("\n" + "="*80)
    print("✅ IMPORTAÇÃO CONCLUÍDA COM SUCESSO")
    print("="*80)
    print(f"\n📊 Resumo:")
    print(f"  • Ficheiro CSV:         {csv_path}")
    print(f"  • Movimentos importados: {len(df_final)}")
    print(f"  • Destino:              {output_db_path}")
    print("="*80 + "\n")


# 🔥 🔥 🔥 GRAVA MOVIMENTOS DEP.PRAZO (POUPANÇA) EM DPRAZO INVERTENDO TIPO MOVIMENTOS E VALORES🔥 🔥 🔥
def sincronizar_poupanca_dprazo(bancos_db='Bancos', dprazo_db='DPrazo'):
    """
    Sincroniza movimentos de poupança (Bancos → DPrazo) via SQLite.
    Cria a tabela DPrazo automaticamente se ainda não existir.
    """
    from pathlib import Path

    def _chave_ordenacao_data(valor):
        """
        Normaliza um valor de DATA (pode vir como None, string ISO devolvida
        pelo SQLite, datetime.date/datetime) para
        um datetime.date comparável, para a ordenação nunca misturar strings
        com objectos data (o que faria sorted() rebentar com TypeError).
        """
        if not valor:
            return date(1900, 1, 1)
        if isinstance(valor, datetime):
            return valor.date()
        if isinstance(valor, date):
            return valor
        if isinstance(valor, str):
            try:
                return datetime.strptime(valor[:10], '%Y-%m-%d').date()
            except ValueError:
                return date(1900, 1, 1)
        if all(hasattr(valor, a) for a in ('year', 'month', 'day')):
            try:
                return date(valor.year, valor.month, valor.day)
            except Exception:
                pass
        return date(1900, 1, 1)

    def recalcular_saldos_dprazo_local(caminho_db):
        rows = carregar_movimentos_fonte(resolver_pasta(caminho_db), fonte_de_path(caminho_db))
        dados = []
        for rec in rows:
            dados.append({
                'DATA': rec.get('DATA', None),
                'TIPO': str(rec.get('TIPO', '')).strip().upper(),
                'CONTA': str(rec.get('CONTA', '')).strip(),
                'DESCRICAO': str(rec.get('DESCRICAO', '')).strip(),
                'VALOR': clean_numeric(rec.get('VALOR', 0.0)),
                'SALDO': clean_numeric(rec.get('SALDO', 0.0)),
                'OBSERVACAO': str(rec.get('OBSERVACAO', '')).strip()
            })

        dados.sort(key=lambda x: _chave_ordenacao_data(x['DATA']))
        saldo = 0.0
        for i, row in enumerate(dados):
            if i == 0:
                saldo = row['SALDO']
            else:
                valor = row['VALOR']
                tipo = row['TIPO']
                if tipo == 'RECEITA':
                    saldo += valor
                elif tipo == 'DESPESA':
                    saldo += valor
                row['SALDO'] = round(saldo, 2)

        df = pd.DataFrame(dados)
        guardar_movimentos_fonte(df, pasta=resolver_pasta(caminho_db), fonte=fonte_de_path(caminho_db))

    # Resolve caminhos relativos contra a pasta do Bancos (e não contra o
    # diretório de trabalho atual). Assim o DPrazo fica sempre ao lado do
    # Bancos, independentemente do CWD, e nunca se cria uma base de dados
    # numa pasta errada (ex.: raiz do projeto).
    bancos_path = Path(bancos_db).resolve()
    dprazo_path = Path(dprazo_db)
    if not dprazo_path.is_absolute():
        dprazo_path = bancos_path.parent / dprazo_path
    dprazo_path = dprazo_path.resolve()

    print("\n" + "="*80)
    print(f"SINCRONIZAÇÃO DE POUPANÇA: {bancos_path.name} → {dprazo_path.name}")
    print("="*80)
    print(f"  📁 Bancos: {bancos_path}")
    print(f"  📁 DPrazo: {dprazo_path}")

    if not existe_dados(dprazo_path):
        print(f"\n  ⚠️  DPrazo ainda não existe. Criando estrutura inicial...")
        try:
            df_seed = pd.DataFrame([{
                'DATA': datetime(1900, 1, 1).date(),
                'TIPO': 'RECEITA',
                'CONTA': 'SALDO ANTERIOR',
                'DESCRICAO': '***',
                'VALOR': 0.0,
                'SALDO': 0.0,
                'OBSERVACAO': ''
            }])
            ok = guardar_movimentos_fonte(
                df_seed, pasta=resolver_pasta(dprazo_path), fonte="dprazo"
            )
            if not ok:
                raise RuntimeError('guardar_movimentos_fonte falhou ao recriar seed de DPrazo')
            print(f"  ✓ DPrazo criado com sucesso!")
        except Exception as e:
            print(f"  ❌ Erro ao criar DPrazo: {e}")
            return 0

    registos_adicionados = 0
    try:
        print(f"\n📖 Lendo {bancos_path.name}...")
        rows_bancos = carregar_movimentos_fonte(resolver_pasta(bancos_path), 'bancos')
        df_bancos = pd.DataFrame(rows_bancos, dtype=object)

        rows_dprazo = carregar_movimentos_fonte(resolver_pasta(dprazo_path), 'dprazo')
        df_dprazo = pd.DataFrame(rows_dprazo, dtype=object)
        if df_dprazo.empty:
            df_dprazo = pd.DataFrame([{
                'DATA': datetime(1900, 1, 1).date(),
                'TIPO': 'RECEITA',
                'CONTA': 'SALDO ANTERIOR',
                'DESCRICAO': '***',
                'VALOR': 0.0,
                'SALDO': 0.0,
                'OBSERVACAO': ''
            }])

        existentes = set()
        for _, rec in df_dprazo.iterrows():
            data_str = str(rec.get('DATA', '')) if rec.get('DATA', '') else ''
            val_str = f"{abs(clean_numeric(rec.get('VALOR', 0.0))):.2f}"
            key = f"{data_str}|{val_str}|{str(rec.get('TIPO', '')).strip()}"
            existentes.add(key)

        total_registos = len(df_bancos)
        for _, rec in df_bancos.iterrows():
            tipo = str(rec.get('TIPO', '')).strip().upper()
            conta = str(rec.get('CONTA', '')).strip().upper()
            descricao = str(rec.get('DESCRICAO', '')).strip().upper()
            valor = clean_numeric(rec.get('VALOR', 0.0))
            data = rec.get('DATA', datetime.now().date())
            observacao = str(rec.get('OBSERVACAO', '')).strip()

            conta_norm = conta.replace('Ç', 'C').replace('Ã', 'A').replace('Õ', 'O').replace('Á', 'A')
            desc_norm = descricao.replace('Ç', 'C').replace('Ã', 'A').replace('Õ', 'O').replace('Á', 'A')
            is_poupanca = ('POUPANCA' in conta_norm or 'POUPANÇA' in conta or 'POUP' in conta_norm or 'POUP' in desc_norm)
            if not is_poupanca:
                continue

            if (tipo == 'DESPESA' and
                ('DEPOSITO' in desc_norm or 'DEPÓSITO' in descricao or 'DEP ' in desc_norm or 'TRANSFER' in desc_norm) and
                ('POUPANCA' in conta_norm or 'POUPANÇA' in conta)):

                valor_dprazo = abs(valor)
                chave = f"{data}|{valor_dprazo:.2f}|RECEITA"
                if chave not in existentes:
                    print(f"  ✅ DEPÓSITO detectado ({data}): +{valor_dprazo:.2f} € → DPrazo")
                    df_dprazo = pd.concat([df_dprazo, pd.DataFrame([{
                        'DATA': data,
                        'TIPO': 'RECEITA',
                        'CONTA': 'Poupança',
                        'DESCRICAO': str(rec.get('DESCRICAO', '')).strip(),
                        'VALOR': valor_dprazo,
                        'SALDO': 0.0,
                        'OBSERVACAO': observacao
                    }])], ignore_index=True)
                    registos_adicionados += 1
                    existentes.add(chave)

            elif (tipo == 'RECEITA' and
                  ('RESGATE' in desc_norm or 'LEV' in desc_norm or 'LEVANT' in desc_norm or 'SAQUE' in desc_norm) and
                  ('POUPANCA' in conta_norm or 'POUPANÇA' in conta)):

                valor_dprazo = -abs(valor)
                chave = f"{data}|{abs(valor_dprazo):.2f}|DESPESA"
                if chave not in existentes:
                    print(f"  ✅ RESGATE detectado ({data}): {valor_dprazo:.2f} € → DPrazo")
                    df_dprazo = pd.concat([df_dprazo, pd.DataFrame([{
                        'DATA': data,
                        'TIPO': 'DESPESA',
                        'CONTA': 'Poupança',
                        'DESCRICAO': str(rec.get('DESCRICAO', '')).strip(),
                        'VALOR': valor_dprazo,
                        'SALDO': 0.0,
                        'OBSERVACAO': observacao
                    }])], ignore_index=True)
                    registos_adicionados += 1
                    existentes.add(chave)

        print(f"\n📊 Total processado: {total_registos} registos em Bancos")
        print(f"✅ {registos_adicionados} novos registos sincronizados para DPrazo")

        if registos_adicionados > 0:
            if not guardar_movimentos_fonte(
                df_dprazo, pasta=resolver_pasta(dprazo_path), fonte="dprazo"
            ):
                raise RuntimeError('guardar_movimentos_fonte falhou para DPrazo')

            print(f"\n🔍 Verificando saldos negativos...")
            dados_temp = []
            for _, row in df_dprazo.iterrows():
                dados_temp.append({
                    'DATA': row.get('DATA', None),
                    'TIPO': str(row.get('TIPO', '')).strip().upper(),
                    'CONTA': str(row.get('CONTA', '')).strip(),
                    'DESCRICAO': str(row.get('DESCRICAO', '')).strip(),
                    'VALOR': clean_numeric(row.get('VALOR', 0.0)),
                    'SALDO': clean_numeric(row.get('SALDO', 0.0)),
                    'OBSERVACAO': str(row.get('OBSERVACAO', '')).strip()
                })

            dados_temp.sort(key=lambda x: _chave_ordenacao_data(x['DATA']))
            saldo = 0.0
            for i, row in enumerate(dados_temp):
                if i == 0:
                    saldo = row['SALDO']
                else:
                    valor = row['VALOR']
                    tipo = row['TIPO']
                    if tipo == 'RECEITA':
                        saldo += valor
                    elif tipo == 'DESPESA':
                        saldo += valor
                    row['SALDO'] = round(saldo, 2)

            registos_juros = []
            for row in dados_temp:
                if row['SALDO'] < -0.01:
                    valor_juros = abs(row['SALDO'])
                    registos_juros.append({
                        'DATA': row['DATA'],
                        'TIPO': 'RECEITA',
                        'CONTA': 'Juros',
                        'DESCRICAO': 'JUROS POUPANCA',
                        'VALOR': valor_juros,
                        'SALDO': 0.0,
                        'OBSERVACAO': ''
                    })
                    print(f"  ✅ Saldo negativo detectado ({row['DATA']}): {row['SALDO']:.2f} € → Adicionar juros de +{valor_juros:.2f} €")

            if registos_juros:
                for reg_juros in registos_juros:
                    df_dprazo = pd.concat([df_dprazo, pd.DataFrame([reg_juros])], ignore_index=True)
                if not guardar_movimentos_fonte(
                    df_dprazo, pasta=resolver_pasta(dprazo_path), fonte="dprazo"
                ):
                    raise RuntimeError('guardar_movimentos_fonte falhou ao guardar juros em DPrazo')

                print(f"\n🔄 Recalculando saldos finais em {dprazo_path.name}...")
                recalcular_saldos_dprazo_local(str(dprazo_path))
            else:
                print(f"\n🔄 Recalculando saldos em {dprazo_path.name}...")
                recalcular_saldos_dprazo_local(str(dprazo_path))

        print("="*80)
        return registos_adicionados

    except Exception as e:
        print(f"\n❌ ERRO crítico na sincronização: {e}")
        import traceback
        traceback.print_exc()
        return 0