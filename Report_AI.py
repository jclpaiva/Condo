"""
Report_AI.py - Integração com OpenRouter.ai
- Usa funções centralizadas de Commons.py
- Gera Relatorio_Analise_IA.txt
- Gera Relatorio_Analise_IA.pdf com formatação moderna
- Mostra loading automático se dentro de PyQt6
- Remove cálculo incorreto de liquidez corrente
- Usa ano do exercício de Configs
- Extrai saldos negativos por condómino de ReceitasN e ReceitasE
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
    obter_ano_exercicio, clean_numeric, carregar_db, existe_dados
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
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
#OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder:free")
YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "http://localhost")
YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME", "CondominioAI")

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
    balanco_path = pasta_dados / "Balanco"
    saldos_path = pasta_dados / "Saldos"
    receitas_n_path = pasta_dados / "ReceitasN"
    receitas_e_path = pasta_dados / "ReceitasE"
    
    # Obter ano do exercício de forma centralizada
    periodo_ano = obter_ano_exercicio(str(pasta_dados.name) if isinstance(pasta_dados, Path) else pasta_dados)
    
    dados = {
        "periodo": str(periodo_ano),
        "receitas_correntes": {"quotas_normais": 0.0, "quotas_extras": 0.0, "juros": 0.0, "total_receitas": 0.0},
        "despesas_correntes": {"detalhe_contas": {}, "total_despesas": 0.0},
        "saldos_iniciais": {"deposito_poupanca": 0.0, "deposito_ordem": 0.0, "numerario_caixa": 0.0, "total_saldo_inicial": 0.0},
        "saldos_finais": {"deposito_poupanca": 0.0, "deposito_ordem": 0.0, "numerario_caixa": 0.0, "total_saldo_final": 0.0},
        "saldo_exercicio": 0.0,  # Este será calculado como total_receitas - total_despesas
        "saldos_negativos_condominos": {},  # Dicionário: {fracao: saldo_total_negativo}
    }

    # Processar Balanco
    if existe_dados(balanco_path):
        rows, _ = carregar_db(balanco_path)
        df_bal = pd.DataFrame(rows, dtype=object)
        for _, row in df_bal.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()
            if tipo == "RECEITA":
                if "Quotas Normais" in conta:
                    dados["receitas_correntes"]["quotas_normais"] = valor
                elif "Quotas Extras" in conta:
                    dados["receitas_correntes"]["quotas_extras"] = valor
                elif "Juros" in conta:
                    dados["receitas_correntes"]["juros"] = valor
            elif tipo == "DESPESA":
                dados["despesas_correntes"]["detalhe_contas"][conta] = valor
            elif conta == "Saldo Final":
                dados["saldos_finais"]["total_saldo_final"] = valor

        # Calcular total_receitas corretamente
        r = dados["receitas_correntes"]
        r["total_receitas"] = r["quotas_normais"] + r["quotas_extras"] + r["juros"]
        
        # Calcular total_despesas
        d = dados["despesas_correntes"]
        d["total_despesas"] = sum(d["detalhe_contas"].values())
        
        # Calcular saldo_exercicio como (total_receitas - total_despesas)
        dados["saldo_exercicio"] = r["total_receitas"] - d["total_despesas"]

    # Processar Saldos (APENAS para saldos iniciais e finais)
    if existe_dados(saldos_path):
        rows, _ = carregar_db(saldos_path)
        df_saldos = pd.DataFrame(rows, dtype=object)
        for _, row in df_saldos.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()
            
            # IMPORTANTE: NÃO extrair "Saldo Exercicio" do Saldos
            # Apenas extrair saldos iniciais e finais
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

    # ====== NOVA FUNCIONALIDADE: Extrair saldos NEGATIVOS de ReceitasN e ReceitasE ======
    saldos_negativos = {}  # {FRACCAO: valor_total}
    
    # Processar ReceitasN
    if existe_dados(receitas_n_path):
        try:
            rows_n, _ = carregar_db(receitas_n_path)
            df_receitas_n = pd.DataFrame(rows_n, dtype=object)
            for _, row in df_receitas_n.iterrows():
                fracao = str(row.get("FRACCAO", "")).strip()
                saldo = clean_numeric(row.get("SALDO", 0))
                
                # IGNORAR linha de TOTAIS
                if fracao.upper() == "TOTAIS":
                    continue
                
                # Apenas saldos NEGATIVOS
                if saldo < 0:
                    if fracao in saldos_negativos:
                        saldos_negativos[fracao] += saldo
                    else:
                        saldos_negativos[fracao] = saldo
        except Exception as e:
            print(f"⚠️ Erro ao processar ReceitasN: {e}")
    
    # Processar ReceitasE
    if existe_dados(receitas_e_path):
        try:
            rows_e, _ = carregar_db(receitas_e_path)
            df_receitas_e = pd.DataFrame(rows_e, dtype=object)
            for _, row in df_receitas_e.iterrows():
                fracao = str(row.get("FRACCAO", "")).strip()
                saldo = clean_numeric(row.get("SALDO", 0))
                
                # IGNORAR linha de TOTAIS
                if fracao.upper() == "TOTAIS":
                    continue
                
                # Apenas saldos NEGATIVOS
                if saldo < 0:
                    if fracao in saldos_negativos:
                        saldos_negativos[fracao] += saldo
                    else:
                        saldos_negativos[fracao] = saldo
        except Exception as e:
            print(f"⚠️ Erro ao processar ReceitasE: {e}")
    
    # Ordenar por saldo (do mais negativo ao menos negativo)
    dados["saldos_negativos_condominos"] = dict(sorted(saldos_negativos.items(), key=lambda x: x[1]))

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
