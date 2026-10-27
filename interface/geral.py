"""Currículo geral: para quando pedem um currículo sem uma vaga em mente.

Um foco opcional ("Analista de marketing digital") orienta o que entra primeiro. O caminho é o mesmo da vaga
(só informações confirmadas, fiscal por IA, alertas), sem aderência: não há vaga para comparar.
"""
from __future__ import annotations

import streamlit as st

from src import tailor
from src.kb import KB

from . import comum, vaga


def contexto() -> dict:
    s = st.session_state
    return {"analise": s.get("geral_analise"), "vaga": s.get("geral_texto", ""), "res": s.get("resultado_geral"),
            "chave_res": "resultado_geral", "geral": True}


def _foco_sugerido(kb: KB) -> str:
    """O objetivo do histórico, se houver uma linha curta, ou o cargo mais recente."""
    perfil = [f.texto for f in kb.fatos("confirmado") if f.slug == "perfil"]
    curto = next((t.rstrip(".") for t in perfil if len(t.split()) <= 8), "")
    exps = kb.experiencias()
    return curto or (exps[0].meta["cargo"] if exps else "")


def tela(kb: KB, cfg: dict) -> None:
    ctx = contexto()
    if ctx["res"] is not None:
        st.markdown(f"**Currículo geral**" + (f" · foco: {ctx['analise']['foco']}" if ctx["analise"].get("foco") else ""))
        vaga.resultado(kb, cfg, ctx)
        return
    st.caption("Para quando pedem o seu currículo sem uma vaga específica: um contato, uma indicação, um cadastro de "
               "banco de talentos. Ele mostra os seus resultados mais fortes e mais recentes.")
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        foco = c1.text_input("Foco (opcional)", value=_foco_sugerido(kb), key="geral_foco",
                             help="O tipo de posição que você busca. Ajuda a escolher o que vem primeiro.",
                             placeholder="Ex.: Analista de marketing digital")
        with c2:
            idioma = st.segmented_control("Idioma", ["pt", "en"], default=kb.idioma_base(), key="geral_idioma",
                                          format_func=lambda x: "Português" if x == "pt" else "Inglês") or kb.idioma_base()
        titulo = st.text_input("Título abaixo do seu nome (opcional)", key="geral_titulo",
                               placeholder="Deixe vazio para usar um cargo do seu histórico")
    vaga.secao_traducao(kb, idioma)
    if st.button("Gerar currículo geral", key="btn_gerar_geral", type="primary", icon=":material/auto_awesome:"):
        r = comum.executar("Escrevendo e conferindo o currículo. Isso leva cerca de um minuto...",
                           lambda: comum.gerar_com_cota(f"geral|{idioma}|{foco}", lambda: tailor.gerar_geral(
                               comum.obter_llm(kb), kb, idioma, cfg, foco, titulo or None)))
        if r is not comum.FALHOU:
            res, analise, texto = r
            st.session_state.update(resultado_geral=res, geral_analise=analise, geral_texto=texto, _vista_res="curriculo")
            st.session_state["gen_id"] += 1
            st.session_state[f"texto_{st.session_state['gen_id']}"] = res.curriculo.markdown
            vaga._salvar(kb, res, res.curriculo.markdown, None, contexto())
            st.rerun()
