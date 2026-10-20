"""Plano de conteúdo: o código decide, antes de gerar, QUAIS fatos entram e ONDE cada palavra-chave aparece.

Sem plano, o modelo escolhe os fatos a cada geração e a nota oscila muito com o mesmo histórico (uma palavra-chave
esquecida vale cerca de 2 pontos). O plano é determinístico: mesmo histórico, mesma análise e mesmos limites dão o
mesmo plano. O modelo continua escrevendo o texto (é isso que ele faz bem), mas com uma lista de conferência.

Nada aqui acrescenta fato: o plano só escolhe entre fatos confirmados e só pede termos que a regra única
(aderencia.palavras_sustentadas) já dá como comprovados.
"""
from __future__ import annotations

from .kb import KB

# Peso de cada coisa que a vaga pede, na mesma proporção do índice (aderencia.PESOS).
PESO_PALAVRAS, PESO_OBRIGATORIOS, PESO_DESEJAVEIS = 45, 30, 10


def itens_da_vaga(analise: dict, sustentadas: dict[str, list[str]]) -> list[dict]:
    """O que a vaga pede e a base comprova, cada um com o seu peso no índice e os fatos que o comprovam."""
    kws = analise.get("palavras_chave", [])
    itens = []
    for k in kws:
        ids = sustentadas.get(k.lower())
        if ids:
            itens.append({"tipo": "palavra", "nome": k, "peso": PESO_PALAVRAS / len(kws), "ids": list(ids)})
    reqs = analise.get("requisitos", [])
    for tipo, peso_total in (("obrigatorio", PESO_OBRIGATORIOS), ("desejavel", PESO_DESEJAVEIS)):
        do_tipo = [r for r in reqs if r.get("tipo") == tipo]
        for r in do_tipo:
            valor = {"coberto": 1.0, "parcial": 0.5}.get(r.get("status"), 0.0)
            if valor and r.get("evidencias"):
                itens.append({"tipo": tipo, "nome": r["requisito"], "peso": peso_total * valor / len(do_tipo),
                              "ids": list(r["evidencias"])})
    return itens


def montar(kb: KB, analise: dict, limites: dict[str, int], sustentadas: dict[str, list[str]]) -> dict:
    """{"experiencias": {slug: [ids na ordem]}, "termos": {id: [palavras-chave]}, "fora_das_experiencias": [...]}

    Em cada experiência, escolhe gulosamente os fatos que mais somam peso AINDA não coberto (um fato que só repete
    o que outro já mostrou vale menos), até o limite de bullets. O que nenhum fato escolhido cobre vai para o resumo
    ou as competências, com os fatos que o comprovam.
    """
    itens = itens_da_vaga(analise, sustentadas)
    confirmados = [f for f in kb.fatos("confirmado")]
    por_slug: dict[str, list] = {}
    for f in confirmados:
        por_slug.setdefault(f.slug, []).append(f)
    coberto: set[int] = set()
    plano: dict[str, list[str]] = {}
    ganho_do_fato: dict[str, float] = {}     # peso NOVO que o fato trouxe quando foi escolhido
    # Experiências em ordem de quanto peso podem mostrar: a que comprova mais escolhe primeiro.
    exps = [e for e in kb.experiencias()]

    def potencial(slug: str) -> float:
        ids = {f.id for f in por_slug.get(slug, [])}
        return sum(it["peso"] for it in itens if ids & set(it["ids"]))

    for e in sorted(exps, key=lambda e: -potencial(e.slug)):
        lim = max(int(limites.get(e.slug, 0)), 0)
        restantes = list(por_slug.get(e.slug, []))
        escolhidos: list[str] = []
        while restantes and len(escolhidos) < lim:
            def ganho(f) -> tuple:
                novo = sum(it["peso"] for n, it in enumerate(itens) if n not in coberto and f.id in it["ids"])
                total = sum(it["peso"] for it in itens if f.id in it["ids"])
                return (novo, total, -f.n)      # empate: o fato que vem antes na base (a ordem dela)
            melhor = max(restantes, key=ganho)
            restantes.remove(melhor)
            escolhidos.append(melhor.id)
            ganho_do_fato[melhor.id] = ganho(melhor)[0]
            coberto.update(n for n, it in enumerate(itens) if melhor.id in it["ids"])
        plano[e.slug] = escolhidos
    escolhidos_todos = {i for ids in plano.values() for i in ids}
    termos: dict[str, list[str]] = {}
    for it in itens:
        if it["tipo"] != "palavra":
            continue
        no_plano = [i for i in it["ids"] if i in escolhidos_todos]
        if no_plano:
            termos.setdefault(no_plano[0], []).append(it["nome"])
    fora = [{"tipo": it["tipo"], "nome": it["nome"], "ids": it["ids"]} for n, it in enumerate(itens) if n not in coberto]
    return {"experiencias": {e.slug: plano.get(e.slug, []) for e in exps}, "termos": termos, "ganho": ganho_do_fato,
            "fora_das_experiencias": fora}


