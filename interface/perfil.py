"""Meu histórico: tudo o que o app sabe sobre a pessoa, à vista, e as formas de completar.

Visão geral em cartões (cada experiência com tudo o que tem dentro, sem menus escondidos), conversa para
completar o que falta, dados pessoais e uma área avançada para quem quiser editar os arquivos.
"""
from __future__ import annotations

import streamlit as st

from src import config, interview, registro
from src.kb import ARQUIVOS_FATOS, KB, ErroBase
from src.render import formatar_data

from . import comum, estilo, inicio, revisao

VISTAS = {"visao": ":material/dashboard: Visão geral", "conversa": ":material/chat: Conversar para completar",
          "dados": ":material/badge: Dados pessoais", "avancado": ":material/tune: Avançado"}
LIMITE_RESPOSTAS_SUGERIDO = 8  # depois disso o app sugere salvar o que foi contado


# ------------------------------------------------------------------ revisões que tomam a tela

def revisao_da_importacao(kb: KB) -> bool:
    """Se há um currículo lido esperando conferência, mostra só isso. Devolve True se mostrou."""
    props = st.session_state["rev_importacao"]
    if not props:
        return False
    estilo.passos(inicio.ETAPAS, 2)
    st.markdown("### Confira o que eu entendi do seu currículo")
    st.caption("Corrija o que estiver errado e desmarque o que não for verdade. Nada disso vai para um currículo "
               "antes de você salvar.")
    r = revisao.formulario("imp", props, st.session_state["rev_id"], kb, com_contato=True)
    if r:
        st.session_state["rev_importacao"] = None
        comum.avisar("success", revisao.resumo(r) + " Agora é só escolher uma vaga, ou completar o que falta.")
        st.session_state["_vista"] = "visao"
        st.rerun()
    if st.button("Descartar esta leitura", key="btn_descartar_imp", type="tertiary", icon=":material/delete:"):
        st.session_state["rev_importacao"] = None
        st.rerun()
    return True


# ------------------------------------------------------------------ visão geral

def _periodo(meta: dict, cfg: dict) -> str:
    ini = formatar_data(meta["inicio"], "pt", cfg)
    fim = "atual" if meta["fim"] == "atual" else formatar_data(meta["fim"], "pt", cfg)
    return f"{ini} – {fim}" + (f" · {meta['local']}" if meta.get("local") else "")


def _itens(kb: KB, arq, vazio: str) -> None:
    """Lista aberta dos itens de um cartão. Os que faltam confirmar têm botões ao lado."""
    fatos = arq.fatos() if arq else []
    confirmados = [f for f in fatos if f.status == "confirmado"]
    pendentes = [f for f in fatos if f.status == "sugerido"]
    if confirmados:
        st.markdown("\n".join(f"- {f.texto}" for f in confirmados))
    elif not pendentes:
        st.caption(vazio)
    for f in pendentes:
        c1, c2, c3 = st.columns([8, 1.3, 1.3], vertical_alignment="center")
        c1.markdown(f":orange-badge[A confirmar] {f.texto}")
        if c2.button("Confirmar", key=f"conf_{f.id}", type="tertiary", icon=":material/check:"):
            kb.confirmar(f.id)
            st.rerun()
        if c3.button("Remover", key=f"rem_{f.id}", type="tertiary", icon=":material/close:"):
            kb.remover(f.id)
            st.rerun()


def _editar_itens(kb: KB, slug: str, arq, chave: str) -> list[tuple[str, str]]:
    """Área de texto com os itens confirmados, um por linha. Os pendentes são mantidos como estão."""
    fatos = arq.fatos() if arq else []
    texto = st.text_area("Itens (um por linha)", "\n".join(f.texto for f in fatos if f.status == "confirmado"),
                         height=max(140, 28 * (len(fatos) + 2)), key=chave,
                         help="Cada linha vira um item do seu histórico. Apague a linha para remover.")
    linhas = [(l.strip().lstrip("-•* ").strip(), "confirmado") for l in texto.splitlines() if l.strip()]
    return linhas + [(f.texto, "sugerido") for f in fatos if f.status == "sugerido"]


