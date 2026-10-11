"""
Condominos.py - Lógica de negócio para gestão de condóminos
Contém funções de manipulação de dados (SQLite), processamento e validações
"""

import pandas as pd
from pathlib import Path
from Commons import BASE_DIR, clean_numeric
from Database import carregar_db, salvar_db, existe_dados

MORADA_FIXA = "Av. Sto Antonio, 42"
CPOSTAL_FIXO = "3810-332"
CIDADE_FIXA = "Aveiro"


# ====================================================================
# FUNÇÕES DE MANIPULAÇÃO DE DADOS (SQLite)
# ====================================================================

def carregar_condominos_db(caminho):
    """
    Carrega dados de condóminos (SQLite).

    Args:
        caminho: Caminho lógico (stem = nome da tabela em condominio.db)

    Returns:
        Lista de dicionários com dados dos condóminos
    """
    try:
        rows, _ = carregar_db(caminho)
    except Exception as exc:
        print(f"⚠️ Erro ao carregar Condominos pela ponte: {exc}")
        return []

    dados = []
    for row in rows:
        dados.append({
            'NOME': str(row.get('NOME') or '').strip(),
            'CHECK': '.T.' if _is_truthy(row.get('CHECK')) else '.F.',
            'MORADA': str(row.get('MORADA') or '').strip(),
            'CPOSTAL': str(row.get('CPOSTAL') or '').strip(),
            'CIDADE': str(row.get('CIDADE') or '').strip(),
            'TELEMOVEL': str(row.get('TELEMOVEL') or '').strip(),
            'EMAIL': str(row.get('EMAIL') or '').strip(),
            'FRACAO': str(row.get('FRACAO') or '').strip(),
            'ANDAR': str(row.get('ANDAR') or '').strip(),
            'PERMILAGEM': float(row.get('PERMILAGEM') or 0.0),
            'QUOTAN': float(row.get('QUOTAN') or 0.0),
            'QUOTAE': float(row.get('QUOTAE') or 0.0),
            'FOTO': str(row.get('FOTO') or '').strip(),
            'ADMIN': '.T.' if _is_truthy(row.get('ADMIN')) else '.F.'
        })
    return dados


def _is_truthy(value):
    if isinstance(value, str):
        return value.strip().upper() in {'.T.', 'T', 'TRUE', '1', 'YES'}
    if isinstance(value, (int, float, bool)):
        return bool(value)
    return bool(value)


def guardar_condominos_db(caminho, dados):
    """
    Guarda dados de condóminos em SQLite.

    Args:
        caminho: Caminho lógico (stem = nome da tabela em condominio.db)
        dados: Lista de dicionários com dados dos condóminos

    Returns:
        True se sucesso, False caso contrário
    """
    caminho_path = Path(caminho)
    field_specs = 'NOME C(40); MORADA C(40); CPOSTAL C(8); CIDADE C(10); TELEMOVEL C(11); EMAIL C(40); FRACAO C(1); ANDAR C(10); PERMILAGEM N(5,3); QUOTAN N(10,2); QUOTAE N(10,2); FOTO C(30); CHECK L; ADMIN L'

    try:
        rows = []
        for row_data in dados:
            check_val = row_data.get('CHECK', '.F.')
            admin_val = row_data.get('ADMIN', '.F.')
            rows.append({
                'NOME': str(row_data['NOME'])[:40],
                'MORADA': MORADA_FIXA,
                'CPOSTAL': CPOSTAL_FIXO,
                'CIDADE': CIDADE_FIXA,
                'TELEMOVEL': str(row_data['TELEMOVEL'])[:11],
                'EMAIL': str(row_data['EMAIL'])[:40],
                'FRACAO': str(row_data['FRACAO'])[:1],
                'ANDAR': str(row_data['ANDAR'])[:10],
                'PERMILAGEM': float(row_data.get('PERMILAGEM', 0) or 0),
                'QUOTAN': float(row_data.get('QUOTAN', 0) or 0),
                'QUOTAE': float(row_data.get('QUOTAE', 0) or 0),
                'FOTO': str(row_data['FOTO'])[:30],
                'CHECK': 1 if check_val in (True, 'T', '.T.', 't') else 0,
                'ADMIN': 1 if admin_val in (True, 'T', '.T.', 't') else 0,
            })
        df = pd.DataFrame(rows, dtype=object)
        return salvar_db(df, str(caminho_path), field_specs)
    except Exception as e:
        print(f"Erro ao guardar Condominos: {e}")
        return False


# ====================================================================
# FUNÇÕES DE VALIDAÇÃO
# ====================================================================

