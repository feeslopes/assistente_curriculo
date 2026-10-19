"""Currículo sob medida: interface Streamlit.

Fina de propósito: a lógica de negócio fica em src/ e cada tela em interface/. Regra de ouro do produto: nada
entra no currículo sem uma informação que a pessoa confirmou. As regras são impostas em src/render.py.

Organização da tela, pensada para quem nunca usou:
- primeiro uso: boas-vindas, com "envie o seu currículo" como caminho principal;
- depois, o Início (o que fazer agora e como andam as candidaturas) e as áreas Novo currículo, Minhas candidaturas
  e Meu histórico;
- configurações técnicas num botão discreto no canto.
"""
from __future__ import annotations

import streamlit as st

from interface import comum, estilo, inicio, painel, perfil, vaga, vagas
from src import atualizador, config, exemplo
from src.kb import KB


def configuracoes(kb: KB, cfg_provedor, config_erro: str | None) -> None:
    with st.popover("", icon=":material/settings:", help="Configurações"):
        st.markdown("**Configurações**")
        if cfg_provedor:
            st.caption(f"IA: {cfg_provedor.nome_provedor} · modelo {cfg_provedor.modelo}")
            if st.button("Testar a conexão com a IA", key="btn_testar"):
                r = comum.executar("Testando...", lambda: comum.obter_llm(kb).conversar(
                    [{"role": "user", "content": "Responda somente com a palavra OK."}], temperatura=0))
                if r is not comum.FALHOU:
                    st.success("Funcionando.")
        else:
            st.warning(config_erro)
        st.caption(f"Versão instalada: {atualizador.versao_local(config.RAIZ)}. Versões novas são instaladas "
                   "sozinhas ao abrir pelo iniciar.")
        st.caption(f"Seu histórico: {kb.base}")
        st.caption(f"Currículos gerados: {config.saidas_dir()}")
        if kb.vazia() and st.button("Carregar dados de exemplo", key="btn_exemplo_cfg"):
            exemplo.copiar_exemplo(kb)
            st.session_state["base_v"] += 1
            comum.ir_para("historico", vista="visao")
            st.rerun()


def aviso_revisao_pendente() -> None:
    """Uma leitura de currículo esperando conferência aparece em qualquer área, com atalho."""
    if st.session_state["rev_importacao"] and st.session_state["area"] != "historico":
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.warning("O seu currículo foi lido e está esperando você conferir.", icon=":material/pending_actions:")
        if c2.button("Conferir agora", key="btn_ir_revisao", type="primary"):
            comum.ir_para("historico")
            st.rerun()


def main() -> None:
    cfg_provedor, config_erro = comum.configuracao_do_provedor()
    st.set_page_config(page_title="Currículo sob medida", page_icon=":material/description:", layout="wide",
                       initial_sidebar_state="collapsed")
    comum.estado_inicial()
    estilo.aplicar_css()
    kb = KB(config.base_dir())
    cfg = config.carregar_config()
    try:
        primeiro_uso = inicio.deve_mostrar(kb)
        topo = st.columns([2.2, 5, 0.5], vertical_alignment="center")
        topo[0].markdown('<div class="marca"><b>Currículo sob medida</b></div>', unsafe_allow_html=True)
        if not primeiro_uso:
            with topo[1]:
                st.segmented_control("Área", list(comum.AREAS), format_func=comum.AREAS.get, key="area",
                                     label_visibility="collapsed", on_change=comum.sem_desmarcar("area"))
        with topo[2]:
            configuracoes(kb, cfg_provedor, config_erro)
        comum.mostrar_mensagem()
        if primeiro_uso:
            inicio.boas_vindas(kb, config_erro)
            return
        aviso_revisao_pendente()
        area = st.session_state.get("area") or "inicio"
        if area == "inicio":
            painel.area(kb, cfg, config_erro)
        elif area == "vaga":
            vaga.area(kb, cfg, config_erro)
        elif area == "vagas":
            vagas.area()
        else:
            perfil.area(kb, cfg, config_erro)
    finally:
        # o finally também roda quando st.rerun() interrompe o script: nada digitado se perde
        comum.persistir(kb)


if __name__ == "__main__":
    main()
