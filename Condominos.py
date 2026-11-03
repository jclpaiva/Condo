"""
Condominos.py - Lógica de negócio para gestão de condóminos
Contém funções de manipulação de dados (SQLite), processamento e validações
"""

import pandas as pd
from pathlib import Path
from Commons import BASE_DIR, clean_numeric, db_path
from Database import carregar_condominos, guardar_condominos, existe_dados, resolver_pasta

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
        rows = carregar_condominos(caminho)
    except Exception as exc:
        print(f"⚠️ Erro ao carregar Condominos: {exc}")
        return []

    dados = []
    for row in rows:
        dados.append({
            'ID': row.get('ID'),
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
            # Preservar 1 / -1 / 0 (atual / cessante / outros)
            'ADMIN': (lambda v: (
                1 if v in (True, 1, '1', 'T', '.T.', 't') else
                (-1 if v in (-1, '-1') or (isinstance(v, (int, float)) and int(v) == -1) else 0)
            ))(row.get('ADMIN', 0)),
            'CC_NUMERO': str(row.get('CC_NUMERO') or '').strip(),
            'CC_VALIDADE': str(row.get('CC_VALIDADE') or '').strip(),
            'NIF': str(row.get('NIF') or '').strip(),
        })
    return dados


def _is_truthy(value):
    if isinstance(value, str):
        return value.strip().upper() in {'.T.', 'T', 'TRUE', '1', 'YES'}
    if isinstance(value, (int, float, bool)):
        return bool(value)
    return bool(value)


def eh_admin_atual(val) -> bool:
    """True apenas para o administrador em exercício (admin == 1).

    admin == -1 é o cessante e não conta como atual (não mostra coroa).
    """
    if val is True:
        return True
    if val is False or val is None or val == "":
        return False
    try:
        return int(val) == 1
    except (TypeError, ValueError):
        return str(val).strip().upper() in ("1", "T", ".T.", "TRUE")


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

    try:
        rows = []
        for row_data in dados:
            check_val = row_data.get('CHECK', '.F.')
            admin_val = row_data.get('ADMIN', '.F.')
            rows.append({
                'ID': row_data.get('ID'),
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
                'ADMIN': (
                    1 if admin_val in (True, 1, '1', 'T', '.T.', 't')
                    else (-1 if admin_val in (-1, '-1') else 0)
                ),
                'CC_NUMERO': str(row_data.get('CC_NUMERO') or '')[:20],
                'CC_VALIDADE': str(row_data.get('CC_VALIDADE') or '')[:10],
                'NIF': str(row_data.get('NIF') or '')[:9],
            })
        df = pd.DataFrame(rows, dtype=object)
        return guardar_condominos(df, pasta=caminho_path)
    except Exception as e:
        print(f"Erro ao guardar Condominos: {e}")
        return False


# ====================================================================
# FUNÇÕES DE LEITURA DA TABELA `fracoes`
# ====================================================================

def obter_fracoes(pasta_dados):
    """
    Obtém a lista de frações (fracao, andar, permilagem) da tabela
    `fracoes` de condominio.db, para alimentar a ComboBox do ANDAR e
    sincronizar automaticamente FRACAO/ANDAR/PERMILAGEM ao editar ou
    adicionar condóminos.

    Args:
        pasta_dados: Nome da pasta de dados (ex: "corrente") ou Path

    Returns:
        Lista de dicionários [{'FRACAO': ..., 'ANDAR': ..., 'PERMILAGEM': ...}, ...]
        ordenada por id. Lista vazia se a tabela/BD não existir ou em caso de erro.
    """
    from Database import FracoesRepo, resolver_pasta

    if not pasta_dados:
        return []

    try:
        pasta = resolver_pasta(pasta_dados)
        if not db_path(pasta).exists():
            return []

        rows = FracoesRepo(pasta).all_ordered()
        return [
            {
                'FRACAO': str(row['fracao'] or '').strip(),
                'ANDAR': str(row['andar'] or '').strip(),
                'PERMILAGEM': float(row['permilagem'] or 0.0),
            }
            for row in rows
        ]
    except Exception as exc:
        print(f"⚠️ Erro ao carregar fracoes: {exc}")
        return []


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
    # Fração é UNIQUE na BD — cada letra só pode estar num condómino
    vistas = {}
    for i, row_data in enumerate(dados or []):
        nome = str(row_data.get('NOME', '')).strip()
        andar = str(row_data.get('ANDAR', '')).strip()
        fracao = str(row_data.get('FRACAO', '')).strip().upper()

        if nome.startswith('[') and nome.endswith(']') and not andar:
            raise ValueError(
                "Para condóminos inativos (nome entre []), "
                "o campo ANDAR é obrigatório e não pode estar vazio."
            )

        if fracao:
            if fracao in vistas:
                outro = vistas[fracao]
                raise ValueError(
                    f"A fração <b>{fracao}</b> está atribuída a mais do que um condómino:\n\n"
                    f"  • {outro}\n"
                    f"  • {nome or '(sem nome)'}\n\n"
                    "Cada fração só pode pertencer a um condómino. "
                    "Altere a fração de um dos registos antes de gravar."
                )
            vistas[fracao] = nome or f"(linha {i + 1})"


