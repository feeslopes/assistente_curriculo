"""Primeiro uso: boas-vindas e leitura do currículo atual.

O caminho mais curto é começar pelo currículo que a pessoa já tem: o app lê, preenche os dados pessoais
(localmente, sem IA) e mostra tudo para ela conferir. Conversar fica como alternativa e como complemento.
"""
from __future__ import annotations

import streamlit as st

from src import config, exemplo, interview
from src.kb import KB
from src.texto import ErroArquivo, detectar_idioma, extrair_contato_local, ler_arquivo, palpite_nome

from . import comum, estilo

ETAPAS = ["Envie seu currículo", "Confira o que eu entendi", "Gere um currículo para cada vaga"]


def deve_mostrar(kb: KB) -> bool:
    s = st.session_state
    return kb.vazia() and not s["rev_importacao"] and not s["rev_entrevista"] and not s["chat"] \
        and not s["comecar_conversando"]


def importar_curriculo(kb: KB, arquivo) -> None:
    try:
        texto = ler_arquivo(arquivo.name, arquivo.getvalue())
    except ErroArquivo as e:
        st.error(str(e))
        return
    if len(texto) < 80:
        st.error("Não consegui ler o texto desse arquivo. Se for um PDF escaneado (uma imagem), envie uma versão "
                 "em Word ou um PDF exportado do editor de texto.")
        return
    # Dados pessoais: lidos aqui, por regras simples, e nunca enviados à IA. Ela confere na tela seguinte.
    achado = extrair_contato_local(texto)
    nome = palpite_nome(texto)
    if nome:
        achado["nome"] = nome
    atual = kb.contato()
    novos = {k: v for k, v in achado.items() if not atual.get(k)}
    if novos:
        kb.salvar_contato({**atual, **novos})
    try:
        llm = comum.obter_llm(kb)
    except comum.ErroConfig as e:
        st.error(str(e))
        return
    props = comum.executar("Lendo o seu currículo. Isso leva cerca de um minuto...", interview.extrair, llm, kb,
                           texto, "curriculo importado")
    if props is comum.FALHOU:
        return
    comum.evento("cv_importado", tipo=arquivo.name.lower().rsplit(".", 1)[-1][:5] if "." in arquivo.name else "txt",
                 fatos_propostos=sum(len(p.fatos) for p in props))
    st.session_state["rev_id"] += 1
    st.session_state["rev_importacao"] = props
    idioma_cv, idioma_base = detectar_idioma(texto), kb.idioma_base()
    if props and kb.fatos() and idioma_cv and idioma_cv != idioma_base:
        nomes = {"pt": "português", "en": "inglês"}
        comum.avisar("warning", f"A sua base está em {nomes[idioma_base]} e este currículo parece estar em "
                                f"{nomes[idioma_cv]}. Se for o mesmo currículo traduzido, clique em **Descartar esta "
                                "leitura**: o app já traduz na hora de gerar, e importar os dois duplicaria tudo.")
    elif not props:
        comum.avisar("warning", "Não encontrei nada novo nesse currículo.")
    comum.ir_para("historico", vista="visao")
    st.rerun()


def enviar_curriculo(kb: KB, chave: str, rotulo_botao: str = "Ler meu currículo") -> None:
    arq = st.file_uploader("Currículo em PDF, Word (DOCX), Markdown ou texto", type=comum.TIPOS_ARQUIVO, key=chave,
                           help="Envie um currículo só, em um idioma só. O app traduz na hora de gerar.")
    if st.button(rotulo_botao, key=f"btn_{chave}", type="primary", disabled=arq is None, icon=":material/upload_file:"):
        importar_curriculo(kb, arq)


def boas_vindas(kb: KB, config_erro: str | None) -> None:
    st.markdown('<div class="hero"><h1>Vamos montar o seu currículo</h1>'
                "<p>Você conta o que fez uma vez. Depois, para cada vaga, o app monta uma versão sob medida, "
                "usando só o que é verdade.</p></div>", unsafe_allow_html=True)
    estilo.passos(ETAPAS, 1)
    if config_erro:
        comum.tela_sem_ia(config_erro)
    else:
        with st.container(border=True):
            st.markdown("#### :material/description: Comece pelo currículo que você já tem")
            st.caption("Pode ser simples ou desatualizado. Eu leio, organizo e você confere tudo antes de salvar.")
            enviar_curriculo(kb, "up_inicio")
        if config.modo_hospedado():
            st.caption(":material/lock: Telefone, e-mail e links são removidos antes do envio à IA. O restante do texto "
                       "vai ao DeepSeek (servidores na China) para ser organizado. Veja os Termos e Privacidade.")
        else:
            st.caption(":material/lock: Telefone, e-mail e endereço ficam só no seu computador. O restante do texto é "
                       "enviado à IA (DeepSeek) para ser organizado.")
    st.write("")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**Não tem currículo?**")
        st.caption("Eu faço perguntas, uma de cada vez, e monto o seu histórico a partir das respostas.")
        if st.button("Começar conversando", key="btn_comecar_conversa", icon=":material/chat:",
                     disabled=bool(config_erro)):
            comum.ir_para("historico", vista="conversa", comecar_conversando=True)
            st.rerun()
    if not config.modo_hospedado():       # dados de exemplo só no app local
        with c2.container(border=True):
            st.markdown("**Só quer ver como funciona?**")
            st.caption("Carrega o histórico de uma pessoa fictícia e duas vagas de exemplo.")
            if st.button("Usar dados de exemplo", key="btn_exemplo", icon=":material/science:"):
                if exemplo.copiar_exemplo(kb):
                    st.session_state["base_v"] += 1
                    comum.avisar("success", "Dados de exemplo carregados. Veja o histórico abaixo e, depois, experimente "
                                            "uma vaga em **Novo currículo**.")
                comum.ir_para("historico", vista="visao")
                st.rerun()
