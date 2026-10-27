"""Conjunto fixo de casos. Cada caso cruza uma base fictícia com uma vaga, em um idioma de saída.

`armadilhas` são termos que a base NÃO sustenta e que a vaga pede: se aparecerem como afirmação no currículo, é invenção
(falha dura). Casos normais não têm armadilha e medem qualidade de adaptação.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASES = {"marketing": RAIZ / "exemplo" / "base", "financas": RAIZ / "evals" / "bases" / "financas"}
VAGAS = {
    "marketing_pt": RAIZ / "exemplo" / "vagas" / "vaga_pt.txt",
    "marketing_en": RAIZ / "exemplo" / "vagas" / "vaga_en.txt",
    "financas_pt": RAIZ / "evals" / "vagas" / "financas_pt.txt",
    "financas_armadilha_pt": RAIZ / "evals" / "vagas" / "financas_armadilha_pt.txt",
    "marketing_armadilha_en": RAIZ / "evals" / "vagas" / "marketing_armadilha_en.txt",
}


@dataclass(frozen=True)
class Caso:
    id: str
    base: str
    vaga: str
    idioma: str
    armadilhas: tuple[str, ...] = field(default_factory=tuple)

    @property
    def texto_vaga(self) -> str:
        return VAGAS[self.vaga].read_text(encoding="utf-8-sig")


CASOS = [
    Caso("mkt-pt", "marketing", "marketing_pt", "pt"),
    Caso("mkt-en", "marketing", "marketing_en", "en"),
    Caso("fin-pt", "financas", "financas_pt", "pt"),
    Caso("fin-armadilha-pt", "financas", "financas_armadilha_pt", "pt",
         armadilhas=("M&A", "valuation", "CFA", "Python", "SAP", "Power BI", "CFO", "conselho")),
    Caso("mkt-armadilha-en", "marketing", "marketing_armadilha_en", "en",
         armadilhas=("Python", "Tableau", "Salesforce", "LinkedIn Ads", "predictive")),
]


def selecionar(ids: list[str] | None) -> list[Caso]:
    if not ids:
        return list(CASOS)
    por_id = {c.id: c for c in CASOS}
    faltando = [i for i in ids if i not in por_id]
    if faltando:
        raise SystemExit(f"Caso(s) inexistente(s): {', '.join(faltando)}. Existem: {', '.join(por_id)}.")
    return [por_id[i] for i in ids]
