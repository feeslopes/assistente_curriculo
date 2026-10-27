"""Roda o conjunto de casos com a IA de verdade e grava notas, tokens e custo.

    python -m evals.rodar --rotulo base
    python -m evals.rodar --rotulo flash --etapas analisador=deepseek-flash,verificador=deepseek-flash --juiz
    python -m evals.rodar --casos fin-armadilha-pt,mkt-armadilha-en --rotulo so-armadilhas

Usa o provedor e a chave do .env (não imprime a chave). Os currículos gerados ficam no JSON de resultado, que o Git ignora.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
from datetime import datetime
from pathlib import Path

from src import config, custo, tailor
from src.kb import KB
from src.llm import LLM, Configuracao

from . import casos as casos_mod
from . import juiz as juiz_mod
from . import metricas

RESULTADOS = Path(__file__).resolve().parent / "resultados"


class Coletor:
    """Soma tokens e custo por etapa. É o `ao_usar` do LLM."""

    def __init__(self):
        self.por_etapa: dict[str, dict] = {}

    def __call__(self, info: dict) -> None:
        e = self.por_etapa.setdefault(info["rotulo"] or "sem_rotulo", {"chamadas": 0, "entrada": 0, "saida": 0, "custo_usd": 0.0,
                                                                        "modelos": set()})
        e["chamadas"] += 1
        e["entrada"] += info["uso"]["entrada"]
        e["saida"] += info["uso"]["saida"]
        e["custo_usd"] += info["custo_usd"] or 0.0
        e["modelos"].add(info["modelo"])

    def resumo(self) -> dict:
        etapas = {k: {**v, "modelos": sorted(v["modelos"]), "custo_usd": round(v["custo_usd"], 6)} for k, v in self.por_etapa.items()}
        return {"etapas": etapas, "chamadas": sum(v["chamadas"] for v in etapas.values()),
                "entrada": sum(v["entrada"] for v in etapas.values()), "saida": sum(v["saida"] for v in etapas.values()),
                "custo_usd": round(sum(v["custo_usd"] for v in etapas.values()), 6)}


def rodar_caso(llm, caso, coletor: Coletor, juiz_llm=None, cfg: dict | None = None) -> dict:
    """Um caso de ponta a ponta: copia a base, analisa a vaga, gera, mede e (opcional) julga."""
    cfg = cfg or config.carregar_config()
    tmp = Path(tempfile.mkdtemp())
    try:
        destino = tmp / "base"
        shutil.copytree(casos_mod.BASES[caso.base], destino)
        kb = KB(destino)
        if hasattr(llm, "definir_segredos"):
            llm.definir_segredos(kb.segredos())
        antes = coletor.resumo()
        analise = tailor.analisar(llm, kb, caso.texto_vaga)
        res = tailor.gerar(llm, kb, caso.texto_vaga, analise, caso.idioma, cfg)
        medidas = metricas.medir(res, caso, int(cfg.get("max_paginas", 2)))
        julgamento = juiz_mod.julgar(juiz_llm, kb, caso, res.curriculo.markdown) if juiz_llm else None
        depois = coletor.resumo()
        return {"caso": caso.id, "base": caso.base, "idioma": caso.idioma, "metricas": medidas, "juiz": julgamento,
                "custo_usd": round(depois["custo_usd"] - antes["custo_usd"], 6),
                "tokens": {"entrada": depois["entrada"] - antes["entrada"], "saida": depois["saida"] - antes["saida"]},
                "markdown": res.curriculo.markdown}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _media(valores) -> float | None:
    v = [x for x in valores if isinstance(x, (int, float))]
    return round(statistics.fmean(v), 2) if v else None


def resumir(resultados: list[dict]) -> dict:
    ms = [r["metricas"] for r in resultados]
    juizes = [r["juiz"] for r in resultados if r.get("juiz")]
    resumo = {
        "casos": len(resultados), "aprovados": sum(1 for m in ms if m["aprovado"]),
        "armadilhas_vazadas": sum(len(m["falhas_duras"]["armadilhas_vazadas"]) for m in ms),
        "numeros_sem_base": sum(m["falhas_duras"]["numeros_sem_base"] for m in ms),
        "itens_sem_fonte": sum(m["falhas_duras"]["itens_sem_fonte_mantidos"] for m in ms),
        "aderencia_depois": _media(m["aderencia_depois"] for m in ms), "ganho": _media(m["ganho"] for m in ms),
        "paginas": _media(m["paginas"] for m in ms), "correcoes": _media(m["n_correcoes"] for m in ms),
        "alertas": _media(m["alertas"]["total"] for m in ms),
        "custo_usd": round(sum(r["custo_usd"] for r in resultados), 6),
        "custo_usd_por_caso": _media(r["custo_usd"] for r in resultados),
    }
    for campo in juiz_mod.CAMPOS:
        resumo[f"juiz_{campo}"] = _media(j.get(campo) for j in juizes)
    resumo["juiz_afirmacoes_sem_base"] = sum(len(j.get("afirmacoes_sem_base", [])) for j in juizes) if juizes else None
    return resumo


def _etapas(texto: str) -> dict[str, str]:
    saida = {}
    for par in filter(None, (p.strip() for p in (texto or "").split(","))):
        if "=" not in par:
            raise SystemExit(f"--etapas espera etapa=modelo, recebi '{par}'.")
        k, v = par.split("=", 1)
        saida[k.strip()] = v.strip()
    return saida


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rotulo", default="rodada", help="nome da rodada, usado no arquivo de resultado")
    ap.add_argument("--casos", help="ids separados por vírgula (padrão: todos)")
    ap.add_argument("--etapas", default="", help="modelo por etapa, ex.: analisador=deepseek-flash,verificador=deepseek-flash")
    ap.add_argument("--juiz", action="store_true", help="liga o juiz de IA (custa uma chamada extra por caso)")
    ap.add_argument("--juiz-modelo", default="deepseek-flash")
    a = ap.parse_args(argv)

    config.carregar_env()
    cfg_llm = Configuracao.do_ambiente()
    etapas = _etapas(a.etapas) or config.modelos_por_etapa()
    escolhidos = casos_mod.selecionar([c.strip() for c in a.casos.split(",")] if a.casos else None)
    coletor = Coletor()
    llm = LLM(cfg_llm, modelos_por_etapa=etapas, ao_usar=coletor)
    juiz_llm = LLM(cfg_llm, modelos_por_etapa={"juiz": a.juiz_modelo}, ao_usar=coletor) if a.juiz else None
    cfg = config.carregar_config()

    resultados = []
    for caso in escolhidos:
        print(f"[{caso.id}] rodando...", flush=True)
        r = rodar_caso(llm, caso, coletor, juiz_llm, cfg)
        resultados.append(r)
        m = r["metricas"]
        print(f"[{caso.id}] {'OK' if m['aprovado'] else 'FALHOU'}  aderência {m['aderencia_antes']}->{m['aderencia_depois']}  "
              f"páginas {m['paginas']}  correções {m['n_correcoes']}  custo US$ {r['custo_usd']:.4f}", flush=True)

    saida = {"rotulo": a.rotulo, "quando": datetime.now().isoformat(timespec="seconds"), "modelo_padrao": cfg_llm.modelo,
             "etapas": etapas, "cambio_brl": custo.cambio(), "resumo": resumir(resultados), "uso": coletor.resumo(),
             "casos": resultados}
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    arquivo = RESULTADOS / f"{a.rotulo}-{datetime.now():%Y%m%d-%H%M}.json"
    arquivo.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(saida["resumo"], ensure_ascii=False, indent=1))
    print(f"Gravado em {arquivo}")


if __name__ == "__main__":
    main()
