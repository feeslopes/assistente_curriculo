"""Relatório da adaptação: como o currículo foi escrito para esta vaga.

O que o código consegue provar vem do código: o encaixe com a vaga, o fato de origem de cada bullet ao lado do
texto final, e quais palavras-chave da vaga entraram onde. A estratégia em linguagem natural vem do gerador
(campo `adaptacao`) e é mostrada rotulada como explicação da IA: ela não entra no currículo.
"""
from __future__ import annotations

from .kb import KB
from .verify import contem_termo

MAX_MUDANCAS = 12


def _linhas_da_secao(corpo: str, titulo: str) -> list[str]:
    linhas, dentro = [], False
    for l in corpo.splitlines():
        if l.startswith("## "):
            dentro = l[3:].strip() == titulo
            continue
        if dentro and l.strip():
            linhas.append(l.strip().removeprefix("* ").strip())
    return linhas


def _texto(valor, limite: int = 400) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _adaptacao_da_ia(bruto: dict) -> dict:
    """Explicação escrita pelo gerador, saneada. Nunca é usada como fonte de nada."""
    a = bruto.get("adaptacao") if isinstance(bruto, dict) else None
    if not isinstance(a, dict):
        return {"estrategia": "", "mudancas": [], "deixou_de_fora": []}
    mudancas = []
    for m in (a.get("mudancas") or [])[:MAX_MUDANCAS]:
        if isinstance(m, dict) and _texto(m.get("o_que")):
            mudancas.append({"onde": _texto(m.get("onde"), 80), "o_que": _texto(m.get("o_que")),
                             "motivo": _texto(m.get("motivo"))})
    fora = [_texto(x) for x in (a.get("deixou_de_fora") or []) if _texto(x)][:MAX_MUDANCAS]
    return {"estrategia": _texto(a.get("estrategia"), 900), "mudancas": mudancas, "deixou_de_fora": fora}


