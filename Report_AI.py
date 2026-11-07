"""
Report_AI.py - Integração com Google Gemini (API REST)
- Usa funções centralizadas de Commons.py e Database.py (fonte = BD)
- Gera Relatorio_Analise_IA.txt e Relatorio_Analise_IA.pdf
- Extração enriquecida: saldos, dívidas (antigas + atuais), composição de despesas
- Indicadores pré-calculados no Python (FCR legal, concentrações, rácios)
- Prompt analítico quantificado (PT-PT) com recomendações prioritárias
- Tratamento de erros com retries em 429/5xx
"""
import os
import re
import time
from xml.sax.saxutils import escape
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
    ensure_views_and_fts,
)

# Garante o carregamento do .env usando o caminho absoluto baseado neste ficheiro
BASE_PATH = Path(__file__).parent
load_dotenv(BASE_PATH / ".env")
load_dotenv()  # fallback: .env na pasta de trabalho (não sobrescreve valores já definidos)

# ============================================
# CONFIGURAÇÃO DA API (GOOGLE GEMINI)
# ============================================
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL_PRIMARY") or "gemini-flash-latest").strip()
GEMINI_MODEL_ALTERNATIVE = (os.getenv("GEMINI_MODEL_ALTERNATIVE") or "").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Mínimo legal FCR (Dec.-Lei n.º 268/94, art. 4.º): 10% das quotas ordinárias
FCR_PERCENTAGEM_LEGAL = 0.10


# ============================================
# CHAMADA À API
# ============================================

