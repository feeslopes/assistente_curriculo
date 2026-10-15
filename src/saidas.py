"""Gravação dos currículos gerados em saidas/<data>-<empresa>-<vaga>/."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config
from .texto import slugify


def pasta_da_saida(empresa: str, titulo_vaga: str, raiz: Path | None = None) -> Path:
    raiz = raiz or config.saidas_dir()
    nome = "-".join(p for p in (date.today().isoformat(), slugify(empresa) if empresa else "",
                                slugify(titulo_vaga) if titulo_vaga else "") if p)[:90].rstrip("-")
    pasta, i = raiz / nome, 2
    while pasta.exists():
        pasta, i = raiz / f"{nome}-{i}", i + 1
    return pasta


def salvar_saida(markdown: str, pdf: bytes, docx: bytes, vaga: str, analise: dict,
                 raiz: Path | None = None, relatorio: str | None = None, indice: dict | None = None) -> Path:
    """Grava o currículo (MD, PDF, DOCX) junto com a vaga e a análise. Devolve a pasta criada."""
    pasta = pasta_da_saida(analise.get("empresa", ""), analise.get("titulo_vaga", ""), raiz)
    pasta.mkdir(parents=True)
    (pasta / "curriculo.md").write_text(markdown, encoding="utf-8", newline="\n")
    (pasta / "curriculo.pdf").write_bytes(pdf)
    (pasta / "curriculo.docx").write_bytes(docx)
    (pasta / "vaga.txt").write_text(vaga, encoding="utf-8", newline="\n")
    (pasta / "analise.json").write_text(json.dumps(analise, ensure_ascii=False, indent=1), encoding="utf-8")
    if indice:
        (pasta / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    if relatorio:
        (pasta / "relatorio.md").write_text(relatorio, encoding="utf-8", newline="\n")
    return pasta