# ====================================================================
# FUNÇÕES DE ATUALIZAÇÃO DE QUOTAS
# ====================================================================

def atualizar_quotas_regras(pasta_dados, dados_condominos):
    """
    Actualiza APENAS normal/extra nas regras de condómino já existentes.

    NÃO cria registos novos em `regras` — só o utilizador cria regras
    (o pattern tem de ser o texto curto que Bancos procura no CSV).

    Critério de match (por ordem):
      1. conta = "Quota - {ANDAR}"  e  classe = RECEITA
      2. conta LIKE "%{ANDAR}%"     e  classe = RECEITA  e  normal IS NOT NULL
      3. pattern começa pelo nome   e  normal IS NOT NULL  (fallback)

    Se não encontrar regra, regista aviso e continua (sem INSERT).
    """
    from Database import get_connection, resolver_pasta
    from Commons import remover_acentos

    # "corrente" ou path → pasta com condominio.db
    pasta = resolver_pasta(pasta_dados)
    condo_db = db_path(pasta)
    if not condo_db.exists():
        print("⚠️ condominio.db não encontrada — quotas não actualizadas")
        return

    def conta_de_andar(andar: str) -> str:
        return f"Quota - {andar.strip()}" if andar.strip() else "Quota"

    actualizados = 0
    sem_regra = []

    try:
        with get_connection(pasta) as conn:
            for cond in dados_condominos:
                nome  = str(cond.get("NOME", "")).strip()
                if nome.startswith("[") and nome.endswith("]"):
                    continue  # inactivo

                andar = str(cond.get("ANDAR", "")).strip()
                quota_n = float(cond.get("QUOTAN", 0) or 0)
                quota_e = float(cond.get("QUOTAE", 0) or 0)

                if not andar:
                    continue

                conta = conta_de_andar(andar)
                pattern_nome = remover_acentos(nome).upper() if nome else ""

                # 1) Match exacto por conta
                rows = conn.execute(
                    """SELECT id, pattern, normal, extra FROM regras
                       WHERE classe = 'RECEITA' AND conta = ?
                       ORDER BY id""",
                    (conta,),
                ).fetchall()

                # 2) Match por conta contendo o andar
                if not rows:
                    rows = conn.execute(
                        """SELECT id, pattern, normal, extra FROM regras
                           WHERE classe = 'RECEITA'
                             AND normal IS NOT NULL
                             AND conta LIKE ?
                           ORDER BY id""",
                        (f"%{andar}%",),
                    ).fetchall()

                # 3) Fallback: pattern começa pelo nome (ou nome começa pelo pattern)
                if not rows and pattern_nome:
                    rows = conn.execute(
                        """SELECT id, pattern, normal, extra FROM regras
                           WHERE classe = 'RECEITA'
                             AND normal IS NOT NULL
                             AND (
                               UPPER(pattern) = ?
                               OR UPPER(pattern) LIKE ?
                               OR ? LIKE UPPER(pattern) || '%'
                             )
                           ORDER BY id""",
                        (pattern_nome, pattern_nome + "%", pattern_nome),
                    ).fetchall()

                if not rows:
                    sem_regra.append(f"{nome or '?'} / {andar}")
                    print(
                        f"  ⚠ Sem regra em `regras` para {nome!r} "
                        f"(conta={conta!r}) — quota NÃO actualizada "
                        f"(crie a regra manualmente na aba Regras)"
                    )
                    continue

                # Actualizar TODAS as regras encontradas (evita ficar com
                # duplicados com valores antigos)
                for r in rows:
                    conn.execute(
                        """UPDATE regras
                           SET normal = ?, extra = ?, ativo = 1
                           WHERE id = ?""",
                        (quota_n, quota_e, r["id"]),
                    )
                    print(
                        f"  ✓ regra id={r['id']}  {r['pattern']!r}  "
                        f"normal {r['normal']}→{quota_n}  "
                        f"extra {r['extra']}→{quota_e}"
                    )
                    actualizados += 1

        print(f"  ✓ Quotas sincronizadas em regras: {actualizados} linha(s) actualizada(s)")
        if sem_regra:
            print(f"  ⚠ Sem regra correspondente: {', '.join(sem_regra)}")
    except Exception as exc:
        print(f"⚠️ Erro ao actualizar quotas em regras: {exc}")
        import traceback
        traceback.print_exc()


