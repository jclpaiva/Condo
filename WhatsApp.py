"""
WhatsApp.py - Envio de mensagens via WhatsApp Web (wa.me)
Abre o WhatsApp Web / App com mensagem pré-preenchida para condóminos
com quotas em atraso.

NOTA IMPORTANTE:
    O WhatsApp não permite envio automático sem a API Business.
    Este módulo abre o cliente WA do utilizador com a mensagem já
    preenchida — o utilizador confirma manualmente o envio (carregando
    em "Enviar" em cada janela). É a forma legal e fiável de enviar
    cobranças sem infração dos ToS do WhatsApp.
"""
from __future__ import annotations
import sys
import time
import webbrowser
import urllib.parse
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox

from Commons import BASE_DIR, format_currency
try:
    from Commons import pasta_e_corrente
except ImportError:
    def pasta_e_corrente(pasta_dados=None) -> bool:
        if pasta_dados is None or str(pasta_dados).strip() in ("", "corrente"):
            return True
        s = str(pasta_dados).replace("\\", "/").strip().lower()
        return "historico" not in s.split("/") and (
            s == "corrente" or s.endswith("/corrente")
        )

# Intervalo (segundos) entre cada abertura de janela/separador do WhatsApp
# no envio em lote, para não sobrecarregar o browser nem disparar bloqueios
# de pop-up quando há muitos condóminos em atraso.
ATRASO_ENTRE_ENVIOS = 0.4


def _aguardar_com_ui_responsiva(segundos: float) -> None:
    """Espera `segundos`, processando eventos Qt entretanto.

    Evita que a janela da aplicação fique "congelada" durante o envio em
    lote (um time.sleep simples bloquearia a UI inteira).
    """
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        try:
            QApplication.processEvents()
        except Exception:
            pass
        time.sleep(0.05)


# ====================================================================
# FORMATAÇÃO / MONTAGEM DE MENSAGEM
# ====================================================================
def formatar_numero_wa(numero: str) -> str:
    """Normaliza um número de telefone para o formato wa.me.

    Regras:
      - Mantém apenas dígitos.
      - Se tiver 9 dígitos → prefixa com 351 (Portugal).
      - Devolve string vazia se não for possível interpretar.
    """
    if not numero:
        return ""
    digits = "".join(ch for ch in str(numero) if ch.isdigit())
    if not digits:
        return ""
    # 9 dígitos → assume Portugal (351 + 9)
    if len(digits) == 9:
        digits = "351" + digits
    # 11 dígitos começando por 351 → OK
    # Outros formatos → devolve tal qual (o utilizador valida)
    return digits


def montar_mensagem_atraso(nome: str, meses_atraso: int, deficit: float,
                           fracao: str = "", andar: str = "") -> str:
    """Monta a mensagem de cobrança a enviar por WhatsApp."""
    nome = (nome or "").strip() or "Condómino"
    valor = format_currency(deficit).replace("\u00a0", "").strip()
    localizacao = fracao or andar or ""
    loc_txt = f" (Fração {localizacao})" if localizacao else ""

    msg = (
        f"Caro condómino {nome}{loc_txt},\n\n"
        f"Informamos que tem {meses_atraso} quota(s) de condomínio em atraso, "
        f"no valor total de {valor}.\n"
        f"Agradecemos que regularize a situação o mais brevemente possível.\n\n"
        f"Obrigado,\nA Administração\n"
        f"[* caso já tenha efetuado a regularização, descarte esta mensagem]"
    )
    return msg


# ====================================================================
# ABERTURA DO WHATSAPP
# ====================================================================
def abrir_whatsapp(numero: str, mensagem: str) -> bool:
    """Abre o WhatsApp Web/App com a mensagem pré-preenchida.

    Devolve True se o browser foi aberto com sucesso.
    """
    wa_number = formatar_numero_wa(numero)
    if not wa_number:
        return False
    encoded = urllib.parse.quote(mensagem)
    url = f"https://wa.me/{wa_number}?text={encoded}"
    try:
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"✗ Erro ao abrir WhatsApp: {e}")
        return False


# ====================================================================
# ENVIO A UM CONDÓMINO (com cálculo de atraso)
# ====================================================================
def enviar_whatsapp_a_condomino(condomino: dict, dados_pagamentos: dict) -> tuple[bool, str]:
    """Calcula atraso do condómino e abre WhatsApp se estiver em atraso.

    Args:
        condomino: dict com NOME, TELEMOVEL, FRACAO, ANDAR, QUOTAN, QUOTAE
        dados_pagamentos: dict devolvido por obter_pagamentos_condomino

    Devolve:
        (sucesso, mensagem_de_status)
    """
    from Condominos import calcular_estado_atraso

    nome = str(condomino.get("NOME", "")).strip()
    # Inativos não recebem
    if nome.startswith("[") and nome.endswith("]"):
        return False, "Condómino inativo"

    telefone = str(condomino.get("TELEMOVEL", "")).strip()
    if not telefone:
        return False, f"{nome}: sem telemóvel definido"

    quota_n = float(condomino.get("QUOTAN") or 0)
    quota_e = float(condomino.get("QUOTAE") or 0)
    total_pago = float(dados_pagamentos.get("total_geral") or 0)

    estado = calcular_estado_atraso(total_pago, quota_n, quota_e)
    if not estado["em_atraso"]:
        return False, f"{nome}: sem quotas em atraso"

    msg = montar_mensagem_atraso(
        nome=nome,
        meses_atraso=estado["meses_atraso"],
        deficit=estado["deficit"],
        fracao=str(condomino.get("FRACAO", "")).strip(),
        andar=str(condomino.get("ANDAR", "")).strip(),
    )
    ok = abrir_whatsapp(telefone, msg)
    if ok:
        return True, (
            f"{nome}: WhatsApp aberto "
            f"({estado['meses_atraso']} quota(s), {format_currency(estado['deficit'])})"
        )
    return False, f"{nome}: falha ao abrir WhatsApp"


