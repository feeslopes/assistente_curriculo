"""Tela "Confira o que eu entendi": a pessoa vê, corrige e salva o que a IA leu ou ouviu.

Usada depois de ler um currículo, depois de uma conversa e depois das respostas às lacunas de uma vaga.
Tudo aparece aberto, em cartões: nada escondido em menus. Um botão só para salvar: o que está marcado entra
como confirmado; o que ficou desmarcado fica guardado como "a confirmar" e nunca vai para um currículo.
"""
from __future__ import annotations

import streamlit as st

from src import config, interview
from src.kb import KB

from . import comum

ROTULO_SECAO = {"perfil": "Resumo e objetivo profissional", "habilidades": "Ferramentas e habilidades",
                "formacao": "Formação", "certificacoes": "Certificações", "idiomas": "Idiomas"}
ORDEM_SECAO = list(ROTULO_SECAO)
CAMPOS_CONTATO = [("nome", "Nome completo"), ("titulo_padrao", "Título profissional (português)"),
                  ("titulo_padrao_en", "Título profissional (inglês)"), ("local", "Cidade e país"),
                  ("telefone", "Telefone"), ("email", "E-mail"), ("linkedin", "LinkedIn"),
                  ("site", "Site ou portfólio")]


def campos_contato(kb: KB, prefixo: str) -> dict:
    """Campos de dados pessoais, já preenchidos. Devolve os valores digitados."""
    atual = kb.contato()
    valores = {}
    colunas = st.columns(2)
    for n, (k, rotulo) in enumerate(CAMPOS_CONTATO):
        valores[k] = colunas[n % 2].text_input(rotulo, atual.get(k, ""), key=f"{prefixo}_{k}")
    return valores


def _ordem(kb: KB, propostas: list) -> list[int]:
    """Experiências primeiro (da mais recente para a mais antiga), depois as outras seções."""
    metas = {a.slug: a.meta for a in kb.experiencias(True)}
    exps, outras = [], []
    for i, p in enumerate(propostas):
        (outras if p.destino in ROTULO_SECAO else exps).append(i)

    def quando(i: int) -> tuple[str, str]:
        p = propostas[i]
        m = metas.get(p.destino) or p.meta
        fim = str(m.get("fim", ""))
        return ("9999-99" if fim == "atual" else fim, str(m.get("inicio", "")))
    exps.sort(key=quando, reverse=True)
    outras.sort(key=lambda i: ORDEM_SECAO.index(propostas[i].destino))
    return exps + outras


def _titulo(kb: KB, p) -> str:
    if p.destino in ROTULO_SECAO:
        return f"**{ROTULO_SECAO[p.destino]}**"
    exp = {a.slug: a.meta for a in kb.experiencias(True)}.get(p.destino)
    if exp:
        return f"**{exp['cargo']}** · {exp['empresa']}  \n:gray[Experiência que já estava no seu histórico]"
    return "**Nova experiência**"


def formulario(chave: str, propostas: list, rev_id: int, kb: KB, com_contato: bool = False):
    """Desenha a revisão. Devolve o resumo do que foi salvo, ou None."""
    marcados: set = set()
    metas: dict = {}
    contato = None
    with st.form(f"form_{chave}_{rev_id}", border=False):
        if com_contato:
            with st.container(border=True):
                st.markdown("**:material/badge: Seus dados**")
                st.caption((":material/lock: Ficam guardados na sua conta. Entram no topo do currículo e nunca são enviados à IA."
                if config.modo_hospedado() else ":material/lock: Ficam só neste computador. Entram no topo do currículo e nunca são enviados à IA."))
                contato = campos_contato(kb, f"rc_{rev_id}")
        for i in _ordem(kb, propostas):
            p = propostas[i]
            with st.container(border=True):
                st.markdown(_titulo(kb, p))
                for problema in p.problemas:
                    st.warning(problema, icon=":material/warning:")
                if p.destino == "nova_experiencia":
                    k = f"{chave}_{rev_id}_{i}"
                    c1, c2 = st.columns(2)
                    metas[i] = {"cargo": c1.text_input("Cargo", p.meta.get("cargo", ""), key=f"{k}_cargo"),
                                "empresa": c2.text_input("Empresa", p.meta.get("empresa", ""), key=f"{k}_empresa")}
                    c3, c4, c5 = st.columns([1, 1, 2])
                    metas[i]["inicio"] = c3.text_input("Início", p.meta.get("inicio", ""), key=f"{k}_inicio",
                                                       placeholder="2022-03", help="Ano e mês (AAAA-MM). Se não lembra o mês, só o ano.")
                    metas[i]["fim"] = c4.text_input("Fim", p.meta.get("fim", ""), key=f"{k}_fim",
                                                    placeholder="atual", help="AAAA-MM, só o ano, ou 'atual' se ainda trabalha lá")
                    metas[i]["local"] = c5.text_input("Local", p.meta.get("local", ""), key=f"{k}_local")
                for j, f in enumerate(p.fatos):
                    rotulo = f.texto if f.origem == "dito" else f"{f.texto} :violet-badge[Sugestão da IA]"
                    if st.checkbox(rotulo, value=f.marcado_por_padrao, key=f"{chave}_{rev_id}_{i}_{j}"):
                        marcados.add((i, j))
        st.caption("O que estiver **marcado** entra no seu histórico e pode ir para os currículos. O que ficar "
                   "**desmarcado** fica guardado como *a confirmar* em Meu histórico e não vai para nenhum currículo. "
                   "As sugestões da IA vêm desmarcadas: marque só se for verdade.")
        salvar = st.form_submit_button("Salvar", type="primary", icon=":material/check:")
    if not salvar:
        return None
    for i, meta in metas.items():
        propostas[i].meta = {**propostas[i].meta, **{k: v.strip() for k, v in meta.items()}}
    r = comum.executar("Salvando...", interview.aplicar, kb, propostas, marcados, True)
    if r is comum.FALHOU:
        return None
    comum.evento("base_atualizada", confirmados=r["confirmados"], pendentes=r["pendentes"],
                 experiencias=r["experiencias_criadas"], ignorados=r["ignorados"])
    if contato is not None:
        kb.salvar_contato(contato)
    return r


def resumo(r: dict) -> str:
    partes = [f"{r['confirmados']} informação(ões) salva(s)"]
    if r["experiencias_criadas"]:
        partes.append(f"{r['experiencias_criadas']} experiência(s) nova(s)")
    if r["pendentes"]:
        partes.append(f"{r['pendentes']} guardada(s) para confirmar depois")
    if r["ignorados"]:
        partes.append(f"{r['ignorados']} já estava(m) no histórico")
    return "Pronto: " + ", ".join(partes) + "."
