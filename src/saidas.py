"""Gravação dos currículos gerados em saidas/<Empresa>_<AAAA-MM>/.

Uma pasta por candidatura, com nome fácil de achar no explorador de arquivos. Dentro dela, o currículo com o nome
da pessoa no arquivo (é o que o recrutador vê ao baixar), a vaga, a análise, o relatório e o índice.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import config

_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def limpar_nome(texto: str, limite: int = 60) -> str:
    """Nome seguro para pasta ou arquivo no Windows e no Linux, mantendo acentos e espaços."""
    t = " ".join(_PROIBIDOS.sub(" ", str(texto or "")).split())
    return t[:limite].strip(" .")


def pasta_da_saida(empresa: str, titulo_vaga: str, raiz: Path | None = None, hoje: date | None = None) -> Path:
    """saidas/<Empresa>_<AAAA-MM>. Outra vaga na mesma empresa e no mesmo mês ganha o título no nome."""
    raiz = raiz or config.saidas_dir()
    mes = (hoje or date.today()).strftime("%Y-%m")
    emp = limpar_nome(empresa) or "Vaga sem empresa"
    pasta = raiz / f"{emp}_{mes}"
    if not pasta.exists():
        return pasta
    vaga = limpar_nome(titulo_vaga, 40) or "vaga"
    pasta, i = raiz / f"{emp}_{mes}_{vaga}", 2
    while pasta.exists():
        pasta, i = raiz / f"{emp}_{mes}_{vaga}_{i}", i + 1
    return pasta


def nome_do_arquivo(nome_pessoa: str, idioma: str = "pt") -> str:
    """Curriculo_Nome_Sobrenome (e _EN quando em inglês), sem extensão."""
    nome = limpar_nome(nome_pessoa).replace(" ", "_")
    return "Curriculo" + (f"_{nome}" if nome else "") + ("_EN" if idioma == "en" else "")


def salvar_saida(markdown: str, pdf: bytes, docx: bytes, vaga: str, analise: dict,
                 raiz: Path | None = None, relatorio: str | None = None, indice: dict | None = None,
                 pasta: Path | None = None, nome_arquivo: str = "curriculo") -> Path:
    """Grava o currículo (MD, PDF, DOCX) junto com a vaga e a análise. Devolve a pasta.

    Com `pasta`, grava por cima nessa pasta (gerar de novo para a mesma vaga não cria outra candidatura).
    """
    empresa = "Geral" if analise.get("geral") else analise.get("empresa", "")   # currículo geral: Geral_AAAA-MM
    pasta = pasta or pasta_da_saida(empresa, analise.get("titulo_vaga", ""), raiz)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome_arquivo}.md").write_text(markdown, encoding="utf-8", newline="\n")
    (pasta / f"{nome_arquivo}.pdf").write_bytes(pdf)
    (pasta / f"{nome_arquivo}.docx").write_bytes(docx)
    (pasta / "vaga.txt").write_text(vaga, encoding="utf-8", newline="\n")
    (pasta / "analise.json").write_text(json.dumps(analise, ensure_ascii=False, indent=1), encoding="utf-8")
    if indice:
        dados = {**indice, "data": date.today().isoformat(), "arquivo": nome_arquivo}
        (pasta / "indice.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    if relatorio:
        (pasta / "relatorio.md").write_text(relatorio, encoding="utf-8", newline="\n")
    return pasta
