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
from .verify import contem_termo, palavras_da_base, termo_suportado

PESOS = {"palavras": 45, "obrigatorios": 30, "desejaveis": 10, "estrutura": 15}
ROTULOS = {"palavras": "Palavras-chave da vaga", "obrigatorios": "Requisitos obrigatórios",
           "desejaveis": "Requisitos desejáveis", "estrutura": "Estrutura legível por ATS"}

AVISO = ("O índice só sobe com o que é verdade. Se a vaga pede algo que você não fez, a saída certa é deixar de "
         "fora: o app remove o que a sua base não sustenta, e inventar aparece na entrevista.")


# ------------------------------------------------------------------------ currículo-base ("antes")

def gerado_base(kb: KB, cfg: dict, limites: dict[str, int] | None = None, preferidos: set[str] | None = None) -> dict:
    """O que um currículo sem adaptação diria: fatos na ordem da base, com os limites de espaço de sempre.

    `limites` (slug -> bullets) e `preferidos` (ids de fatos que a vaga valoriza, que vêm primeiro) servem à
    estimativa de páginas antes de gerar.
    """
    confirmados = kb.fatos("confirmado")

    def de(slug: str) -> list:
        return [f for f in confirmados if f.slug == slug]

    def lista(slug: str) -> list[dict]:
        return [{"texto": f.texto, "fontes": [f.id]} for f in de(slug)]

    perfil = de("perfil")[:2]
    experiencias = []
    for pos, e in enumerate(kb.experiencias()):
        lim = (limites or {}).get(e.slug, render._limite_bullets(cfg, pos))
        fatos = sorted(de(e.slug), key=lambda f: f.id not in (preferidos or ()))   # estável: o resto segue a ordem
        experiencias.append({"id": e.slug, "bullets": [{"texto": f.texto, "fontes": [f.id]} for f in fatos[:max(lim, 0)]]})
    return {
        "titulo": "",
        "resumo": {"texto": " ".join(f.texto for f in perfil), "fontes": [f.id for f in perfil]} if perfil else None,
        "competencias": [{"grupo": "", "itens": f.texto, "fontes": [f.id]}
                         for f in de("habilidades")[:int(cfg.get("max_grupos_competencias", 6))]],
        "experiencias": experiencias,
        "formacao": lista("formacao"), "certificacoes": lista("certificacoes"), "idiomas": lista("idiomas"),
    }


def curriculo_base(kb: KB, cfg: dict, limites: dict[str, int] | None = None,
                   preferidos: set[str] | None = None) -> render.Curriculo:
    return render.montar(kb, gerado_base(kb, cfg, limites, preferidos), kb.idioma_base(), cfg, fiscal="ausente")


PALAVRAS_POR_PAGINA = 450   # medido em PDFs reais (A4, fonte 10): 430 a 480 por página


def estimar_palavras(kb: KB, cfg: dict, limites: dict[str, int], preferidos: set[str] | None = None) -> int:
    """Tamanho aproximado, em palavras, de um currículo com estes limites, antes de gerar (só código, sem IA).

    Parte dos fatos como estão escritos e soma 8%, que é o que o resumo e as competências costumam acrescentar
    (medido em currículos gerados). É uma estimativa: o número exato só existe depois de gerar.
    """
    return round(len(curriculo_base(kb, cfg, limites, preferidos).markdown.split()) * 1.08)


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


NOME_CHECK_PAGINAS = "Páginas dentro do limite"


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
        "Preencha e-mail e telefone em Meu histórico, Dados pessoais (ficam só no seu computador).")
    if paginas is not None:
        limite = int(cfg.get("max_paginas", 2))
        add(NOME_CHECK_PAGINAS, paginas <= limite, f"O PDF tem {paginas} páginas e o limite é {limite}.")
    return checks


def _idioma_valido_para_palavras(analise: dict, idioma_cv: str) -> bool:
    """Comparar o texto com as palavras da vaga só é confiável se estiverem no mesmo idioma."""
    iv = analise.get("idioma_vaga")
    return not (iv in ("pt", "en") and iv != idioma_cv)


