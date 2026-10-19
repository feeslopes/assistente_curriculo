"""Início: a tela de quem volta. O que fazer agora, como andam as candidaturas e o que merece atenção.

Ordem pensada para a pergunta "o que eu faço hoje?": as duas ações principais, as próximas ações (com um clique
cada), o andamento das candidaturas (com taxas só quando há dados) e o que várias vagas pedem.
"""
from __future__ import annotations

import streamlit as st

from src import candidaturas, historico
from src.kb import KB

from . import comum


def _acoes_principais() -> None:
    s = st.session_state
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("#### :material/work: Currículo para uma vaga")
        st.caption("Cole a vaga e eu adapto o currículo a ela, usando só o que é verdade.")
        em_andamento = s.get("analise")
        barra = st.container(horizontal=True)
        if em_andamento:
            if barra.button(f"Continuar: {em_andamento['titulo_vaga'] or 'vaga em andamento'}"[:60], key="ini_continuar",
                            type="primary", icon=":material/arrow_forward:"):
                comum.ir_para("vaga", modo="vaga")
                st.rerun()
        if barra.button("Nova vaga", key="ini_nova_vaga", type="secondary" if em_andamento else "primary",
                        icon=":material/add:"):
            comum.ir_para("vaga", modo="vaga", analise=None, resultado=None, passo_vaga=1, vaga_texto="")
            st.rerun()
    with c2.container(border=True):
        st.markdown("#### :material/description: Currículo geral")
        st.caption("Para quando pedem o seu currículo sem uma vaga em mente: um contato, uma indicação, um cadastro.")
        if st.button("Fazer currículo geral", key="ini_geral", icon=":material/auto_awesome:"):
            comum.ir_para("vaga", modo="geral", resultado_geral=None)
            st.rerun()


def _proximas_acoes(kb: KB, entradas: list[dict], cfg: dict) -> None:
    s = st.session_state
    itens = []   # (texto, rótulo do botão, chave, ação)
    if s["rev_importacao"]:
        itens.append(("O seu currículo foi lido e está esperando você conferir.", "Conferir", "ini_rev_imp",
                      lambda: comum.ir_para("historico")))
    if s["rev_entrevista"]:
        itens.append(("Há uma conversa esperando você conferir o que eu entendi.", "Conferir", "ini_rev_conv",
                      lambda: comum.ir_para("historico", vista="conversa")))
    contato = kb.contato()
    if not contato.get("nome") or not (contato.get("email") or contato.get("telefone")):
        itens.append(("Faltam seus dados pessoais: sem eles, o currículo sai sem cabeçalho.", "Preencher", "ini_dados",
                      lambda: comum.ir_para("historico", vista="dados")))
    pendentes = len(kb.fatos("sugerido"))
    if pendentes:
        itens.append((f"{pendentes} informação(ões) do seu histórico ainda a confirmar. Enquanto isso, elas ficam fora "
                      "dos currículos.", "Revisar", "ini_pendentes", lambda: comum.ir_para("historico", vista="visao")))
    faltas = kb.lacunas()
    if faltas:
        exemplo = faltas[0]["rotulo"]
        itens.append((f"O seu histórico ainda tem {len(faltas)} ponto(s) a completar, como: {exemplo}.", "Completar",
                      "ini_lacunas_hist", lambda: comum.ir_para("historico", vista="conversa")))
    regras = candidaturas.regras(cfg)
    for e in candidaturas.sugerir_sem_retorno(entradas, cfg=cfg):
        pasta = e["pasta"]
        itens.append((f"**{e['empresa'] or e['titulo_vaga']}**: enviada há {e['dias']} dias, sem resposta registrada. "
                      "Marcar como sem retorno?", "Marcar sem retorno", f"ini_sr_{e['nome']}",
                      lambda p=pasta: candidaturas.definir_situacao(p, "sem_retorno")))
    nao_enviadas = [e for e in entradas if not e["geral"] and e["situacao"] == "gerado"]
    if nao_enviadas:
        itens.append((f"{len(nao_enviadas)} currículo(s) gerado(s) ainda sem marcação de envio. Se você já mandou, "
                      "marque em Minhas candidaturas: é isso que permite acompanhar o retorno.", "Atualizar",
                      "ini_nao_enviadas", lambda: comum.ir_para("vagas")))
    with st.container(border=True):
        st.markdown("**:material/checklist: Próximas ações**")
        if not itens:
            st.caption(f"Tudo em dia. Candidaturas enviadas há mais de {regras['dias_sem_retorno']} dias sem resposta "
                       "aparecem aqui.")
        for texto, rotulo, chave, acao in itens:
            c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
            c1.markdown(texto)
            if c2.button(rotulo, key=chave):
                acao()
                st.rerun()


