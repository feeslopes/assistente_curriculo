"""Aparência: um pouco de CSS, o indicador de passos, etiquetas e os gráficos.

O tema base (cores, cantos, fonte) está em .streamlit/config.toml. Aqui fica só o que o tema não cobre.
"""
from __future__ import annotations

import html

import streamlit as st

CLARO = {"cor": "#3F51B5", "antes": "#C3C9D4", "texto": "#1F2937", "texto2": "#4B5563", "mudo": "#6B7280",
         "apagado": "#9CA3AF", "linha": "#E5E7EB", "n_borda": "#D1D5DB", "rotulo_grafico": "#374151",
         "ok_bg": "#E8F5E9", "ok_fg": "#1B5E20", "ok_borda": "#C8E6C9",
         "tem_bg": "#FFF8E1", "tem_fg": "#7A4F01", "tem_borda": "#FFE082",
         "nao_bg": "#F3F4F6", "nao_fg": "#4B5563", "nao_borda": "#E5E7EB", "n_atual_fg": "#FFFFFF"}
ESCURO = {"cor": "#8C9EFF", "antes": "#4A5262", "texto": "#E6E8EC", "texto2": "#B4BAC5", "mudo": "#9AA1AE",
          "apagado": "#6B7380", "linha": "#2C323D", "n_borda": "#3A414D", "rotulo_grafico": "#C9CED6",
          "ok_bg": "#16301C", "ok_fg": "#9BD8A4", "ok_borda": "#25502D",
          "tem_bg": "#33280A", "tem_fg": "#F0C36A", "tem_borda": "#5A4513",
          "nao_bg": "#1F242D", "nao_fg": "#B4BAC5", "nao_borda": "#2C323D", "n_atual_fg": "#101318"}

COR = CLARO["cor"]          # cor principal do tema claro (os gráficos usam a paleta do tema ativo)
COR_ANTES = CLARO["antes"]


def tema_escuro() -> bool:
    """O tema ativo é o escuro? Lido do Streamlit a cada execução; sem contexto (testes), vale o claro."""
    try:
        return st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001 - versão antiga, sem contexto de sessão ou stub de teste
        return False


def paleta() -> dict:
    return ESCURO if tema_escuro() else CLARO


_CSS = """
<style>
/* respiro e largura confortável de leitura */
.block-container {padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1100px;}
h1, h2, h3, h4 {letter-spacing: -0.01em;}
/* cabeçalho */
.marca {display:flex; align-items:baseline; gap:.6rem; margin-bottom:.2rem;}
.marca b {font-size:1.35rem;}
.marca span {color:%(mudo)s; font-size:.92rem;}
/* indicador de passos */
.passos {display:flex; align-items:center; gap:.5rem; margin:.4rem 0 1.2rem 0; flex-wrap:wrap;}
.passo {display:flex; align-items:center; gap:.45rem; color:%(apagado)s; font-weight:500; font-size:.95rem;}
.passo .n {width:1.7rem; height:1.7rem; border-radius:50%%; display:inline-flex; align-items:center;
           justify-content:center; border:2px solid %(n_borda)s; font-size:.85rem;}
.passo.atual {color:%(texto)s;}
.passo.atual .n {border-color:%(cor)s; background:%(cor)s; color:%(n_atual_fg)s;}
.passo.feito {color:%(texto2)s;}
.passo.feito .n {border-color:%(cor)s; color:%(cor)s;}
.passo-linha {flex:0 0 2.2rem; height:2px; background:%(linha)s;}
/* etiquetas de palavras-chave */
.chips {display:flex; flex-wrap:wrap; gap:.35rem; margin:.2rem 0 .6rem 0;}
.chip {padding:.15rem .6rem; border-radius:999px; font-size:.85rem; border:1px solid transparent;}
.chip.ok {background:%(ok_bg)s; color:%(ok_fg)s; border-color:%(ok_borda)s;}
.chip.tem {background:%(tem_bg)s; color:%(tem_fg)s; border-color:%(tem_borda)s;}
.chip.nao {background:%(nao_bg)s; color:%(nao_fg)s; border-color:%(nao_borda)s;}
/* destaque da tela de boas-vindas */
.hero h1 {font-size:2.1rem; margin-bottom:.3rem;}
.hero p {font-size:1.08rem; color:%(texto2)s; margin-top:0;}
/* pré-visualização do currículo: títulos no tamanho de um documento, não de uma página web */
.st-key-previa h1 {font-size:1.7rem; margin-bottom:.2rem;}
.st-key-previa h2 {font-size:1.1rem; margin-top:1rem; padding-bottom:.2rem; border-bottom:1px solid %(linha)s;}
.st-key-previa p, .st-key-previa li {font-size:.95rem;}
.etapa-num {font-size:.8rem; color:%(cor)s; font-weight:600; text-transform:uppercase; letter-spacing:.04em;}
</style>
"""


