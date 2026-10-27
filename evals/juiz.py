"""Juiz de IA: nota fidelidade, relevância, clareza e tradução contra os fatos confirmados.

Use um modelo DIFERENTE do gerador (padrão: deepseek-flash) e calibre contra notas humanas (evals/calibracao.md) antes de
confiar nos números. As métricas determinísticas continuam sendo a trava; o juiz mostra o que o código não enxerga.
"""
from __future__ import annotations

from pathlib import Path

from src.llm import completar_json

PROMPT = Path(__file__).resolve().parent / "prompts" / "juiz.md"
CAMPOS = ("fidelidade", "relevancia", "clareza", "traducao")


def julgar(llm, kb, caso, markdown: str) -> dict:
    usuario = (f"## Idioma de saída\n{caso.idioma}\n\n## Vaga\n{caso.texto_vaga.strip()}\n\n"
               f"## Fatos confirmados\n{kb.para_prompt()}\n\n## Currículo gerado\n{markdown}")
    bruto = completar_json(llm, [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                                 {"role": "user", "content": usuario}], temperatura=0.0, rotulo="juiz")
    if not isinstance(bruto, dict):
        bruto = {}
    nota = {}
    for c in CAMPOS:
        try:
            v = int(bruto.get(c))
            nota[c] = v if 1 <= v <= 5 else None
        except (TypeError, ValueError):
            nota[c] = None
    sem_base = [str(x)[:300] for x in (bruto.get("afirmacoes_sem_base") or [])]
    return {**nota, "afirmacoes_sem_base": sem_base, "comentario": str(bruto.get("comentario", ""))[:300]}
