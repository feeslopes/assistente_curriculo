"""Custo estimado das chamadas à IA, a partir dos tokens que o provedor informa.

Preços do DeepSeek por 1M de tokens em US$, no horário fora do pico (https://api-docs.deepseek.com/quick_start/pricing,
lidos em 26/10/2026). No pico o preço é o dobro. Pico: 01h-04h e 06h-10h UTC, de segunda a sexta. A página também diz
"exceto feriados chineses", que não tratamos: o custo estimado fica um pouco acima do real nesses dias.

É estimativa para decidir preço e teto de uso. A fatura do provedor é a referência.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

# modelo -> (entrada com cache hit, entrada com cache miss, saída), em US$ por 1M de tokens, fora do pico
PRECOS_FORA_DO_PICO = {
    "deepseek-v4-pro": (0.022, 0.66, 1.98),
    "deepseek-flash": (0.003, 0.15, 0.60),
}
# Nomes antigos são cobrados como o Flash.
ALIASES = {"deepseek-v4-flash": "deepseek-flash", "deepseek-v4-flash-vision-exp": "deepseek-flash"}

CAMBIO_PADRAO = 5.5  # R$ por US$, placeholder: ajuste com CV_CAMBIO_BRL no .env


def cambio() -> float:
    try:
        v = float(os.environ.get("CV_CAMBIO_BRL", "").replace(",", "."))
        return v if v > 0 else CAMBIO_PADRAO
    except ValueError:
        return CAMBIO_PADRAO


def em_pico(quando: datetime | None = None) -> bool:
    q = (quando or datetime.now(timezone.utc))
    q = q.astimezone(timezone.utc) if q.tzinfo else q.replace(tzinfo=timezone.utc)
    return q.weekday() < 5 and (1 <= q.hour < 4 or 6 <= q.hour < 10)


def normalizar_uso(uso: dict | None) -> dict:
    """Tokens de entrada (com cache hit e miss) e de saída, a partir do campo `usage` da resposta."""
    uso = uso if isinstance(uso, dict) else {}

    def n(chave: str) -> int:
        try:
            return max(int(uso.get(chave) or 0), 0)
        except (TypeError, ValueError):
            return 0

    entrada = n("prompt_tokens")
    hit = n("prompt_cache_hit_tokens")
    miss = n("prompt_cache_miss_tokens")
    if hit + miss == 0:
        miss = entrada          # provedor sem informação de cache: tudo como miss (estimativa para cima)
    elif entrada == 0:
        entrada = hit + miss
    return {"entrada": entrada, "cache_hit": hit, "cache_miss": miss, "saida": n("completion_tokens")}


def custo_usd(modelo: str, uso: dict | None, quando: datetime | None = None) -> float | None:
    """Custo em US$, ou None se o modelo não tem preço conhecido (outro provedor)."""
    precos = PRECOS_FORA_DO_PICO.get(ALIASES.get(modelo, modelo))
    if not precos:
        return None
    u = normalizar_uso(uso)
    hit_p, miss_p, saida_p = precos
    total = (u["cache_hit"] * hit_p + u["cache_miss"] * miss_p + u["saida"] * saida_p) / 1_000_000
    return total * (2 if em_pico(quando) else 1)


def custo_brl(modelo: str, uso: dict | None, quando: datetime | None = None) -> float | None:
    c = custo_usd(modelo, uso, quando)
    return None if c is None else c * cambio()
