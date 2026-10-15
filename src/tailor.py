"""Currículo por vaga: análise, perguntas de lacuna e geração."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from . import aderencia, config, interview, relatorio, render
from .kb import KB, ErroBase
from .llm import ErroLLM, completar_json
from .texto import detectar_idioma
from .verify import cobertura_palavras, percentual

STATUS = ("coberto", "parcial", "lacuna")
NOMES_IDIOMA = {"pt": "Português do Brasil", "en": "English (inglês)"}


@dataclass
class Resultado:
    curriculo: render.Curriculo
    cobertura: dict
    gerado_bruto: dict
    verificacao_ia: bool = False
    limites: dict = field(default_factory=dict)   # slug -> {limite, motivo}
    relatorio: dict = field(default_factory=dict)  # ver relatorio.montar
    aderencia: dict = field(default_factory=dict)  # ver aderencia.comparar (antes, depois, melhorias)


# ------------------------------------------------------------------------ análise

def validar_analise(bruto, ids_ok: set[str]) -> dict:
    """Pós-validação em código: ids inexistentes caem, `coberto` sem evidência vira `parcial`."""
    a = bruto if isinstance(bruto, dict) else {}
    reqs = []
    for r in a.get("requisitos") or []:
        if not isinstance(r, dict) or not str(r.get("requisito", "")).strip():
            continue
        evid = [str(e).strip() for e in (r.get("evidencias") or []) if str(e).strip() in ids_ok]
        status = str(r.get("status", "")).strip().lower()
        if status not in STATUS:
            status = "lacuna"
        if status == "coberto" and not evid:
            status = "parcial"
        tipo = "desejavel" if str(r.get("tipo", "")).strip().lower().startswith("dese") else "obrigatorio"
        reqs.append({
            "requisito": str(r["requisito"]).strip(),
            "tipo": tipo,
            "termo_na_vaga": str(r.get("termo_na_vaga", "")).strip(),
            "status": status,
            "evidencias": evid,
            "pergunta": "" if status == "coberto" else str(r.get("pergunta", "")).strip(),
        })
    palavras, vistas = [], set()
    for p in a.get("palavras_chave") or []:
        p = str(p).strip()
        if p and p.lower() not in vistas:
            vistas.add(p.lower())
            palavras.append(p)
    por_norma = {p.lower(): p for p in palavras}
    base: list[dict] = []
    vistos_base: set[str] = set()
    for item in a.get("palavras_chave_base") or []:
        if not isinstance(item, dict):
            continue
        termo = por_norma.get(str(item.get("termo", "")).strip().lower())
        evid = [str(e).strip() for e in (item.get("evidencias") or []) if str(e).strip() in ids_ok]
        if termo and evid and termo.lower() not in vistos_base:   # sem fato real, não é "sustentada"
            vistos_base.add(termo.lower())
            base.append({"termo": termo, "evidencias": evid})
    idioma = str(a.get("idioma_vaga", "")).strip().lower()
    return {
        "titulo_vaga": str(a.get("titulo_vaga", "")).strip(),
        "empresa": str(a.get("empresa", "")).strip(),
        "idioma_vaga": idioma if idioma in ("pt", "en", "es", "outro") else "outro",
        "palavras_chave": palavras[:25],
        "palavras_chave_base": base,
        "requisitos": reqs,
        "observacoes": str(a.get("observacoes", "")).strip(),
    }


def analisar(llm, kb: KB, vaga: str) -> dict:
    if not vaga.strip():
        raise ErroBase("Cole o texto da vaga antes de analisar.")
    ids_ok = kb.ids_confirmados()
    if not ids_ok:
        raise ErroBase("A base ainda não tem nenhum fato confirmado. Faça a entrevista ou importe um "
                       "currículo antes de analisar uma vaga.")
    msgs = [
        {"role": "system", "content": config.ler_prompt("analisador")},
        {"role": "user", "content": f"## Vaga\n{vaga.strip()}\n\n## Base confirmada\n{kb.para_prompt()}"},
    ]
    return validar_analise(completar_json(llm, msgs, rotulo="analisador"), ids_ok)


def perguntas_lacuna(analise: dict) -> list[dict]:
    """Requisitos `lacuna` ou `parcial` que têm pergunta, obrigatórios primeiro."""
    itens = [r for r in analise.get("requisitos", []) if r["status"] != "coberto" and r["pergunta"]]
    return sorted(itens, key=lambda r: (r["tipo"] != "obrigatorio", r["status"] != "lacuna"))


def extrair_respostas(llm, kb: KB, respostas: list[tuple[str, str, bool]]) -> list[interview.Proposta]:
    """respostas: (pergunta, resposta, nao_tenho). Quem marcou 'não tenho' ou deixou vazio não gera fato."""
    blocos = [f"PERGUNTA: {p}\nRESPOSTA: {r.strip()}" for p, r, nao in respostas if r.strip() and not nao]
    if not blocos:
        return []
    return interview.extrair(llm, kb, "\n\n".join(blocos), "respostas")


def recomendar_idioma(vaga: str, analise: dict | None, cfg: dict) -> str:
    """Heurística local primeiro; o idioma que o modelo detectou desempata."""
    d = detectar_idioma(vaga)
    if d:
        return d
    ia = (analise or {}).get("idioma_vaga")
    if ia in ("pt", "en"):
        return ia
    return cfg.get("idioma_padrao", "pt")


# ------------------------------------------------------------------------ geração

def _anos_desde(fim: str, hoje: date) -> float:
    if fim == "atual":
        return 0.0
    ano, mes = (int(x) for x in fim.split("-"))
    return ((hoje.year - ano) * 12 + (hoje.month - mes)) / 12


def relevancia_por_experiencia(analise: dict | None) -> dict[str, int]:
    """Quanto cada experiência pesa nesta vaga, pelas evidências da análise (obrigatório vale 2, desejável 1)."""
    pesos: dict[str, int] = {}
    for r in (analise or {}).get("requisitos", []):
        if r.get("status") not in ("coberto", "parcial"):
            continue
        peso = 2 if r.get("tipo") == "obrigatorio" else 1
        for slug in {i.split("#")[0] for i in r.get("evidencias", [])}:
            pesos[slug] = pesos.get(slug, 0) + peso
    return pesos


def limites_por_experiencia(kb: KB, cfg: dict, analise: dict | None = None, hoje: date | None = None) -> dict[str, dict]:
    """Quantos bullets cada experiência recebe nesta vaga: {slug: {"limite": n, "motivo": texto}}.

    Parte do limite por posição (mais recente, mais espaço). Experiência que terminou há muito tempo é
    resumida, a menos que a análise da vaga a torne relevante. 0 significa só cargo, empresa e datas.
    """
    hoje = hoje or date.today()
    regra = {**config.PADROES["experiencias_antigas"], **(cfg.get("experiencias_antigas") or {})}
    pesos = relevancia_por_experiencia(analise)
    topo = render._limite_bullets(cfg, 0)
    saida: dict[str, dict] = {}
    exps = kb.experiencias()
    total = len(exps)
    for pos, e in enumerate(exps):
        base = render._limite_bullets(cfg, pos)
        lim = base
        motivo = "a mais recente" if pos == 0 else f"{pos + 1}ª mais recente"
        relevante = pesos.get(e.slug, 0) >= 2
        anos = _anos_desde(e.meta["fim"], hoje)
        # "início de carreira": as N mais antigas, mas só quando sobram ao menos 3 recentes completas
        inicio_de_carreira = (bool(regra["ativo"]) and total - int(regra["mais_antigas"]) >= 3
                              and pos >= total - int(regra["mais_antigas"]))
        if regra["ativo"] and (anos > float(regra["anos"]) or inicio_de_carreira):
            quando = f"terminou há {anos:.0f} anos" if anos > float(regra["anos"]) else "início de carreira"
            if relevante:
                lim = int(regra["max_bullets_relevante"])
                motivo = f"{quando}, mas a vaga a torna relevante"
            else:
                lim = min(base, int(regra["max_bullets"]))
                motivo = f"{quando} e pesa pouco nesta vaga: resumida"
        elif relevante and pos > 0:
            lim = min(topo, base + 1)
            motivo += ", relevante para esta vaga (+1)" if lim > base else ", relevante para esta vaga"
        saida[e.slug] = {"limite": lim, "motivo": motivo, "rotulo": f"{e.meta['empresa']} · {e.meta['cargo']}"}
    return saida


def _limites(cfg: dict, kb: KB, limites: dict[str, dict]) -> str:
    por_exp = "\n".join(f"  - {e.slug}: {limites[e.slug]['limite']} ({limites[e.slug]['motivo']})"
                        for e in kb.experiencias() if e.slug in limites)
    return (
        "# Limites desta geração\n"
        f"- Resumo: no máximo {cfg['resumo_max_palavras']} palavras.\n"
        f"- Competências: no máximo {cfg['max_grupos_competencias']} grupos.\n"
        f"- Máximo de bullets por experiência:\n{por_exp or '  (nenhuma)'}\n"
        "- Experiência com limite 1 ou 2 é um RESUMO: escreva bullets curtos e densos que sintetizem a função e o "
        "resultado mais relevante para a vaga, sem repetir o que as experiências recentes já dizem. Limite 0: devolva "
        "`bullets` vazio (o sistema mostra só cargo e datas).\n"
        "O sistema corta o que passar desses limites."
    )


def _analise_para_prompt(analise: dict) -> str:
    enxuta = {
        "titulo_vaga": analise.get("titulo_vaga"),
        # o que a base sustenta (com os fatos) e o que NÃO pode ser usado: o gerador casa o vocabulário só no primeiro
        "palavras_chave_que_a_base_sustenta": [
            {"termo": p["termo"], "fatos": p["evidencias"]} for p in analise.get("palavras_chave_base", [])],
        "palavras_chave_sem_base_NAO_USE": [
            p for p in analise.get("palavras_chave", [])
            if p.lower() not in {x["termo"].lower() for x in analise.get("palavras_chave_base", [])}],
        "requisitos": [{k: r[k] for k in ("requisito", "tipo", "status", "evidencias")}
                       for r in analise.get("requisitos", [])],
    }
    return json.dumps(enxuta, ensure_ascii=False, indent=1)


def gerar(llm, kb: KB, vaga: str, analise: dict, idioma: str, cfg: dict | None = None,
          titulo_usuario: str | None = None, verificar_ia: bool = True,
          limites_manuais: dict[str, int] | None = None) -> Resultado:
    cfg = cfg or config.carregar_config()
    if not kb.ids_confirmados():
        raise ErroBase("A base não tem fatos confirmados para gerar um currículo.")
    detalhe = limites_por_experiencia(kb, cfg, analise)
    for slug, n in (limites_manuais or {}).items():
        if slug in detalhe and int(n) != detalhe[slug]["limite"]:
            detalhe[slug] = {**detalhe[slug], "limite": int(n), "motivo": "ajustado por você"}
    limites = {slug: v["limite"] for slug, v in detalhe.items()}
    sistema = "\n\n".join([config.ler_prompt("gerador"),
                           "# Guidelines de escrita\n" + config.ler_guidelines(),
                           _limites(cfg, kb, detalhe)])
    usuario = (
        f"## Idioma de saída\n{NOMES_IDIOMA[idioma]}. Escreva TODO o conteúdo nesse idioma.\n\n"
        f"## Título escolhido pela candidata\n{titulo_usuario.strip() if titulo_usuario and titulo_usuario.strip() else '(nenhum)'}\n\n"
        f"## Vaga\n{vaga.strip()}\n\n"
        f"## Análise da vaga\n{_analise_para_prompt(analise)}\n\n"
        f"## Base confirmada (use somente isto)\n{kb.para_prompt()}"
    )
    bruto = completar_json(llm, [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                           temperatura=0.3, rotulo="gerador")
    palavras = analise.get("palavras_chave", [])
    cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, fiscal="pendente" if verificar_ia else "ausente", limites=limites)
    cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
    verificou = False
    pendentes = cob["fora_indeterminadas"] + cob["usadas_indeterminadas"]
    if verificar_ia and (cv.itens_fiscal or pendentes):
        try:
            v = verificar_com_ia(llm, kb, cv.itens_fiscal, pendentes, palavras)
            verificou = True
            if v["problemas"]:
                # Segunda montagem, sem IA: o código aplica o veredito (remove termos, alerta frases).
                cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, veredito=v["problemas"], fiscal="ok", limites=limites)
                cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
            _resolver_indeterminadas(cob, v["palavras"])
        except ErroLLM as e:
            # Sem fiscal, volta à regra do código (siglas e termos julgados pelas palavras da base).
            cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, fiscal="ausente", limites=limites)
            cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
            cv.alertas.append(f"A verificação por IA não rodou ({e}). Revise com atenção os termos e frases.")
    res = Resultado(cv, cob, bruto if isinstance(bruto, dict) else {}, verificou, detalhe)
    res.relatorio = relatorio.montar(kb, analise, res, cfg, idioma)
    res.aderencia = aderencia.comparar(kb, analise, cv.markdown, cv.rastro, cfg, idioma)
    return res


# ------------------------------------------------------------- fiscal por IA

def verificar_com_ia(llm, kb: KB, itens: list[dict], palavras_pendentes: list[str],
                     palavras_vaga: list[str] | None = None) -> dict:
    """Uma chamada: confere cada item do currículo contra os fatos citados (em qualquer idioma) e
    resolve palavras-chave que o código não consegue comparar entre idiomas.

    Devolve {"problemas": {chave_do_item: motivo}, "palavras": {termo: bool}}.
    O modelo só opina; quem remove ou alerta é o render. Item que a IA não menciona fica como está.
    """
    blocos = []
    for n, it in enumerate(itens):
        fatos = "\n".join(f"   - {f}" for f in it["fatos"]) or "   - (nenhum)"
        blocos.append(f"[{n}] ({it['tipo']}) {it['texto']}\n   Fatos de apoio:\n{fatos}")
    usuario = "## Itens do currículo\n" + ("\n\n".join(blocos) or "(nenhum)")
    if palavras_vaga:
        usuario += ("\n\n## Palavras-chave da vaga (ATENÇÃO: é daqui que costumam vir os termos inventados)\n"
                    + "\n".join(f"- {p}" for p in palavras_vaga))
    if palavras_pendentes:
        usuario += ("\n\n## PALAVRAS-CHAVE da vaga para classificar\n" + "\n".join(f"- {p}" for p in palavras_pendentes)
                    + f"\n\n## Base completa de fatos\n{kb.para_prompt()}")
    bruto = completar_json(llm, [{"role": "system", "content": config.ler_prompt("verificador")},
                                 {"role": "user", "content": usuario}], temperatura=0.0, rotulo="verificador")
    bruto = bruto if isinstance(bruto, dict) else {}
    problemas: dict[str, str] = {}
    descartados = 0
    # Formato novo: um veredito por item. Formato antigo ("problemas"): só a lista dos ruins (compatibilidade).
    for p in (bruto.get("itens") or []) + (bruto.get("problemas") or []):
        if not isinstance(p, dict):
            continue
        try:
            n = int(p.get("n"))
        except (TypeError, ValueError):
            continue
        veredito = str(p.get("veredito", "exagero")).strip().lower()   # sem veredito = veio do formato antigo
        motivo = str(p.get("problema", "")).strip()
        if not (0 <= n < len(itens)) or veredito not in ("exagero", "sem_respaldo") or not motivo:
            continue
        if _contradiz(motivo):
            descartados += 1      # o modelo apontou o item e, no mesmo texto, disse que está fiel: é ok
            continue
        problemas[itens[n]["chave"]] = motivo
    palavras = {}
    for p in bruto.get("palavras") or []:
        if isinstance(p, dict) and p.get("termo") in palavras_pendentes and isinstance(p.get("na_base"), bool):
            palavras[p["termo"]] = p["na_base"]
    return {"problemas": problemas, "palavras": palavras, "descartados": descartados}


# Frases com que o modelo, ao "apontar" um item, admite que não há problema. Rede de segurança do veredito.
_ADMITE_QUE_ESTA_OK = (
    "traducao fiel", "tradução fiel", "e fiel", "é fiel", "fiel ao", "e suportado", "é suportado", "esta suportado",
    "está suportado", "nao tem problema", "não tem problema", "sem problema", "nao apresenta problema",
    "não apresenta problema", "equivalente", "corresponde", "boa traducao", "boa tradução", "traducao correta",
    "tradução correta", "consistente com os fatos", "sustentado pelos fatos", "e sustentado", "é sustentado",
)


def _contradiz(motivo: str) -> bool:
    t = motivo.lower()
    return any(f in t for f in _ADMITE_QUE_ESTA_OK)


def _resolver_indeterminadas(cob: dict, palavras: dict) -> None:
    """Move as palavras que o código não conseguia comparar para a categoria certa, pelo veredito da IA."""
    ainda = []
    for t in cob["fora_indeterminadas"]:
        if t in palavras:
            cob["fora_com_base" if palavras[t] else "fora_sem_base"].append(t)
        else:
            ainda.append(t)
    cob["fora_indeterminadas"] = ainda
    ainda = []
    for t in cob["usadas_indeterminadas"]:
        if t in palavras:
            cob["usadas" if palavras[t] else "usadas_sem_base"].append(t)
        else:
            ainda.append(t)
    cob["usadas_indeterminadas"] = ainda
    cob["percentual"] = percentual(cob)


# ------------------------------------------------- tradução de cargos (com confirmação)

def sugerir_traducoes(llm, kb: KB, idioma: str) -> list[dict]:
    """Sugere cargo/local no idioma de saída para as experiências sem tradução.

    Só SUGERE: nada é gravado. A tela mostra, ela edita e confirma, e aplicar_traducoes grava.
    Devolve [{"slug", "empresa", "cargo_original", "cargo", "local_original", "local"}].
    """
    if idioma == kb.idioma_base():
        return []
    pendentes = [e for e in kb.experiencias() if not e.meta.get(f"cargo_{idioma}")]
    if not pendentes:
        return []
    entrada = {"idioma_destino": idioma,
               "itens": [{"slug": e.slug, "cargo": e.meta["cargo"], "local": e.meta.get("local", "")} for e in pendentes]}
    bruto = completar_json(llm, [{"role": "system", "content": config.ler_prompt("tradutor_cargos")},
                                 {"role": "user", "content": json.dumps(entrada, ensure_ascii=False)}], temperatura=0.0,
                           rotulo="tradutor_cargos")
    por_slug = {str(t.get("slug")): t for t in (bruto.get("traducoes") if isinstance(bruto, dict) else []) or []
                if isinstance(t, dict)}
    saida = []
    for e in pendentes:
        t = por_slug.get(e.slug) or {}
        saida.append({"slug": e.slug, "empresa": e.meta["empresa"], "cargo_original": e.meta["cargo"],
                      "cargo": str(t.get("cargo", "")).strip(), "local_original": e.meta.get("local", ""),
                      "local": str(t.get("local", "")).strip()})
    return saida


def aplicar_traducoes(kb: KB, idioma: str, confirmadas: list[dict]) -> int:
    """Grava as traduções que a pessoa confirmou (cargo vazio = não confirmou, ignora)."""
    n = 0
    for t in confirmadas:
        if str(t.get("cargo", "")).strip():
            kb.definir_traducao(t["slug"], idioma, t["cargo"], t.get("local", ""))
            n += 1
    return n


# -------------------------------------------------- uso manual: python -m src.tailor
if __name__ == "__main__":  # pragma: no cover
    import sys
    from .llm import LLM, Configuracao

    if len(sys.argv) < 3:
        sys.exit("Uso: python -m src.tailor arquivo_da_vaga.txt pt|en [pasta_da_base]")
    config.carregar_env()
    from pathlib import Path
    base = Path(sys.argv[3]) if len(sys.argv) > 3 else config.base_dir()
    kb = KB(base)
    llm = LLM(Configuracao.do_ambiente(), segredos=kb.segredos())
    vaga = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    cfg = config.carregar_config()
    analise = analisar(llm, kb, vaga)
    print(json.dumps(analise, ensure_ascii=False, indent=1))
    res = gerar(llm, kb, vaga, analise, sys.argv[2], cfg)
    print("\n" + "=" * 60 + "\n" + res.curriculo.markdown)
    print("ALERTAS:", *res.curriculo.alertas, sep="\n- ")
    print("\nCOBERTURA:", json.dumps(res.cobertura, ensure_ascii=False, indent=1))
