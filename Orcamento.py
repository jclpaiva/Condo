"""
Orcamento.py — lógica do módulo Orçamento (projeção e quotas).

Dados:
  - Despesas / quotas correntes: funções do Balanço
  - Frações / permilagens: tabela ``fracoes``
"""
from __future__ import annotations

import math
from typing import Any

from Commons import clean_numeric
from Database import FracoesRepo, resolver_pasta
from Balanco import (
    carregar_despesas,
    carregar_quotas_normais,
    carregar_quotas_extras,
)


def arredondar_quota_mensal(valor: float) -> float:
    """
    Arredondamento da quota mensal:
      parte decimal ∈ ]0.00, 0.50] → 0.50
      parte decimal ∈ ]0.50, 1.00[ → sobe para o inteiro seguinte
      parte decimal ≈ 0 → mantém o inteiro
    """
    try:
        x = float(valor or 0)
    except (TypeError, ValueError):
        return 0.0
    if x <= 0:
        return 0.0
    inteiro = math.floor(x + 1e-9)
    frac = x - inteiro
    if frac <= 0.001:
        return float(inteiro)
    if frac <= 0.50 + 1e-9:
        return float(inteiro) + 0.50
    return float(inteiro + 1)


def carregar_dados_orcamento(pasta=None) -> dict[str, Any]:
    """
    Carrega despesas, receitas (quotas) e frações para o ecrã de orçamento.

    Returns:
        {
          "despesas": [{"conta": str, "corrente": float}, ...],
          "quotas_normais": float,   # total anual corrente
          "quotas_extras": float,
          "fracoes": [{"fracao", "andar", "permilagem", "quota_normal", "quota_extra"}, ...],
        }
    """
    pasta = resolver_pasta(pasta)
    despesas_raw = carregar_despesas(pasta)
    despesas = [
        {"conta": d["conta"], "corrente": float(d["valor"] or 0)}
        for d in despesas_raw
    ]
    qn = float(carregar_quotas_normais(pasta) or 0)
    qe = float(carregar_quotas_extras(pasta) or 0)

    fracoes = []
    try:
        for r in FracoesRepo(pasta).all_ordered():
            keys = r.keys() if hasattr(r, "keys") else []
            qn_f = float(r["quota_normal"] or 0) if "quota_normal" in keys else 0.0
            qe_f = float(r["quota_extra"] or 0) if "quota_extra" in keys else 0.0
            fracoes.append({
                "fracao": str(r["fracao"] or "").strip().upper(),
                "andar": str(r["andar"] or "").strip(),
                "permilagem": float(r["permilagem"] or 0),
                "quota_normal": qn_f,
                "quota_extra": qe_f,
            })
    except Exception as exc:
        print(f"⚠️ orçamento: fracoes: {exc}")

    return {
        "despesas": despesas,
        "quotas_normais": qn,
        "quotas_extras": qe,
        "fracoes": fracoes,
    }