# ====================================================================
# ENVIO EM LOTE A TODOS OS CONDÓMINOS COM ATRASO
# ====================================================================
def enviar_whatsapp_a_todos_atrasados(pasta_dados, parent=None) -> dict:
    """Percorre todos os condóminos ativos e abre WA para os que têm atraso.

    Só opera no exercício corrente (pasta ``corrente``). Em histórico
    devolve imediatamente com um erro explicativo.

    Devolve dict: {total, enviados, ignorados: [nomes], erros: [nomes]}
    """
    from Condominos import (
        carregar_condominos_db,
        obter_pagamentos_condomino,
        condominos_ativos_na_fracao,
    )

    resultado = {
        "total": 0,
        "enviados": 0,
        "ignorados": [],   # sem atraso / inativos / sem telefone
        "erros": [],
    }

    if not pasta_e_corrente(pasta_dados):
        msg = (
            "Envio WhatsApp bloqueado: está a visualizar um exercício histórico. "
            "Só é permitido no ano corrente."
        )
        print(f"⚠️ {msg}")
        resultado["erros"].append(msg)
        if parent is not None:
            try:
                QMessageBox.information(parent, "Exercício histórico", msg)
            except Exception:
                pass
        return resultado

    try:
        caminho = BASE_DIR / pasta_dados / "Condominos"
        condominos = carregar_condominos_db(str(caminho))
    except Exception as e:
        print(f"✗ Erro a carregar condóminos: {e}")
        resultado["erros"].append(f"Erro a carregar condóminos: {e}")
        return resultado

    resultado["total"] = len(condominos)

    for cond in condominos:
        nome = str(cond.get("NOME", "")).strip()
        andar = str(cond.get("ANDAR", "")).strip()

        # Inativos saltam
        if nome.startswith("[") and nome.endswith("]"):
            resultado["ignorados"].append(f"{nome} (inativo)")
            continue

        # Sem telefone
        if not str(cond.get("TELEMOVEL", "")).strip():
            resultado["ignorados"].append(f"{nome} (sem telefone)")
            continue

        # Sem andar → não conseguimos calcular pagamentos
        if not andar:
            resultado["ignorados"].append(f"{nome} (sem andar)")
            continue

        # Controlo: ANDAR partilhado por mais de um condómino ativo (ex.
        # transição de venda a meio do ano). Os pagamentos são calculados
        # por ANDAR, não por condómino, pelo que o atraso ficaria agregado
        # e não pode ser atribuído com confiança — não enviar automaticamente.
        outros = condominos_ativos_na_fracao(condominos, andar, excluir_nome=nome)
        if outros:
            resultado["erros"].append(
                f"{nome}: ANDAR '{andar}' partilhado com {', '.join(outros)} — "
                f"cálculo de atraso ambíguo, envio ignorado (requer confirmação manual)"
            )
            continue

        try:
            dados = obter_pagamentos_condomino(andar, pasta_dados)
        except Exception as e:
            resultado["erros"].append(f"{nome}: {e}")
            continue

        ok, msg_status = enviar_whatsapp_a_condomino(cond, dados)
        if ok:
            resultado["enviados"] += 1
            print(f"  ✓ {msg_status}")
            # Pequeno intervalo entre aberturas de janelas do WhatsApp
            _aguardar_com_ui_responsiva(ATRASO_ENTRE_ENVIOS)
        else:
            resultado["ignorados"].append(msg_status)

    return resultado


# ====================================================================
# CLI (execução independente)
# ====================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    pasta = "corrente"
    print(f"\n{'='*70}")
    print(f"📱 WhatsApp — Condóminos com quotas em atraso ({pasta})")
    print(f"{'='*70}\n")

    confirm = QMessageBox.question(
        None,
        "Confirmação",
        "Pretende abrir o WhatsApp para TODOS os condóminos com quotas em atraso?\n\n"
        "(Será aberta uma janela do WhatsApp por condómino — confirme o envio em cada uma.)",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
        print("Operação cancelada.")
        sys.exit(0)

    resultado = enviar_whatsapp_a_todos_atrasados(pasta)

    print(f"\n{'='*70}")
    print(f"Resumo:")
    print(f"  • Total de condóminos : {resultado['total']}")
    print(f"  • WhatsApp abertos    : {resultado['enviados']}")
    print(f"  • Ignorados           : {len(resultado['ignorados'])}")
    print(f"  • Erros               : {len(resultado['erros'])}")
    print(f"{'='*70}\n")
    sys.exit(0)