"""Currículo por vaga: análise, perguntas de lacuna e geração."""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import config, interview, render
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
    idioma = str(a.get("idioma_vaga", "")).strip().lower()
    return {
        "titulo_vaga": str(a.get("titulo_vaga", "")).strip(),
        "empresa": str(a.get("empresa", "")).strip(),
        "idioma_vaga": idioma if idioma in ("pt", "en", "es", "outro") else "outro",
        "palavras_chave": palavras[:25],
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

def _limites(cfg: dict, kb: KB) -> str:
    por_exp = ", ".join(
        f"{e.slug}={render._limite_bullets(cfg, i)}" for i, e in enumerate(kb.experiencias()))
    return (
        "# Limites desta geração\n"
        f"- Resumo: no máximo {cfg['resumo_max_palavras']} palavras.\n"
        f"- Competências: no máximo {cfg['max_grupos_competencias']} grupos.\n"
        f"- Máximo de bullets por experiência: {por_exp or '(nenhuma)'}.\n"
        "O sistema corta o que passar desses limites."
    )


def _analise_para_prompt(analise: dict) -> str:
    enxuta = {
        "titulo_vaga": analise.get("titulo_vaga"),
        "palavras_chave": analise.get("palavras_chave"),
        "requisitos": [{k: r[k] for k in ("requisito", "tipo", "status", "evidencias")}
                       for r in analise.get("requisitos", [])],
    }
    return json.dumps(enxuta, ensure_ascii=False, indent=1)


def gerar(llm, kb: KB, vaga: str, analise: dict, idioma: str, cfg: dict | None = None,
          titulo_usuario: str | None = None, verificar_ia: bool = True) -> Resultado:
    cfg = cfg or config.carregar_config()
    if not kb.ids_confirmados():
        raise ErroBase("A base não tem fatos confirmados para gerar um currículo.")
    sistema = "\n\n".join([config.ler_prompt("gerador"),
                           "# Guidelines de escrita\n" + config.ler_guidelines(),
                           _limites(cfg, kb)])
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
    cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, fiscal="pendente" if verificar_ia else "ausente")
    cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
    verificou = False
    pendentes = cob["fora_indeterminadas"] + cob["usadas_indeterminadas"]
    if verificar_ia and (cv.itens_fiscal or pendentes):
        try:
            v = verificar_com_ia(llm, kb, cv.itens_fiscal, pendentes, palavras)
            verificou = True
            if v["problemas"]:
                # Segunda montagem, sem IA: o código aplica o veredito (remove termos, alerta frases).
                cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, veredito=v["problemas"], fiscal="ok")
                cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
            _resolver_indeterminadas(cob, v["palavras"])
        except ErroLLM as e:
            # Sem fiscal, volta à regra do código (siglas e termos julgados pelas palavras da base).
            cv = render.montar(kb, bruto, idioma, cfg, titulo_usuario, fiscal="ausente")
            cob = cobertura_palavras(palavras, cv.corpo, kb.textos_confirmados(), cv.mesmo_idioma)
            cv.alertas.append(f"A verificação por IA não rodou ({e}). Revise com atenção os termos e frases.")
    return Resultado(cv, cob, bruto if isinstance(bruto, dict) else {}, verificou)


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
    problemas = {}
    for p in bruto.get("problemas") or []:
        try:
            n = int(p.get("n"))
        except (AttributeError, TypeError, ValueError):
            continue
        if 0 <= n < len(itens) and str(p.get("problema", "")).strip():
            problemas[itens[n]["chave"]] = str(p["problema"]).strip()
    palavras = {}
    for p in bruto.get("palavras") or []:
        if isinstance(p, dict) and p.get("termo") in palavras_pendentes and isinstance(p.get("na_base"), bool):
            palavras[p["termo"]] = p["na_base"]
    return {"problemas": problemas, "palavras": palavras}


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
