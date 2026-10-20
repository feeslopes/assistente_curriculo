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

    # O que o fiscal responde quando a fila não traz uma resposta de fiscal: nada a apontar.
    FISCAL_PADRAO = json.dumps({"itens": [], "palavras": []})

    def __init__(self, *respostas):
        self.fila = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in respostas]
        self.chamadas = []
        self.ultima: dict[str, str] = {}

    @staticmethod
    def _parece_fiscal(resposta: str) -> bool:
        try:
            d = json.loads(resposta)
        except ValueError:
            return False
        return isinstance(d, dict) and bool(set(d) & {"itens", "palavras", "problemas"}) and "requisitos" not in d

    @staticmethod
    def _parece_curriculo(resposta: str) -> bool:
        try:
            d = json.loads(resposta)
        except ValueError:
            return False
        return isinstance(d, dict) and bool(set(d) & {"experiencias", "resumo", "competencias"})

    def conversar(self, mensagens, json_mode=False, temperatura=0.3, rotulo=""):
        self.chamadas.append({"mensagens": copy.deepcopy(mensagens), "json_mode": json_mode, "rotulo": rotulo})
        # O fiscal roda em pontos que os testes antigos não previam (termos duvidosos na análise): se a próxima
        # resposta da fila não é de fiscal, ele não aponta nada e a fila segue intacta.
        if rotulo == "verificador" and (not self.fila or not self._parece_fiscal(self.fila[0])):
            return self.FISCAL_PADRAO
        # Correções extras do gerador (tamanho, plano): se a fila não traz outra versão de currículo, repete a última,
        # como um modelo que não mudou nada.
        if rotulo == "gerador" and rotulo in self.ultima and (not self.fila or not self._parece_curriculo(self.fila[0])):
            return self.ultima[rotulo]
        if not self.fila:
            raise AssertionError("LLMFalso: fila de respostas esgotada")
        resposta = self.fila.pop(0)
        self.ultima[rotulo] = resposta
        return resposta


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
