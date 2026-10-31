"""
Report_AI.py - Integração com OpenRouter.ai
- Usa funções centralizadas de Commons.py
- Gera Relatorio_Analise_IA.txt
- Gera Relatorio_Analise_IA.pdf com formatação moderna
- Mostra loading automático se dentro de PyQt6
- Remove cálculo incorreto de liquidez corrente
- Usa ano do exercício de Configs
- Extrai saldos negativos por condómino de ReceitasN e ReceitasE
- Prompt aprimorado para análise contábil especializada em condomínios
- Extração de dados mais robusta com validação completa
- Tratamento de erros aprimorado com logs detalhados
- Melhor organização do código com funções modulares
"""
import os
import json
import requests
import pandas as pd

from pathlib import Path
from dotenv import load_dotenv

# Importações centralizadas
from Commons import (
    BASE_DIR, DOCS_DIR,
    obter_ano_exercicio, clean_numeric,
)
from Database import (
    resolver_pasta,
    db_existe,
    load_balanco_wide,
    load_saldos_wide,
    load_receitas_wide,
)

# Carrega variáveis de ambiente do .env junto à aplicação (BASE_DIR), com
# override=True para que uma alteração no .env tenha sempre efeito.
#
# Sem override=True, load_dotenv() NUNCA substitui uma variável que já
# esteja definida no ambiente/sessão (ex: OPENROUTER_API_KEY definida uma
# vez nas Variáveis de Ambiente do Windows) - nesse caso, editar o .env
# não tem qualquer efeito, mesmo que o ficheiro esteja correto.
_env_path = BASE_DIR / '.env'
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    # Fallback: procura .env a partir da pasta de trabalho atual, caso não
    # exista junto à aplicação.
    load_dotenv(override=True)

# Configurações da API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-5-super-vl:free")
YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "http://localhost")
YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME", "42Condo.ddns.net")

# Nota: a validação da chave NÃO é feita à importação do módulo (um .env em
# falta ou uma chave inválida não deve impedir o resto da aplicação, como o
# Balanço, de carregar - só a funcionalidade de IA fica indisponível). A
# validação acontece em tempo de utilização, em call_openrouter_api().

# ============================================
# FUNÇÃO DE CHAMADA COM FALLBACK AUTOMÁTICO
# ============================================

def call_openrouter_api(messages, model=None, max_retries=2):
    import time

    if not OPENROUTER_API_KEY:
        print(
            "❌ Variável OPENROUTER_API_KEY não encontrada. Certifique-se de "
            "que existe um ficheiro .env com OPENROUTER_API_KEY=sua_chave_aqui"
        )
        return None

    model = model or OPENROUTER_MODEL
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": YOUR_SITE_URL,
        "X-Title": YOUR_SITE_NAME
    }
    
    print(f"🔄 Tentando modelo: {model}")
    
    for attempt in range(max_retries):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 600
                },
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ Modelo ({model}) respondeu com sucesso!")
                return response.json()
            
            elif response.status_code == 402:
                print(f"⚠️ Créditos insuficientes para {model}.")
                break
            
            elif response.status_code == 429:
                wait_time = 2 ** attempt
                print(f"⏳ Rate limit atingido. Aguardando {wait_time}s antes de nova tentativa...")
                time.sleep(wait_time)
                continue
            
            else:
                print(f"❌ Erro inesperado ({response.status_code}): {response.text}")
                break
                
        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            print(f"⏰ Timeout na tentativa {attempt + 1}/{max_retries}. Aguardando {wait_time}s...")
            time.sleep(wait_time)
            if attempt == max_retries - 1:
                break
        except Exception as e:
            print(f"❌ Erro na chamada API: {str(e)}")
            return None
    return None

# ============================================
# FUNÇÃO AUXILIAR PARA EXTRAIR RESPOSTA
# ============================================

def get_ai_response(messages, **kwargs):
    """
    Função simplificada para obter resposta da IA com fallback automático.
    """
    response = call_openrouter_api(messages, **kwargs)
    
    if response and "choices" in response and len(response["choices"]) > 0:
        return response["choices"][0]["message"]["content"]
    return None

