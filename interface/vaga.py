"""Currículo para uma vaga, em três passos: a vaga, o encaixe com o histórico e o currículo.

Só o passo atual aparece por inteiro. O resultado tem um bloco único de aderência (número e gráfico) e, abaixo,
quatro vistas: o currículo, o que mudou, como melhorar e o que conferir antes de enviar.
"""
from __future__ import annotations

import hashlib

import streamlit as st

from src import aderencia, config, export, historico, relatorio, saidas, tailor
from src.kb import KB
from src.texto import ler_arquivo

from . import comum, estilo, revisao

PASSOS = ["A vaga", "Encaixe com o seu histórico", "Currículo"]
STATUS = {"coberto": (":green[:material/check_circle:]", "Comprovado"),
          "parcial": (":orange[:material/radio_button_partial:]", "Em parte"),
          "lacuna": (":gray[:material/cancel:]", "Não aparece no seu histórico")}
ROTULO_COMPONENTE = {"palavras": "Palavras-chave", "obrigatorios": "Obrigatórios", "desejaveis": "Desejáveis",
                     "estrutura": "Formato"}
VISTAS = {"curriculo": ":material/description: Currículo", "mudou": ":material/compare_arrows: O que mudou",
          "melhorar": ":material/trending_up: Como melhorar", "conferir": ":material/fact_check: Conferir antes de enviar"}


# ------------------------------------------------------------------ passo 1: a vaga

def analisar_vaga(kb: KB, vaga: str) -> bool:
    analise = comum.executar("Lendo a vaga e comparando com o seu histórico...", lambda: tailor.analisar(
        comum.obter_llm(kb), kb, vaga))
    if analise is comum.FALHOU:
        return False
    st.session_state["analise_id"] += 1
    st.session_state.update(analise=analise, vaga_analisada=vaga, resultado=None, trad=None, rev_lacuna=None,
                            passo_vaga=2)
    return True


def passo_vaga(kb: KB) -> None:
    if st.session_state["rev_importacao"] or st.session_state["rev_entrevista"]:
        st.warning("Há informações esperando você conferir em **Meu histórico**. Enquanto não forem salvas, a "
                   "comparação com a vaga não as enxerga.", icon=":material/info:")
    avisos = kb.diagnostico()
    if avisos:
        with st.container(border=True):
            st.markdown("**:material/info: Antes de começar**")
            st.markdown("\n".join(f"- {a}" for a in avisos))
    escrito = st.text_area("Cole aqui o texto completo da vaga", height=260, key="vaga_texto",
                           placeholder="Título, empresa, responsabilidades, requisitos... Quanto mais completo, melhor.")
    arq = st.file_uploader("Ou envie a vaga em arquivo", type=comum.TIPOS_ARQUIVO, key="vaga_arquivo")
    vaga = escrito.strip() or (ler_arquivo(arq.name, arq.getvalue()) if arq is not None else "")
    st.caption("O app não abre links de vaga (os sites bloqueiam). Copie e cole o texto.")
    if st.button("Analisar vaga", key="btn_analisar", type="primary", disabled=not vaga, icon=":material/search:"):
        if analisar_vaga(kb, vaga):
            st.rerun()


# ------------------------------------------------------------------ passo 2: encaixe

def cabecalho_vaga(analise: dict, voltar_para: int, rotulo: str) -> None:
    c1, c2 = st.columns([5, 1.4], vertical_alignment="center")
    titulo = analise["titulo_vaga"] or "Vaga"
    c1.markdown(f"**{titulo}**" + (f" · {analise['empresa']}" if analise["empresa"] else ""))
    if c2.button(rotulo, key=f"btn_voltar_{voltar_para}", type="tertiary", icon=":material/arrow_back:"):
        st.session_state["passo_vaga"] = voltar_para
        if voltar_para == 1:
            st.session_state.update(analise=None, resultado=None)
        st.rerun()


def resumo_encaixe(analise: dict) -> str:
    def conta(tipo):
        rs = [r for r in analise["requisitos"] if r["tipo"] == tipo]
        return sum(r["status"] == "coberto" for r in rs), len(rs)
    co, to = conta("obrigatorio")
    cd, td = conta("desejavel")
    partes = []
    if to:
        partes.append(f"**{co} de {to}** requisitos obrigatórios")
    if td:
        partes.append(f"**{cd} de {td}** desejáveis")
    return ("O seu histórico comprova " + " e ".join(partes) + ".") if partes else "A vaga não lista requisitos claros."


