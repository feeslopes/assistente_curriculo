"""Dublês de teste: LLM falso com fila de respostas e sessão HTTP falsa."""
import copy
import json
import shutil
import tempfile
from pathlib import Path

from src.kb import KB

RAIZ = Path(__file__).resolve().parent.parent

SLUG_ATUAL = "empresa-exemplo-digital-analista-de-marketing"
SLUG_ASSIST = "loja-modelo-assistente-de-marketing"
SLUG_ESTAG = "loja-modelo-estagiaria-de-marketing"


class LLMFalso:
    """Devolve as respostas da fila, na ordem. Guarda as chamadas para inspeção."""

    def __init__(self, *respostas):
        self.fila = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in respostas]
        self.chamadas = []

    def conversar(self, mensagens, json_mode=False, temperatura=0.3):
        self.chamadas.append({"mensagens": copy.deepcopy(mensagens), "json_mode": json_mode})
        if not self.fila:
            raise AssertionError("LLMFalso: fila de respostas esgotada")
        return self.fila.pop(0)


class Resp:
    def __init__(self, status=200, corpo=None, headers=None, texto=""):
        self.status_code = status
        self._corpo = corpo
        self.headers = headers or {}
        self.text = texto

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


def ok(conteudo):
    return Resp(200, {"choices": [{"message": {"content": conteudo}}]})


class SessaoFalsa:
    def __init__(self, *respostas):
        self.fila = list(respostas)
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "json": copy.deepcopy(json)})
        item = self.fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None):
        return self.fila.pop(0)


def base_exemplo():
    """Copia a base de exemplo para uma pasta temporária e devolve (KB, pasta_tmp)."""
    tmp = Path(tempfile.mkdtemp())
    destino = tmp / "base"
    shutil.copytree(RAIZ / "exemplo" / "base", destino)
    return KB(destino), tmp


def limpar(tmp):
    shutil.rmtree(tmp, ignore_errors=True)