def montar(kb: KB, analise: dict, resultado, cfg: dict, idioma: str) -> dict:
    """Monta o relatório. `resultado` é um tailor.Resultado (curriculo, cobertura, gerado_bruto, limites)."""
    cv, cob = resultado.curriculo, resultado.cobertura
    palavras = analise.get("palavras_chave", [])
    reqs = analise.get("requisitos", [])

    def contagem(tipo: str) -> dict:
        d = {"total": 0, "coberto": 0, "parcial": 0, "lacuna": 0}
        for r in reqs:
            if r["tipo"] == tipo:
                d["total"] += 1
                d[r["status"]] += 1
        return d

    usadas = len(cob["usadas"])
    total_pal = sum(len(cob[k]) for k in ("usadas", "usadas_sem_base", "usadas_indeterminadas", "fora_com_base",
                                          "fora_sem_base", "fora_indeterminadas"))
    encaixe = {
        "obrigatorios": contagem("obrigatorio"), "desejaveis": contagem("desejavel"),
        "palavras": {"usadas": usadas, "total": total_pal, "percentual": cob["percentual"]},
        "lacunas_obrigatorias": [r["requisito"] for r in reqs if r["tipo"] == "obrigatorio" and r["status"] == "lacuna"],
        "parciais_obrigatorias": [r["requisito"] for r in reqs if r["tipo"] == "obrigatorio" and r["status"] == "parcial"],
    }

    titulos = cfg["titulos_secoes"][idioma]
    resumo_txt = " ".join(_linhas_da_secao(cv.corpo, titulos["resumo"]))
    competencias = [{"linha": l, "palavras": [p for p in palavras if contem_termo(l, p)]}
                    for l in _linhas_da_secao(cv.corpo, titulos["competencias"])]

    texto_por_id = {f.id: f.texto for f in kb.fatos("confirmado")}
    experiencias = []
    for e in kb.experiencias():
        itens = []
        for r in cv.rastro:
            if (r["secao"].startswith("experiência") and r["fontes_validas"] and r["texto"] in cv.markdown
                    and r["fontes_validas"][0].split("#")[0] == e.slug):
                base = [texto_por_id[f] for f in r["fontes_validas"] if f in texto_por_id]
                kws = [p for p in palavras if contem_termo(r["texto"], p)]
                # vocabulário adotado: palavra-chave que está no bullet e não estava no fato (só comparável no mesmo idioma)
                novas = ([p for p in kws if not any(contem_termo(t, p) for t in base)] if cv.mesmo_idioma else [])
                itens.append({"final": r["texto"], "base": base, "palavras": kws, "vocabulario_adotado": novas})
        lim = resultado.limites.get(e.slug, {})
        experiencias.append({
            "rotulo": f"{e.meta['empresa']} · {e.meta['cargo']} ({e.meta['inicio'][:4]} a "
                      f"{'atual' if e.meta['fim'] == 'atual' else e.meta['fim'][:4]})",
            "limite": lim.get("limite"), "motivo": lim.get("motivo", ""), "bullets": itens})

    resumidas = [x["rotulo"] for x in experiencias if x["limite"] is not None and x["limite"] <= 1]

    # onde cada palavra-chave que a base sustenta entrou no currículo (a vaga e o currículo costumam estar no mesmo idioma)
    palavras_base = []
    for item in analise.get("palavras_chave_base", []):
        termo, onde = item["termo"], []
        if contem_termo(resumo_txt, termo):
            onde.append("Resumo")
        if any(contem_termo(c["linha"], termo) for c in competencias):
            onde.append("Competências")
        for x in experiencias:
            n = sum(1 for b in x["bullets"] if contem_termo(b["final"], termo))
            if n:
                onde.append(f"{x['rotulo'].split(' (')[0]} ({n})")
        palavras_base.append({"termo": termo, "onde": onde})
    return {
        "vaga": {"titulo": analise.get("titulo_vaga", ""), "empresa": analise.get("empresa", "")},
        "encaixe": encaixe,
        "ia": _adaptacao_da_ia(resultado.gerado_bruto),
        "palavras_base": palavras_base,
        "resumo": {"texto": resumo_txt, "palavras": [p for p in palavras if contem_termo(resumo_txt, p)]},
        "competencias": competencias,
        "experiencias": experiencias,
        "fora": {
            "removidos": [f"{r['secao']}: {r['texto']} ({r['motivo']})" for r in cv.removidos],
            "palavras_sem_base": list(cob["fora_sem_base"]),
            "palavras_com_base_nao_usadas": list(cob["fora_com_base"]),
            "experiencias_resumidas": resumidas,
        },
        "conferir": list(cv.alertas),
    }