def aplicar_css() -> None:
    st.markdown(_CSS % paleta(), unsafe_allow_html=True)


def passos(rotulos: list[str], atual: int) -> None:
    """Indicador de passos (1 = primeiro). Os anteriores aparecem como feitos."""
    partes = []
    for i, r in enumerate(rotulos, start=1):
        classe = "atual" if i == atual else ("feito" if i < atual else "")
        marca = "&#10003;" if i < atual else str(i)
        if partes:
            partes.append('<div class="passo-linha"></div>')
        partes.append(f'<div class="passo {classe}"><span class="n">{marca}</span>{html.escape(r)}</div>')
    st.markdown(f'<div class="passos">{"".join(partes)}</div>', unsafe_allow_html=True)


def etiquetas(termos: list[str], tipo: str) -> None:
    """Palavras em etiquetas. tipo: ok (verde), tem (amarelo), nao (cinza)."""
    if termos:
        chips = "".join(f'<span class="chip {tipo}">{html.escape(t)}</span>' for t in termos)
        st.markdown(f'<div class="chips">{chips}</div>', unsafe_allow_html=True)


def grafico_antes_depois(grupos: list[str], antes: list[float | None], depois: list[float | None],
                         titulo_y: str = "% atingido", altura: int = 300) -> None:
    """Barras verticais lado a lado: antes (cinza) e depois (cor), eixo fixo de 0 a 100 e valor em cima."""
    import altair as alt  # tardio: só quem mostra gráfico precisa

    pal = paleta()

    linhas = []
    for g, a, d in zip(grupos, antes, depois):
        if a is not None:
            linhas.append({"grupo": g, "serie": "Antes", "valor": round(a)})
        if d is not None:
            linhas.append({"grupo": g, "serie": "Depois", "valor": round(d)})
    dados = alt.Data(values=linhas)
    x = alt.X("grupo:N", title=None, sort=grupos, scale=alt.Scale(paddingInner=0.3),
              axis=alt.Axis(labelAngle=0, labelLimit=160, labelFontSize=12))
    deslocamento = alt.XOffset("serie:N", sort=["Antes", "Depois"], scale=alt.Scale(paddingInner=0.08))
    y = alt.Y("valor:Q", title=titulo_y, scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(grid=True, tickCount=5))
    cor = alt.Color("serie:N", title=None, scale=alt.Scale(domain=["Antes", "Depois"], range=[pal["antes"], pal["cor"]]),
                    legend=alt.Legend(orient="top", direction="horizontal", labelFontSize=12))
    barras = alt.Chart(dados).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=x, xOffset=deslocamento, y=y, color=cor,
        tooltip=[alt.Tooltip("grupo:N", title=" "), alt.Tooltip("serie:N", title=" "), alt.Tooltip("valor:Q", title="Valor")])
    rotulos = alt.Chart(dados).mark_text(dy=-8, fontSize=12, color=pal["rotulo_grafico"]).encode(
        x=x, xOffset=deslocamento, y=y, text="valor:Q")
    grafico = (barras + rotulos).properties(height=altura).configure_view(strokeWidth=0)
    # com poucos grupos (uma ou duas vagas), o gráfico ocupa só parte da largura: barras largas e longe uma da outra
    # confundem mais do que ajudam
    lugar = st.columns([len(grupos), 4 - len(grupos)])[0] if len(grupos) < 4 else st
    lugar.altair_chart(grafico, use_container_width=True)