def extrair_dados_financeiros(pasta_dados: Path):
    """
    Extrai e valida dados financeiros de uma pasta de dados.
    
    Realiza extração robusta com validação completa de integridade dos dados,
    tratamento de erros detalhado e logs informativos para debugging.
    """
    pasta = resolver_pasta(pasta_dados)
    
    # Log de início da extração
    print(f"🔍 Extraindo dados financeiros da pasta: {pasta.name}")
    
    periodo_ano = obter_ano_exercicio(str(pasta.name) if isinstance(pasta, Path) else pasta)
    print(f"📅 Período de análise: {periodo_ano}")

    # Inicializar estrutura de dados com validação
    dados = {
        "periodo": str(periodo_ano),
        "receitas_correntes": {
            "quotas_normais": 0.0, 
            "quotas_extras": 0.0, 
            "juros": 0.0, 
            "total_receitas": 0.0
        },
        "despesas_correntes": {
            "detalhe_contas": {}, 
            "total_despesas": 0.0
        },
        "saldos_iniciais": {
            "deposito_poupanca": 0.0, 
            "deposito_ordem": 0.0, 
            "numerario_caixa": 0.0, 
            "total_saldo_inicial": 0.0
        },
        "saldos_finais": {
            "deposito_poupanca": 0.0, 
            "deposito_ordem": 0.0, 
            "numerario_caixa": 0.0, 
            "total_saldo_final": 0.0
        },
        "saldo_exercicio": 0.0,
        "saldos_negativos_condominos": {},
        "validacao": {
            "balanco_carregado": False,
            "saldos_carregados": False,
            "receitas_carregadas": False,
            "erros": []
        }
    }

    def _rows_wide(load_fn, *args):
        """Carrega linhas wide com tratamento de erro robusto e logs detalhados."""
        try:
            rows, metadata = load_fn(*args, pasta=pasta)
            if not rows:
                print(f"⚠️ load wide: Nenhum dado retornado por {load_fn.__name__}")
                return []
            print(f"✅ load wide: {len(rows)} linhas carregadas de {load_fn.__name__}")
            return rows
        except Exception as exc:
            error_msg = f"❌ Erro ao carregar {load_fn.__name__}: {str(exc)}"
            print(error_msg)
            dados["validacao"]["erros"].append(error_msg)
            return []

    # ===== PROCESSAR BALANÇO =====
    print("📊 Processando dados do Balanço...")
    rows_bal = _rows_wide(load_balanco_wide)
    
    if rows_bal:
        dados["validacao"]["balanco_carregado"] = True
        df_bal = pd.DataFrame(rows_bal, dtype=object)
        
        # Validar estrutura do DataFrame
        required_columns = ["CONTA", "VALOR", "TIPO"]
        missing_cols = [col for col in required_columns if col not in df_bal.columns]
        if missing_cols:
            error_msg = f"❌ Colunas faltando no Balanço: {missing_cols}"
            print(error_msg)
            dados["validacao"]["erros"].append(error_msg)
        
        for idx, row in df_bal.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()
            
            # Validação de dados
            if not conta:
                print(f"⚠️ Linha {idx}: Conta vazia ignorada")
                continue
                
            if valor == 0 and conta not in ["Saldo Final", "Saldo Exercicio"]:
                print(f"⚠️ Linha {idx}: Valor zero para conta '{conta}'")
            
            if tipo == "RECEITA":
                if "Quotas Normais" in conta:
                    dados["receitas_correntes"]["quotas_normais"] = valor
                elif "Quotas Extras" in conta:
                    dados["receitas_correntes"]["quotas_extras"] = valor
                elif "Juros" in conta:
                    dados["receitas_correntes"]["juros"] = valor
                else:
                    print(f"⚠️ Conta receita não reconhecida: '{conta}'")
                    
            elif tipo == "DESPESA":
                dados["despesas_correntes"]["detalhe_contas"][conta] = valor
                
            elif conta == "Saldo Final":
                dados["saldos_finais"]["total_saldo_final"] = valor
            elif conta == "Saldo Exercicio":
                # Usar Saldo Exercicio do Balanco se disponível
                dados["saldo_exercicio"] = valor
                print(f"ℹ️ Saldo Exercicio encontrado no Balanco: {valor}")

        # Calcular totais com validação
        r = dados["receitas_correntes"]
        r["total_receitas"] = r["quotas_normais"] + r["quotas_extras"] + r["juros"]
        
        d = dados["despesas_correntes"]
        d["total_despesas"] = sum(d["detalhe_contas"].values())
        
        # Calcular saldo_exercicio como (total_receitas - total_despesas) se não foi encontrado no Balanco
        if dados["saldo_exercicio"] == 0:
            dados["saldo_exercicio"] = r["total_receitas"] - d["total_despesas"]
            print(f"📊 Saldo Exercicio calculado: {dados['saldo_exercicio']}")
        
        # Log de resumo do Balanço
        print(f"📈 Resumo do Balanço - Receitas: {r['total_receitas']:.2f}, Despesas: {d['total_despesas']:.2f}, Saldo: {dados['saldo_exercicio']:.2f}")

    # ===== PROCESSAR SALDOS =====
    print("🏦 Processando dados de Saldos...")
    rows_saldos = _rows_wide(load_saldos_wide)
    
    if rows_saldos:
        dados["validacao"]["saldos_carregados"] = True
        df_saldos = pd.DataFrame(rows_saldos, dtype=object)
        
        for idx, row in df_saldos.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()
            
            if not conta:
                print(f"⚠️ Linha {idx}: Conta vazia ignorada em Saldos")
                continue
                
            # IMPORTANTE: NÃO extrair "Saldo Exercicio" do Saldos, é calculado do Balanco
            if tipo == "RECEITA":
                if "Depósito Poupança_I" in conta:
                    dados["saldos_iniciais"]["deposito_poupanca"] = valor
                elif "Depósito Ordem_I" in conta:
                    dados["saldos_iniciais"]["deposito_ordem"] = valor
                elif "Numerário Caixa_I" in conta:
                    dados["saldos_iniciais"]["numerario_caixa"] = valor
                elif "Depósito Poupança_F" in conta:
                    dados["saldos_finais"]["deposito_poupanca"] = valor
                elif "Depósito Ordem_F" in conta:
                    dados["saldos_finais"]["deposito_ordem"] = valor
                elif "Numerário Caixa_F" in conta:
                    dados["saldos_finais"]["numerario_caixa"] = valor
                # NOTA: NÃO extraímos "Saldo Exercicio" do Saldos, é calculado
                
        # Calcular totais dos saldos
        dados["saldos_iniciais"]["total_saldo_inicial"] = sum([
            dados["saldos_iniciais"]["deposito_poupanca"],
            dados["saldos_iniciais"]["deposito_ordem"],
            dados["saldos_iniciais"]["numerario_caixa"]
        ])
        
        # Se total_saldo_final ainda for 0 (não foi encontrado no Balanco), calcular
        if dados["saldos_finais"]["total_saldo_final"] == 0:
            dados["saldos_finais"]["total_saldo_final"] = sum([
                dados["saldos_finais"]["deposito_poupanca"],
                dados["saldos_finais"]["deposito_ordem"],
                dados["saldos_finais"]["numerario_caixa"]
            ])
        
        print(f"🏦 Resumo de Saldos - Inicial: {dados['saldos_iniciais']['total_saldo_inicial']:.2f}, Final: {dados['saldos_finais']['total_saldo_final']:.2f}")

    # ===== PROCESSAR RECEITAS (Saldos Negativos) =====
    print("💰 Processando dados de Receitas (saldos negativos)...")
    saldos_negativos = {}  # {FRACCAO: valor_total}
    
    for tipo in ("NORMAL", "EXTRA"):
        try:
            rows_r = _rows_wide(load_receitas_wide, tipo)
            if rows_r:
                dados["validacao"]["receitas_carregadas"] = True
                for row in rows_r:
                    fracao = str(row.get("FRACCAO", "")).strip()
                    saldo = clean_numeric(row.get("SALDO", 0))
                    
                    if not fracao:
                        print(f"⚠️ Linha sem fração ignorada em Receitas {tipo}")
                        continue
                        
                    if fracao.upper() == "TOTAIS":
                        continue
                        
                    if saldo < 0:
                        saldos_negativos[fracao] = saldos_negativos.get(fracao, 0.0) + saldo
                        print(f"⚠️ Saldo negativo encontrado - Fração: {fracao}, Saldo: {saldo:.2f}")
        except Exception as e:
            error_msg = f"❌ Erro ao processar Receitas {tipo}: {str(e)}"
            print(error_msg)
            dados["validacao"]["erros"].append(error_msg)
    
    # Ordenar por saldo (do mais negativo ao menos negativo)
    dados["saldos_negativos_condominos"] = dict(sorted(saldos_negativos.items(), key=lambda x: x[1]))
    
    # Log de validação final
    print(f"✅ Extração concluída - Erros: {len(dados['validacao']['erros'])}")
    if dados["validacao"]["erros"]:
        print("⚠️ Erros encontrados durante extração:")
        for erro in dados["validacao"]["erros"]:
            print(f"  {erro}")

    return dados