def pontuacao_de_hoje(kb: KB, analise: dict) -> None:
    """A pontuação do currículo sem adaptar, antes de gerar: a régua que a versão adaptada não pode ficar abaixo."""
    chave = f"orig_{st.session_state['analise_id']}"
    if chave not in st.session_state:
        st.session_state[chave] = aderencia.indice_original(kb, analise, config.carregar_config())["indice"]
    ind = st.session_state[chave]
    c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")
    c1.metric("Seu currículo hoje, para esta vaga", f"{ind['total']} de 100",
              help="O currículo montado com o seu histórico, sem nenhuma adaptação, medido com a régua desta vaga.")
    c2.metric("Máximo com o seu histórico", f"{ind['teto']} de 100",
              help="Até onde dá para chegar adaptando o texto. Acima disso, só com informações novas e verdadeiras.")
    if ind["total"] >= ind["teto"] - 2:
        c3.caption("O seu histórico já aparece quase todo no currículo de hoje. Adaptar vai organizar o texto e usar as "
                   "palavras da vaga, mas o número só sobe com informações novas e verdadeiras: responda às perguntas abaixo.")
    else:
        c3.caption("Ao gerar, você vê quanto a adaptação melhora este número. A versão adaptada nunca fica abaixo da de "
                   "hoje sem você ser avisada.")


def passo_encaixe(kb: KB, analise: dict) -> None:
    cabecalho_vaga(analise, 1, "Trocar de vaga")
    props = st.session_state["rev_lacuna"]
    if props:
        st.markdown("### Confira o que entendi das suas respostas")
        r = revisao.formulario("lac", props, st.session_state["rev_id"], kb)
        if r:
            st.session_state["rev_lacuna"] = None
            comum.avisar("success", revisao.resumo(r) + " Encaixe atualizado com o seu histórico novo.")
            analisar_vaga(kb, st.session_state["vaga_analisada"])
            st.rerun()
        if st.button("Descartar respostas", key="btn_descartar_lac", type="tertiary"):
            st.session_state["rev_lacuna"] = None
            st.rerun()
        return

    st.markdown(resumo_encaixe(analise))
    pontuacao_de_hoje(kb, analise)
    obrig = [r for r in analise["requisitos"] if r["tipo"] == "obrigatorio"]
    if obrig and sum(r["status"] != "lacuna" for r in obrig) / len(obrig) < 0.25:
        st.warning("Esta vaga pede quase nada do que o seu histórico mostra. Se você tem experiências que não contou, "
                   "responda abaixo. Se não tem, um currículo para esta vaga vai sair fraco, e talvez valha procurar "
                   "vagas mais próximas do que você já fez.", icon=":material/report:")
    if analise["observacoes"]:
        st.info(f"**Leitura da IA** (opinião, não fato): {analise['observacoes']}", icon=":material/smart_toy:")
    st.caption("**Comprovado** quer dizer que há no seu histórico uma informação confirmada que mostra isso. "
               "Onde não há, eu pergunto: responda só o que for verdade.")
    aid = st.session_state["analise_id"]
    perguntas = []
    for tipo, titulo in (("obrigatorio", "Obrigatórios"), ("desejavel", "Desejáveis")):
        reqs = [r for r in analise["requisitos"] if r["tipo"] == tipo]
        if not reqs:
            continue
        with st.container(border=True):
            st.markdown(f"**{titulo}**")
            for r in sorted(reqs, key=lambda r: ["lacuna", "parcial", "coberto"].index(r["status"])):
                icone, nome = STATUS[r["status"]]
                st.markdown(f"{icone} {r['requisito']}  \n:gray[{nome}]")
                if r["status"] != "coberto" and r["pergunta"]:
                    i = len(perguntas)
                    perguntas.append(r)
                    c1, c2 = st.columns([4, 1.3], vertical_alignment="bottom")
                    c1.text_input(r["pergunta"], key=f"lac_{aid}_{i}", placeholder="Se você fez, conte em uma ou duas frases")
                    c2.checkbox("Não tenho", key=f"lacnao_{aid}_{i}")
    if perguntas:
        respondidas = [(r["pergunta"], st.session_state.get(f"lac_{aid}_{i}", ""), bool(st.session_state.get(f"lacnao_{aid}_{i}")))
                       for i, r in enumerate(perguntas)]
        tem = any(txt.strip() and not nao for _, txt, nao in respondidas)
        if st.button("Salvar respostas e atualizar o encaixe", key="btn_lacunas", disabled=not tem,
                     icon=":material/refresh:"):
            props = comum.executar("Lendo as suas respostas...", lambda: tailor.extrair_respostas(
                comum.obter_llm(kb), kb, respondidas))
            if props is not comum.FALHOU:
                st.session_state["rev_id"] += 1
                st.session_state["rev_lacuna"] = props or None
                if not props:
                    comum.avisar("info", "Nenhuma resposta para registrar.")
                st.rerun()

    base = [p["termo"] for p in analise.get("palavras_chave_base", [])]
    sem = [p for p in analise["palavras_chave"] if p.lower() not in {b.lower() for b in base}]
    if base or sem:
        with st.container(border=True):
            st.markdown("**Palavras-chave da vaga**")
            st.caption("Sistemas de triagem procuram estas palavras. As verdes estão no seu histórico e vão para o "
                       "currículo. As cinzas só entram se você tiver essa experiência e contar acima.")
            estilo.etiquetas(base, "ok")
            estilo.etiquetas(sem, "nao")
    if st.button("Continuar: montar o currículo", key="btn_para_gerar", type="primary", icon=":material/arrow_forward:"):
        st.session_state["passo_vaga"] = 3
        st.rerun()