def cartao_experiencia(kb: KB, arq, cfg: dict) -> None:
    m = arq.meta
    v = st.session_state["base_v"]
    with st.container(border=True):
        editando = st.session_state["editando"] == arq.slug
        c1, c2 = st.columns([6, 1], vertical_alignment="top")
        selo = " :gray-badge[Fora dos currículos]" if m.get("ocultar") else ""
        c1.markdown(f"**{m['cargo']}** · {m['empresa']}{selo}  \n:gray[{_periodo(m, cfg)}]")
        if not editando and c2.button("Editar", key=f"ed_{arq.slug}", type="tertiary", icon=":material/edit:"):
            st.session_state["editando"] = arq.slug
            st.rerun()
        if not editando:
            _itens(kb, arq, "Nenhum detalhe ainda. Use Editar ou converse para completar.")
            return
        with st.form(f"form_exp_{arq.slug}_{v}", border=False):
            a, b = st.columns(2)
            campos = {"cargo": a.text_input("Cargo", m["cargo"]), "empresa": b.text_input("Empresa", m["empresa"])}
            a, b, c = st.columns([1, 1, 2])
            campos["inicio"] = a.text_input("Início", m["inicio"], help="AAAA-MM, ou só o ano")
            campos["fim"] = b.text_input("Fim", m["fim"], help="AAAA-MM, só o ano, ou 'atual'")
            campos["local"] = c.text_input("Local", m.get("local", ""))
            itens = _editar_itens(kb, arq.slug, arq, f"itens_{arq.slug}_{v}")
            campos["ocultar"] = st.checkbox("Não usar esta experiência nos currículos", value=bool(m.get("ocultar")))
            s1, s2, _ = st.columns([1, 1, 3])
            salvar = s1.form_submit_button("Salvar", type="primary", icon=":material/check:")
            cancelar = s2.form_submit_button("Cancelar")
        if salvar:
            try:
                kb.atualizar_experiencia(arq.slug, campos)
                kb.substituir_fatos(arq.slug, itens)
            except ErroBase as e:
                st.error(str(e))
                return
            st.session_state.update(editando=None, base_v=v + 1)
            comum.avisar("success", f"{campos['cargo']} · {campos['empresa']} atualizada.")
            st.rerun()
        if cancelar:
            st.session_state["editando"] = None
            st.rerun()
        with st.popover("Excluir experiência", icon=":material/delete:"):
            st.write("A experiência e todos os itens dela saem do seu histórico. Não dá para desfazer.")
            if st.button("Excluir de vez", key=f"del_{arq.slug}", type="primary"):
                kb.remover_experiencia(arq.slug)
                st.session_state.update(editando=None, base_v=v + 1)
                comum.avisar("success", "Experiência excluída.")
                st.rerun()


def cartao_secao(kb: KB, slug: str, arqs: dict) -> None:
    arq = arqs.get(slug)
    v = st.session_state["base_v"]
    with st.container(border=True):
        editando = st.session_state["editando"] == slug
        c1, c2 = st.columns([6, 1])
        c1.markdown(f"**{revisao.ROTULO_SECAO[slug]}**")
        if not editando and c2.button("Editar", key=f"ed_{slug}", type="tertiary", icon=":material/edit:"):
            st.session_state["editando"] = slug
            st.rerun()
        if not editando:
            _itens(kb, arq, "Nada registrado ainda.")
            return
        with st.form(f"form_sec_{slug}_{v}", border=False):
            itens = _editar_itens(kb, slug, arq, f"itens_{slug}_{v}")
            if slug == "formacao":
                st.caption("Formato sugerido: Instituição | Curso | 2016 – 2021")
            s1, s2, _ = st.columns([1, 1, 3])
            salvar = s1.form_submit_button("Salvar", type="primary", icon=":material/check:")
            cancelar = s2.form_submit_button("Cancelar")
        if salvar:
            kb.substituir_fatos(slug, itens)
            st.session_state.update(editando=None, base_v=v + 1)
            comum.avisar("success", f"{revisao.ROTULO_SECAO[slug]} atualizado.")
            st.rerun()
        if cancelar:
            st.session_state["editando"] = None
            st.rerun()


