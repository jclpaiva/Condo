"""
Quotas.py — Matemática partilhada de classificação de quotas (v1.01)

Contrato
--------
- **Bancos** classifica cada movimento do extracto (CONTA + OBSERVACAO).
- **Receitas** agrega por fracção+mês e reparte Normal/Extra no quadro.

Ambos usam ``decompor_valor_quota`` para a fórmula:

    valor ≈ a × quota_normal + b × quota_extra   (a, b inteiros ≥ 0)

Prioridade de soluções exactas (dentro de ``tol``):
  1. menor erro absoluto
  2. meses iguais (a==b) > só extra > só normal > misto
  3. menos parcelas (a+b)

Valores de quota vêm sempre da tabela ``condominos`` (nunca adivinhados).
Não altera regras de match de nomes no extracto (isso fica em Bancos / regras).
"""
from __future__ import annotations

from typing import NamedTuple


class DecomposicaoQuota(NamedTuple):
    """Resultado da decomposição de um valor em normal + extra."""
    parte_normal: float
    parte_extra: float
    n_normal: int          # meses (parcelas) de quota normal
    n_extra: int           # meses (parcelas) de quota extra
    tipo: str              # NORMAL | EXTRA | TOTAL | MISTO | INDEFINIDO
    exacta: bool           # True se encontrou solução dentro de tol


def decompor_valor_quota(
    valor,
    v_norm,
    v_extra,
    tol: float = 0.05,
) -> DecomposicaoQuota:
    """
    Decompõe ``valor`` em a×normal + b×extra.

    Returns:
        DecomposicaoQuota com partes monetárias e tipo.
        Se não houver solução exacta, ``exacta=False`` e as partes são 0
        (o chamador decide o fallback — ex. proporção em Receitas).
    """
    try:
        valor = abs(float(valor))
    except (TypeError, ValueError):
        valor = 0.0
    try:
        v_norm = float(v_norm or 0)
    except (TypeError, ValueError):
        v_norm = 0.0
    try:
        v_extra = float(v_extra or 0)
    except (TypeError, ValueError):
        v_extra = 0.0

    if valor < 0.005:
        return DecomposicaoQuota(0.0, 0.0, 0, 0, "INDEFINIDO", False)

    unidades = [u for u in (v_norm, v_extra) if u > 0.005]
    if not unidades:
        return DecomposicaoQuota(0.0, 0.0, 0, 0, "INDEFINIDO", False)

    max_m = min(24, int(valor / min(unidades)) + 2)
    candidatos: list[tuple] = []  # (err, prio, a+b, a, b, tn, te, tipo)

    for a in range(0, max_m + 1):
        for b in range(0, max_m + 1):
            if a == 0 and b == 0:
                continue
            esperado = a * v_norm + b * v_extra
            err = abs(valor - esperado)
            if err > tol:
                continue

            tn = round(a * v_norm, 2)
            te = round(b * v_extra, 2)

            if a > 0 and b > 0:
                tipo = "TOTAL" if a == b else "MISTO"
                prio = 0 if a == b else 1
            elif b > 0:
                tipo = "EXTRA"
                prio = 2
            else:
                tipo = "NORMAL"
                prio = 3

            candidatos.append((err, prio, a + b, a, b, tn, te, tipo))

    if not candidatos:
        return DecomposicaoQuota(0.0, 0.0, 0, 0, "INDEFINIDO", False)

    candidatos.sort()
    _, _, _, a, b, tn, te, tipo = candidatos[0]
    return DecomposicaoQuota(tn, te, a, b, tipo, True)


def classificar_valor_quota(valor, v_norm, v_extra, conta_base, tol: float = 0.05):
    """
    Wrapper para Bancos: devolve (CONTA, OBSERVACAO) a partir da decomposição.

    Mantém o mesmo contrato que a função original em Bancos.py.
    """
    conta_base = (conta_base or "").strip() or "?"
    d = decompor_valor_quota(valor, v_norm, v_extra, tol=tol)

    if d.exacta:
        if d.tipo in ("TOTAL", "MISTO"):
            conta = f"Quota TOTAL - {conta_base}"
            if d.n_normal == 1 and d.n_extra == 1:
                obs = f"Normal({d.parte_normal:.2f})+Extra({d.parte_extra:.2f})"
            else:
                obs = (
                    f"{d.n_normal}Normal({d.parte_normal:.2f})"
                    f"+{d.n_extra}Extra({d.parte_extra:.2f})"
                )
            return conta, obs
        if d.tipo == "EXTRA":
            conta = f"Quota extra - {conta_base}"
            obs = (
                f"{d.n_extra}Extra({d.parte_extra:.2f})"
                if d.n_extra >= 2
                else ""
            )
            return conta, obs
        # NORMAL
        conta = f"Quota - {conta_base}"
        obs = (
            f"{d.n_normal}Normal({d.parte_normal:.2f})"
            if d.n_normal >= 2
            else ""
        )
        return conta, obs

    # Sem decomposição exacta: mesma heurística que Bancos (nunca deixar vazio)
    try:
        valor_f = abs(float(valor))
    except (TypeError, ValueError):
        valor_f = 0.0
    try:
        v_norm_f = float(v_norm or 0)
    except (TypeError, ValueError):
        v_norm_f = 0.0
    try:
        v_extra_f = float(v_extra or 0)
    except (TypeError, ValueError):
        v_extra_f = 0.0

    if valor_f < 0.005:
        return f"Quota - {conta_base}", ""
    if v_extra_f > 0 and valor_f < v_extra_f - tol:
        return f"Quota - {conta_base}", ""
    if v_norm_f > 0 and v_extra_f <= 0:
        return f"Quota - {conta_base}", ""
    return f"Quota extra - {conta_base}", ""


def repartir_para_mapas(valor, v_norm, v_extra, tol: float = 0.05):
    """
    Para Receitas: devolve (parte_normal, parte_extra, etiqueta_log).

    Se a decomposição exacta falhar e houver total > 0, aplica proporção
    (comportamento legado de Receitas.processar_receitas_simplificado).
    """
    d = decompor_valor_quota(valor, v_norm, v_extra, tol=tol)
    if d.exacta:
        if d.tipo == "NORMAL":
            label = f"NORMAL ({d.parte_normal:.2f})"
        elif d.tipo == "EXTRA":
            label = f"EXTRA ({d.parte_extra:.2f})"
        elif d.tipo == "TOTAL":
            n = d.n_normal
            if n >= 2:
                label = f"{n}x TOTAL = {n}x Normal + {n}x Extra"
            else:
                label = (
                    f"TOTAL ({d.parte_normal + d.parte_extra:.2f}) "
                    f"= Normal + Extra"
                )
        else:  # MISTO
            label = (
                f"MISTO {d.n_normal}N+{d.n_extra}E "
                f"(N={d.parte_normal:.2f}, E={d.parte_extra:.2f})"
            )
        return d.parte_normal, d.parte_extra, label

    # Fallback proporcional (legado Receitas)
    try:
        valor_f = abs(float(valor))
        qn = float(v_norm or 0)
        qe = float(v_extra or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0, "INDEFINIDO"
    qt = qn + qe
    if qt > 0.005 and valor_f > 0.005:
        pn = round(valor_f * (qn / qt), 2)
        pe = round(valor_f * (qe / qt), 2)
        return pn, pe, f"Proporção N={pn:.2f}, E={pe:.2f}"
    return 0.0, 0.0, "INDEFINIDO"