# ------------------------------------------------------------------ passo 3: currículo

def secao_traducao(kb: KB, idioma: str) -> None:
    """Cargos sem tradução: a IA sugere, ela confirma."""
    if idioma == kb.idioma_base():
        return
    pendentes = [e for e in kb.experiencias() if not e.meta.get(f"cargo_{idioma}")]
    if not pendentes:
        return
    nome = {"pt": "português", "en": "inglês"}[idioma]
    with st.container(border=True):
        st.markdown(f"**:material/translate: Como os seus cargos aparecem em {nome}**")
        st.caption("Os cargos estão em outro idioma no seu histórico. Eu sugiro a tradução, você corrige se precisar e "
                   "confirma. Ela fica guardada para as próximas vagas.")
        trad = st.session_state["trad"]
        if trad is None or trad["idioma"] != idioma:
            if st.button("Sugerir traduções", key="btn_sugerir_trad", icon=":material/auto_awesome:"):
                sug = comum.executar("Sugerindo traduções...", lambda: tailor.sugerir_traducoes(
                    comum.obter_llm(kb), kb, idioma))
                if sug is not comum.FALHOU:
                    st.session_state["trad_id"] += 1
                    st.session_state["trad"] = {"idioma": idioma, "itens": sug}
                    st.rerun()
            st.caption("Sem confirmar, os cargos ficam no idioma original.")
            return
        tid = st.session_state["trad_id"]
        for s in trad["itens"]:
            c1, c2 = st.columns(2)
            c1.text_input(f"{s['cargo_original']} ({s['empresa']})", s["cargo"], key=f"trad_{tid}_{s['slug']}_c")
            c2.text_input(f"Local: {s['local_original'] or 'sem local'}", s["local"], key=f"trad_{tid}_{s['slug']}_l")
        if st.button("Confirmar traduções", key="btn_confirmar_trad", icon=":material/check:"):
            confirmadas = [{"slug": s["slug"], "cargo": st.session_state.get(f"trad_{tid}_{s['slug']}_c", ""),
                            "local": st.session_state.get(f"trad_{tid}_{s['slug']}_l", "")} for s in trad["itens"]]
            n = comum.executar("Salvando...", tailor.aplicar_traducoes, kb, idioma, confirmadas)
            if n is not comum.FALHOU:
                st.session_state["trad"] = None
                comum.avisar("success", f"{n} tradução(ões) confirmada(s).")
                st.rerun()