@st.dialog("Adicionar experiência")
def dialogo_nova_experiencia(kb: KB) -> None:
    with st.form("form_nova_exp", border=False):
        a, b = st.columns(2)
        meta = {"cargo": a.text_input("Cargo", key="ne_cargo"), "empresa": b.text_input("Empresa", key="ne_empresa")}
        a, b = st.columns(2)
        meta["inicio"] = a.text_input("Início", placeholder="2022-03", help="AAAA-MM, ou só o ano se não lembra o mês", key="ne_inicio")
        meta["fim"] = b.text_input("Fim", placeholder="atual", help="AAAA-MM, só o ano, ou 'atual'", key="ne_fim")
        meta["local"] = st.text_input("Local", placeholder="São Paulo, Brasil", key="ne_local")
        texto = st.text_area("O que você fez lá (um item por linha)", height=160, key="ne_itens",
                             placeholder="Ex.: Atendeu 30 clientes por dia no balcão.\nTreinou 2 pessoas novas da equipe.")
        if st.form_submit_button("Adicionar", type="primary"):
            try:
                slug = kb.criar_experiencia(meta)
                kb.substituir_fatos(slug, [(l.strip(), "confirmado") for l in texto.splitlines() if l.strip()])
            except ErroBase as e:
                st.error(str(e))
                return
            st.session_state["base_v"] += 1
            comum.avisar("success", f"Experiência adicionada: {meta['cargo']} · {meta['empresa']}.")
            st.rerun()


@st.dialog("Ler um currículo")
def dialogo_ler_curriculo(kb: KB) -> None:
    st.caption("Use para acrescentar o que falta. Envie um currículo em um idioma só: o app traduz na hora de gerar.")
    inicio.enviar_curriculo(kb, "up_dialogo", "Ler este currículo")


def visao_geral(kb: KB, cfg: dict, config_erro: str | None) -> None:
    for erro in kb.erros:
        st.error(f"Um arquivo do histórico tem um problema e foi ignorado: {erro}")
    exps = kb.experiencias(True)
    fatos = kb.fatos()
    pendentes = sum(1 for f in fatos if f.status == "sugerido")
    c1, c2, c3 = st.columns(3)
    c1.metric("Experiências", len(exps))
    c2.metric("Informações confirmadas", len(fatos) - pendentes)
    c3.metric("A confirmar", pendentes, help="Guardadas, mas fora dos currículos até você confirmar.")

    acoes = st.container(horizontal=True)
    if acoes.button("Adicionar experiência", key="btn_nova_exp", icon=":material/add:"):
        dialogo_nova_experiencia(kb)
    if acoes.button("Ler um currículo", key="btn_ler_cv", icon=":material/upload_file:", disabled=bool(config_erro)):
        dialogo_ler_curriculo(kb)

    if st.session_state["rev_entrevista"]:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.warning("Há uma conversa esperando você conferir o que eu entendi.", icon=":material/pending_actions:")
        if c2.button("Conferir agora", key="btn_ir_rev_conversa", type="primary"):
            st.session_state["_vista"] = "conversa"
            st.rerun()
    contato = kb.contato()
    faltam_dados = [r for k, r in (("nome", "nome"), ("email", "e-mail"), ("telefone", "telefone")) if not contato.get(k)]
    if faltam_dados:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.warning(f"Faltam seus dados pessoais ({', '.join(faltam_dados)}). Sem eles, o currículo sai sem cabeçalho.",
                   icon=":material/badge:")
        if c2.button("Preencher", key="btn_ir_dados", type="primary"):
            st.session_state["_vista"] = "dados"
            st.rerun()
    faltas = kb.lacunas()
    if faltas:
        with st.container(border=True):
            st.markdown("**:material/checklist: O que ainda falta**")
            st.caption("Quanto mais completo, melhor o encaixe com as vagas. Na conversa, eu pergunto só isto.")
            st.markdown("\n".join(f"- {f['rotulo'][0].upper() + f['rotulo'][1:]}" for f in faltas[:8]))
            if st.button("Conversar para completar", key="btn_ir_conversa", icon=":material/chat:", type="primary",
                         disabled=bool(config_erro)):
                st.session_state["_vista"] = "conversa"
                st.rerun()
    if kb.mistura_idiomas():
        c = kb.composicao_idiomas()
        st.warning(f"O seu histórico mistura idiomas ({c['pt']} itens em português, {c['en']} em inglês). Prefira um "
                   "idioma só: o app traduz na hora de gerar, e as verificações funcionam melhor assim.")

    arqs = kb.arquivos()
    st.markdown("#### Resumo")
    cartao_secao(kb, "perfil", arqs)
    st.markdown("#### Experiências")
    if not exps:
        st.caption("Nenhuma experiência ainda.")
    for a in exps:
        cartao_experiencia(kb, a, cfg)
    st.markdown("#### Formação, habilidades e idiomas")
    for slug in ARQUIVOS_FATOS:
        if slug != "perfil":
            cartao_secao(kb, slug, arqs)


