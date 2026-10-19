"""Minhas vagas: cada candidatura numa pasta <Empresa>_<AAAA-MM>, com o currículo, a vaga e a aderência."""
from __future__ import annotations

import streamlit as st

from src import config, historico

from . import comum, estilo

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _rotulo(e: dict) -> str:
    return (e["empresa"] or e["titulo_vaga"] or e["nome"])[:28]


def area() -> None:
    st.markdown("### Minhas vagas")
    entradas = historico.listar()
    pasta_raiz = config.saidas_dir()
    if not entradas:
        with st.container(border=True):
            st.markdown("**Nenhuma vaga ainda**")
            st.caption("Cada currículo que você gerar aparece aqui, numa pasta com o nome da empresa e o mês, junto com a "
                       "vaga e a aderência.")
            if st.button("Fazer um currículo para uma vaga", key="btn_primeira_vaga", type="primary", icon=":material/add:"):
                comum.ir_para("vaga")
                st.rerun()
        return
    topo = st.container(horizontal=True, vertical_alignment="center")
    topo.caption(f"{len(entradas)} vaga(s). Os arquivos ficam em {pasta_raiz}.")
    if topo.button("Abrir a pasta", key="btn_abrir_saidas", type="tertiary", icon=":material/folder_open:"):
        if not comum.abrir_pasta(pasta_raiz):
            st.info(f"A pasta fica em: {pasta_raiz}")

    com_indice = [e for e in entradas if e["tem_indice"]][:8]
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

    rec = historico.lacunas_recorrentes(entradas)
    if rec["palavras"] or rec["requisitos"]:
        with st.container(border=True):
            st.markdown("**:material/repeat: O que várias vagas pedem e o seu histórico não mostra**")
            st.caption("Se você fez isso, contar em Meu histórico melhora todas as próximas candidaturas. Se não fez, "
                       "deixe de fora: inventar para cobrir um requisito aparece na entrevista.")
            if rec["requisitos"]:
                estilo.etiquetas([f"{t} · {n} vagas" for t, n in rec["requisitos"]], "tem")
            if rec["palavras"]:
                estilo.etiquetas([f"{t} · {n} vagas" for t, n in rec["palavras"]], "nao")

    for i, e in enumerate(entradas):
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            idioma = f" :blue-badge[{e['idioma'].upper()}]" if e["idioma"] else ""
            c1.markdown(f"**{e['empresa'] or 'Empresa não informada'}** · {e['titulo_vaga'] or 'vaga'}{idioma}  \n"
                        f":gray[{e['data']} · pasta {e['nome']}]")
            if e["tem_indice"]:
                c2.metric("Aderência", e["depois"], delta=f"{e['depois'] - e['antes']:+d}", label_visibility="visible")
            acoes = st.container(horizontal=True)
            if e["pdf"]:
                acoes.download_button("PDF", e["pdf"].read_bytes(), file_name=e["pdf"].name, mime="application/pdf",
                                      key=f"hist_pdf_{i}", icon=":material/download:")
            if e["docx"]:
                acoes.download_button("Word", e["docx"].read_bytes(), file_name=e["docx"].name, mime=MIME_DOCX,
                                      key=f"hist_docx_{i}", icon=":material/download:")
            if acoes.button("Abrir a pasta", key=f"hist_abrir_{i}", type="tertiary", icon=":material/folder_open:"):
                if not comum.abrir_pasta(e["pasta"]):
                    st.info(f"A pasta fica em: {e['pasta']}")
            if (e["pasta"] / "relatorio.md").exists():
                with st.expander("Ver o que foi adaptado para esta vaga"):
                    st.markdown((e["pasta"] / "relatorio.md").read_text(encoding="utf-8"))
