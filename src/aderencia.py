"""Índice de aderência à vaga: antes e depois da adaptação, e o que ainda dá para melhorar.

Não é a nota de nenhum ATS (elas não são públicas). É um índice nosso, de 0 a 100, que o código calcula do mesmo
jeito para qualquer currículo, e que NUNCA sobe por inventar: só conta palavra-chave que a base sustenta e requisito
cujo fato de apoio está de fato no texto.

Componentes (pesos; um componente sem itens sai e os outros se reescalam):
- palavras-chave da vaga que a base sustenta E que aparecem no texto (45)
- requisitos obrigatórios refletidos no texto, pelos fatos que o sustentam (30)
- requisitos desejáveis, idem (10)
- estrutura que o ATS lê: seções convencionais, contato no cabeçalho, páginas dentro do limite (15)

"Antes" é o currículo-base: os fatos confirmados na ordem em que estão na base, com os mesmos limites de espaço,
sem nenhuma adaptação. "Depois" é o currículo gerado (ou o texto que você editou).
"""
from __future__ import annotations

import re

from . import render
from .kb import KB
from .verify import contem_termo

PESOS = {"palavras": 45, "obrigatorios": 30, "desejaveis": 10, "estrutura": 15}
ROTULOS = {"palavras": "Palavras-chave da vaga", "obrigatorios": "Requisitos obrigatórios",
           "desejaveis": "Requisitos desejáveis", "estrutura": "Estrutura legível por ATS"}

AVISO = ("O índice só sobe com o que é verdade. Se a vaga pede algo que você não fez, a saída certa é deixar de "
         "fora: o app remove o que a sua base não sustenta, e inventar aparece na entrevista.")


# ------------------------------------------------------------------------ currículo-base ("antes")

def gerado_base(kb: KB, cfg: dict) -> dict:
    """O que um currículo sem adaptação diria: fatos na ordem da base, com os limites de espaço de sempre."""
    confirmados = kb.fatos("confirmado")

    def de(slug: str) -> list:
        return [f for f in confirmados if f.slug == slug]

    def lista(slug: str) -> list[dict]:
        return [{"texto": f.texto, "fontes": [f.id]} for f in de(slug)]

    perfil = de("perfil")[:2]
    experiencias = []
    for pos, e in enumerate(kb.experiencias()):
        lim = render._limite_bullets(cfg, pos)
        experiencias.append({"id": e.slug, "bullets": [{"texto": f.texto, "fontes": [f.id]}
                                                       for f in de(e.slug)[:max(lim, 0)]]})
    return {
        "titulo": "",
        "resumo": {"texto": " ".join(f.texto for f in perfil), "fontes": [f.id for f in perfil]} if perfil else None,
        "competencias": [{"grupo": "", "itens": f.texto, "fontes": [f.id]}
                         for f in de("habilidades")[:int(cfg.get("max_grupos_competencias", 6))]],
        "experiencias": experiencias,
        "formacao": lista("formacao"), "certificacoes": lista("certificacoes"), "idiomas": lista("idiomas"),
    }


def curriculo_base(kb: KB, cfg: dict) -> render.Curriculo:
    return render.montar(kb, gerado_base(kb, cfg), kb.idioma_base(), cfg, fiscal="ausente")


# ------------------------------------------------------------------------ cálculo

def _corpo(markdown: str) -> str:
    """O currículo sem o cabeçalho de contato."""
    i = markdown.find("\n## ")
    return markdown[i:] if i >= 0 else markdown


def fontes_usadas(markdown: str, rastro: list[dict]) -> set[str]:
    """Ids dos fatos que sustentam o que está de fato no texto (item cortado ou removido não conta)."""
    usadas: set[str] = set()
    for r in rastro:
        texto = r["texto"]
        if r["secao"] == "competências":
            no_texto = any(x.strip() and x.strip() in markdown for x in re.split(r"[,;]", texto))
        else:
            no_texto = texto[:40] in markdown
        if no_texto:
            usadas.update(r["fontes_validas"])
    return usadas


def _estrutura(markdown: str, kb: KB, cfg: dict, idioma: str, paginas: int | None) -> list[dict]:
    titulos = cfg["titulos_secoes"][idioma]
    tem = {a.slug for a in kb.arquivos().values() if any(True for _ in a.fatos())}
    checks = []

    def add(nome: str, ok: bool, dica: str) -> None:
        checks.append({"nome": nome, "ok": bool(ok), "dica": dica})

    if "perfil" in tem:
        add("Seção de resumo", f"## {titulos['resumo']}" in markdown, "Falta o resumo no topo do currículo.")
    add("Seção de experiência", f"## {titulos['experiencia']}" in markdown, "Falta a seção de experiência.")
    if "formacao" in tem:
        add("Seção de formação", f"## {titulos['formacao']}" in markdown, "Falta a seção de formação.")
    cabecalho = markdown.split("\n## ")[0]
    add("Contato no cabeçalho", "@" in cabecalho or re.search(r"\d[\d\s().-]{7,}\d", cabecalho),
        "Preencha e-mail e telefone na aba Minha base (ficam só no seu computador).")
    if paginas is not None:
        limite = int(cfg.get("max_paginas", 2))
        add("Páginas dentro do limite", paginas <= limite, f"O PDF tem {paginas} páginas e o limite é {limite}.")
    return checks