def calcular(analise: dict, markdown: str, rastro: list[dict], kb: KB, cfg: dict, idioma_cv: str,
             paginas: int | None = None, suspeitos: list[str] | None = None,
             rejeitados: list[str] | None = None) -> dict:
    """Índice de um currículo. `markdown` é o texto final (pode ser o que a pessoa editou).

    `suspeitos`: frases que o fiscal por IA apontou como exagero ou sem respaldo. Elas continuam no currículo (a pessoa
    decide), mas não contam pontos: o índice não pode subir por causa de um exagero.
    """
    for t in suspeitos or []:
        markdown = markdown.replace(t, "")
    corpo = _corpo(markdown)
    usadas = fontes_usadas(markdown, rastro)
    literal = _idioma_valido_para_palavras(analise, idioma_cv)

    # palavras-chave
    kws = analise.get("palavras_chave", [])
    fora = {t.lower() for t in rejeitados or []}       # o fiscal por IA não confirmou: não vale como comprovado
    base = {p["termo"].lower(): p["evidencias"] for p in analise.get("palavras_chave_base", [])
            if p["termo"].lower() not in fora}
    # A análise às vezes esquece um termo que está escrito no histórico ("centros de distribuição" num fato, ou no
    # nome da empresa). O código acha esses sozinho, quando vaga e histórico estão no mesmo idioma.
    if analise.get("idioma_vaga") == kb.idioma_base():
        confirmados = kb.fatos("confirmado")
        for k in kws:
            if k.lower() in base or k.lower() in fora:
                continue
            evid = [f.id for f in confirmados if contem_termo(f.texto, k)]
            for e in kb.experiencias():
                if contem_termo(" ".join(str(e.meta.get(c, "")) for c in ("cargo", "empresa")), k):
                    evid += [f.id for f in confirmados if f.slug == e.slug]
            if evid:
                base[k.lower()] = list(dict.fromkeys(evid))
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
    # Das ausentes, quais os fatos citados dizem com as mesmas palavras? O modelo às vezes liga um termo a um vizinho
    # ("Google Sheets" a um fato sobre Excel). Sugerir esse termo seria sugerir inventar, então ele vai para "parecidas".
    texto_por_id = {f.id: f.texto for f in kb.fatos("confirmado")}
    comparavel = analise.get("idioma_vaga") == kb.idioma_base()
    iguais, parecidas = [], []
    for k in ausentes:
        palavras = palavras_da_base([texto_por_id[i] for i in base[k.lower()] if i in texto_por_id])
        (iguais if not comparavel or termo_suportado(k, palavras, estrito=True) else parecidas).append(k)
    comp: dict[str, dict] = {}
    if kws:
        comp["palavras"] = {"fracao": len(acertos) / len(kws), "resumo": f"{len(acertos)} de {len(kws)}",
                            "detalhe": {"usadas": acertos, "sustentadas_ausentes": iguais, "parecidas_ausentes": parecidas,
                                        "sem_base": sem_base, "sem_base_usadas": sem_base_usadas,
                                        "estimado": not literal}}

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

    # teto: o índice se o texto usasse tudo o que a base já sustenta (o limite de páginas conta como cumprido)
    teto = 0.0
    for k, c in comp.items():
        if k == "palavras":
            f = (len(acertos) + len(iguais)) / len(kws)   # "parecidas" não contam: não são o que a base diz
        elif k in ("obrigatorios", "desejaveis"):
            itens = [r for r in reqs if r["tipo"] == ("obrigatorio" if k == "obrigatorios" else "desejavel")]
            f = sum({"coberto": 1.0, "parcial": 0.5}.get(r["status"], 0.0) * bool(r["evidencias"]) for r in itens) / len(itens)
        elif k == "estrutura":
            # o limite de páginas se resolve condensando o texto, não mexendo na base: no teto ele conta como cumprido
            checks_ok = [c_["ok"] or c_["nome"] == NOME_CHECK_PAGINAS for c_ in c["detalhe"]["checks"]]
            f = sum(checks_ok) / len(checks_ok)
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
        det = p["detalhe"]
        n = sum(len(det[k]) for k in ("usadas", "sustentadas_ausentes", "parecidas_ausentes", "sem_base", "sem_base_usadas"))

        def ganho(lista: list) -> int:
            return round(p["peso"] * len(lista) / n)
        if det["sustentadas_ausentes"]:
            saida.append({"tipo": "usar_base", "titulo": "O seu histórico já tem, mas o texto não usa",
                          "detalhe": "Inclua estes termos onde forem verdade: editando o currículo, ou dando mais "
                                     "espaço à experiência que os contém e gerando de novo.",
                          "itens": det["sustentadas_ausentes"], "ganho": ganho(det["sustentadas_ausentes"])})
        if det["parecidas_ausentes"]:
            saida.append({"tipo": "confirmar", "titulo": "Parecidas com o que você tem, mas não iguais",
                          "detalhe": "A IA ligou estes termos a algo do seu histórico, mas as palavras não batem (Excel "
                                     "não é Google Sheets, por exemplo). Use só se for exatamente o que você fez.",
                          "itens": det["parecidas_ausentes"], "ganho": ganho(det["parecidas_ausentes"])})
        if det["sem_base"]:
            saida.append({"tipo": "confirmar", "titulo": "Palavras-chave que não estão no seu histórico",
                          "detalhe": "Só entram se você de fato fez isso. Se fez, responda a pergunta no passo Encaixe "
                                     "ou converse em Meu histórico. Se não fez, deixe de fora.",
                          "itens": det["sem_base"], "ganho": ganho(det["sem_base"])})
        if det["sem_base_usadas"]:
            saida.append({"tipo": "confirmar", "titulo": "Estão no texto, mas o seu histórico não comprova",
                          "detalhe": "Confira com cuidado: ou é verdade e falta registrar em Meu histórico, ou deve sair "
                                     "do currículo.",
                          "itens": det["sem_base_usadas"], "ganho": 0})

    for chave, nome in (("obrigatorios", "obrigatórios"), ("desejaveis", "desejáveis")):
        c = comp.get(chave)
        if not c:
            continue
        itens = c["detalhe"]["itens"]
        usar = [x for x in itens if x["maximo"] > 0 and x["ponto"] < x["maximo"]]
        if usar:
            saida.append({"tipo": "usar_base", "titulo": f"Requisitos {nome} que o seu histórico cobre, mas o texto não mostra",
                          "detalhe": "A comprovação existe no seu histórico, mas nenhuma frase do currículo a usa.",
                          "itens": [x["requisito"] for x in usar],
                          "ganho": round(c["peso"] * sum(x["maximo"] - x["ponto"] for x in usar) / len(itens))})
        faltam = [x for x in itens if x["status"] != "coberto" and x["maximo"] < 1]
        if faltam:
            saida.append({"tipo": "confirmar", "titulo": f"Requisitos {nome} sem comprovação completa",
                          "detalhe": "Você fez isso? Se sim, responda a pergunta no passo Encaixe. Se não, é uma lacuna "
                                     "real e fica de fora.",
                          "itens": [x["requisito"] for x in faltam],
                          "ganho": round(c["peso"] * sum(1 - x["maximo"] for x in faltam) / len(itens))})

    e = comp.get("estrutura")
    if e:
        falhas = [x for x in e["detalhe"]["checks"] if not x["ok"]]
        if falhas:
            saida.append({"tipo": "estrutura", "titulo": "Formato", "detalhe": "Ajustes de formato, sem mexer no conteúdo.",
                          "itens": [x["dica"] for x in falhas],
                          "ganho": round(e["peso"] * len(falhas) / len(e["detalhe"]["checks"]))})
    return sorted(saida, key=lambda m: -m["ganho"])