# Alias legado (nome antigo referia Configs; a fonte é `regras`)
atualizar_quotas_configs = atualizar_quotas_regras


# ====================================================================
# FUNÇÕES DE PROCESSAMENTO DE PAGAMENTOS
# ====================================================================

def _divida_anterior_por_andar(pasta, andar: str) -> float:
    """Dívida transitada de anos anteriores (SALDO_ANT < 0) para um ANDAR.

    Soma Quotas normais + extra. Só lê (receitas_resumo via load_receitas_wide);
    saldos positivos (crédito) ou falhas de leitura contam como 0.
    """
    try:
        from Database import load_receitas_wide
    except Exception:
        return 0.0
    alvo = str(andar or "").strip().lower()
    total = 0.0
    for tipo in ("NORMAL", "EXTRA"):
        try:
            rows, _ = load_receitas_wide(tipo, pasta)
        except Exception:
            continue
        for r in rows:
            if str(r.get("FRACCAO", "")).strip().lower() == alvo:
                sa = float(r.get("SALDO_ANT") or 0)
                if sa < -0.005:
                    total += -sa
                break
    return round(total, 2)


def _divida_anterior_liquidada(dados_mensais, quota_mensal: float,
                               divida_anterior: float) -> float:
    """Parte da dívida antiga que foi paga ESTE ano (e não é quota de 2026).

    Os pagamentos de dívida antiga entram no mapa do mês em que foram feitos
    (ex.: Jan = 28 + 336). Contam como liquidação o excedente de cada mês
    sobre a quota mensal, limitado à dívida existente. Sem dívida anterior
    devolve 0 (pré-pagamentos de quotas correntes não são tocados) e, se a
    dívida antiga NÃO foi paga, também 0: nunca gera atraso em 2026.
    """
    if divida_anterior <= 0.005 or quota_mensal <= 0.005:
        return 0.0
    excedente = sum(
        max(0.0, float(m.get("total", 0) or 0) - quota_mensal)
        for m in dados_mensais
    )
    return round(min(divida_anterior, excedente), 2)