def validar_condominos(dados):
    """
    Valida dados dos condóminos
    
    Args:
        dados: Lista de dicionários com dados dos condóminos
    
    Raises:
        ValueError: Se alguma validação falhar
    """
    for row_data in dados:
        nome = str(row_data.get('NOME', '')).strip()
        andar = str(row_data.get('ANDAR', '')).strip()
        if nome.startswith('[') and nome.endswith(']') and not andar:
            raise ValueError(
                "Para condôminos inativos (nome entre []), "
                "o campo ANDAR é obrigatório e não pode estar vazio."
            )


# ====================================================================
# FUNÇÕES DE ATUALIZAÇÃO DE QUOTAS
# ====================================================================

def atualizar_quotas_configs(pasta_dados, dados_condominos):
    """
    V5: Actualiza as regras de condóminos na tabela 'regras' com base nos
    dados editados na GUI de Condóminos (quotas normal/extra).

    Faz upsert por (pattern=NOME_NORMALIZADO, normal IS NOT NULL):
    - Se já existe uma regra para este condómino → actualiza normal/extra
    - Se não existe → cria com pattern=nome_normalizado, conta=andar, classe=RECEITA
    """
    from Database import get_connection, db_path
    from Commons import remover_acentos

    pasta = BASE_DIR / pasta_dados
    condo_db = db_path(pasta)
    if not condo_db.exists():
        print("⚠️ condominio.db não encontrada — quotas não actualizadas")
        return

    # Mapeamento de ANDAR → conta contabilística (mesmo formato das regras)
    def conta_de_andar(andar: str) -> str:
        return f"Quota - {andar.strip()}" if andar.strip() else "Quota"

    try:
        with get_connection(pasta) as conn:
            for cond in dados_condominos:
                nome  = str(cond.get("NOME", "")).strip()
                andar = str(cond.get("ANDAR", "")).strip()
                quota_n = float(cond.get("QUOTAN", 0) or 0)
                quota_e = float(cond.get("QUOTAE", 0) or 0)

                if not nome or not andar:
                    continue

                # Pattern = nome normalizado (sem acentos, maiúsculas)
                pattern = remover_acentos(nome).upper()
                conta   = conta_de_andar(andar)

                # Verificar se já existe regra para este condómino
                existing = conn.execute(
                    "SELECT id FROM regras WHERE pattern=? AND normal IS NOT NULL LIMIT 1",
                    (pattern,)
                ).fetchone()

                if existing:
                    conn.execute(
                        "UPDATE regras SET conta=?, normal=?, extra=? WHERE id=?",
                        (conta, quota_n, quota_e, existing["id"])
                    )
                else:
                    # Calcular prioridade: condóminos têm 10-60 (antes das regras gerais)
                    n_cond = conn.execute(
                        "SELECT COUNT(*) FROM regras WHERE normal IS NOT NULL"
                    ).fetchone()[0]
                    prio = (n_cond + 1) * 10
                    conn.execute(
                        """INSERT INTO regras (prioridade, classe, conta, pattern, normal, extra)
                           VALUES (?,'RECEITA',?,?,?,?)""",
                        (prio, conta, pattern, quota_n, quota_e)
                    )
        print(f"  ✓ Quotas actualizadas na tabela regras ({len(dados_condominos)} condóminos)")
    except Exception as exc:
        print(f"⚠️ Erro ao actualizar quotas em regras: {exc}")


# ====================================================================
# FUNÇÕES DE PROCESSAMENTO DE PAGAMENTOS
# ====================================================================

