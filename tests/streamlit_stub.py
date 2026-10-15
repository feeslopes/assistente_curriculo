"""Módulo `streamlit` falso, permissivo, para o teste de fumaça do app.py.

Só pega erro de import, de nome e de desempacotamento. O comportamento real do Streamlit precisa ser
conferido rodando o aplicativo.
"""
from __future__ import annotations


class Estado(dict):
    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError:
            raise AttributeError(nome) from None

    def __setattr__(self, nome, valor):
        self[nome] = valor


class Parar(Exception):
    """st.rerun() de verdade interrompe a execução do script; o stub também."""


class Ctx:
    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, nome):
        return getattr(self._st, nome)


class FakeStreamlit:
    def __init__(self):
        self.session_state = Estado()
        self.cliques: set[str] = set()
        self.uploads: dict = {}
        self.chat: list[str] = []
        self.valores: dict = {}      # key -> valor forçado para text_input/text_area/checkbox/radio
        self.chamadas: list[tuple] = []
        self.sidebar = Ctx(self)

    # --- saídas sem retorno
    def _mudo(self, nome):
        def f(*a, **k):
            self.chamadas.append((nome, a, k))
        return f

    def __getattr__(self, nome):
        if nome in {"set_page_config", "title", "header", "subheader", "markdown", "write", "caption", "info",
                    "warning", "error", "success", "divider", "code", "json", "metric", "table", "dataframe", "text",
                    "bar_chart"}:
            return self._mudo(nome)
        raise AttributeError(f"stub do streamlit não conhece st.{nome}")

    # --- contêineres
    def tabs(self, rotulos):
        return [Ctx(self) for _ in rotulos]

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(self) for _ in range(n)]

    def container(self, *a, **k): return Ctx(self)
    def empty(self, *a, **k): return Ctx(self)
    def expander(self, *a, **k): return Ctx(self)
    def form(self, *a, **k): return Ctx(self)
    def spinner(self, *a, **k): return Ctx(self)
    def chat_message(self, *a, **k): return Ctx(self)

    def rerun(self):
        raise Parar()

    # --- widgets
    def _valor(self, key, padrao):
        """Como o Streamlit: o valor do widget fica em session_state[key]."""
        if key in self.valores:
            self.session_state[key] = self.valores[key]
        elif key is not None and key not in self.session_state:
            self.session_state[key] = padrao
        return self.session_state[key] if key is not None else padrao

    def button(self, rotulo, key=None, **k):
        return (key or rotulo) in self.cliques and not k.get("disabled", False)

    form_submit_button = button

    def download_button(self, rotulo, data=None, key=None, **k):
        self.chamadas.append(("download_button", (rotulo, len(data or b"")), {}))
        return False

    def text_input(self, rotulo, value="", key=None, **k):
        return self._valor(key, value)

    def text_area(self, rotulo, value="", key=None, **k):
        return self._valor(key, value)

    def checkbox(self, rotulo, value=False, key=None, **k):
        return bool(self._valor(key, value))

    def radio(self, rotulo, opcoes, index=0, key=None, **k):
        return self._valor(key, opcoes[index])

    def number_input(self, rotulo, min_value=None, max_value=None, value=0, step=1, key=None, **k):
        return self._valor(key, value)

    def selectbox(self, rotulo, opcoes, index=0, key=None, **k):
        return self._valor(key, opcoes[index])

    def file_uploader(self, rotulo, type=None, key=None, **k):
        return self.uploads.get(key or rotulo)

    def chat_input(self, rotulo=""):
        return self.chat.pop(0) if self.chat else None


class ArquivoFalso:
    def __init__(self, nome, dados):
        self.name, self._d = nome, dados

    def getvalue(self):
        return self._d
