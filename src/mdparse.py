"""Parser do subconjunto de Markdown que o currículo usa.

Suporta: `#`/`##`/`###`, parágrafos (quebra dura com dois espaços ou barra no fim da linha), listas com
`*`, `-` ou `+`, **negrito**, _itálico_ (ou *itálico*) e [texto](url). O PDF e o DOCX saem deste mesmo
resultado, então o que a pessoa edita é o que é exportado.

Cada bloco é {"tipo": "h1" | "h2" | "h3" | "p" | "li", "linhas": [[(texto, estilos), ...], ...]}.
`estilos` é um frozenset com "b" e/ou "i". Um parágrafo tem uma lista de linhas (quebras duras).
"""
from __future__ import annotations

import re

_INLINE = re.compile(
    r"\*\*(?P<b>.+?)\*\*"
    r"|(?<![\w*])\*(?![\s*])(?P<i1>.+?)(?<![\s*])\*(?![\w*])"
    r"|(?<!\w)_(?!\s)(?P<i2>.+?)(?<!\s)_(?!\w)"
    r"|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)\)"
)
_LISTA = re.compile(r"^\s*[-*+]\s+(.*)$")
_TITULO = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
_VAZIO = frozenset()


def parse_inline(texto: str, estilos: frozenset = _VAZIO) -> list[tuple[str, frozenset]]:
    """Divide o texto em trechos (texto, estilos). Link vira 'texto (url)'."""
    saida: list[tuple[str, frozenset]] = []
    pos = 0
    for m in _INLINE.finditer(texto):
        if m.start() > pos:
            saida.append((texto[pos:m.start()], estilos))
        if m.group("b") is not None:
            saida += parse_inline(m.group("b"), estilos | {"b"})
        elif m.group("i1") is not None:
            saida += parse_inline(m.group("i1"), estilos | {"i"})
        elif m.group("i2") is not None:
            saida += parse_inline(m.group("i2"), estilos | {"i"})
        else:
            texto_link, url = m.group("lt"), m.group("lu")
            saida.append((texto_link if texto_link.strip() == url else f"{texto_link} ({url})", estilos))
        pos = m.end()
    if pos < len(texto):
        saida.append((texto[pos:], estilos))
    return [(t, e) for t, e in saida if t]


def _quebra_dura(linha: str) -> bool:
    return linha.endswith("  ") or linha.endswith("\\")


def parse(markdown: str) -> list[dict]:
    blocos: list[dict] = []
    paragrafo: list[str] = []   # linhas do parágrafo corrente, já com marca de quebra

    def fechar():
        if not paragrafo:
            return
        linhas, atual = [], []
        for bruta in paragrafo:
            dura = _quebra_dura(bruta)
            limpa = bruta.rstrip().removesuffix("\\").rstrip()
            atual.append(limpa)
            if dura:
                linhas.append(" ".join(atual))
                atual = []
        if atual:
            linhas.append(" ".join(atual))
        blocos.append({"tipo": "p", "linhas": [parse_inline(l) for l in linhas if l.strip()]})
        paragrafo.clear()

    for bruta in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        linha = bruta.rstrip("\n")
        if not linha.strip():
            fechar()
            continue
        t = _TITULO.match(linha.strip())
        if t:
            fechar()
            blocos.append({"tipo": f"h{len(t.group(1))}", "linhas": [parse_inline(t.group(2))]})
            continue
        li = _LISTA.match(linha)
        if li and not re.match(r"^\s*\*\*", linha):
            fechar()
            blocos.append({"tipo": "li", "linhas": [parse_inline(li.group(1).strip())]})
            continue
        # linha de continuação de um item de lista (indentada) gruda no item anterior
        if blocos and blocos[-1]["tipo"] == "li" and not paragrafo and linha.startswith((" ", "\t")):
            blocos[-1]["linhas"][0] += [(" ", _VAZIO)] + parse_inline(linha.strip())
            continue
        paragrafo.append(linha)
    fechar()
    return [b for b in blocos if b["linhas"]]


def texto_simples(linha: list[tuple[str, frozenset]]) -> str:
    return "".join(t for t, _ in linha)


def so_estilo(linha: list[tuple[str, frozenset]], estilo: str) -> bool:
    """True se a linha inteira está no estilo ('b' ou 'i'). Usado para empresa e cargo."""
    return bool(linha) and all(estilo in e for t, e in linha if t.strip())