def aplicar_incremento(corrente: float, pct: float) -> float:
    """Aplica percentagem de incremento: corrente * (1 + pct/100)."""
    try:
        c = float(corrente or 0)
        p = float(pct or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(c * (1.0 + p / 100.0), 2)


def projetar_despesas(despesas: list[dict], pct: float) -> list[dict]:
    """Devolve cópia com campo ``projecao`` em cada linha."""
    out = []
    for d in despesas or []:
        c = float(d.get("corrente") or 0)
        out.append({
            "conta": d.get("conta", ""),
            "corrente": c,
            "projecao": aplicar_incremento(c, pct),
        })
    return out


def projetar_total_anual(total_anual_corrente: float, pct: float) -> float:
    """Aplica o incremento a um total anual de quotas (normais ou extras)."""
    return aplicar_incremento(total_anual_corrente, pct)


# Alias legado
projetar_quotas_normais = projetar_total_anual


def calcular_quotas_por_fracao(
    total_normais_projetado: float,
    fracoes: list[dict],
    total_extras_projetado: float = 0.0,
) -> list[dict]:
    """
    Quota mensal por fração (N e E):

      Quota N = arredondar(total_normais_projetado × permilagem / 12)
      Quota E = arredondar(total_extras_projetado × permilagem / 12)
    """
    total_n = float(total_normais_projetado or 0)
    total_e = float(total_extras_projetado or 0)
    resultado = []
    for f in fracoes or []:
        perm = float(f.get("permilagem") or 0)
        bruto_n = (total_n * perm / 12.0) if total_n > 0 and perm > 0 else 0.0
        bruto_e = (total_e * perm / 12.0) if total_e > 0 and perm > 0 else 0.0
        resultado.append({
            "fracao": f.get("fracao", ""),
            "andar": f.get("andar", ""),
            "permilagem": perm,
            "quota_normal": arredondar_quota_mensal(bruto_n),
            "quota_extra": arredondar_quota_mensal(bruto_e),
            "quota_normal_bruta": round(bruto_n, 4),
            "quota_extra_bruta": round(bruto_e, 4),
        })
    return resultado


# ====================================================================
# Proposta de quotas aprovadas (JSON → aplicado no Fim de Ano)
# ====================================================================
import json
from datetime import datetime
from pathlib import Path as _Path

QUOTAS_APROVADAS_NOME = "quotas_aprovadas.json"


def caminho_quotas_aprovadas(pasta=None) -> _Path:
    from Database import resolver_pasta
    return resolver_pasta(pasta) / QUOTAS_APROVADAS_NOME


def gravar_quotas_aprovadas(
    fracoes_calculadas: list[dict],
    *,
    incremento_pct: float,
    incluir_normais: bool,
    incluir_extras: bool,
    total_normais_proj: float,
    total_extras_proj: float,
    exercicio_origem: int | None = None,
    pasta=None,
) -> _Path:
    """
    Grava ``corrente/quotas_aprovadas.json`` com a proposta aprovada.
    Só será aplicada em ``fracoes`` no encerramento de ano.

    ``valor_orcamentado`` = Σ (quota_mensal_arredondada × 12) por fração —
    o montante real a cobrar no ano (não o total teórico antes do arredondamento).
    """
    from Database import resolver_pasta
    from Commons import obter_ano_exercicio

    pasta = resolver_pasta(pasta)
    if exercicio_origem is None:
        try:
            exercicio_origem = int(obter_ano_exercicio(str(pasta)))
        except Exception:
            exercicio_origem = datetime.now().year

    fracoes_out = []
    soma_mensal_n = 0.0
    soma_mensal_e = 0.0
    for f in (fracoes_calculadas or []):
        fr = str(f.get("fracao") or "").strip().upper()
        if not fr:
            continue
        qn = round(float(f.get("quota_normal") or 0), 2)
        qe = round(float(f.get("quota_extra") or 0), 2)
        if not incluir_normais:
            qn = 0.0
        if not incluir_extras:
            qe = 0.0
        soma_mensal_n += qn
        soma_mensal_e += qe
        fracoes_out.append({
            "fracao": fr,
            "quota_normal": qn,
            "quota_extra": qe,
        })

    # Totais anuais reais (após arredondamento mensal)
    total_n_anual = round(soma_mensal_n * 12.0, 2)
    total_e_anual = round(soma_mensal_e * 12.0, 2)
    valor_orcamentado = round(total_n_anual + total_e_anual, 2)

    payload = {
        "aprovado_em": datetime.now().isoformat(timespec="seconds"),
        "exercicio_origem": int(exercicio_origem),
        "exercicio_destino": int(exercicio_origem) + 1,
        "incremento_pct": float(incremento_pct),
        "incluir_normais": bool(incluir_normais),
        "incluir_extras": bool(incluir_extras),
        # Base teórica (antes do arredondamento mensal) — só referência
        "total_normais_proj_base": round(float(total_normais_proj or 0), 2),
        "total_extras_proj_base": round(float(total_extras_proj or 0), 2),
        # Totais reais a cobrar (Σ quotas mensais × 12)
        "total_normais_proj": total_n_anual,
        "total_extras_proj": total_e_anual,
        "valor_orcamentado": valor_orcamentado,
        "fracoes": fracoes_out,
    }
    dest = pasta / QUOTAS_APROVADAS_NOME
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"✓ Quotas aprovadas: {dest} ({len(fracoes_out)} frações) — "
        f"orçamentado {valor_orcamentado:.2f} € "
        f"(base teórica N {float(total_normais_proj or 0):.2f} €)"
    )
    return dest