def para_markdown(rel: dict, com_titulo: bool = True) -> str:
    """Relatório em Markdown limpo (a tela e o arquivo relatorio.md usam o mesmo texto)."""
    e, o = rel["encaixe"], rel["encaixe"]["obrigatorios"]
    d, p = rel["encaixe"]["desejaveis"], rel["encaixe"]["palavras"]
    v = rel["vaga"]
    L: list[str] = ["# Relatório da adaptação", ""] if com_titulo else []
    if v["titulo"] or v["empresa"]:
        L += [f"Vaga: {v['titulo']}" + (f" ({v['empresa']})" if v["empresa"] else ""), ""]
    L += ["## Encaixe com a vaga", "",
          f"- Requisitos obrigatórios: {o['coberto']} de {o['total']} cobertos, {o['parcial']} parciais, {o['lacuna']} lacunas.",
          f"- Requisitos desejáveis: {d['coberto']} de {d['total']} cobertos, {d['parcial']} parciais, {d['lacuna']} lacunas.",
          f"- Palavras-chave da vaga usadas com respaldo na sua base: {p['usadas']} de {p['total']} ({p['percentual']}%)."]
    if e["lacunas_obrigatorias"]:
        L += ["", "Lacunas obrigatórias (a base não comprova; responda na etapa de lacunas se for verdade):"]
        L += [f"- {x}" for x in e["lacunas_obrigatorias"]]
    if e["parciais_obrigatorias"]:
        L += ["", "Obrigatórios só parcialmente cobertos:"] + [f"- {x}" for x in e["parciais_obrigatorias"]]

    if rel["palavras_base"]:
        L += ["", "## Palavras-chave da vaga que a sua base sustenta, e onde entraram", ""]
        for pb in rel["palavras_base"]:
            L.append(f"- {pb['termo']}: " + ("; ".join(pb["onde"]) if pb["onde"] else "não entrou no currículo (a base tem; dá para incluir editando)"))

    ia = rel["ia"]
    if ia["estrategia"] or ia["mudancas"] or ia["deixou_de_fora"]:
        L += ["", "## Estratégia da adaptação (explicação da IA; não faz parte do currículo)", ""]
        if ia["estrategia"]:
            L += [ia["estrategia"], ""]
        for m in ia["mudancas"]:
            L.append(f"- {m['onde']}: {m['o_que']}" + (f" Motivo: {m['motivo']}" if m["motivo"] else ""))
        if ia["deixou_de_fora"]:
            L += ["", "Deixou de fora:"] + [f"- {x}" for x in ia["deixou_de_fora"]]

    L += ["", "## Como cada parte foi escrita", ""]
    if rel["resumo"]["texto"]:
        L += ["### Resumo", "", rel["resumo"]["texto"], ""]
        if rel["resumo"]["palavras"]:
            L += ["Palavras-chave da vaga presentes: " + ", ".join(rel["resumo"]["palavras"]) + ".", ""]
    if rel["competencias"]:
        L += ["### Competências", ""]
        for c in rel["competencias"]:
            L.append(f"- {c['linha']}" + (f" (da vaga: {', '.join(c['palavras'])})" if c["palavras"] else ""))
        L.append("")
    L += ["### Experiências", ""]
    for x in rel["experiencias"]:
        cab = f"#### {x['rotulo']}"
        if x["limite"] is not None:
            cab += f": {len(x['bullets'])} de até {x['limite']} bullet(s), {x['motivo']}"
        L += [cab, ""]
        if not x["bullets"]:
            L += ["Só cargo, empresa e datas.", ""]
        for b in x["bullets"]:
            L.append(f"- Currículo: {b['final']}")
            for t in b["base"]:
                L.append(f"  - Base: {t}")
            if b["palavras"]:
                L.append("  - Palavras-chave da vaga neste bullet: " + ", ".join(b["palavras"]))
            if b["vocabulario_adotado"]:
                L.append("  - Vocabulário da vaga adotado (não estava no fato): " + ", ".join(b["vocabulario_adotado"]))
        L.append("")

    f = rel["fora"]
    L += ["## O que ficou de fora e por quê", ""]
    if f["removidos"]:
        L += ["Removido pelo sistema por falta de respaldo:"] + [f"- {x}" for x in f["removidos"]] + [""]
    if f["palavras_sem_base"]:
        L += ["Palavras-chave sem base (você não comprovou, então não entraram):", ", ".join(f["palavras_sem_base"]), ""]
    if f["palavras_com_base_nao_usadas"]:
        L += ["A base tem, mas o currículo não usou (dá para incluir editando):", ", ".join(f["palavras_com_base_nao_usadas"]), ""]
    if f["experiencias_resumidas"]:
        L += ["Experiências resumidas por serem antigas ou pouco relevantes para esta vaga:"]
        L += [f"- {x}" for x in f["experiencias_resumidas"]] + [""]
    if not (f["removidos"] or f["palavras_sem_base"] or f["palavras_com_base_nao_usadas"] or f["experiencias_resumidas"]):
        L += ["Nada relevante ficou de fora.", ""]

    L += ["## Pontos a conferir antes de enviar", ""]
    L += [f"- {a}" for a in rel["conferir"]] if rel["conferir"] else ["Nenhum alerta."]
    return "\n".join(L).rstrip() + "\n"
