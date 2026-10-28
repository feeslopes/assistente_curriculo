"""Minhas candidaturas: cada vaga numa pasta <Empresa>_<AAAA-MM>, com o currículo, a aderência e a situação.

A situação muda com um clique no próprio cartão (Enviado, Entrevista...), e a data de envio fica registrada.
Currículos gerais aparecem também, sem situação: não são candidaturas.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from src import candidaturas, config, historico

from . import comum, estilo

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FILTROS = {"todas": "Todas", "andamento": "Em andamento", "encerradas": "Encerradas", "gerais": "Currículos gerais"}
EM_ANDAMENTO = {"gerado", "enviado", "entrevista"}


def _rotulo(e: dict) -> str:
    return (e["empresa"] or e["titulo_vaga"] or e["nome"])[:28]


def _data_br(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _passa(e: dict, filtro: str) -> bool:
    if filtro == "gerais":
        return e["geral"]
    if e["geral"]:
        return filtro == "todas"
    if filtro == "andamento":
        return e["situacao"] in EM_ANDAMENTO
    if filtro == "encerradas":
        return e["situacao"] not in EM_ANDAMENTO
    return True


def _cartao(e: dict, i: int) -> None:
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1.4, 1], vertical_alignment="center")
        idioma = f" :blue-badge[{e['idioma'].upper()}]" if e["idioma"] else ""
        if e["geral"]:
            foco = (e["analise"] or {}).get("foco")
            c1.markdown(f"**Currículo geral**{(' · ' + foco) if foco else ''}{idioma}  \n:gray[{_data_br(e['data'])} · "
                        f"pasta {e['nome']}]")
        else:
            c1.markdown(f"**{e['empresa'] or 'Empresa não informada'}** · {e['titulo_vaga'] or 'vaga'}{idioma}  \n"
                        f":gray[gerado em {_data_br(e['data'])} · pasta {e['nome']}]")
            opcoes = list(candidaturas.SITUACOES)
            nova = c2.selectbox("Situação", opcoes, index=opcoes.index(e["situacao"]), key=f"sit_{e['nome']}",
                                format_func=candidaturas.SITUACOES.get)
            if nova != e["situacao"]:
                candidaturas.definir_situacao(e["pasta"], nova)
                e.update(candidaturas.ler(e["pasta"]))
            if e["enviado_em"]:
                dias = candidaturas.dias_desde(e["enviado_em"])
                c2.caption(f"Enviado em {_data_br(e['enviado_em'])}" + (f" (há {dias} dias)" if dias else ""))
        if e["tem_indice"]:
            c3.metric("Aderência", e["depois"], delta=f"{e['depois'] - e['antes']:+d}")
        acoes = st.container(horizontal=True, vertical_alignment="center")
        if e["pdf"]:
            acoes.download_button("PDF", e["pdf"].read_bytes(), file_name=e["pdf"].name, mime="application/pdf",
                                  key=f"hist_pdf_{i}", icon=":material/download:")
        if e["docx"]:
            acoes.download_button("Word", e["docx"].read_bytes(), file_name=e["docx"].name, mime=MIME_DOCX,
                                  key=f"hist_docx_{i}", icon=":material/download:")
        if not config.modo_hospedado() and acoes.button("Abrir a pasta", key=f"hist_abrir_{i}", type="tertiary",
                                                         icon=":material/folder_open:"):
            if not comum.abrir_pasta(e["pasta"]):
                st.info(f"A pasta fica em: {e['pasta']}")
        if not e["geral"]:
            nota = st.text_input("Anotação", e["anotacao"], key=f"nota_{e['nome']}", label_visibility="collapsed",
                                 placeholder="Anotação: recrutador, data da entrevista, próximo passo...")
            if nota != e["anotacao"]:
                candidaturas.anotar(e["pasta"], nota)
        if (e["pasta"] / "relatorio.md").exists():
            with st.expander("Ver o que foi adaptado" if not e["geral"] else "Ver como foi escrito"):
                st.markdown((e["pasta"] / "relatorio.md").read_text(encoding="utf-8"))


def area() -> None:
    st.markdown("### Minhas candidaturas")
    entradas = historico.listar()
    pasta_raiz = config.saidas_dir()
    if not entradas:
        with st.container(border=True):
            st.markdown("**Nenhuma candidatura ainda**")
            st.caption("Cada currículo que você gerar aparece aqui, numa pasta com o nome da empresa e o mês. Depois, "
                       "marque se enviou, se foi chamada para entrevista, e o app acompanha para você.")
            if st.button("Fazer um currículo para uma vaga", key="btn_primeira_vaga", type="primary", icon=":material/add:"):
                comum.ir_para("vaga", modo="vaga")
                st.rerun()
        return
    if not config.modo_hospedado():     # no servidor não há pasta para abrir, e o caminho não deve aparecer
        topo = st.container(horizontal=True, vertical_alignment="center")
        topo.caption(f"Os arquivos ficam em {pasta_raiz}.")
        if topo.button("Abrir a pasta", key="btn_abrir_saidas", type="tertiary", icon=":material/folder_open:"):
            if not comum.abrir_pasta(pasta_raiz):
                st.info(f"A pasta fica em: {pasta_raiz}")

    com_indice = [e for e in entradas if e["tem_indice"] and not e["geral"]][:8]
    if com_indice:
        with st.container(border=True):
            st.markdown("**Aderência por vaga**")
            st.caption("Antes e depois da adaptação, de 0 a 100. As vagas mais recentes ficam à esquerda.")
            nomes: list[str] = []
            for e in com_indice:
                n, k = _rotulo(e), 2
                while n in nomes:      # duas vagas na mesma empresa: o gráfico precisa de nomes distintos
                    n, k = f"{_rotulo(e)} ({k})", k + 1
                nomes.append(n)
            estilo.grafico_antes_depois(nomes, [e["antes"] for e in com_indice], [e["depois"] for e in com_indice],
                                        titulo_y="Aderência", altura=280)

    filtro = st.segmented_control("Mostrar", list(FILTROS), format_func=FILTROS.get, key="filtro_candidaturas",
                                  default="todas", label_visibility="collapsed") or "todas"
    visiveis = [(i, e) for i, e in enumerate(entradas) if _passa(e, filtro)]
    if not visiveis:
        st.caption("Nada aqui com este filtro.")
    for i, e in visiveis:
        _cartao(e, i)