def ler_quotas_aprovadas(pasta=None) -> dict | None:
    """Lê a proposta; devolve None se não existir ou estiver inválida."""
    path = caminho_quotas_aprovadas(pasta)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("fracoes"):
            return None
        return data
    except Exception as exc:
        print(f"⚠️ ler_quotas_aprovadas: {exc}")
        return None


def estado_proposta_aprovada(pasta=None) -> str:
    """Texto curto para a UI (status)."""
    data = ler_quotas_aprovadas(pasta)
    if not data:
        return "Sem proposta de quotas aprovada."
    return (
        f"Proposta aprovada em {data.get('aprovado_em', '?')} "
        f"(para exercício {data.get('exercicio_destino', '?')}) — "
        f"{len(data.get('fracoes') or [])} fração(ões)."
    )


def aplicar_quotas_aprovadas(pasta=None, novo_ano: int | None = None) -> tuple[bool, str]:
    """
    Aplica ``quotas_aprovadas.json`` à tabela ``fracoes`` do corrente.

    Chamado no Fim de Ano *depois* do backup para historico (as quotas
    antigas ficam no arquivo) e *depois* do commit principal.

    - Se não houver ficheiro: sucesso silencioso (não altera quotas).
    - Se ``exercicio_destino`` ≠ ``novo_ano`` (quando conhecido): não aplica.
    - Após aplicar: move o JSON para ``historico/{exercicio_origem}/``.
    """
    import shutil
    from Database import resolver_pasta, guardar_quota_fracao
    from Commons import BASE_DIR

    pasta = resolver_pasta(pasta)
    path = pasta / QUOTAS_APROVADAS_NOME
    data = ler_quotas_aprovadas(pasta)
    if not data:
        return True, "Sem quotas_aprovadas.json — fracoes inalteradas."

    destino = data.get("exercicio_destino")
    if novo_ano is not None and destino is not None:
        try:
            if int(destino) != int(novo_ano):
                return False, (
                    f"Proposta destinada a {destino}, mas o novo exercício é {novo_ano}. "
                    "Quotas não aplicadas."
                )
        except (TypeError, ValueError):
            pass

    n_ok = 0
    erros = []
    for item in data.get("fracoes") or []:
        fr = str(item.get("fracao") or "").strip().upper()
        if not fr:
            continue
        ok = guardar_quota_fracao(
            fr,
            float(item.get("quota_normal") or 0),
            float(item.get("quota_extra") or 0),
            pasta=pasta,
        )
        if ok:
            n_ok += 1
        else:
            erros.append(fr)

    # Arquivar JSON no historico do ano de origem
    origem_ano = data.get("exercicio_origem")
    try:
        if origem_ano is not None:
            dest_dir = BASE_DIR / "historico" / str(origem_ano)
            dest_dir.mkdir(parents=True, exist_ok=True)
            arquivo = dest_dir / QUOTAS_APROVADAS_NOME
            shutil.copy2(path, arquivo)
            path.unlink(missing_ok=True)
            print(f"  ✓ {QUOTAS_APROVADAS_NOME} arquivado em {arquivo}")
        elif path.exists():
            path.unlink()
    except Exception as exc:
        print(f"  ⚠️ Não foi possível arquivar/remover JSON: {exc}")

    if erros:
        return False, f"Aplicadas {n_ok} frações; falhas: {', '.join(erros)}"
    return True, f"Aplicadas quotas aprovadas a {n_ok} fração(ões)."
