"""Peças usadas por todas as telas: estado, navegação, mensagens, IA e ações que podem falhar."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from src import atualizador, config, registro, sessao
from src.kb import KB, ErroBase
from src.llm import LLM, Configuracao, ErroConfig, ErroLLM

FALHOU = object()  # sentinela: a ação deu erro e a mensagem já foi mostrada
TIPOS_ARQUIVO = ["pdf", "docx", "md", "txt"]

# Áreas do aplicativo, na ordem do menu de cima.
AREAS = {"inicio": ":material/home: Início",
         "vaga": ":material/add_circle: Novo currículo",
         "vagas": ":material/fact_check: Minhas candidaturas",
         "historico": ":material/person: Meu histórico"}


def estado_inicial() -> None:
    for chave, valor in (("chat", []), ("rev_id", 0), ("rev_entrevista", None), ("rev_importacao", None),
                         ("analise_id", 0), ("analise", None), ("vaga_analisada", ""), ("rev_lacuna", None),
                         ("gen_id", 0), ("resultado", None), ("trad", None), ("trad_id", 0), ("base_v", 0),
                         ("msg", None), ("area", "inicio"), ("vista_historico", "visao"), ("passo_vaga", 1),
                         ("modo_curriculo", "vaga"), ("resultado_geral", None),
                         ("vista_resultado", "curriculo"), ("pastas_por_vaga", {}), ("editando", None),
                         ("comecar_conversando", False)):
        if chave not in st.session_state:
            st.session_state[chave] = valor
    # Uma vez por sessão do navegador: recupera a conversa e as revisões que estavam salvas em disco.
    if not st.session_state.get("_sessao_carregada"):
        st.session_state["_sessao_carregada"] = True
        salvo = sessao.carregar(config.base_dir())
        if salvo["chat"] or salvo["rev_importacao"] or salvo["rev_entrevista"]:
            st.session_state["chat"] = salvo["chat"]
            st.session_state["rev_importacao"] = salvo["rev_importacao"] or None
            st.session_state["rev_entrevista"] = salvo["rev_entrevista"] or None
            st.session_state["rev_id"] += 1
            partes = []
            if salvo["chat"]:
                partes.append(f"a conversa ({sum(1 for m in salvo['chat'] if m['role'] == 'user')} resposta(s) sua(s))")
            if salvo["rev_importacao"] or salvo["rev_entrevista"]:
                partes.append("o que ainda estava para você conferir")
            st.session_state["msg"] = ("info", "Continuei de onde você parou: recuperei " + " e ".join(partes) + ".")
        # Atualização instalada pelo `iniciar` desde a última vez: avisa uma vez, com as notas da versão.
        aviso = atualizador.aviso_pendente(config.RAIZ)
        if aviso:
            notas = aviso.get("notas", "").strip()
            texto = (f"O aplicativo foi atualizado para a versão **{aviso['para']}**. O seu histórico e os seus currículos "
                     "continuam como estavam." + (f"\n\n**O que mudou:**\n\n{notas[:600]}" if notas else ""))
            anterior = st.session_state.get("msg")
            st.session_state["msg"] = ("success", texto + (f"\n\n{anterior[1]}" if anterior else ""))
    # Navegação pedida por um botão na execução anterior (o menu é um widget: só pode mudar antes de ser desenhado).
    if "_ir_para" in st.session_state:
        st.session_state["area"] = st.session_state.pop("_ir_para")


def ir_para(area: str, vista: str | None = None, modo: str | None = None, **extras) -> None:
    """Muda de área (e, opcionalmente, de seção dentro de Meu histórico) no próximo desenho da tela.

    Área e seção são widgets: o Streamlit não deixa mudar o valor deles depois de desenhados na mesma execução,
    então o pedido fica guardado e é aplicado no começo da próxima. Chame st.rerun() logo depois.
    """
    st.session_state["_ir_para"] = area
    if vista:
        st.session_state["_vista"] = vista
    if modo:
        st.session_state["_modo"] = modo    # "vaga" ou "geral" dentro de Novo currículo
    st.session_state.update(extras)


def sem_desmarcar(chave: str):
    """Callback para seletores de uma opção: clicar de novo na opção atual não deixa a tela sem seleção."""
    anterior = f"_anterior_{chave}"

    def callback() -> None:
        if st.session_state.get(chave) is None:
            st.session_state[chave] = st.session_state.get(anterior)
        else:
            st.session_state[anterior] = st.session_state[chave]
    st.session_state.setdefault(anterior, st.session_state.get(chave))
    return callback


def persistir(kb: KB) -> None:
    """Grava a conversa e as revisões pendentes. Roda a cada execução, inclusive antes de um st.rerun()."""
    s = st.session_state
    if s.get("_sessao_carregada"):
        sessao.salvar(kb.base, s.get("chat") or [], s.get("rev_importacao"), s.get("rev_entrevista"))


def configuracao_do_provedor():
    """(Configuracao, None) ou (None, mensagem de erro)."""
    config.carregar_env()
    try:
        return Configuracao.do_ambiente(), None
    except ErroConfig as e:
        return None, str(e)


def obter_llm(kb: KB) -> LLM:
    cfg, erro = configuracao_do_provedor()
    if erro:
        raise ErroConfig(erro)
    return LLM(cfg, segredos=kb.segredos(), log_dir=config.logs_dir() if registro.ativo() else None)


def executar(rotulo: str, funcao, *args):
    """Roda uma ação que pode falhar e mostra o erro em português, sem derrubar a tela."""
    try:
        with st.spinner(rotulo):
            return funcao(*args)
    except (ErroLLM, ErroBase, ErroConfig) as e:
        st.error(str(e))
        return FALHOU


def mostrar_mensagem() -> None:
    """Mensagem da ação anterior, num espaço fixo (st.empty existe sempre, para a tela não pular)."""
    espaco = st.empty()
    msg = st.session_state.get("msg")
    if msg:
        getattr(espaco, msg[0])(msg[1])
        st.session_state["msg"] = None


def avisar(tipo: str, texto: str) -> None:
    """Guarda uma mensagem para aparecer depois do próximo rerun."""
    st.session_state["msg"] = (tipo, texto)


def abrir_pasta(pasta: Path) -> bool:
    """Abre a pasta no explorador de arquivos. O app roda no computador dela, então isso funciona."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(pasta))  # noqa: S606 - pasta local do próprio aplicativo
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(pasta)])
        else:
            subprocess.Popen(["xdg-open", str(pasta)])
        return True
    except OSError:
        return False


def tela_sem_ia(erro: str) -> None:
    """Falta a chave da IA. Explica em linguagem simples, sem travar o resto do app."""
    with st.container(border=True):
        st.markdown("#### :material/key: Falta ligar a IA")
        st.markdown(
            "O aplicativo precisa da chave do DeepSeek para ler currículos, conversar e gerar.\n\n"
            "1. Na pasta do aplicativo, abra o arquivo `.env` no Bloco de Notas "
            "(se ele não existir, copie o `.env.example` e renomeie a cópia para `.env`).\n"
            "2. Cole a chave logo depois de `DEEPSEEK_API_KEY=`, sem espaços e sem aspas.\n"
            "3. Salve, feche esta janela e abra o aplicativo de novo.")
        st.caption(f"Detalhe técnico: {erro}")
