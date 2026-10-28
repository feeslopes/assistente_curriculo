"""Métricas determinísticas de um currículo gerado. Nenhuma chama a IA."""
from __future__ import annotations

import re
import unicodedata

from src import export

TIPOS_DE_ALERTA = {"numero_sem_base": "Número(s)", "sigla_sem_base": "Sigla(s) ou ferramenta(s)",
                   "sem_fonte": "SEM fato confirmado", "removido_sem_fonte": "Removido de",
                   "titulo_trocado": "título sugerido", "experiencia_fora": "ficou de fora",
                   "fiscal_ia": "verificação por IA"}


def _norma(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


def termo_presente(texto: str, termo: str) -> bool:
    """O termo aparece como palavra inteira (sem confundir 'SAP' com 'sapato')."""
    t, alvo = _norma(texto), _norma(termo)
    if not alvo:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(alvo) + r"(?![a-z0-9])", t) is not None


def classificar_alertas(alertas: list[str]) -> dict[str, int]:
    contagem = {k: 0 for k in TIPOS_DE_ALERTA}
    for a in alertas:
        for k, trecho in TIPOS_DE_ALERTA.items():
            if trecho in a:
                contagem[k] += 1
    contagem["total"] = len(alertas)
    return contagem


def medir(res, caso, max_paginas: int = 2) -> dict:
    """Notas determinísticas de um `tailor.Resultado` para um `Caso`."""
    cv = res.curriculo
    try:
        paginas = export.gerar_pdf(cv.markdown)[1]
    except Exception:  # noqa: BLE001 - o eval segue mesmo se o PDF falhar
        paginas = None
    vazadas = [a for a in caso.armadilhas if termo_presente(cv.corpo, a)]
    alertas = classificar_alertas(cv.alertas)
    ad = res.aderencia or {}
    antes = ad.get("antes", {}).get("total")
    depois = ad.get("depois", {}).get("total")
    cob = res.cobertura or {}
    reprovado = bool(vazadas) or alertas["numero_sem_base"] > 0 or alertas["sem_fonte"] > 0
    return {
        "aprovado": not reprovado and (paginas is None or paginas <= max_paginas),
        "falhas_duras": {"armadilhas_vazadas": vazadas, "numeros_sem_base": alertas["numero_sem_base"],
                         "siglas_sem_base": alertas["sigla_sem_base"], "itens_sem_fonte_mantidos": alertas["sem_fonte"]},
        "paginas": paginas, "max_paginas": max_paginas,
        "aderencia_antes": antes, "aderencia_depois": depois, "aderencia_teto": ad.get("depois", {}).get("teto"),
        "ganho": None if antes is None or depois is None else depois - antes,
        "abaixo_do_original": bool(res.abaixo_do_original),
        "palavras_usadas": len(cob.get("usadas", [])),
        "palavras_fora_sem_base": len(cob.get("fora_sem_base", [])),
        "alertas": alertas, "itens_removidos": len(cv.removidos),
        "correcoes": list(res.correcoes), "n_correcoes": len(res.correcoes),
        "segunda_tentativa": bool(res.segunda_tentativa), "condensada": bool(res.condensada),
    }
