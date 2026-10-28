"""Compara duas rodadas do eval e diz se a segunda piorou algo que importa.

    python -m evals.comparar evals/resultados/base-20261026-1000.json evals/resultados/flash-20261026-1100.json

Regressões (código de saída 1): qualquer armadilha vazada, número sem base ou item sem fonte novo; menos casos aprovados;
aderência média caindo mais de 3 pontos; fidelidade do juiz caindo mais de 0,3. Custo e correções só informam.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LIMITE_ADERENCIA = 3.0
LIMITE_FIDELIDADE = 0.3

# (campo, rótulo, maior é melhor?)
LINHAS = [("aprovados", "Casos aprovados", True), ("armadilhas_vazadas", "Armadilhas vazadas", False),
          ("numeros_sem_base", "Números sem base", False), ("itens_sem_fonte", "Itens sem fonte", False),
          ("aderencia_depois", "Aderência média", True), ("ganho", "Ganho médio sobre o original", True),
          ("paginas", "Páginas (média)", False), ("correcoes", "Correções por caso", False),
          ("alertas", "Alertas por caso", False), ("custo_usd_por_caso", "Custo por caso (US$)", False),
          ("juiz_fidelidade", "Juiz: fidelidade", True), ("juiz_relevancia", "Juiz: relevância", True),
          ("juiz_clareza", "Juiz: clareza", True), ("juiz_traducao", "Juiz: tradução", True),
          ("juiz_afirmacoes_sem_base", "Juiz: afirmações sem base", False)]


def comparar(a: dict, b: dict) -> dict:
    ra, rb = a["resumo"], b["resumo"]
    linhas, regressoes = [], []
    for campo, rotulo, _melhor_maior in LINHAS:
        va, vb = ra.get(campo), rb.get(campo)
        delta = None if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)) else round(vb - va, 4)
        linhas.append({"campo": campo, "rotulo": rotulo, "a": va, "b": vb, "delta": delta})
    for campo in ("armadilhas_vazadas", "numeros_sem_base", "itens_sem_fonte"):
        if (rb.get(campo) or 0) > (ra.get(campo) or 0):
            regressoes.append(f"{campo} subiu de {ra.get(campo)} para {rb.get(campo)}")
    if rb["aprovados"] / max(rb["casos"], 1) < ra["aprovados"] / max(ra["casos"], 1):
        regressoes.append(f"casos aprovados caíram de {ra['aprovados']}/{ra['casos']} para {rb['aprovados']}/{rb['casos']}")
    if isinstance(ra.get("aderencia_depois"), (int, float)) and isinstance(rb.get("aderencia_depois"), (int, float)):
        if ra["aderencia_depois"] - rb["aderencia_depois"] > LIMITE_ADERENCIA:
            regressoes.append(f"aderência média caiu de {ra['aderencia_depois']} para {rb['aderencia_depois']}")
    fa, fb = ra.get("juiz_fidelidade"), rb.get("juiz_fidelidade")
    if isinstance(fa, (int, float)) and isinstance(fb, (int, float)) and fa - fb > LIMITE_FIDELIDADE:
        regressoes.append(f"fidelidade do juiz caiu de {fa} para {fb}")
    return {"linhas": linhas, "regressoes": regressoes}


def formatar(a: dict, b: dict, r: dict) -> str:
    saida = [f"A: {a['rotulo']} ({a['quando']}, etapas {a.get('etapas') or 'modelo padrão'})",
             f"B: {b['rotulo']} ({b['quando']}, etapas {b.get('etapas') or 'modelo padrão'})", "",
             f"{'Métrica':38} {'A':>10} {'B':>10} {'B-A':>10}"]
    for l in r["linhas"]:
        if l["a"] is None and l["b"] is None:
            continue
        d = "" if l["delta"] is None else f"{l['delta']:+.2f}"
        saida.append(f"{l['rotulo']:38} {str(l['a']):>10} {str(l['b']):>10} {d:>10}")
    saida.append("")
    saida += ["REGRESSÕES:"] + [f"- {x}" for x in r["regressoes"]] if r["regressoes"] else ["Sem regressões nas métricas que travam."]
    return "\n".join(saida)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.exit("Uso: python -m evals.comparar rodada_A.json rodada_B.json")
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in argv)
    r = comparar(a, b)
    print(formatar(a, b, r))
    return 1 if r["regressoes"] else 0


if __name__ == "__main__":
    sys.exit(main())
