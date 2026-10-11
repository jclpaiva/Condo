"""
Imprimir_Recibos.py - Geração de recibos em lote para todos os condóminos

Funcionalidades:
- Gera recibo anual de quotas pagas por todos os condóminos
- Processa todos os condóminos da base de dados
- Formato talão 80 mm × 150 mm (igual ao Imprimir_Recibo.py)
- Valor por extenso
- Numeração automática: FRAÇÃO/ANO  (ex: "A/2026")
- A fração é deduzida a partir do ANDAR
- NIF fixo do condomínio
- Gera um PDF por condómino
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Importações do projecto (presentes no ambiente real)
# ---------------------------------------------------------------------------
try:
    from Commons import BASE_DIR, ICONS_DIR, DOCS_DIR, obter_ano_exercicio, carregar_db
except ImportError:
    # Fallback para testes standalone
    BASE_DIR = Path(".")
    ICONS_DIR = Path(".")
    DOCS_DIR = Path("docs")
    def carregar_db(caminho):
        return [], None

# ---------------------------------------------------------------------------
# Importações do projecto
# ---------------------------------------------------------------------------
try:
    from Condominos import carregar_condominos_db
    from Imprimir_Recibo import gerar_recibo_pdf
except ImportError:
    # Fallback para testes standalone
    def carregar_condominos_db(caminho):
        return []

    def gerar_recibo_pdf(*args, **kwargs):
        raise NotImplementedError("gerar_recibo_pdf não disponível")

# ---------------------------------------------------------------------------
# Constantes do condomínio
# ---------------------------------------------------------------------------
CONDOMINIO_NOME = "Condomínio Av. Sto. António, 42"
CONDOMINIO_NIF  = "901579220"

# Mapeamento ANDAR → FRAÇÃO (letra)  – corrigido "2º Dto."
ANDAR_PARA_FRACAO = {
    "R/c Esq.":  "A",
    "R/c Dto.":  "B",
    "1º Esq.":   "C",
    "1º Dto.":   "D",
    "2º Esq.":   "E",
    "2º Dto.":   "F",
}


# ====================================================================
# FUNÇÃO PRINCIPAL: GERAR TODOS OS RECIBOS
# ====================================================================

def gerar_recibos_para_todos_condominos(pasta_dados, output_dir=None):
    """
    Gera recibo para todos os condóminos ativos (CHECK = .T.)

    Args:
        pasta_dados: Pasta de dados (ex: "corrente")
        output_dir: Diretório de saída (padrão: BASE_DIR/docs)

    Returns:
        dict: {"sucessos": [], "erros": [], "total": int}
    """
    if output_dir is None:
        output_dir = BASE_DIR / "docs"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Carregar condóminos
    condominos_path = BASE_DIR / pasta_dados / "Condominos"
    condominos = carregar_condominos_db(str(condominos_path))

    if not condominos:
        return {"sucessos": [], "erros": ["Nenhum condómino encontrado"], "total": 0}

    # Filtrar condóminos ativos (CHECK = .T.)
    condominos_ativos = []
    for c in condominos:
        check_val = c.get('CHECK', '.F.')
        if check_val in (True, 'T', '.T.', 't'):
            condominos_ativos.append(c)

    if not condominos_ativos:
        return {"sucessos": [], "erros": ["Nenhum condómino ativo encontrado"], "total": 0}

    # Obter dados de pagamentos
    try:
        from Condominos import obter_pagamentos_condomino
        dados_pagamentos = {}

        for c in condominos_ativos:
            andar = str(c.get('ANDAR', '')).strip()
            if andar:
                try:
                    dados_pagamentos[andar] = obter_pagamentos_condomino(andar, pasta_dados)
                except Exception as e:
                    print(f"⚠️ Erro ao obter pagamentos para andar {andar}: {e}")
                    dados_pagamentos[andar] = None
            else:
                print(f"⚠️ Condómino {c.get('NOME', 'Sem nome')} sem ANDAR definido")
                dados_pagamentos[andar] = None
    except ImportError:
        print("⚠️ Módulo Condominos não disponível para obter pagamentos")
        dados_pagamentos = {
            andar: None
            for andar in set(c.get('ANDAR', '') for c in condominos_ativos if c.get('ANDAR'))
        }

    # Gerar recibo para cada condómino
    sucessos = []
    erros = []

    for i, c in enumerate(condominos_ativos, 1):
        try:
            # Obter dados do condómino
            nome = str(c.get('NOME', '')).strip()
            andar = str(c.get('ANDAR', '')).strip()
            fracao = ANDAR_PARA_FRACAO.get(andar, "?")

            # Obter dados de pagamentos
            dados_pag = dados_pagamentos.get(andar)

            if dados_pag:
                valor_total = dados_pag.get('total_geral', 0.0)
                valor_normal = dados_pag.get('total_normal', 0.0)
                valor_extra = dados_pag.get('total_extra', 0.0)
            else:
                # Se não houver dados de pagamentos, usar valores padrão
                valor_total = 0.0
                valor_normal = 0.0
                valor_extra = 0.0

            # Nº de meses = total pago ÷ valor da quota mensal
            # (corrige o caso em que o condómino paga vários meses de uma só vez)
            quota_n = float(c.get('QUOTAN', 0) or 0)
            quota_e = float(c.get('QUOTAE', 0) or 0)
            meses_normal = round(valor_normal / quota_n) if quota_n > 0 else 0
            meses_extra  = round(valor_extra  / quota_e) if quota_e > 0 else 0

            # Obter administrador (usa a função local para evitar import circular)
            try:
                administradores = obter_lista_administradores(pasta_dados)
                administrador = administradores[0] if administradores else "Administrador Padrão"
            except Exception:
                administrador = "Administrador Padrão"

            # Gerar recibo
            pdf_path = gerar_recibo_pdf(
                fracao=fracao,
                nome_condomino=nome,
                valor_total=valor_total,
                administrador_nome=administrador,
                pasta_dados=pasta_dados,
                output_dir=output_dir,
                valor_normal=valor_normal,
                valor_extra=valor_extra,
                meses_normal=meses_normal,
                meses_extra=meses_extra,
            )

            sucessos.append({
                "index": i,
                "nome": nome,
                "fracao": fracao,
                "andar": andar,
                "pdf_path": str(pdf_path),
                "valor_total": valor_total,
                "administrador": administrador
            })

            print(f"✓ Recibo gerado para {nome} ({fracao}) - {pdf_path}")

        except Exception as e:
            erro_msg = f"Erro ao gerar recibo para {c.get('NOME', 'Sem nome')}: {str(e)}"
            erros.append(erro_msg)
            print(f"✗ {erro_msg}")

    return {
        "sucessos": sucessos,
        "erros": erros,
        "total": len(condominos_ativos)
    }


# ====================================================================
# FUNÇÃO AUXILIAR: OBTER LISTA DE ADMINISTRADORES
# ====================================================================

def obter_lista_administradores(pasta_dados):
    """
    Obtém lista de condóminos que são administradores (ADMIN = .T.)

    Args:
        pasta_dados: Pasta de dados (ex: "corrente")

    Returns:
        list: Lista de nomes de administradores
    """
    try:
        condominos_path = BASE_DIR / pasta_dados / "Condominos"
        rows, _ = carregar_db(condominos_path)

        administradores = []
        for row in rows:
            nome = str(row.get('NOME', '')).strip()
            if not nome:
                continue

            # Normalização do boolean de ADMIN para formato legacy
            flag_admin = row.get('ADMIN', False)
            if isinstance(flag_admin, str):
                flag_admin = flag_admin.strip().upper() in ('T', '.T.', 'TRUE', '1')
            elif isinstance(flag_admin, int):
                flag_admin = bool(flag_admin)
            elif isinstance(flag_admin, float):
                flag_admin = bool(flag_admin)

            if flag_admin:
                administradores.append(nome)

        return administradores
    except Exception as e:
        print(f"⚠️ Erro ao obter lista de administradores: {e}")
        return []


# ====================================================================
# TESTE STANDALONE
# ====================================================================

if __name__ == "__main__":
    print("=== TESTE: GERAÇÃO DE RECIBOS EM LOTE ===")

    # Testar com pasta de dados padrão
    pasta_teste = "corrente"

    print(f"\nGerando recibos para todos os condóminos em '{pasta_teste}'...")

    resultado = gerar_recibos_para_todos_condominos(pasta_teste)

    print(f"\n=== RESULTADO ===")
    print(f"Total de condóminos processados: {resultado['total']}")
    print(f"Sucessos: {len(resultado['sucessos'])}")
    print(f"Erros: {len(resultado['erros'])}")

    if resultado['sucessos']:
        print(f"\n--- Recibos Gerados ---")
        for s in resultado['sucessos']:
            print(f"  {s['index']}. {s['nome']} ({s['fracao']}) - {s['pdf_path']}")

    if resultado['erros']:
        print(f"\n--- Erros ---")
        for e in resultado['erros']:
            print(f"  ✗ {e}")

    print(f"\nTodos os PDFs foram gerados em: {BASE_DIR / 'docs'}")