# ------------------------------------------------------------------ conversa

def textos_aguardando_revisao() -> list[str]:
    """O que a pessoa ainda não conferiu. O entrevistador trata como já informado."""
    textos: list[str] = []
    for chave in ("rev_importacao", "rev_entrevista"):
        for p in st.session_state.get(chave) or []:
            textos += [f.texto for f in p.fatos]
    return textos


def conversa(kb: KB, config_erro: str | None) -> None:
    if config_erro:
        comum.tela_sem_ia(config_erro)
        return
    props = st.session_state["rev_entrevista"]
    if props:
        st.markdown("### Confira o que entendi da conversa")
        st.caption("Desmarque o que não estiver certo. Depois de salvar, a conversa recomeça só com o que ainda falta.")
        r = revisao.formulario("ent", props, st.session_state["rev_id"], kb)
        if r:
            st.session_state.update(rev_entrevista=None, chat=[])
            comum.avisar("success", revisao.resumo(r))
            st.rerun()
        if st.button("Descartar e voltar à conversa", key="btn_descartar_ent", type="tertiary"):
            st.session_state["rev_entrevista"] = None
            st.rerun()
        return

    st.caption(":material/lock: Não digite telefone, e-mail nem endereço aqui. O que você escreve é enviado à IA.")
    with st.chat_message("assistant"):
        st.write(interview.abertura(kb))
    for m in st.session_state["chat"]:
        with st.chat_message(m["role"]):
            st.write(m["content"])
    respostas = sum(1 for m in st.session_state["chat"] if m["role"] == "user")
    if respostas:
        if respostas >= LIMITE_RESPOSTAS_SUGERIDO:
            st.info(f"Você já respondeu {respostas} perguntas. Salve agora: o que você confirmar fica guardado e eu "
                    "não pergunto de novo.")
        barra = st.container(horizontal=True)
        if barra.button("Salvar o que eu contei", key="btn_encerrar", type="primary", icon=":material/save:"):
            props = comum.executar("Organizando o que você contou...", interview.extrair_da_conversa,
                                   comum.obter_llm(kb), kb, st.session_state["chat"])
            if props is not comum.FALHOU:
                st.session_state["rev_id"] += 1
                st.session_state["rev_entrevista"] = props
                if not props:
                    comum.avisar("warning", "Não encontrei nada novo nessa conversa para guardar.")
                st.rerun()
        with barra.popover("Recomeçar a conversa", type="tertiary"):
            st.write("A conversa atual some e eu começo de novo. O que você já salvou no histórico fica.")
            if st.button("Recomeçar", key="btn_nova_conversa", type="primary"):
                st.session_state["chat"] = []
                st.rerun()
    texto = st.chat_input("Escreva a sua resposta")
    if texto:
        resposta = comum.executar("Pensando...", lambda: interview.responder(
            comum.obter_llm(kb), kb, st.session_state["chat"], texto, textos_aguardando_revisao()))
        if resposta is not comum.FALHOU:
            st.session_state["chat"] += [{"role": "user", "content": texto}, {"role": "assistant", "content": resposta}]
            st.rerun()