def _andamento(entradas: list[dict], cfg: dict) -> None:
    vagas = [e for e in entradas if not e["geral"]]
    with st.container(border=True):
        c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
        c1.markdown("**:material/fact_check: Candidaturas**")
        if vagas and c2.button("Ver todas", key="ini_ver_todas", type="tertiary"):
            comum.ir_para("vagas")
            st.rerun()
        if not vagas:
            st.caption("Nenhuma candidatura ainda. Cada currículo para uma vaga entra aqui, e você marca se enviou, se "
                       "foi chamada para entrevista e assim por diante.")
            return
        r = candidaturas.resumo(entradas, cfg)
        n = r["contagem"]
        m = st.columns(5)
        m[0].metric("Geradas", len(vagas))
        m[1].metric("Enviadas", r["enviadas"])
        m[2].metric("Entrevistas", n["entrevista"] + n["proposta"], help="Inclui as que chegaram a proposta.")
        m[3].metric("Propostas", n["proposta"])
        m[4].metric("Sem retorno", n["sem_retorno"])
        if r["taxa_resposta"] is None:
            st.caption(f"A taxa de resposta aparece a partir de {candidaturas.regras(cfg)['minimo_para_taxas']} "
                       f"candidaturas enviadas (faltam {r['faltam_para_taxas']}). Com menos que isso, o número muda "
                       "demais a cada resposta para dizer alguma coisa.")
            return
        st.markdown(f"**Taxa de resposta: {r['taxa_resposta']}%** ({r['respostas']} entrevista(s) ou proposta(s) em "
                    f"{r['enviadas']} enviadas).")
        rel = r["relacao"]
        if rel:
            st.caption(f"Indício, não conclusão: as candidaturas com resposta tinham aderência média de "
                       f"{rel['media_com_resposta']}; as sem resposta, {rel['media_sem_resposta']}. Com {r['enviadas']} "
                       "candidaturas, isso ainda pode ser acaso, e muita coisa além do currículo pesa no retorno.")
        else:
            st.caption(f"A comparação entre aderência e resultado aparece a partir de "
                       f"{candidaturas.regras(cfg)['minimo_para_relacao']} candidaturas enviadas (faltam "
                       f"{r['faltam_para_relacao']}). Antes disso, ela pareceria uma conclusão sem ser.")


def _onde_se_desenvolver(entradas: list[dict]) -> None:
    """O que as vagas que ela busca pedem e o histórico não mostra: contar (se tem) ou desenvolver (se não tem)."""
    p = historico.pontos_de_desenvolvimento(entradas)
    if not p["itens"]:
        return
    with st.container(border=True):
        st.markdown("**:material/school: Onde se desenvolver para aumentar suas chances**")
        origem = ("nas vagas em que você se candidatou" if p["base"] == "enviadas"
                  else "nas vagas para as quais você gerou currículo (quando você marcar as enviadas, a conta passa a "
                       "usar só elas)")
        st.caption(f"O que mais se repete {origem} e o seu histórico não mostra. Base: {p['total']} vagas.")
        linhas = []
        for i in p["itens"]:
            selo = " :orange-badge[obrigatório]" if i["obrigatorio"] else ""
            linhas.append(f"- **{i['termo']}**{selo}: pedido em {i['vagas']} de {p['total']} vagas")
        st.markdown("\n".join(linhas))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Você já tem e não contou?**")
            st.caption("Contar em Meu histórico melhora todas as próximas candidaturas de uma vez.")
            if st.button("Contar em Meu histórico", key="ini_lacunas", icon=":material/chat:"):
                comum.ir_para("historico", vista="conversa")
                st.rerun()
        with c2:
            st.markdown("**Ainda não tem?**")
            st.caption("São os pontos que mais pesam nas vagas que você busca. Um curso, um projeto pessoal ou uma tarefa "
                       "no trabalho atual podem virar uma experiência verdadeira para contar depois. Até lá, fica de fora "
                       "do currículo: inventar aparece na entrevista.")


def area(kb: KB, cfg: dict, config_erro: str | None) -> None:
    nome = (kb.contato().get("nome") or "").split()
    st.markdown(f"### Olá, {nome[0]}" if nome else "### Início")
    if config_erro:
        comum.tela_sem_ia(config_erro)
    entradas = historico.listar()
    _acoes_principais()
    _proximas_acoes(kb, entradas, cfg)
    _andamento(entradas, cfg)
    _onde_se_desenvolver(entradas)
    exps = kb.experiencias()
    if exps and exps[0].meta["fim"] == "atual":
        c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
        c1.caption(f":material/update: Teve um resultado novo em {exps[0].meta['empresa']}, ou mudou de emprego? Registrar "
                   "agora deixa os próximos currículos mais fortes.")
        if c2.button("Registrar", key="ini_registrar", type="tertiary"):
            comum.ir_para("historico", vista="conversa")
            st.rerun()
