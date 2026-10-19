"""Acompanhamento das candidaturas: em que situação cada vaga está, e o que dá para concluir disso.

A situação fica em `candidatura.json`, na pasta de cada vaga (saidas/<Empresa>_<AAAA-MM>/), junto com o currículo.
Ela é marcada pela pessoa, com um clique. O app só SUGERE "Sem retorno" depois de um tempo, nunca muda sozinho.

Índices de sucesso só com dados suficientes: com poucas candidaturas, qualquer taxa é ruído e qualquer relação com a
aderência pareceria uma conclusão que não é.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config

ARQUIVO = "candidatura.json"
SITUACOES = {
    "gerado": "Gerado, não enviado",
    "enviado": "Enviado",
    "entrevista": "Entrevista",
    "proposta": "Proposta",
    "sem_retorno": "Sem retorno",
    "nao_seguiu": "Não seguiu",
}
# a partir de "enviado", tudo conta como candidatura enviada; entrevista e proposta contam como resposta
ENVIADAS = {"enviado", "entrevista", "proposta", "sem_retorno", "nao_seguiu"}
RESPOSTAS = {"entrevista", "proposta"}
PADROES = {"dias_sem_retorno": 21, "minimo_para_taxas": 5, "minimo_para_relacao": 20}


def regras(cfg: dict | None = None) -> dict:
    cfg = cfg if cfg is not None else config.carregar_config()
    return {**PADROES, **(cfg.get("candidaturas") or {})}


def ler(pasta: Path) -> dict:
    """{"situacao", "enviado_em", "anotacao", "historico": [{"situacao", "data"}]}. Pasta sem arquivo = gerado."""
    try:
        d = json.loads((pasta / ARQUIVO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    situacao = d.get("situacao") if d.get("situacao") in SITUACOES else "gerado"
    return {"situacao": situacao, "enviado_em": d.get("enviado_em") or "", "anotacao": str(d.get("anotacao") or ""),
            "historico": d.get("historico") if isinstance(d.get("historico"), list) else []}


def _gravar(pasta: Path, dados: dict) -> None:
    (pasta / ARQUIVO).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def definir_situacao(pasta: Path, situacao: str, hoje: date | None = None) -> dict:
    if situacao not in SITUACOES:
        raise ValueError(f"Situação desconhecida: {situacao}")
    hoje = hoje or date.today()
    d = ler(pasta)
    if d["situacao"] == situacao:
        return d
    d["situacao"] = situacao
    d["historico"].append({"situacao": situacao, "data": hoje.isoformat()})
    # a data de envio é a primeira vez que a candidatura passou de "gerado"; voltar para "gerado" apaga
    if situacao == "gerado":
        d["enviado_em"] = ""
    elif not d["enviado_em"]:
        d["enviado_em"] = hoje.isoformat()
    _gravar(pasta, d)
    return d


def anotar(pasta: Path, texto: str) -> None:
    d = ler(pasta)
    d["anotacao"] = " ".join(str(texto or "").split())[:500]
    _gravar(pasta, d)


def dias_desde(data_iso: str, hoje: date | None = None) -> int | None:
    try:
        return ((hoje or date.today()) - date.fromisoformat(data_iso)).days
    except ValueError:
        return None


def sugerir_sem_retorno(entradas: list[dict], hoje: date | None = None, cfg: dict | None = None) -> list[dict]:
    """Candidaturas enviadas há mais de N dias, sem nenhuma resposta registrada. Só sugestão."""
    limite = regras(cfg)["dias_sem_retorno"]
    saida = []
    for e in entradas:
        if e.get("situacao") == "enviado":
            dias = dias_desde(e.get("enviado_em", ""), hoje)
            if dias is not None and dias > limite:
                saida.append({**e, "dias": dias})
    return saida


def resumo(entradas: list[dict], cfg: dict | None = None) -> dict:
    """Contagens por situação e, só com dados suficientes, a taxa de resposta e a relação com a aderência."""
    r = regras(cfg)
    vagas = [e for e in entradas if not e.get("geral")]
    contagem = {k: sum(1 for e in vagas if e.get("situacao") == k) for k in SITUACOES}
    enviadas = [e for e in vagas if e.get("situacao") in ENVIADAS]
    respostas = [e for e in enviadas if e.get("situacao") in RESPOSTAS]
    saida = {"contagem": contagem, "enviadas": len(enviadas), "respostas": len(respostas),
             "taxa_resposta": None, "relacao": None, "faltam_para_taxas": max(0, r["minimo_para_taxas"] - len(enviadas)),
             "faltam_para_relacao": max(0, r["minimo_para_relacao"] - len(enviadas))}
    if len(enviadas) >= r["minimo_para_taxas"]:
        saida["taxa_resposta"] = round(100 * len(respostas) / len(enviadas))
    if len(enviadas) >= r["minimo_para_relacao"]:
        com = [e["depois"] for e in respostas if e.get("depois") is not None]
        sem = [e["depois"] for e in enviadas if e not in respostas and e.get("depois") is not None]
        if com and sem:
            saida["relacao"] = {"media_com_resposta": round(sum(com) / len(com)),
                                "media_sem_resposta": round(sum(sem) / len(sem)), "n_com": len(com), "n_sem": len(sem)}
    return saida