# ------------------------------------------------------------------ dados pessoais e avançado

def dados_pessoais(kb: KB) -> None:
    st.caption(":material/lock: Ficam só neste computador. Entram no topo do currículo e nunca são enviados à IA.")
    with st.form(f"form_contato_{st.session_state['base_v']}"):
        valores = revisao.campos_contato(kb, f"ct_{st.session_state['base_v']}")
        if st.form_submit_button("Salvar", type="primary", icon=":material/check:"):
            kb.salvar_contato(valores)
            st.session_state["base_v"] += 1
            comum.avisar("success", "Dados pessoais salvos.")
            st.rerun()


def avancado(kb: KB) -> None:
    st.caption("Para quem prefere editar os arquivos do histórico diretamente. Cada item é uma linha começando com "
               "`- [confirmado]` ou `- [sugerido]` (a confirmar). Linhas sem essa marca são ignoradas.")
    sem_marca = kb.linhas_sem_marca()
    if sem_marca:
        st.warning(f"{sem_marca} linha(s) sem a marca [confirmado] ou [sugerido]. Elas não entram nos currículos.")
    slugs = list(dict.fromkeys(list(ARQUIVOS_FATOS) + list(kb.arquivos())))
    slug = st.selectbox("Arquivo", slugs, key="ed_arquivo")
    v = st.session_state["base_v"]
    texto = st.text_area("Conteúdo", kb.ler_texto(slug), height=320, key=f"ed_{slug}_{v}")
    if st.button("Salvar arquivo", key="btn_salvar_arquivo"):
        try:
            kb.salvar_texto(slug, texto)
        except ErroBase as e:
            st.error(str(e))
        else:
            st.session_state["base_v"] += 1
            comum.avisar("success", f"Arquivo '{slug}' salvo.")
            st.rerun()
    st.markdown("#### Registro das conversas com a IA")
    if not registro.ativo():
        st.caption("O registro está desligado (CV_LOG=0 no arquivo .env).")
        return
    st.caption(f"Cada chamada à IA fica salva em {registro.pasta()}, um arquivo por dia, já sem telefone, e-mail e "
               "links. Serve para entender um resultado estranho. Contém o seu histórico: apague a pasta antes de "
               "compartilhar o computador.")
    recentes = registro.ultimos(8)
    for r in recentes:
        st.write("- " + registro.resumo(r))
    arqs = registro.arquivos()
    if arqs:
        st.download_button(f"Baixar o registro de {arqs[0].stem}", arqs[0].read_bytes(), file_name=arqs[0].name,
                           mime="application/x-ndjson", key="dl_registro")


# ------------------------------------------------------------------ área

def area(kb: KB, cfg: dict, config_erro: str | None) -> None:
    if revisao_da_importacao(kb):
        return
    if "_vista" in st.session_state:   # pedido de um botão: o seletor só muda antes de ser desenhado
        st.session_state["vista_historico"] = st.session_state.pop("_vista")
    st.markdown("### Meu histórico")
    st.caption("Tudo o que o app sabe sobre você. Só o que está confirmado entra nos currículos.")
    vista = st.segmented_control("Seção", list(VISTAS), format_func=VISTAS.get, key="vista_historico",
                                 label_visibility="collapsed", on_change=comum.sem_desmarcar("vista_historico")) or "visao"
    if vista == "conversa":
        conversa(kb, config_erro)
    elif vista == "dados":
        dados_pessoais(kb)
    elif vista == "avancado":
        avancado(kb)
    else:
        visao_geral(kb, cfg, config_erro)
