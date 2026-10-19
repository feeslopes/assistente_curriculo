"""Histórico das vagas já geradas (pastas em saidas/) e das lacunas que se repetem entre elas."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from . import config
from .texto import normalizar

ARQUIVO_INDICE = "indice.json"


def dados_do_indice(analise: dict, comparacao: dict) -> dict:
    """O que fica salvo ao lado do currículo para o histórico (sem texto do currículo nem da vaga)."""
    antes, depois = comparacao["antes"], comparacao["depois"]
    det = (depois["componentes"].get("palavras") or {}).get("detalhe", {})
    return {
        "empresa": analise.get("empresa", ""), "titulo_vaga": analise.get("titulo_vaga", ""),
        "idioma": comparacao["idioma_depois"],
        "antes": antes["total"], "depois": depois["total"], "teto": depois["teto"],
        "estimado": bool(antes.get("estimado") or depois.get("estimado")),
        "componentes": {k: {"antes": antes["componentes"].get(k, {}).get("pontos"), "depois": c["pontos"],
                            "peso": c["peso"]} for k, c in depois["componentes"].items()},
        "palavras_sem_base": det.get("sem_base", []),
    }


def _ler_json(caminho: Path) -> dict:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _primeiro(pasta: Path, nome: str, ext: str) -> Path | None:
    """O arquivo do currículo: o nome registrado no índice, senão o primeiro com a extensão."""
    alvo = pasta / f"{nome}{ext}"
    if alvo.exists():
        return alvo
    return next(iter(sorted(pasta.glob(f"*{ext}"))), None)


def listar(raiz: Path | None = None) -> list[dict]:
    """Vagas salvas, da mais recente para a mais antiga. Pasta sem análise é ignorada."""
    raiz = raiz or config.saidas_dir()
    if not raiz.is_dir():
        return []
    saida = []
    pastas = [p for p in raiz.iterdir() if p.is_dir() and (p / "analise.json").exists()]
    # a mais recente primeiro, pela última gravação (o nome da pasta não começa mais pela data)
    for p in sorted(pastas, key=lambda p: (p / "analise.json").stat().st_mtime, reverse=True):
        analise, idx = _ler_json(p / "analise.json"), _ler_json(p / ARQUIVO_INDICE)
        if idx.get("data"):
            data = str(idx["data"])
        elif re.match(r"\d{4}-\d{2}-\d{2}", p.name):     # pastas do formato antigo: data-empresa-vaga
            data = p.name[:10]
        else:
            data = date.fromtimestamp((p / "analise.json").stat().st_mtime).isoformat()
        arquivo = idx.get("arquivo") or "curriculo"
        saida.append({
            "pasta": p, "nome": p.name, "data": data, "arquivo": arquivo,
            "pdf": _primeiro(p, arquivo, ".pdf"), "docx": _primeiro(p, arquivo, ".docx"),
            "empresa": analise.get("empresa") or idx.get("empresa", ""),
            "titulo_vaga": analise.get("titulo_vaga") or idx.get("titulo_vaga", ""),
            "idioma": idx.get("idioma", ""),
            "antes": idx.get("antes"), "depois": idx.get("depois"), "teto": idx.get("teto"),
            "estimado": bool(idx.get("estimado")), "componentes": idx.get("componentes", {}),
            "tem_indice": "depois" in idx,
            "analise": analise,
        })
    return saida


def lacunas_recorrentes(entradas: list[dict], minimo: int = 2) -> dict:
    """O que a base não sustenta em várias vagas: onde confirmar um fato verdadeiro rende mais.

    Conta cada termo no máximo uma vez por vaga. Só entram análises que registraram `palavras_chave_base`
    (as antigas não dizem o que a base sustentava, então não dá para saber o que era lacuna).
    """
    palavras: Counter = Counter()
    requisitos: Counter = Counter()
    original: dict[str, str] = {}
    for e in entradas:
        a = e.get("analise") or {}
        if "palavras_chave_base" in a:
            sustentadas = {normalizar(x["termo"]) for x in a["palavras_chave_base"]}
            vistas: set[str] = set()
            for k in a.get("palavras_chave", []):
                n = normalizar(k)
                if n and n not in sustentadas and n not in vistas:
                    vistas.add(n)
                    palavras[n] += 1
                    original.setdefault(n, k)
        for r in a.get("requisitos", []):
            if r.get("status") == "lacuna" and r.get("tipo") == "obrigatorio":
                n = normalizar(r.get("termo_na_vaga") or r.get("requisito", ""))
                if n:
                    requisitos[n] += 1
                    original.setdefault(n, r.get("termo_na_vaga") or r["requisito"])
    pegar = lambda c: [(original[k], n) for k, n in c.most_common() if n >= minimo]
    return {"palavras": pegar(palavras), "requisitos": pegar(requisitos), "vagas": len(entradas)}