def cortar_bullets(kb: KB, analise: dict, limites: dict[str, int], sustentadas: dict[str, list[str]],
                   quantos: int) -> dict[str, int]:
    """Tira `quantos` bullets, um de cada vez, de onde eles valem menos para a vaga (para caber nas páginas).

    A cada passo, a experiência perde o último fato do plano dela, o que trouxe menos peso novo. Em empate, a mais
    antiga. Nunca zera uma experiência (fica ao menos 1 bullet).
    """
    limites = dict(limites)
    ordem = {e.slug: n for n, e in enumerate(kb.experiencias())}
    for _ in range(max(quantos, 0)):
        p = montar(kb, analise, limites, sustentadas)
        candidatas = [(p["ganho"].get(ids[-1], 0.0), -ordem.get(slug, 0), slug)
                      for slug, ids in p["experiencias"].items() if len(ids) >= 2 and limites.get(slug, 0) >= 2]
        if not candidatas:
            break
        slug = min(candidatas)[2]
        limites[slug] = len(p["experiencias"][slug]) - 1
    return limites


def para_prompt(plano: dict) -> str:
    linhas = ["# Plano de conteúdo (calculado pelo sistema; siga)",
              "O sistema escolheu os fatos que mais mostram o que a vaga pede, dentro do limite de cada experiência. "
              "Use estes fatos, nesta ordem. Pode juntar dois fatos num bullet, mas não troque por outros. Quando um "
              "fato traz termos indicados, escreva o bullet com o termo EXATO da vaga, sem mudar o significado."]
    for slug, ids in plano["experiencias"].items():
        if not ids:
            linhas.append(f"- {slug}: nenhum bullet")
            continue
        partes = [f"{i}" + (f" (use: {', '.join(plano['termos'][i])})" if plano["termos"].get(i) else "") for i in ids]
        linhas.append(f"- {slug}: " + "; ".join(partes))
    palavras = [x for x in plano["fora_das_experiencias"] if x["tipo"] == "palavra"]
    reqs = [x for x in plano["fora_das_experiencias"] if x["tipo"] != "palavra"]
    if palavras:
        linhas.append("Estas palavras-chave comprovadas não cabem nos bullets escolhidos: ponha cada uma nas competências, "
                      "citando um dos fatos indicados em `fontes`. Escreva cada item como uma competência legível, com o "
                      "termo exato dentro dela quando ele sozinho não for uma competência (\"times multidisciplinares\", "
                      "não \"multidisciplinares\"). Se o termo não fizer sentido como competência, use-o de forma natural "
                      "num bullet do fato indicado ou deixe de fora:")
        linhas += [f"  - {x['nome']} (fatos: {', '.join(x['ids'][:3])})" for x in palavras]
    if reqs:
        linhas.append("Estes requisitos comprovados também precisam aparecer, nas competências ou num bullet, citando um "
                      "dos fatos:")
        linhas += [f"  - {x['nome']} (fatos: {', '.join(x['ids'][:3])})" for x in reqs]
    linhas.append("O resumo NÃO é uma lista de palavras-chave: 2 ou 3 frases naturais, com no máximo 4 termos da vaga, "
                  "e só o que os fatos citados dizem. Quem lê é uma pessoa: texto amontoado de termos piora o currículo.")
    return "\n".join(linhas)