def _chamar_modelo(messages, active_model, max_retries=3):
    """
    Chama o Gemini (generateContent) com um modelo específico e devolve
    o texto da resposta (str), ou None se falhar.
    """
    system_instruction = None
    contents = []
    for msg in messages:
        texto = str(msg.get("content", ""))
        if msg.get("role") == "system":
            system_instruction = texto
        else:
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": texto}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 6144,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = f"{GEMINI_BASE_URL}/{active_model}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    print(f"🔄 A chamar o modelo: {active_model}")

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    print(f"❌ Gemini devolveu resposta não-JSON: {response.text[:200]}")
                    return None

                candidates = data.get("candidates") or []
                if not candidates:
                    print(f"⚠️ Gemini sem candidatos (possível bloqueio): {str(data)[:300]}")
                    return None

                cand = candidates[0]
                parts = (cand.get("content") or {}).get("parts") or []
                texto = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                finish = cand.get("finishReason")

                if not texto:
                    print(f"⚠️ Gemini devolveu resposta vazia (finishReason={finish}).")
                    return None
                if finish == "MAX_TOKENS":
                    print("⚠️ Resposta cortada por limite de tokens (MAX_TOKENS).")

                print(f"✅ Modelo {active_model} respondeu com sucesso!")
                return texto

            if response.status_code in (429, 500, 502, 503, 504):
                wait_time = 2 ** (attempt + 1)
                print(f"⏳ Gemini ocupado/rate limit ({response.status_code}). Aguardando {wait_time}s "
                      f"(tentativa {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
                continue

            # 400/401/403/404...: chave, permissões ou nome de modelo -> não adianta repetir
            print(f"❌ Erro no Gemini ({response.status_code}): {response.text[:500]}")
            return None

        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            print(f"⏰ Timeout no Gemini (tentativa {attempt + 1}/{max_retries}). Aguardando {wait_time}s...")
            time.sleep(wait_time)
        except Exception as e:
            print(f"❌ Erro na chamada à API do Gemini: {e}")
            return None

    return None


def get_ai_response(messages, model=None, max_retries=3):
    """
    Tenta o modelo principal e, se falhar, o alternativo
    (GEMINI_MODEL_ALTERNATIVE no .env). Devolve o texto ou None.
    """
    if not GEMINI_API_KEY:
        print("❌ Variável GEMINI_API_KEY não encontrada no .env.")
        return None

    modelos = []
    for m in (model or GEMINI_MODEL, GEMINI_MODEL_ALTERNATIVE):
        if m and m not in modelos:
            modelos.append(m)

    for i, m in enumerate(modelos):
        if i > 0:
            print(f"⚠️ A tentar o modelo alternativo: {m}")
        texto = _chamar_modelo(messages, m, max_retries)
        if texto:
            return texto

    return None


# ============================================
# EXTRAÇÃO E INDICADORES (fonte = BD)
# ============================================

def extrair_dados_financeiros(pasta_dados: Path):
    """
    Extrai da BD (via loaders Database.py) todos os blocos necessários
    para a análise de IA: balanço, saldos, receitas N/E com saldo_ant e saldo.
    """
    pasta = resolver_pasta(pasta_dados)
    print(f"🔍 Extraindo dados financeiros da pasta: {pasta.name}")

    # Garante views/FTS antes das leituras (evita falha em v_receitas_pivot)
    try:
        ensure_views_and_fts(pasta)
    except Exception as exc:
        print(f"⚠️ ensure_views_and_fts: {exc}")

    periodo_ano = obter_ano_exercicio(str(pasta.name) if isinstance(pasta, Path) else pasta)
    print(f"📅 Período de análise: {periodo_ano}")

    dados = {
        "periodo": str(periodo_ano),
        "receitas_correntes": {
            "quotas_normais": 0.0,
            "quotas_extras": 0.0,
            "juros": 0.0,
            "total_receitas": 0.0,
        },
        "despesas_correntes": {
            "detalhe_contas": {},
            "total_despesas": 0.0,
        },
        "saldos_iniciais": {
            "deposito_poupanca": 0.0,
            "deposito_ordem": 0.0,
            "numerario_caixa": 0.0,
            "total_saldo_inicial": 0.0,
        },
        "saldos_finais": {
            "deposito_poupanca": 0.0,
            "deposito_ordem": 0.0,
            "numerario_caixa": 0.0,
            "total_saldo_final": 0.0,
        },
        "saldo_exercicio": 0.0,
        # Por fração: {fracao: {"normal": x, "extra": y, "total": z,
        #                       "saldo_ant_normal": a, "saldo_ant_extra": b}}
        "dividas_por_fracao": {},
        "validacao": {
            "balanco_carregado": False,
            "saldos_carregados": False,
            "receitas_carregadas": False,
            "erros": [],
        },
    }

    def _rows_wide(load_fn, *args):
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

    # ---------- Balanço ----------
    print("📊 Processando dados do Balanço...")
    rows_bal = _rows_wide(load_balanco_wide)

    if rows_bal:
        dados["validacao"]["balanco_carregado"] = True
        df_bal = pd.DataFrame(rows_bal, dtype=object)

        required_columns = ["CONTA", "VALOR", "TIPO"]
        missing_cols = [col for col in required_columns if col not in df_bal.columns]
        if missing_cols:
            error_msg = f"❌ Colunas faltando no Balanço: {missing_cols}"
            print(error_msg)
            dados["validacao"]["erros"].append(error_msg)

        for _, row in df_bal.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()

            if not conta:
                continue

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
            elif conta == "Saldo Exercicio":
                dados["saldo_exercicio"] = valor

        r = dados["receitas_correntes"]
        r["total_receitas"] = r["quotas_normais"] + r["quotas_extras"] + r["juros"]

        d = dados["despesas_correntes"]
        d["total_despesas"] = sum(d["detalhe_contas"].values())

        if dados["saldo_exercicio"] == 0:
            dados["saldo_exercicio"] = r["total_receitas"] - d["total_despesas"]

    # ---------- Saldos (inicial / final) ----------
    print("🏦 Processando dados de Saldos...")
    rows_saldos = _rows_wide(load_saldos_wide)

    if rows_saldos:
        dados["validacao"]["saldos_carregados"] = True
        df_saldos = pd.DataFrame(rows_saldos, dtype=object)

        for _, row in df_saldos.iterrows():
            conta = str(row.get("CONTA", "")).strip()
            valor = clean_numeric(row.get("VALOR", 0))
            tipo = str(row.get("TIPO", "")).strip().upper()

            if not conta:
                continue

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
            elif tipo == "EXERCICIO" or conta == "Saldo Exercício":
                if valor:
                    dados["saldo_exercicio"] = valor
            elif tipo == "FINAL" or conta == "Saldo Final":
                if valor and dados["saldos_finais"]["total_saldo_final"] == 0:
                    dados["saldos_finais"]["total_saldo_final"] = valor

        dados["saldos_iniciais"]["total_saldo_inicial"] = sum([
            dados["saldos_iniciais"]["deposito_poupanca"],
            dados["saldos_iniciais"]["deposito_ordem"],
            dados["saldos_iniciais"]["numerario_caixa"],
        ])

        if dados["saldos_finais"]["total_saldo_final"] == 0:
            dados["saldos_finais"]["total_saldo_final"] = sum([
                dados["saldos_finais"]["deposito_poupanca"],
                dados["saldos_finais"]["deposito_ordem"],
                dados["saldos_finais"]["numerario_caixa"],
            ])

    # ---------- Receitas N + E (dívidas com saldo_ant) ----------
    print("💰 Processando dados de Receitas (dívidas por fração)...")
    dividas = {}  # fracao -> dict

    for tipo_quota in ("NORMAL", "EXTRA"):
        chave = "normal" if tipo_quota == "NORMAL" else "extra"
        chave_ant = f"saldo_ant_{chave}"
        try:
            rows_r = _rows_wide(load_receitas_wide, tipo_quota)
            if not rows_r:
                continue
            dados["validacao"]["receitas_carregadas"] = True
            for row in rows_r:
                fracao = str(row.get("FRACCAO", "")).strip()
                if not fracao or fracao.upper() == "TOTAIS":
                    continue
                saldo = clean_numeric(row.get("SALDO", 0))
                saldo_ant = clean_numeric(row.get("SALDO_ANT", 0))

                if fracao not in dividas:
                    dividas[fracao] = {
                        "normal": 0.0,
                        "extra": 0.0,
                        "total": 0.0,
                        "saldo_ant_normal": 0.0,
                        "saldo_ant_extra": 0.0,
                    }
                # Guardamos o saldo atual (pode ser 0 ou negativo)
                dividas[fracao][chave] = saldo
                dividas[fracao][chave_ant] = saldo_ant
        except Exception as e:
            error_msg = f"❌ Erro ao processar Receitas {tipo_quota}: {str(e)}"
            dados["validacao"]["erros"].append(error_msg)
            print(error_msg)

    for fracao, d in dividas.items():
        d["total"] = d["normal"] + d["extra"]

    # Ordenar por dívida total (mais negativa primeiro)
    dados["dividas_por_fracao"] = dict(
        sorted(dividas.items(), key=lambda x: x[1]["total"])
    )

    # Compatibilidade: mapa simples de saldos negativos totais
    dados["saldos_negativos_condominos"] = {
        f: d["total"] for f, d in dados["dividas_por_fracao"].items() if d["total"] < 0
    }

    return dados


def calcular_indicadores(dados: dict) -> dict:
    """
    Calcula rácios e alertas a partir dos dados extraídos.
    Tudo é feito em Python para a IA receber números já corretos.
    """
    r = dados["receitas_correntes"]
    d = dados["despesas_correntes"]
    s_i = dados["saldos_iniciais"]
    s_f = dados["saldos_finais"]
    dividas = dados["dividas_por_fracao"]

    total_rec = r["total_receitas"] or 0.0
    total_desp = d["total_despesas"] or 0.0
    tsa = s_i["total_saldo_inicial"] or 0.0
    tsf = s_f["total_saldo_final"] or 0.0

    # Composição de despesas (peso %)
    detalhe_despesas = []
    for conta, valor in sorted(d["detalhe_contas"].items(), key=lambda x: -x[1]):
        peso = (valor / total_desp * 100) if total_desp else 0.0
        detalhe_despesas.append({"conta": conta, "valor": valor, "peso_pct": peso})

    maior_despesa = detalhe_despesas[0] if detalhe_despesas else None

    # Dívidas
    dividas_neg = {f: v for f, v in dividas.items() if v["total"] < 0}
    total_divida = sum(v["total"] for v in dividas_neg.values())  # negativo
    total_divida_abs = abs(total_divida)
    n_devedores = len(dividas_neg)

    # Top 2 frações (maior dívida)
    top_devedores = sorted(dividas_neg.items(), key=lambda x: x[1]["total"])[:2]
    top2_valor = sum(v["total"] for _, v in top_devedores)
    top2_pct = (abs(top2_valor) / total_divida_abs * 100) if total_divida_abs else 0.0

    # Dívida antiga (saldo_ant negativo) vs. do exercício
    divida_antiga = 0.0
    for v in dividas.values():
        ant = (v.get("saldo_ant_normal") or 0.0) + (v.get("saldo_ant_extra") or 0.0)
        if ant < 0:
            divida_antiga += ant
    divida_antiga_abs = abs(divida_antiga)

    # FCR legal
    fcr_minimo = r["quotas_normais"] * FCR_PERCENTAGEM_LEGAL
    fcr_atual = s_f["deposito_poupanca"]
    fcr_em_falta = max(0.0, fcr_minimo - fcr_atual)

    # Rácios
    peso_extras_pct = (r["quotas_extras"] / total_rec * 100) if total_rec else 0.0
    peso_normais_pct = (r["quotas_normais"] / total_rec * 100) if total_rec else 0.0
    racio_desp_rec_pct = (total_desp / total_rec * 100) if total_rec else 0.0
    variacao_tesouraria = tsf - tsa
    variacao_tesouraria_pct = (variacao_tesouraria / tsa * 100) if tsa else 0.0

    # Liquidez ociosa aproximada: DO acima do necessário para despesas anuais + FCR
    liquidez_do = s_f["deposito_ordem"]
    reserva_operacional_sugerida = total_desp  # 1 ano de despesas correntes
    excesso_liquidez = max(0.0, liquidez_do - reserva_operacional_sugerida - fcr_em_falta)

    return {
        "detalhe_despesas": detalhe_despesas,
        "maior_despesa": maior_despesa,
        "total_divida": total_divida,
        "total_divida_abs": total_divida_abs,
        "n_devedores": n_devedores,
        "top_devedores": [
            {
                "fracao": f,
                "normal": v["normal"],
                "extra": v["extra"],
                "total": v["total"],
                "saldo_ant_normal": v.get("saldo_ant_normal", 0.0),
                "saldo_ant_extra": v.get("saldo_ant_extra", 0.0),
            }
            for f, v in top_devedores
        ],
        "top2_pct": top2_pct,
        "divida_antiga_abs": divida_antiga_abs,
        "fcr_minimo": fcr_minimo,
        "fcr_atual": fcr_atual,
        "fcr_em_falta": fcr_em_falta,
        "peso_extras_pct": peso_extras_pct,
        "peso_normais_pct": peso_normais_pct,
        "racio_desp_rec_pct": racio_desp_rec_pct,
        "variacao_tesouraria": variacao_tesouraria,
        "variacao_tesouraria_pct": variacao_tesouraria_pct,
        "excesso_liquidez": excesso_liquidez,
        "reserva_operacional_sugerida": reserva_operacional_sugerida,
    }


def _fmt_eur(v: float) -> str:
    """Formata valor em euros estilo PT (1.234,56)."""
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def montar_prompt_ia(dados: dict):
    """
    Constrói system + user content com indicadores pré-calculados
    e estrutura de relatório analítica.
    """
    periodo = dados["periodo"]
    r = dados["receitas_correntes"]
    d = dados["despesas_correntes"]
    s_i = dados["saldos_iniciais"]
    s_f = dados["saldos_finais"]
    ind = calcular_indicadores(dados)

    # --- bloco despesas ---
    linhas_desp = []
    for item in ind["detalhe_despesas"]:
        linhas_desp.append(
            f"  • {item['conta']}: €{_fmt_eur(item['valor'])} ({item['peso_pct']:.1f}%)"
        )
    detalhe_despesas = "\n".join(linhas_desp) if linhas_desp else "  (sem despesas registadas)"

    # --- bloco dívidas por fração ---
    linhas_div = []
    for fracao, v in dados["dividas_por_fracao"].items():
        if v["total"] >= 0 and (v.get("saldo_ant_normal", 0) + v.get("saldo_ant_extra", 0)) >= 0:
            continue
        ant_n = v.get("saldo_ant_normal", 0.0)
        ant_e = v.get("saldo_ant_extra", 0.0)
        linhas_div.append(
            f"  • {fracao}: total €{_fmt_eur(v['total'])} "
            f"(N €{_fmt_eur(v['normal'])} | E €{_fmt_eur(v['extra'])}; "
            f"saldo ant. N €{_fmt_eur(ant_n)} | E €{_fmt_eur(ant_e)})"
        )
    if not linhas_div:
        info_dividas = "🔹 DÍVIDAS POR FRAÇÃO:\nNenhum condómino com saldo negativo.\n"
    else:
        info_dividas = (
            f"🔹 DÍVIDAS POR FRAÇÃO (saldo atual; negativo = em dívida):\n"
            f"{chr(10).join(linhas_div)}\n"
            f"→ TOTAL EM DÍVIDA: €{_fmt_eur(ind['total_divida'])} "
            f"({ind['n_devedores']} frações)\n"
        )

    # --- indicadores prontos ---
    maior = ind["maior_despesa"]
    maior_txt = (
        f"{maior['conta']} (€{_fmt_eur(maior['valor'])}, {maior['peso_pct']:.1f}%)"
        if maior else "n/d"
    )
    top_txt = "; ".join(
        f"{t['fracao']} €{_fmt_eur(t['total'])}" for t in ind["top_devedores"]
    ) or "n/d"

    indicadores = f"""🔹 INDICADORES PRÉ-CALCULADOS (usar estes valores; não recalcular):
- Peso Quotas Normais / Receitas: {ind['peso_normais_pct']:.1f}%
- Peso Quotas Extras / Receitas: {ind['peso_extras_pct']:.1f}%
- Rácio Despesas / Receitas: {ind['racio_desp_rec_pct']:.1f}%
- Maior rubrica de despesa: {maior_txt}
- FCR legal mínimo (10% quotas normais): €{_fmt_eur(ind['fcr_minimo'])} | Atual (Poupança): €{_fmt_eur(ind['fcr_atual'])} | Em falta: €{_fmt_eur(ind['fcr_em_falta'])}
- Dívida total (saldos negativos): €{_fmt_eur(ind['total_divida'])} | N.º de frações em dívida: {ind['n_devedores']}
- Concentração top 2 devedores: {ind['top2_pct']:.1f}% → {top_txt}
- Dívida transitada (saldo_ant negativo, abs): €{_fmt_eur(ind['divida_antiga_abs'])}
- Variação de tesouraria: €{_fmt_eur(ind['variacao_tesouraria'])} ({ind['variacao_tesouraria_pct']:+.1f}%)
- Excesso de liquidez estimado (após 1 ano de despesas + FCR em falta): €{_fmt_eur(ind['excesso_liquidez'])}
"""

    system_instruction = (
        "Você é um contabilista certificado especializado em administração de condomínios em Portugal. "
        "Elabore um relatório contabilístico e financeiro profissional, em português de Portugal, "
        "claro e quantificado (cerca de 500–650 palavras).\n\n"
        "Estrutura OBRIGATÓRIA (use estes títulos numerados):\n"
        "1. Síntese executiva\n"
        "2. Tesouraria e liquidez\n"
        "3. Receitas e cobrança\n"
        "4. Despesas\n"
        "5. Cumprimento legal e reservas (FCR)\n"
        "6. Riscos prioritários\n"
        "7. Recomendações práticas quantificadas\n\n"
        "Regras:\n"
        "- Use APENAS os números e indicadores fornecidos; não invente valores.\n"
        "- Quantifique sempre que possível (euros e percentagens).\n"
        "- Nas recomendações: indique valores, prazos e ordem de prioridade.\n"
        "- Referências legais só quando aplicável (ex.: FCR — Dec.-Lei n.º 268/94).\n"
        "- Tom técnico, objetivo, sem floreados. Não use markdown de código; pode usar **negrito** pontual."
    )

    user_content = f"""Com base nos dados do exercício de {periodo} (fonte: base de dados do condomínio), elabore o relatório pedido.

{indicadores}
{info_dividas}
🔹 RECEITAS DO EXERCÍCIO:
- Quotas Normais: €{_fmt_eur(r['quotas_normais'])}
- Quotas Extras: €{_fmt_eur(r['quotas_extras'])}
- Juros Recebidos: €{_fmt_eur(r['juros'])}
→ TOTAL RECEITAS: €{_fmt_eur(r['total_receitas'])}

🔹 DESPESAS DO EXERCÍCIO:
{detalhe_despesas}
→ TOTAL DESPESAS: €{_fmt_eur(d['total_despesas'])}

🔹 SALDOS INICIAIS (TSA):
- Depósito Poupança: €{_fmt_eur(s_i['deposito_poupanca'])}
- Depósito Ordem: €{_fmt_eur(s_i['deposito_ordem'])}
- Numerário Caixa: €{_fmt_eur(s_i['numerario_caixa'])}
→ TOTAL: €{_fmt_eur(s_i['total_saldo_inicial'])}

🔹 SALDOS FINAIS:
- Depósito Poupança: €{_fmt_eur(s_f['deposito_poupanca'])}
- Depósito Ordem: €{_fmt_eur(s_f['deposito_ordem'])}
- Numerário Caixa: €{_fmt_eur(s_f['numerario_caixa'])}
→ TOTAL: €{_fmt_eur(s_f['total_saldo_final'])}

🔹 SALDO DO EXERCÍCIO (Receitas − Despesas): €{_fmt_eur(dados['saldo_exercicio'])}
"""

    return system_instruction, user_content


# ============================================
# PDF  (pontos 1–7 em barra azul; corpo livre)
# ============================================

# Cores alinhadas com Gerar_Ata / Report (balanço)
_AI_HEADER_BG = "#D6E3F0"       # fundo azul claro dos 7 pontos principais
_AI_TITLE_BG = "#2F5597"        # fundo azul do título principal
_AI_BORDER = "#C0C0C0"
_AI_MARGIN_CM = 1.5             # margens L/R (igual preferência dos mapas)


# Palavras-chave dos 7 capítulos obrigatórios (prompt da IA).
# Usadas para NÃO confundir com sub-pontos numerados ("1. Incumprimento…").
_AI_CAPITULOS = (
    (1, r"s[ií]ntese\s+executiva"),
    (2, r"tesouraria"),
    (3, r"receitas"),
    (4, r"despesas"),
    (5, r"cumprimento\s+legal|reservas|\bFCR\b"),
    (6, r"riscos\s+priorit"),
    (7, r"recomenda[cç][oõ]es"),
)


def _ai_is_ponto_principal(linha: str) -> bool:
    """
    Só os 7 títulos de capítulo do relatório.
    Ex.: "1. Síntese executiva", "6. Riscos prioritários".
    NÃO apanha sub-pontos como "1. Incumprimento Normativo…".
    """
    if not linha:
        return False
    # Remover marcadores markdown / heading
    t = linha.strip()
    t = re.sub(r"^#{1,3}\s*", "", t)
    t = t.strip("*").strip()

    m = re.match(r"^([1-7])\.\s+(.+)$", t, flags=re.IGNORECASE)
    if not m:
        return False
    num = int(m.group(1))
    resto = m.group(2)
    for n, pat in _AI_CAPITULOS:
        if n == num and re.search(pat, resto, flags=re.IGNORECASE):
            return True
    return False


def _ai_titulo_limpo(linha: str) -> str:
    t = linha.strip()
    t = re.sub(r"^#{1,3}\s*", "", t)
    t = t.strip("*").strip()
    return t


def salvar_relatorio_ia_pdf(texto: str, caminho_pdf: Path):
    """
    Gera PDF A4 portrait:
      - barra de título do documento (azul escuro)
      - cada um dos 7 pontos principais numa célula a toda a largura,
        fundo azul claro
      - subtítulos e texto corrido FORA de tabelas (fundo branco da página)
    Margens L/R = 1,5 cm.
    """
    try:
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer,
        )
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.colors import HexColor, white
        from reportlab.lib.units import cm
    except ImportError:
        print("⚠️ 'reportlab' não instalado. PDF da IA não será gerado.")
        return False

    margin = _AI_MARGIN_CM * cm
    doc = SimpleDocTemplate(
        str(caminho_pdf),
        pagesize=A4,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        leftMargin=margin,
        rightMargin=margin,
    )
    page_w, _ = A4
    usable = page_w - 2 * margin

    header_bg = HexColor(_AI_HEADER_BG)
    title_bg = HexColor(_AI_TITLE_BG)
    border = HexColor(_AI_BORDER)

    style_doc_title = ParagraphStyle(
        name="AIDocTitle",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=white,
        alignment=TA_CENTER,
        spaceBefore=0,
        spaceAfter=0,
    )
    style_section = ParagraphStyle(
        name="AISection",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=HexColor("#1F3864"),
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=0,
    )
    style_body = ParagraphStyle(
        name="AIBody",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=HexColor("#333333"),
        alignment=TA_JUSTIFY,
        spaceBefore=2,
        spaceAfter=4,
    )
    style_bullet = ParagraphStyle(
        name="AIBullet",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=HexColor("#333333"),
        alignment=TA_LEFT,
        leftIndent=12,
        spaceBefore=1,
        spaceAfter=2,
    )
    style_subtitle = ParagraphStyle(
        name="AISubtitle",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=HexColor("#333333"),
        alignment=TA_LEFT,
        spaceBefore=6,
        spaceAfter=3,
    )

    def _fmt(txt: str) -> str:
        txt = escape(txt)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", txt)

    def _barra_titulo(texto_titulo: str, *, principal: bool = False) -> Table:
        """Célula a toda a largura com fundo azul (título doc ou ponto 1–7)."""
        if principal:
            p = Paragraph(texto_titulo, style_doc_title)
            bg, pad = title_bg, 10
        else:
            p = Paragraph(_fmt(texto_titulo), style_section)
            bg, pad = header_bg, 6
        t = Table([[p]], colWidths=[usable])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER" if principal else "LEFT"),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.4, border),
        ]))
        return t

    elements = []

    # Barra de título do documento
    elements.append(_barra_titulo(
        "Análise Financeira por IA — Relatório do Exercício",
        principal=True,
    ))
    elements.append(Spacer(1, 10))

    # Pontos 1–7 → célula azul; resto → corpo livre (fundo branco da página)
    for raw in texto.split("\n"):
        linha = raw.strip()
        if not linha:
            elements.append(Spacer(1, 4))
            continue

        if _ai_is_ponto_principal(linha):
            elements.append(Spacer(1, 6))
            elements.append(_barra_titulo(_ai_titulo_limpo(linha)))
            elements.append(Spacer(1, 4))
            continue

        # **subtítulo** sozinho → negrito no corpo (sem célula)
        if linha.startswith("**") and linha.endswith("**") and linha.count("**") == 2:
            elements.append(Paragraph(_fmt(linha.strip("*")), style_subtitle))
            continue

        if linha.startswith("- ") or linha.startswith("* ") or linha.startswith("• "):
            elements.append(Paragraph(f"• {_fmt(linha[2:].strip())}", style_bullet))
            continue

        if linha.startswith("#"):
            elements.append(Paragraph(_fmt(linha.lstrip("# ").strip()), style_subtitle))
            continue

        elements.append(Paragraph(_fmt(linha), style_body))

    try:
        doc.build(elements)
    except Exception as e:
        print(f"⚠️ Falha ao gerar o PDF da IA: {e}")
        return False

    print(f"📄 PDF da IA salvo: {caminho_pdf}")
    return True