def obter_pagamentos_condomino(andar, pasta_dados):
    """
    Processa receitas e filtra para o condómino específico.
    
    Args:
        andar: ANDAR do condómino (ex: "R/c Dto.")
        pasta_dados: Nome da pasta de dados (ex: "corrente")
    
    Returns:
        dict com dados dos pagamentos por mês
    """
    
    from Database import (
        quotas_por_fracao,
        resolver_pasta,
        movimentos_dataframe,
    )
    try:
        from Receitas import processar_receitas_simplificado
    except ImportError as e:
        raise Exception(f"Erro ao importar Receitas.py: {e}")

    pasta = resolver_pasta(pasta_dados)
    if not db_path(pasta).exists():
        raise FileNotFoundError(f"condominio.db não encontrada em {pasta}")

    # 1. Movimentos via API canónica (bancos + caixa)
    df_movimentos = movimentos_dataframe(pasta, fontes=("bancos", "caixa"))
    if df_movimentos.empty:
        raise Exception("Nenhum movimento encontrado")
    df_movimentos = df_movimentos[
        [c for c in ("DATA", "TIPO", "CONTA", "DESCRICAO", "VALOR", "OBSERVACAO")
         if c in df_movimentos.columns]
    ].copy()

    # 2. Quotas via API canónica (regras)
    tabela_quotas = quotas_por_fracao(pasta)

    if not tabela_quotas:
        raise Exception(
            "Nenhuma quota configurada em Regras.\n"
            "Verifique se existem regras de RECEITA com normal/extra "
            "preenchidos na aba Regras."
        )

    # 3. Processar receitas
    mapa_normal, mapa_extra = processar_receitas_simplificado(
        df_movimentos,
        tabela_quotas,
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
    
    # 6. Dívida de anos anteriores já liquidada este ano (só para o cálculo
    #    de atraso; as chaves existentes não mudam)
    try:
        q = tabela_quotas.get(fracao_normalizada, {})
        quota_mensal = float(q.get('QUOTA_NORMAL') or 0) + float(q.get('QUOTA_EXTRA') or 0)
        divida_ant = _divida_anterior_por_andar(pasta, fracao_normalizada)
        divida_liq = _divida_anterior_liquidada(dados_mensais, quota_mensal, divida_ant)
    except Exception:
        divida_ant = divida_liq = 0.0

    # 7. Retornar estrutura completa
    return {
        'dados_mensais': dados_mensais,
        'total_normal': total_normal,
        'total_extra': total_extra,
        'total_geral': total_normal + total_extra,
        'divida_anterior': divida_ant,
        'divida_anterior_liquidada': divida_liq,
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
        'ID': None,
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
        'CC_NUMERO': '',
        'CC_VALIDADE': '',
        'NIF': '',
        'MORADA': MORADA_FIXA, 
        'CPOSTAL': CPOSTAL_FIXO, 
        'CIDADE': CIDADE_FIXA
    }


def parse_quota_valor(value):
    """Converte string de quota (com €, espaços, vírgulas/pontos) para float.

    Raises:
        ValueError: se o valor não for numérico
    """
    if value is None or value == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("€", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        # Ambos presentes: o último é o separador decimal
        # ex: "1.234,56" → remove os pontos, troca vírgula por ponto
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        # Só vírgula → separador decimal ("24,5" → "24.5")
        s = s.replace(",", ".")
    return float(s)


def construir_mapas_fracoes(fracoes):
    """Constrói mapas de consulta a partir da lista de frações.

    A chave canónica é a **fração** (letra, UNIQUE na BD). O andar é um
    rótulo derivado; se houver andares duplicados, regista-se aviso e
    prevalece a última ocorrência.

    Args:
        fracoes: Lista de dicts {'FRACAO', 'ANDAR', 'PERMILAGEM'}

    Returns:
        (por_fracao, por_andar, andares_duplicados)
        - por_fracao: {fracao: {'ANDAR': ..., 'PERMILAGEM': ...}}
        - por_andar:  {andar:  {'FRACAO': ..., 'PERMILAGEM': ...}}
        - andares_duplicados: lista de andares que aparecem mais do que uma vez
    """
    por_fracao = {}
    por_andar = {}
    andares_duplicados = []
    for f in fracoes or []:
        fracao = str(f.get('FRACAO') or '').strip().upper()
        andar = str(f.get('ANDAR') or '').strip()
        try:
            perm = float(f.get('PERMILAGEM') or 0)
        except (TypeError, ValueError):
            perm = 0.0
        if not fracao:
            continue
        por_fracao[fracao] = {'ANDAR': andar, 'PERMILAGEM': perm}
        if andar:
            if andar in por_andar and por_andar[andar].get('FRACAO') != fracao:
                if andar not in andares_duplicados:
                    andares_duplicados.append(andar)
            por_andar[andar] = {'FRACAO': fracao, 'PERMILAGEM': perm}
    if andares_duplicados:
        print(
            f"⚠️ Andares duplicados na tabela fracoes (não são UNIQUE): "
            f"{', '.join(andares_duplicados)}"
        )
    return por_fracao, por_andar, andares_duplicados


def validar_e_normalizar_campo(campo, valor, fracoes_validas=None):
    """Valida e normaliza um campo editável de condómino.

    Args:
        campo: Nome do campo (TELEMOVEL, EMAIL, FRACAO, PERMILAGEM, QUOTAN, QUOTAE, ...)
        valor: Valor bruto proveniente da UI
        fracoes_validas: Lista de frações aceites. Se for uma lista (mesmo vazia),
            FRACAO tem de pertencer a ela (ou ficar vazia). Se for None, não há
            restrição de lista (apenas normalização para maiúsculas).

    Returns:
        (True, valor_normalizado) se válido;
        (False, None) se inválido.
    """
    if campo == 'TELEMOVEL':
        valor = str(valor).strip()
        if valor and not valor.isdigit():
            return False, None
        if len(valor) > 11:
            return False, None
        return True, valor

    if campo == 'EMAIL':
        valor = str(valor).strip()
        if valor and '@' not in valor:
            return False, None
        return True, valor

    if campo == 'FRACAO':
        valor = str(valor).strip().upper()
        if fracoes_validas is not None:
            validas = {str(x).strip().upper() for x in fracoes_validas}
            if valor and valor not in validas:
                return False, None
        return True, valor

    if campo == 'ANDAR':
        # ANDAR é derivado da fração — não se edita livremente.
        # Aceita-se o valor apenas para normalização (strip).
        return True, str(valor).strip() if valor is not None else ''

    if campo == 'PERMILAGEM':
        try:
            if valor is None or valor == '':
                return True, 0.0
            valor = float(str(valor).replace(',', '.'))
            if not 0 <= valor <= 999.999:
                return False, None
            return True, valor
        except (TypeError, ValueError):
            return False, None

    if campo in ('QUOTAN', 'QUOTAE'):
        try:
            return True, parse_quota_valor(valor)
        except (TypeError, ValueError):
            return False, None

    # Campos sem validação específica: devolver o valor tal como veio
    return True, valor


def _float_quota(valor, default=0.0) -> float:
    try:
        return float(valor if valor is not None else default)
    except (TypeError, ValueError):
        return default


def taxas_quota_por_permilagem(dados_condominos, excluir_row=None):
    """Calcula a taxa €/permilagem a partir dos registos já com quotas.

    Ignora linhas sem permilagem > 0. `excluir_row` permite ignorar a linha
    que está a ser editada (comparação por identidade do dict).

    Returns:
        (taxa_normal, taxa_extra) — 0.0 se não houver base de cálculo
    """
    soma_p = soma_n = soma_e = 0.0
    for row in dados_condominos or []:
        if excluir_row is not None and row is excluir_row:
            continue
        p = _float_quota(row.get('PERMILAGEM'))
        if p <= 0:
            continue
        soma_p += p
        soma_n += _float_quota(row.get('QUOTAN'))
        soma_e += _float_quota(row.get('QUOTAE'))
    if soma_p <= 0:
        return 0.0, 0.0
    return soma_n / soma_p, soma_e / soma_p


def obter_quotas_para_fracao(fracao, andar, permilagem, dados_condominos, excluir_row=None):
    """Determina QUOTAN/QUOTAE ao atribuir uma fração.

    Ordem de prioridade:
      1. Outro condómino com a **mesma FRACAO** e quotas já definidas → copiar
      2. Outro com o **mesmo ANDAR** e quotas já definidas → copiar
      3. Fração/andar novos: calcular por proporção da permilagem
         (taxa = soma quotas / soma permilagens dos restantes)
      4. Sem base de cálculo → (0.0, 0.0) — o utilizador define manualmente

    As quotas continuam sempre editáveis na grelha; este valor é apenas
    a sugestão automática ao mudar a fração.

    Returns:
        (quota_normal, quota_extra, origem) onde origem é
        'fracao' | 'andar' | 'permilagem' | 'vazio'
    """
    fracao = str(fracao or '').strip().upper()
    andar = str(andar or '').strip()
    perm = _float_quota(permilagem)

    def _tem_quotas(row):
        return _float_quota(row.get('QUOTAN')) > 0 or _float_quota(row.get('QUOTAE')) > 0

    # 1) Mesma fração já existente noutro registo
    if fracao:
        for row in dados_condominos or []:
            if excluir_row is not None and row is excluir_row:
                continue
            if str(row.get('FRACAO') or '').strip().upper() != fracao:
                continue
            if _tem_quotas(row):
                return (
                    round(_float_quota(row.get('QUOTAN')), 2),
                    round(_float_quota(row.get('QUOTAE')), 2),
                    'fracao',
                )

    # 2) Mesmo andar já existente noutro registo
    if andar:
        for row in dados_condominos or []:
            if excluir_row is not None and row is excluir_row:
                continue
            if str(row.get('ANDAR') or '').strip() != andar:
                continue
            if _tem_quotas(row):
                return (
                    round(_float_quota(row.get('QUOTAN')), 2),
                    round(_float_quota(row.get('QUOTAE')), 2),
                    'andar',
                )

    # 3) Nova fração/andar: proporção pela permilagem
    if perm > 0:
        taxa_n, taxa_e = taxas_quota_por_permilagem(dados_condominos, excluir_row=excluir_row)
        if taxa_n > 0 or taxa_e > 0:
            return (
                round(taxa_n * perm, 2),
                round(taxa_e * perm, 2),
                'permilagem',
            )

    # 4) Sem referência — utilizador preenche à mão
    return 0.0, 0.0, 'vazio'


def sincronizar_por_fracao(row_dict, fracao, por_fracao, dados_condominos=None):
    """Deriva ANDAR, PERMILAGEM e quotas a partir da FRACAO (chave canónica).

    ANDAR/PERMILAGEM vêm da tabela `fracoes`. As quotas são sugeridas por
    `obter_quotas_para_fracao` (cópia se já existir, senão proporção pela
    permilagem). O utilizador pode sempre alterar QUOTAN/QUOTAE à mão.

    Args:
        row_dict: Dicionário do registo (modificado in-place)
        fracao: Valor já normalizado da fração (ex.: 'A')
        por_fracao: {fracao: {'ANDAR': ..., 'PERMILAGEM': ...}}
        dados_condominos: Lista de registos para procurar quotas de referência
            e calcular taxas (tipicamente model._data)

    Returns:
        Lista de chaves actualizadas, ou [] se a fração não existir no mapa.
    """
    fracao = str(fracao or '').strip().upper()
    if not fracao:
        return []
    correspondencia = (por_fracao or {}).get(fracao)
    if not correspondencia:
        return []

    row_dict['ANDAR'] = correspondencia['ANDAR']
    row_dict['PERMILAGEM'] = correspondencia['PERMILAGEM']
    actualizadas = ['ANDAR', 'PERMILAGEM']

    qn, qe, _origem = obter_quotas_para_fracao(
        fracao=fracao,
        andar=correspondencia['ANDAR'],
        permilagem=correspondencia['PERMILAGEM'],
        dados_condominos=dados_condominos,
        excluir_row=row_dict,
    )
    row_dict['QUOTAN'] = qn
    row_dict['QUOTAE'] = qe
    actualizadas.extend(['QUOTAN', 'QUOTAE'])
    return actualizadas


def sincronizar_fracao_andar(row_dict, campo, valor, por_andar, por_fracao):
    """Compatibilidade: sincroniza a partir de FRACAO (preferido) ou ANDAR.

    A identidade canónica é a FRACAO. O ramo ANDAR mantém-se apenas para
    código legado; a UI actual só edita FRACAO.
    """
    if campo == 'FRACAO':
        return sincronizar_por_fracao(row_dict, valor, por_fracao)
    if campo == 'ANDAR':
        correspondencia = (por_andar or {}).get(str(valor).strip())
        if correspondencia:
            row_dict['FRACAO'] = correspondencia['FRACAO']
            row_dict['PERMILAGEM'] = correspondencia['PERMILAGEM']
            return ['FRACAO', 'PERMILAGEM']
    return []


def reconciliar_com_fracoes(dados, por_fracao):
    """Alinha ANDAR/PERMILAGEM de cada condómino com a tabela `fracoes`.

    Usa a FRACAO como chave. Não altera linhas sem fração ou com fração
    desconhecida. Não marca dirty — é correcção de leitura.

    Returns:
        Número de registos em que ANDAR ou PERMILAGEM foram corrigidos.
    """
    if not por_fracao:
        return 0
    n = 0
    for row in dados or []:
        fracao = str(row.get('FRACAO') or '').strip().upper()
        if not fracao:
            continue
        info = por_fracao.get(fracao)
        if not info:
            continue
        mudou = False
        if str(row.get('ANDAR') or '').strip() != str(info['ANDAR'] or '').strip():
            row['ANDAR'] = info['ANDAR']
            mudou = True
        try:
            perm_actual = float(row.get('PERMILAGEM') or 0)
        except (TypeError, ValueError):
            perm_actual = 0.0
        if abs(perm_actual - float(info['PERMILAGEM'])) > 1e-9:
            row['PERMILAGEM'] = info['PERMILAGEM']
            mudou = True
        if mudou:
            # Garantir FRACAO normalizada
            row['FRACAO'] = fracao
            n += 1
    return n


def calcular_meses_quotas(total_normal, total_extra, quota_normal, quota_extra):
    """Calcula o nº de meses pagos a partir dos totais e do valor mensal.

    Corrige o caso em que o condómino paga vários meses de uma só vez
    (meses = total pago ÷ quota mensal).

    Returns:
        (meses_normal, meses_extra) como int
    """
    try:
        qn = float(quota_normal or 0)
        qe = float(quota_extra or 0)
        tn = float(total_normal or 0)
        te = float(total_extra or 0)
    except (TypeError, ValueError):
        return 0, 0
    meses_n = round(tn / qn) if qn > 0 else 0
    meses_e = round(te / qe) if qe > 0 else 0
    return meses_n, meses_e


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
            administradores.append((nome, eh_admin_atual(cond.get('ADMIN', 0))))
    
    return administradores


def definir_administrador(pasta_dados, nome_administrador):
    """
    Define um condómino como administrador atual (admin=1).
    O anterior com admin=1 passa a cessante (admin=-1); restantes ficam 0.

    Args:
        pasta_dados: Nome da pasta de dados (ex: "corrente")
        nome_administrador: Nome do condómino a ser definido como admin

    Returns:
        True se sucesso, False caso contrário
    """
    condominos_path = BASE_DIR / pasta_dados / "Condominos"
    if not existe_dados(condominos_path):
        return False

    try:
        rows = carregar_condominos(condominos_path)

        def _admin_int(val):
            try:
                return int(val)
            except (TypeError, ValueError):
                if val in (True, "T", ".T.", "t", "True", "true", "1"):
                    return 1
                return 0

        for row in rows:
            nome_atual = str(row.get('NOME', '')).strip()
            if nome_atual == nome_administrador:
                row['ADMIN'] = 1
            elif _admin_int(row.get('ADMIN', 0)) == 1:
                row['ADMIN'] = -1
            else:
                row['ADMIN'] = 0

        df = pd.DataFrame(rows, dtype=object)
        ok = guardar_condominos(df, pasta=condominos_path)
        return bool(ok)
    except Exception as exc:
        print(f"Erro ao definir administrador: {exc}")
        return False


# ====================================================================
# CÁLCULO DE ATRASO DE QUOTAS (reutilizável por GUI e WhatsApp)
# ====================================================================
DIA_LIMITE_PAGAMENTO = 8  # último dia para pagar sem ficar em atraso


def meses_vencidos_corrente(hoje=None, dia_limite: int = DIA_LIMITE_PAGAMENTO) -> int:
    """Nº de quotas mensais JÁ VENCIDAS no ano corrente.

    A quota de cada mês pode ser paga até ao dia ``dia_limite`` (8). A partir
    do dia seguinte (dia 9, inclusive) o mês não pago passa a estar em atraso.

      - dia <= 8 : vencidos = mês corrente - 1  (ex.: 2 Nov -> 10)
      - dia >= 9 : vencidos = mês corrente      (ex.: 9 Nov -> 11)

    Nunca passa de 12, pelo que Nov/Dez só contam a partir do dia 9 desses meses.
    """
    from datetime import datetime
    hoje = hoje or datetime.now()
    meses = hoje.month if hoje.day > dia_limite else hoje.month - 1
    return max(0, min(12, meses))


def calcular_estado_atraso(total_pago: float, quota_normal: float,
                            quota_extra: float,
                            meses_decorridos: "Optional[int]" = None,
                            divida_anterior: float = 0.0) -> dict:
    """Calcula o estado de atraso de um condómino (apenas ano corrente).

    Critério:
      - Esperado = (quota_normal + quota_extra) × meses VENCIDOS do ano
        (por omissão: mês corrente - 1; Nov/Dez nunca contam antes de tempo)
      - Pago do ano = total_pago − divida_anterior
        (``divida_anterior`` = valor de anos anteriores liquidado este ano,
        i.e. max(0, −SALDO_ANT); não deve contar como pagamento de 2026)
      - Em atraso se esperado − pago do ano > 0,01 € e quota mensal > 0

    O SALDO_ANT / SALDO é só controlo contabilístico: nunca decide atraso;
    apenas é usado para retirar do total pago o que foi dívida antiga.
    """
    import math
    from Commons import format_currency

    try:
        qn = float(quota_normal or 0)
        qe = float(quota_extra or 0)
        tp = float(total_pago or 0)
        da = max(0.0, float(divida_anterior or 0))
    except (TypeError, ValueError):
        qn = qe = tp = da = 0.0

    if meses_decorridos is None:
        meses_decorridos = meses_vencidos_corrente()
    meses_decorridos = max(0, min(12, int(meses_decorridos)))

    quota_mensal = qn + qe
    pago_ano = tp - da
    esperado_ate_hoje = quota_mensal * meses_decorridos
    deficit = esperado_ate_hoje - pago_ano

    em_atraso = deficit > 0.01 and quota_mensal > 0
    if em_atraso:
        meses_atraso = math.ceil(round(deficit / quota_mensal, 6))
        meses_atraso = min(meses_atraso, meses_decorridos)
        status_msg = (
            f"{meses_atraso} quota{'s' if meses_atraso != 1 else ''} em atraso "
            f"({format_currency(deficit)})"
        )
        status_color = "#dc3545"
    else:
        meses_atraso = 0
        deficit = max(deficit, 0.0)
        status_msg = "Em Dia"
        status_color = "#28a745"

    return {
        "em_atraso": em_atraso,
        "meses_atraso": meses_atraso,
        "deficit": deficit,
        "status_msg": status_msg,
        "status_color": status_color,
    }


# ====================================================================
# DETEÇÃO DE PARTILHA DE FRAÇÃO/ANDAR (controlo de ambiguidade)
# ====================================================================
def condominos_ativos_na_fracao(condominos, andar, excluir_nome=None):
    """Devolve os nomes dos OUTROS condóminos ATIVOS que partilham o mesmo ANDAR.

    Atualmente a lógica da aplicação assume um único condómino ativo por
    fração/andar. Esta função serve de controlo para o caso (ainda não
    suportado) de existir mais de um — por exemplo, um condómino vende o
    apartamento a meio do ano contabilístico e, durante a transição, ficam
    registados tanto o condómino antigo como o novo para a mesma fração.

    Nesse cenário, `obter_pagamentos_condomino` calcula o total pago por
    ANDAR (não por condómino individual), pelo que o atraso calculado por
    `calcular_estado_atraso` não pode ser atribuído com confiança a um só
    dos condóminos — os valores ficam agregados entre todos os que partilham
    o ANDAR. Esta função permite detetar essa situação para que o chamador
    decida como lidar com ela (ex.: avisar o utilizador, ou não enviar
    cobrança automática por WhatsApp).

    Args:
        condominos: lista de dicts (resultado de carregar_condominos_db,
            ou o equivalente já carregado em memória, ex. model._data)
        andar: ANDAR do condómino a verificar
        excluir_nome: nome do próprio condómino a excluir do resultado

    Returns:
        Lista de nomes (str) de outros condóminos ativos no mesmo ANDAR.
        Lista vazia = situação normal (sem ambiguidade).
    """
    andar_norm = str(andar or "").strip()
    if not andar_norm:
        return []

    excluir_norm = str(excluir_nome or "").strip()
    outros = []
    for c in condominos or []:
        nome_c = str(c.get("NOME", "")).strip()
        # Ignorar inativos
        if nome_c.startswith("[") and nome_c.endswith("]"):
            continue
        if str(c.get("ANDAR", "")).strip() != andar_norm:
            continue
        if excluir_norm and nome_c == excluir_norm:
            continue
        outros.append(nome_c)
    return outros