def _pasta_da_vaga(vaga: str):
    chave = hashlib.sha1(vaga.encode("utf-8")).hexdigest()[:12]
    return chave, st.session_state["pastas_por_vaga"].get(chave)


def _salvar(kb: KB, res, markdown: str, comp: dict | None) -> None:
    """Grava a candidatura na pasta desta vaga (cria na primeira vez, regrava depois)."""
    analise, vaga = st.session_state["analise"], st.session_state["vaga_analisada"]
    pdf, _ = export.gerar_pdf(markdown)
    docx = export.gerar_docx(markdown)
    chave, pasta = _pasta_da_vaga(vaga)
    nome = saidas.nome_do_arquivo(kb.contato().get("nome", ""), res.aderencia.get("idioma_depois", "pt"))
    pasta = saidas.salvar_saida(markdown, pdf, docx, vaga, analise, pasta=pasta, nome_arquivo=nome,
                                relatorio=relatorio.para_markdown(res.relatorio) if res.relatorio else None,
                                indice=historico.dados_do_indice(analise, comp) if comp else None)
    st.session_state["pastas_por_vaga"][chave] = pasta
    st.session_state["md_salvo"] = markdown


def opcoes_e_gerar(kb: KB, cfg: dict, analise: dict) -> None:
    vaga = st.session_state["vaga_analisada"]
    aid = st.session_state["analise_id"]
    recomendado = tailor.recomendar_idioma(vaga, analise, cfg)
    with st.container(border=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            idioma = st.segmented_control("Idioma do currículo", ["pt", "en"], default=recomendado, key=f"idioma_{aid}",
                                          format_func=lambda x: "Português" if x == "pt" else "Inglês") or recomendado
            st.caption(f"A vaga está em {'português' if recomendado == 'pt' else 'inglês'}.")
        titulo = c2.text_input("Título abaixo do seu nome (opcional)", key=f"titulo_{aid}",
                               placeholder="Deixe vazio para usar um cargo do seu histórico")
        detalhe = tailor.limites_por_experiencia(kb, cfg, analise)
        manuais: dict[str, int] = {}
        with st.expander("Ajustar o espaço de cada experiência (opcional)"):
            st.caption("O app dá mais espaço às experiências recentes e às que mais combinam com a vaga, e resume as "
                       "antigas. Mude se quiser: 0 mostra só o cargo, a empresa e as datas.")
            for e in kb.experiencias():
                d = detalhe[e.slug]
                manuais[e.slug] = int(st.number_input(f"{d['rotulo']}: {d['motivo']}", min_value=0, max_value=8,
                                                      value=int(d["limite"]), step=1, key=f"lim_{aid}_{e.slug}"))
    secao_traducao(kb, idioma)
    contato = kb.contato()
    if not contato.get("nome") or not (contato.get("email") or contato.get("telefone")):
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.warning("Faltam seu nome ou seu contato. O currículo vai sair sem esses dados no topo.", icon=":material/badge:")
        if c2.button("Preencher agora", key="btn_dados_antes_de_gerar"):
            comum.ir_para("historico", vista="dados")
            st.rerun()
    if st.button("Gerar currículo", key="btn_gerar", type="primary", icon=":material/auto_awesome:"):
        res = comum.executar("Escrevendo e conferindo o currículo. Isso leva cerca de um minuto...", lambda: tailor.gerar(
            comum.obter_llm(kb), kb, vaga, analise, idioma, cfg, titulo or None, True, manuais))
        if res is not comum.FALHOU:
            st.session_state["gen_id"] += 1
            st.session_state["resultado"] = res
            st.session_state["_vista_res"] = "curriculo"
            # o texto fica numa chave própria, fora do editor: o Streamlit apaga o estado de um campo que sai da tela
            st.session_state[f"texto_{st.session_state['gen_id']}"] = res.curriculo.markdown
            _salvar(kb, res, res.curriculo.markdown, res.aderencia or None)
            st.rerun()


def bloco_aderencia(comp: dict) -> None:
    antes, depois = comp["antes"], comp["depois"]
    with st.container(border=True):
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        with c1:
            ganho = depois["total"] - antes["total"]
            st.metric("Aderência à vaga", f"{depois['total']} de 100", delta=f"{ganho:+d} com a adaptação",
                      delta_color="normal" if ganho > 0 else ("off" if ganho == 0 else "inverse"))
            st.caption(f"Seu currículo sem adaptar: **{antes['total']}**.  \nMáximo com o seu histórico atual: "
                       f"**{depois['teto']}**.")
            with st.popover("O que é esse número?", icon=":material/help:"):
                st.markdown(
                    "É um índice nosso, de 0 a 100, que mede o quanto o currículo mostra o que a vaga pede:\n\n"
                    "- **Palavras-chave** (45%): termos da vaga que o seu histórico comprova e que aparecem no texto.\n"
                    "- **Obrigatórios** (30%) e **Desejáveis** (10%): requisitos cuja comprovação está no texto.\n"
                    "- **Formato** (15%): seções que os sistemas de triagem reconhecem, contato e número de páginas.\n\n"
                    "Não é a nota de nenhum sistema de recrutamento (essas notas não são públicas). E **não sobe por "
                    "inventar**: o que o seu histórico não comprova não conta.")
            if comp["idioma_antes"] != comp["idioma_depois"] and ganho > 0:
                st.caption("O currículo sem adaptar está em outro idioma, então parte da diferença é a tradução.")
            elif ganho <= 0 and depois["teto"] < 40:
                st.caption("A vaga pede pouco do que o seu histórico mostra, então adaptar o texto não muda muito. "
                           "Veja o que falta em **Como melhorar**.")
            elif ganho <= 0 and depois["total"] >= depois["teto"] - 2:
                st.caption("A adaptação não mudou o número porque o seu histórico já aparece quase todo. Para subir, "
                           "só com informações novas e verdadeiras: veja **Como melhorar**.")
            elif ganho <= 0:
                st.caption("Desta vez a adaptação não aumentou o número. Veja em **Como melhorar** o que o seu histórico "
                           "já tem e o texto não usou.")
        with c2:
            chaves = list(depois["componentes"])
            estilo.grafico_antes_depois(
                [ROTULO_COMPONENTE[k] for k in chaves],
                [100 * antes["componentes"].get(k, {}).get("fracao", 0) for k in chaves],
                [100 * depois["componentes"][k]["fracao"] for k in chaves], altura=260)


def vista_curriculo(kb: KB, res, cfg: dict, texto_atual: str, comp: dict | None) -> None:
    gid = st.session_state["gen_id"]
    try:
        pdf, paginas = export.gerar_pdf(texto_atual)
        docx = export.gerar_docx(texto_atual)
    except Exception as e:  # texto editado com algo que o exportador não aguenta
        st.error(f"Não consegui montar o PDF ou o Word com este texto ({type(e).__name__}). Revise a formatação.")
        pdf = docx = None
        paginas = 0
    nome = saidas.nome_do_arquivo(kb.contato().get("nome", ""), res.aderencia.get("idioma_depois", "pt") if res.aderencia else "pt")
    _, pasta = _pasta_da_vaga(st.session_state["vaga_analisada"])
    barra = st.container(horizontal=True, vertical_alignment="center")
    if pdf:
        barra.download_button("Baixar PDF", pdf, file_name=f"{nome}.pdf", mime="application/pdf", key="dl_pdf",
                              type="primary", icon=":material/download:")
        barra.download_button("Baixar Word", docx, file_name=f"{nome}.docx", key="dl_docx", icon=":material/download:",
                              mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if pasta and barra.button("Abrir a pasta", key="btn_abrir_pasta", icon=":material/folder_open:"):
        if not comum.abrir_pasta(pasta):
            st.info(f"A pasta fica em: {pasta}")
    limite = int(cfg.get("max_paginas", 2))
    info = f"{paginas} página(s)." if paginas <= limite else f"**{paginas} páginas**: passa do limite de {limite}. Corte algum trecho."
    if pasta:
        info += f" Guardado em Minhas vagas, na pasta **{pasta.name}**."
    st.caption(info)
    editar = st.toggle("Editar o texto", key=f"editar_{gid}")
    if editar:
        st.caption("O PDF e o Word saem deste texto. `**negrito**`, `_itálico_` e linhas começando com `* ` viram lista.")
        chave = f"editor_{gid}_{st.session_state.get(f'versao_{gid}', 0)}"

        def guardar() -> None:
            st.session_state[f"texto_{gid}"] = st.session_state[chave]
        novo = st.text_area("Texto do currículo", value=texto_atual, height=560, key=chave,
                            label_visibility="collapsed", on_change=guardar)
        if novo != texto_atual:
            st.session_state[f"texto_{gid}"] = texto_atual = novo
    else:
        with st.container(border=True, key="previa"):
            st.markdown(texto_atual)
    if texto_atual != st.session_state.get("md_salvo") and pdf:
        if st.button("Guardar esta versão em Minhas vagas", key="btn_salvar_edicao", icon=":material/save:"):
            _salvar(kb, res, texto_atual, comp)
            comum.avisar("success", "Esta versão foi guardada em Minhas vagas.")
            st.rerun()


def vista_melhorar(res, comp: dict | None) -> None:
    if comp:
        st.info(comp["aviso"], icon=":material/verified_user:")
        if not comp["melhorias"]:
            st.write("Com o que o seu histórico tem hoje, não há o que melhorar.")
        for m in comp["melhorias"]:
            with st.container(border=True):
                ganho = "" if not m["ganho"] else (f" :green-badge[+{m['ganho']} pontos]" if m["tipo"] != "confirmar"
                                                   else f" :orange-badge[até +{m['ganho']} pontos, só se for verdade]")
                st.markdown(f"**{m['titulo']}**{ganho}")
                st.caption(m["detalhe"])
                if m["tipo"] == "estrutura":
                    st.markdown("\n".join(f"- {x}" for x in m["itens"]))
                else:
                    estilo.etiquetas(m["itens"], "tem" if m["tipo"] == "usar_base" else "nao")
    cob = res.cobertura
    with st.container(border=True):
        st.markdown("**Palavras-chave da vaga neste currículo**")
        st.caption("Verde: no currículo e comprovadas. Amarelo: o seu histórico tem, mas o texto não usou. "
                   "Cinza: não estão no seu histórico, e por isso ficaram de fora.")
        estilo.etiquetas(cob["usadas"] + cob["usadas_indeterminadas"], "ok")
        estilo.etiquetas(cob["fora_com_base"], "tem")
        estilo.etiquetas(cob["fora_sem_base"] + cob["fora_indeterminadas"], "nao")
        if cob["usadas_sem_base"]:
            st.warning("Aparecem no currículo, mas o seu histórico não comprova. Confira: "
                       + ", ".join(cob["usadas_sem_base"]), icon=":material/warning:")


def vista_conferir(kb: KB, res) -> None:
    cv = res.curriculo
    if not res.verificacao_ia:
        st.warning("A segunda verificação por IA não rodou desta vez. Leia o texto com mais atenção.", icon=":material/warning:")
    if cv.alertas:
        st.caption("Pontos que o app encontrou. Nenhum é bloqueio, mas leia antes de enviar.")
        for a in cv.alertas:
            st.warning(a, icon=":material/flag:")
    else:
        st.success("Nada a apontar. Ainda assim, leia o currículo inteiro antes de enviar.", icon=":material/check:")
    if cv.removidos:
        with st.container(border=True):
            st.markdown(f"**Tirado do currículo por falta de comprovação ({len(cv.removidos)})**")
            st.caption("A IA escreveu, mas o seu histórico não sustenta. Se for verdade, acrescente em Meu histórico.")
            st.markdown("\n".join(f"- {r['texto']} :gray[({r['secao']})]" for r in cv.removidos))
    with st.expander("De onde veio cada frase"):
        st.caption("Cada item do currículo e as informações do seu histórico que o sustentam.")
        textos = {f.id: f.texto for f in kb.fatos("confirmado")}
        for r in cv.rastro:
            origem = "; ".join(textos.get(f, f) for f in r["fontes_validas"]) or "sem comprovação"
            st.markdown(f"- {r['texto']}  \n  :gray[{origem}]")


def resultado(kb: KB, cfg: dict) -> None:
    res = st.session_state["resultado"]
    gid = st.session_state["gen_id"]
    cv = res.curriculo
    analise = st.session_state["analise"]
    texto_atual = st.session_state.get(f"texto_{gid}") or cv.markdown
    usando_original = bool(res.aderencia) and texto_atual == res.aderencia.get("markdown_antes")
    rastro = res.aderencia.get("rastro_antes", cv.rastro) if usando_original else cv.rastro
    comp = None
    if res.aderencia:
        try:
            paginas = export.gerar_pdf(texto_atual)[1]
        except Exception:
            paginas = None
        idioma_atual = res.aderencia["idioma_antes"] if usando_original else res.aderencia["idioma_depois"]
        depois = aderencia.calcular(analise, texto_atual, rastro, kb, cfg, idioma_atual, paginas,
                                    res.trechos_suspeitos, res.termos_rejeitados)
        comp = {**res.aderencia, "depois": depois, "melhorias": aderencia.melhorias(analise, depois)}
        bloco_aderencia(comp)
        if usando_original:
            st.info("Você está usando a versão sem adaptar.", icon=":material/undo:")
        elif res.abaixo_do_original:
            c1, c2 = st.columns([3, 1.3], vertical_alignment="center")
            c1.warning("Mesmo depois de refeita, a versão adaptada ficou abaixo do seu currículo sem adaptar. Você pode "
                       "usar a versão sem adaptar, ou gerar de novo com outras opções.", icon=":material/warning:")
            if c2.button("Usar a versão sem adaptar", key="btn_usar_original", icon=":material/undo:"):
                st.session_state[f"texto_{gid}"] = res.aderencia["markdown_antes"]
                st.session_state[f"versao_{gid}"] = st.session_state.get(f"versao_{gid}", 0) + 1   # editor novo
                st.rerun()
        elif res.segunda_tentativa:
            st.caption(":material/autorenew: A primeira versão ficou abaixo do seu currículo sem adaptar, então eu refiz "
                       "uma vez pedindo de volta o que tinha ficado de fora.")
    if "_vista_res" in st.session_state:
        st.session_state["vista_resultado"] = st.session_state.pop("_vista_res")
    rotulos = dict(VISTAS)
    if cv.alertas:
        rotulos["conferir"] += f" ({len(cv.alertas)})"
    vista = st.segmented_control("Ver", list(rotulos), format_func=rotulos.get, key="vista_resultado",
                                 label_visibility="collapsed", on_change=comum.sem_desmarcar("vista_resultado")) or "curriculo"
    if vista == "mudou" and res.relatorio:
        st.download_button("Baixar este relatório", relatorio.para_markdown(res.relatorio), file_name="relatorio.md",
                           mime="text/markdown", key="dl_relatorio", icon=":material/download:")
        st.markdown(relatorio.para_markdown(res.relatorio, com_titulo=False))
    elif vista == "melhorar":
        vista_melhorar(res, comp)
    elif vista == "conferir":
        vista_conferir(kb, res)
    else:
        vista_curriculo(kb, res, cfg, texto_atual, comp)
    st.divider()
    fim = st.container(horizontal=True)
    if fim.button("Mudar opções e gerar de novo", key="btn_gerar_de_novo", icon=":material/tune:"):
        st.session_state["resultado"] = None
        st.rerun()
    if fim.button("Fazer para outra vaga", key="btn_outra_vaga", icon=":material/add:"):
        st.session_state.update(analise=None, resultado=None, passo_vaga=1, vaga_texto="")
        st.rerun()


def passo_curriculo(kb: KB, cfg: dict, analise: dict) -> None:
    cabecalho_vaga(analise, 2, "Voltar ao encaixe")
    if st.session_state["resultado"] is None:
        opcoes_e_gerar(kb, cfg, analise)
    else:
        resultado(kb, cfg)


# ------------------------------------------------------------------ área

def area(kb: KB, cfg: dict, config_erro: str | None) -> None:
    st.markdown("### Currículo para uma vaga")
    if config_erro:
        comum.tela_sem_ia(config_erro)
        return
    if not kb.ids_confirmados():
        st.info("Primeiro, monte o seu histórico em **Meu histórico**: é dele que saem os currículos.",
                icon=":material/arrow_back:")
        return
    analise = st.session_state["analise"]
    passo = st.session_state["passo_vaga"] if analise else 1
    estilo.passos(PASSOS, passo)
    if passo == 1:
        passo_vaga(kb)
    elif passo == 2:
        passo_encaixe(kb, analise)
    else:
        passo_curriculo(kb, cfg, analise)