def obter_pagamentos_condomino(andar, pasta_dados):
    """
    Processa receitas e filtra para o condómino específico.
    
    Args:
        andar: ANDAR do condómino (ex: "R/c Dto.")
        pasta_dados: Nome da pasta de dados (ex: "corrente")
    
    Returns:
        dict com dados dos pagamentos por mês
    """
    
    # Importar funções de Receitas.py
    try:
        from Receitas import (
            aglutinar_movimentos,
            carregar_tabela_quotas,
            processar_receitas_simplificado
        )
    except ImportError as e:
        raise Exception(f"Erro ao importar Receitas.py: {e}")
    
    # Caminhos dos ficheiros
    bancos_path = BASE_DIR / pasta_dados / "Bancos"
    caixa_path = BASE_DIR / pasta_dados / "Caixa"
    configs_path = BASE_DIR / pasta_dados / "Configs"
    
    # Verificar se há dados em condominio.db
    if not existe_dados(bancos_path):
        raise FileNotFoundError(f"Bancos não encontrado em {bancos_path}")
    if not existe_dados(configs_path):
        raise FileNotFoundError(f"Configs não encontrado em {configs_path}")
    
    # 1. Aglutinar movimentos
    df_movimentos = aglutinar_movimentos(str(bancos_path), str(caixa_path))
    
    if df_movimentos.empty:
        raise Exception("Nenhum movimento encontrado nos ficheiros")
    
    # 2. Carregar tabela de quotas
    tabela_quotas = carregar_tabela_quotas(str(configs_path))
    
    if not tabela_quotas:
        raise Exception("Nenhuma quota configurada em Configs")
    
    # 3. Processar receitas
    mapa_normal, mapa_extra = processar_receitas_simplificado(
        df_movimentos, 
        tabela_quotas
    )
    
    # 4. Filtrar para este condómino (ANDAR)
    fracao_normalizada = andar.strip()
    
    # Extrair dados dos mapas
    pagamentos_normais = mapa_normal.get(fracao_normalizada, {})
    pagamentos_extras = mapa_extra.get(fracao_normalizada, {})
    
    # 5. Construir tabela por mês
    meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 
             'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    
    dados_mensais = []
    total_normal = 0.0
    total_extra = 0.0
    
    for mes_num in range(1, 13):
        valor_normal = pagamentos_normais.get(mes_num, 0.0)
        valor_extra = pagamentos_extras.get(mes_num, 0.0)
        total_mes = valor_normal + valor_extra
        
        dados_mensais.append({
            'mes': meses[mes_num - 1],
            'normal': valor_normal,
            'extra': valor_extra,
            'total': total_mes
        })
        
        total_normal += valor_normal
        total_extra += valor_extra
    
    # 6. Retornar estrutura completa
    return {
        'dados_mensais': dados_mensais,
        'total_normal': total_normal,
        'total_extra': total_extra,
        'total_geral': total_normal + total_extra
    }


# ====================================================================
# FUNÇÕES AUXILIARES
# ====================================================================

def criar_novo_condomino():
    """
    Cria estrutura de um novo condómino com valores padrão
    
    Returns:
        Dicionário com dados padrão de um condómino
    """
    return {
        'NOME': '', 
        'TELEMOVEL': '', 
        'CHECK': '.F.', 
        'EMAIL': '', 
        'FRACAO': '', 
        'ANDAR': '',
        'PERMILAGEM': 0.0, 
        'QUOTAN': 0.0, 
        'QUOTAE': 0.0, 
        'FOTO': '', 
        'ADMIN': '.F.',
        'MORADA': MORADA_FIXA, 
        'CPOSTAL': CPOSTAL_FIXO, 
        'CIDADE': CIDADE_FIXA
    }


def obter_lista_administradores(pasta_dados):
    """
    Obtém lista de condóminos para seleção de administrador
    
    Args:
        pasta_dados: Nome da pasta de dados (ex: "corrente")
    
    Returns:
        Lista de tuplas (nome, is_admin_atual)
    """
    condominos_path = BASE_DIR / pasta_dados / "Condominos"
    if not existe_dados(condominos_path):
        return []
    
    dados = carregar_condominos_db(str(condominos_path))
    
    # Filtrar apenas condóminos ativos (sem [] no nome)
    administradores = []
    for cond in dados:
        nome = str(cond.get('NOME', '')).strip()
        if not (nome.startswith('[') and nome.endswith(']')):
            is_admin = cond.get('ADMIN', '.F.') in (True, 'T', '.T.', 't')
            administradores.append((nome, is_admin))
    
    return administradores


def definir_administrador(pasta_dados, nome_administrador):
    """
    Define um condómino como administrador (e remove flag dos outros)
    
    Args:
        pasta_dados: Nome da pasta de dados (ex: "corrente")
        nome_administrador: Nome do condómino a ser definido como admin
    
    Returns:
        True se sucesso, False caso contrário
    """
    condominos_path = BASE_DIR / pasta_dados / "Condominos"
    if not existe_dados(condominos_path):
        return False

    field_specs = 'NOME C(40); MORADA C(40); CPOSTAL C(8); CIDADE C(10); TELEMOVEL C(11); EMAIL C(40); FRACAO C(1); ANDAR C(10); PERMILAGEM N(5,3); QUOTAN N(10,2); QUOTAE N(10,2); FOTO C(30); CHECK L; ADMIN L'

    try:
        rows, _ = carregar_db(str(condominos_path))
        for row in rows:
            nome_atual = str(row.get('NOME', '')).strip()
            row['ADMIN'] = (nome_atual == nome_administrador)

        df = pd.DataFrame(rows, dtype=object)
        ok = salvar_db(df, str(condominos_path), field_specs)
        return bool(ok)
    except Exception as exc:
        print(f"Erro ao definir administrador: {exc}")
        return False