# ============================================
# ORQUESTRADOR
# ============================================

def gerar_report_ai(pasta_dados: str):
    pasta = BASE_DIR / pasta_dados
    output_txt = DOCS_DIR / "Relatorio_Analise_IA.txt"
    output_pdf = DOCS_DIR / "Relatorio_Analise_IA.pdf"

    print("\n" + "=" * 80)
    print("🤖 INICIANDO ANÁLISE POR IA (Google Gemini)...")
    print("=" * 80)

    try:
        dados = extrair_dados_financeiros(pasta)
        sys_instruction, user_content = montar_prompt_ia(dados)

        messages = [
            {"role": "system", "content": sys_instruction},
            {"role": "user", "content": user_content},
        ]

        relatorio = get_ai_response(messages)

        if relatorio:
            DOCS_DIR.mkdir(parents=True, exist_ok=True)

            with open(output_txt, "w", encoding="utf-8") as f:
                f.write(relatorio)
            print(f"✅ Relatório TXT salvo: {str(output_txt)}")

            pdf_gerado = salvar_relatorio_ia_pdf(relatorio, output_pdf)

            print("\n📝 Trecho do relatório:\n" + "-" * 60)
            print(relatorio[:500] + ("..." if len(relatorio) > 500 else ""))

            return str(output_pdf) if pdf_gerado else str(output_txt)
        else:
            print("❌ Falha crítica: O Gemini não devolveu resposta.")
            return None

    except Exception as e:
        print(f"💥 Erro crítico: {e}")
        import traceback
        traceback.print_exc()
        return None