def _idioma_valido_para_palavras(analise: dict, idioma_cv: str) -> bool:
    """Comparar o texto com as palavras da vaga só é confiável se estiverem no mesmo idioma."""
    iv = analise.get("idioma_vaga")
    return not (iv in ("pt", "en") and iv != idioma_cv)


def calcular(analise: dict, markdown: str, rastro: list[dict], kb: KB, cfg: dict, idioma_cv: str,
             paginas: int | None = None) -> dict:
    """Índice de um currículo. `markdown` é o texto final (pode ser o que a pessoa editou)."""
    corpo = _corpo(markdown)
    usadas = fontes_usadas(markdown, rastro)
    literal = _idioma_valido_para_palavras(analise, idioma_cv)

    # palavras-chave
    kws = analise.get("palavras_chave", [])
    base = {p["termo"].lower(): p["evidencias"] for p in analise.get("palavras_chave_base", [])}
    acertos, ausentes, sem_base, sem_base_usadas = [], [], [], []
    for k in kws:
        evid = base.get(k.lower())
        presente = contem_termo(corpo, k) if literal else bool(evid and set(evid) & usadas)
        if evid and presente:
            acertos.append(k)
        elif evid:
            ausentes.append(k)
        elif presente:
            sem_base_usadas.append(k)
        else:
            sem_base.append(k)
    comp: dict[str, dict] = {}
    if kws:
        comp["palavras"] = {"fracao": len(acertos) / len(kws), "resumo": f"{len(acertos)} de {len(kws)}",
                            "detalhe": {"usadas": acertos, "sustentadas_ausentes": ausentes, "sem_base": sem_base,
                                        "sem_base_usadas": sem_base_usadas, "estimado": not literal}}

    # requisitos
    reqs = analise.get("requisitos", [])
    for chave, tipo in (("obrigatorios", "obrigatorio"), ("desejaveis", "desejavel")):
        itens = [r for r in reqs if r["tipo"] == tipo]
        if not itens:
            continue
        linhas, soma = [], 0.0
        for r in itens:
            valor = {"coberto": 1.0, "parcial": 0.5}.get(r["status"], 0.0)
            refletido = bool(set(r["evidencias"]) & usadas)
            ponto = valor if refletido else 0.0
            soma += ponto
            linhas.append({"requisito": r["requisito"], "status": r["status"], "no_curriculo": refletido,
                           "ponto": ponto, "maximo": valor, "pergunta": r.get("pergunta", "")})
        comp[chave] = {"fracao": soma / len(itens), "resumo": f"{soma:g} de {len(itens)}",
                       "detalhe": {"itens": linhas}}

    # estrutura
    checks = _estrutura(markdown, kb, cfg, idioma_cv, paginas)
    comp["estrutura"] = {"fracao": sum(c["ok"] for c in checks) / len(checks),
                         "resumo": f"{sum(c['ok'] for c in checks)} de {len(checks)}", "detalhe": {"checks": checks}}

    soma_pesos = sum(PESOS[k] for k in comp)
    for k, c in comp.items():
        c["rotulo"], c["peso"] = ROTULOS[k], round(PESOS[k] * 100 / soma_pesos, 1)
        c["pontos"] = round(c["peso"] * c["fracao"], 1)
    total = round(sum(c["pontos"] for c in comp.values()))

    # teto: o índice se o texto usasse tudo o que a base já sustenta (a estrutura fica como está)
    teto = 0.0
    for k, c in comp.items():
        if k == "palavras":
            f = (len(acertos) + len(ausentes)) / len(kws)
        elif k in ("obrigatorios", "desejaveis"):
            itens = [r for r in reqs if r["tipo"] == ("obrigatorio" if k == "obrigatorios" else "desejavel")]
            f = sum({"coberto": 1.0, "parcial": 0.5}.get(r["status"], 0.0) * bool(r["evidencias"]) for r in itens) / len(itens)
        else:
            f = c["fracao"]
        teto += c["peso"] * f
    return {"total": total, "teto": max(total, round(teto)), "componentes": comp, "estimado": not literal,
            "paginas": paginas}


# ------------------------------------------------------------------------ o que ainda dá para melhorar