def comparar(kb: KB, analise: dict, markdown: str, rastro: list[dict], cfg: dict, idioma: str,
             paginas_depois: int | None = None, suspeitos: list[str] | None = None,
             rejeitados: list[str] | None = None) -> dict:
    """Antes (currículo-base) e depois (este texto), os dois pelo mesmo cálculo."""
    original = indice_original(kb, analise, cfg, rejeitados)
    if paginas_depois is None:
        paginas_depois = _paginas(markdown)
    depois = calcular(analise, markdown, rastro, kb, cfg, idioma, paginas_depois, suspeitos, rejeitados)
    return {"antes": original["indice"], "depois": depois, "idioma_antes": kb.idioma_base(), "idioma_depois": idioma,
            "markdown_antes": original["markdown"], "rastro_antes": original["rastro"],
            "melhorias": melhorias(analise, depois), "aviso": AVISO}


def _paginas(md: str) -> int | None:
    from . import export   # import tardio: reportlab só é necessário aqui
    try:
        return export.gerar_pdf(md)[1]
    except Exception:  # o índice não pode quebrar por causa de uma contagem de páginas
        return None


def indice_original(kb: KB, analise: dict, cfg: dict, rejeitados: list[str] | None = None) -> dict:
    """A pontuação do currículo SEM adaptação para esta vaga, antes de gerar qualquer coisa (só código, sem IA).

    Devolve {"indice": calcular(...), "markdown": o currículo-base}. É a régua que o currículo adaptado não pode
    ficar abaixo (ver tailor.gerar).
    """
    base = curriculo_base(kb, cfg)
    indice = calcular(analise, base.markdown, base.rastro, kb, cfg, kb.idioma_base(), _paginas(base.markdown),
                      rejeitados=rejeitados)
    return {"indice": indice, "markdown": base.markdown, "rastro": base.rastro}


def o_que_se_perdeu(antes: dict, depois: dict) -> dict:
    """O que a versão sem adaptar mostrava e a adaptada deixou de mostrar (para pedir de volta ao gerador)."""
    pa, pd = antes["componentes"].get("palavras"), depois["componentes"].get("palavras")
    palavras = [k for k in (pa["detalhe"]["usadas"] if pa else []) if pd and k not in pd["detalhe"]["usadas"]]
    requisitos = []
    for chave in ("obrigatorios", "desejaveis"):
        a, d = antes["componentes"].get(chave), depois["componentes"].get(chave)
        if a and d:
            no_depois = {x["requisito"] for x in d["detalhe"]["itens"] if x["no_curriculo"]}
            requisitos += [x["requisito"] for x in a["detalhe"]["itens"] if x["no_curriculo"] and x["requisito"] not in no_depois]
    return {"palavras": palavras, "requisitos": requisitos}