def montar_prompt_ia(dados):
    periodo = dados["periodo"]
    r = dados["receitas_correntes"]
    d = dados["despesas_correntes"]
    s_i = dados["saldos_iniciais"]
    s_f = dados["saldos_finais"]
    saldos_neg = dados["saldos_negativos_condominos"]
    
    detalhe_despesas = "\n".join([f"  • {conta}: €{valor:,.2f}" for conta, valor in d["detalhe_contas"].items()])
    
    # Formatar saldos negativos por condómino
    if saldos_neg:
        detalhe_saldos_negativos = "\n".join([
            f"  • Fração {fracao}: €{saldo:,.2f}" 
            for fracao, saldo in saldos_neg.items()
        ])
        total_dividas = sum(saldos_neg.values())
        info_saldos_negativos = f"""🔹 SALDOS NEGATIVOS POR CONDÓMINO:
{detalhe_saldos_negativos}
→ TOTAL EM DÍVIDA: €{total_dividas:,.2f}

"""
    else:
        info_saldos_negativos = "🔹 SALDOS NEGATIVOS POR CONDÓMINO:\nNenhum condómino com saldo negativo.\n\n"
    
    return f"""
Você é um contador especializado em gestão financeira de condomínios em Portugal.
Com base nos seguintes dados do período de {periodo}:

{info_saldos_negativos}🔹 RECEITAS CORRENTES:
- Quotas Normais: €{r['quotas_normais']:,.2f}
- Quotas Extras: €{r['quotas_extras']:,.2f}
- Juros Recebidos: €{r['juros']:,.2f}
→ TOTAL RECEITAS: €{r['total_receitas']:,.2f}

🔹 DESPESAS CORRENTES:
{detalhe_despesas}
→ TOTAL DESPESAS: €{d['total_despesas']:,.2f}

🔹 SALDOS INICIAIS:
- Depósito Poupança: €{s_i['deposito_poupanca']:,.2f}
- Depósito Ordem: €{s_i['deposito_ordem']:,.2f}
- Numerário Caixa: €{s_i['numerario_caixa']:,.2f}
→ TOTAL: €{s_i['total_saldo_inicial']:,.2f}

🔹 SALDOS FINAIS:
- Depósito Poupança: €{s_f['deposito_poupanca']:,.2f}
- Depósito Ordem: €{s_f['deposito_ordem']:,.2f}
- Numerário Caixa: €{s_f['numerario_caixa']:,.2f}
→ TOTAL: €{s_f['total_saldo_final']:,.2f}

🔹 SALDO DO EXERCÍCIO CORRENTE (Receitas - Despesas): €{dados['saldo_exercicio']:,.2f}

Elabore um relatório contabilístico conciso (máx. 350 palavras) com:
1. Avaliação da saúde financeira;
2. Pontos fortes e riscos (incluindo análise dos saldos negativos dos condóminos);
3. 2–3 sugestões práticas;
4. Comentário sobre evolução dos saldos.
Use linguagem clara, técnica e em português de Portugal.
"""