def melhorias(analise: dict, indice: dict) -> list[dict]:
    """Ações que aumentariam o índice, com o ganho aproximado SE a informação for verdadeira.

    tipo "usar_base": a base já sustenta, é só o texto usar (editar ou gerar de novo com mais espaço).
    tipo "confirmar": só vale se você de fato fez; exige responder à pergunta e confirmar o fato.
    tipo "estrutura": ajuste de formato ou de contato.
    """
    comp = indice["componentes"]
    saida: list[dict] = []

    p = comp.get("palavras")
    if p:
        det, n = p["detalhe"], len(p["detalhe"]["usadas"]) + len(p["detalhe"]["sustentadas_ausentes"]) + len(
            p["detalhe"]["sem_base"]) + len(p["detalhe"]["sem_base_usadas"])
        if det["sustentadas_ausentes"]:
            saida.append({"tipo": "usar_base", "titulo": "A sua base já sustenta, mas o texto não usa",
                          "detalhe": "Inclua estes termos onde forem verdade (editando o currículo, ou dando mais "
                                     "espaço à experiência que os contém).",
                          "itens": det["sustentadas_ausentes"], "ganho": round(p["peso"] * len(det["sustentadas_ausentes"]) / n)})
        if det["sem_base"]:
            saida.append({"tipo": "confirmar", "titulo": "Palavras-chave sem base",
                          "detalhe": "Só entram se você de fato fez isso. Se fez, conte na etapa de lacunas e confirme "
                                     "o fato. Se não fez, deixe de fora.",
                          "itens": det["sem_base"], "ganho": round(p["peso"] * len(det["sem_base"]) / n)})
        if det["sem_base_usadas"]:
            saida.append({"tipo": "confirmar", "titulo": "Estão no texto, mas a base não sustenta",
                          "detalhe": "Confira com cuidado: ou é verdade e falta confirmar o fato, ou deve sair do currículo.",
                          "itens": det["sem_base_usadas"], "ganho": 0})

    for chave, nome in (("obrigatorios", "obrigatórios"), ("desejaveis", "desejáveis")):
        c = comp.get(chave)
        if not c:
            continue
        itens = c["detalhe"]["itens"]
        usar = [x for x in itens if x["maximo"] > 0 and x["ponto"] < x["maximo"]]
        if usar:
            saida.append({"tipo": "usar_base", "titulo": f"Requisitos {nome} que a base cobre, mas o texto não mostra",
                          "detalhe": "O fato existe na base, mas nenhum bullet do currículo o usa.",
                          "itens": [x["requisito"] for x in usar],
                          "ganho": round(c["peso"] * sum(x["maximo"] - x["ponto"] for x in usar) / len(itens))})
        faltam = [x for x in itens if x["status"] != "coberto" and x["maximo"] < 1]
        if faltam:
            saida.append({"tipo": "confirmar", "titulo": f"Requisitos {nome} sem cobertura completa",
                          "detalhe": "Pergunte a si mesma: eu fiz isso? Se sim, responda na etapa de lacunas. "
                                     "Se não, é uma lacuna real e fica de fora.",
                          "itens": [x["requisito"] for x in faltam],
                          "ganho": round(c["peso"] * sum(1 - x["maximo"] for x in faltam) / len(itens))})

    e = comp.get("estrutura")
    if e:
        falhas = [x for x in e["detalhe"]["checks"] if not x["ok"]]
        if falhas:
            saida.append({"tipo": "estrutura", "titulo": "Estrutura", "detalhe": "Ajustes de formato, sem mexer no conteúdo.",
                          "itens": [x["dica"] for x in falhas],
                          "ganho": round(e["peso"] * len(falhas) / len(e["detalhe"]["checks"]))})
    return sorted(saida, key=lambda m: -m["ganho"])


def comparar(kb: KB, analise: dict, markdown: str, rastro: list[dict], cfg: dict, idioma: str,
             paginas_depois: int | None = None) -> dict:
    """Antes (currículo-base) e depois (este texto), os dois pelo mesmo cálculo."""
    from . import export   # import tardio: reportlab só é necessário aqui

    def contar(md: str) -> int | None:
        try:
            return export.gerar_pdf(md)[1]
        except Exception:  # o índice não pode quebrar por causa de uma contagem de páginas
            return None

    base = curriculo_base(kb, cfg)
    paginas_antes = contar(base.markdown)
    if paginas_depois is None:
        paginas_depois = contar(markdown)
    antes = calcular(analise, base.markdown, base.rastro, kb, cfg, kb.idioma_base(), paginas_antes)
    depois = calcular(analise, markdown, rastro, kb, cfg, idioma, paginas_depois)
    return {"antes": antes, "depois": depois, "idioma_antes": kb.idioma_base(), "idioma_depois": idioma,
            "melhorias": melhorias(analise, depois), "aviso": AVISO}