def gerar_relatorio_com_openrouter(prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": YOUR_SITE_URL,
        "X-Title": YOUR_SITE_NAME,
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 600
    }
    print(f"📡 Enviando requisição para OpenRouter (modelo: {OPENROUTER_MODEL})...")
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if response.status_code != 200:
            print(f"❌ Erro HTTP {response.status_code}: {response.text}")
            return None
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ Erro na API: {e}")
        return None

# ===================== GERAR PDF MODERNO DA IA =====================
def salvar_relatorio_ia_pdf(texto: str, caminho_pdf: Path):
    """Gera um PDF moderno a partir do texto da análise."""
    try:
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.colors import HexColor
    except ImportError:
        print("⚠️ 'reportlab' não instalado. PDF da IA não será gerado.")
        return False

    doc = SimpleDocTemplate(
        str(caminho_pdf),
        pagesize=A4,
        topMargin=50,
        bottomMargin=50,
        leftMargin=50,
        rightMargin=50
    )

    title_style = ParagraphStyle(
        name="Titulo",
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=HexColor("#2F5597"),
        spaceAfter=20,
        alignment=TA_LEFT
    )
    section_style = ParagraphStyle(
        name="Secao",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=HexColor("#1a73e8"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        name="Corpo",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=8,
        textColor=HexColor("#333333")
    )

    elements = []
    linhas = texto.split("\n")
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            elements.append(Spacer(1, 10))
            continue
        if linha.startswith("**") and linha.endswith("**"):
            elements.append(Paragraph(linha.strip("*"), title_style))
        elif any(linha.startswith(f"{i}. ") for i in range(1, 10)):
            elements.append(Paragraph(linha, section_style))
        elif linha.startswith("- "):
            elements.append(Paragraph(f"• {linha[2:]}", body_style))
        else:
            elements.append(Paragraph(linha, body_style))

    doc.build(elements)
    print(f"📄 PDF da IA salvo: {caminho_pdf}")
    return True

# ===================== FUNÇÃO PRINCIPAL =====================
def gerar_report_ai(pasta_dados: str):
    pasta = BASE_DIR / pasta_dados
    output_txt = DOCS_DIR / "Relatorio_Analise_IA.txt"
    output_pdf = DOCS_DIR / "Relatorio_Analise_IA.pdf"

    print("\n" + "="*80)
    print("🤖 INICIANDO ANÁLISE POR IA (OpenRouter)...")
    print("="*80)

    try:
        dados = extrair_dados_financeiros(pasta)
        prompt = montar_prompt_ia(dados)
        relatorio = gerar_relatorio_com_openrouter(prompt)

        if relatorio:
            # Garantir que a pasta Docs existe
            DOCS_DIR.mkdir(exist_ok=True)
            
            # Salvar TXT
            with open(output_txt, "w", encoding="utf-8") as f:
                f.write(relatorio)
            print(f"✅ Relatório TXT salvo: {str(output_txt)}")
            
            # Salvar PDF com formatação moderna
            pdf_gerado = salvar_relatorio_ia_pdf(relatorio, output_pdf)

            print("\n📝 Trecho do relatório:\n" + "-"*60)
            print(relatorio[:400] + ("..." if len(relatorio) > 400 else ""))
            
            # RETORNAR O CAMINHO DO PDF (correção)
            if pdf_gerado:
                return str(output_pdf)
            else:
                return str(output_txt)
        else:
            print("❌ Falha ao gerar relatório com OpenRouter.")
            return None
    except Exception as e:
        print(f"💥 Erro crítico: {e}")
        import traceback
        traceback.print_exc()
        return None

    print("="*80 + "\n")
    # Adicione um retorno no final também
    return None
