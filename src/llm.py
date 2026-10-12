"""Cliente único para APIs compatíveis com OpenAI (Gemini, DeepSeek, OpenRouter)."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from .texto import extrair_json, mascarar_contato, remover_raciocinio


class ErroLLM(Exception):
    """Erro já em português, pronto para mostrar na tela."""


class ErroConfig(ErroLLM):
    """Provedor ou chave não configurados."""


PROVEDORES = {
    "gemini": {
        "nome": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "chave": "GEMINI_API_KEY",
        # Confirmado na página de preços do Google em 12/10/2026: gemini-3.8-flash tem camada gratuita.
        "modelo_padrao": "gemini-3.8-flash",
    },
    "deepseek": {
        "nome": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "chave": "DEEPSEEK_API_KEY",
        # Não usar deepseek-chat nem deepseek-reasoner (descontinuados).
        "modelo_padrao": "deepseek-flash",
        # O raciocínio é o padrão e deixa tudo lento. Desligamos para as tarefas de formato.
        "extras": {"thinking": {"type": "disabled"}},
    },
    "openrouter": {
        "nome": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "chave": "OPENROUTER_API_KEY",
        "modelo_padrao": None,
    },
}


@dataclass
class Configuracao:
    provedor: str
    chave: str
    modelo: str
    base_url: str
    extras: dict

    @classmethod
    def do_ambiente(cls, env=None) -> "Configuracao":
        env = os.environ if env is None else env
        prov = (env.get("PROVEDOR") or "gemini").strip().lower()
        if prov not in PROVEDORES:
            raise ErroConfig(f"PROVEDOR '{prov}' não existe. Use gemini, deepseek ou openrouter no arquivo .env.")
        info = PROVEDORES[prov]
        chave = (env.get(info["chave"]) or "").strip()
        if not chave:
            raise ErroConfig(f"Falta a chave {info['chave']} no arquivo .env (provedor {info['nome']}).")
        modelo = (env.get("MODELO") or "").strip() or info["modelo_padrao"]
        if not modelo:
            raise ErroConfig(
                "O OpenRouter não tem modelo padrão. Escreva MODELO=nome-do-modelo:free no arquivo .env. "
                "Lembre que modelos gratuitos mais fracos inventam mais, e isso é o risco de um currículo."
            )
        return cls(prov, chave, modelo, info["base_url"].rstrip("/"), dict(info.get("extras", {})))

    @property
    def nome_provedor(self) -> str:
        return PROVEDORES[self.provedor]["nome"]


class LLM:
    """Uma classe, uma rota (/chat/completions). A sessão HTTP é injetável para testes."""

    def __init__(self, cfg: Configuracao, sessao=None, dormir=time.sleep, timeout: int = 180,
                 segredos: list[str] | None = None, debug_log: Path | None = None):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self._dormir = dormir
        self.timeout = timeout
        self.segredos: list[str] = []
        self.definir_segredos(segredos or [])
        self.debug_log = debug_log if debug_log else (
            Path("saidas") / "debug.log" if os.environ.get("CV_DEBUG") else None)

    # ---------------------------------------------------------------- privacidade
    def definir_segredos(self, valores) -> None:
        """Valores literais (telefone, e-mail, nome...) que nunca podem sair no prompt."""
        self.segredos = [str(v).strip() for v in valores if v and len(str(v).strip()) >= 4]

    def _limpar(self, texto: str) -> str:
        t = mascarar_contato(texto)
        for s in self.segredos:
            t = re.sub(re.escape(s), "[omitido]", t, flags=re.I)
        return t

    # ------------------------------------------------------------------ chamadas
    def _cabecalhos(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.chave}", "Content-Type": "application/json"}

    def _log(self, corpo: dict) -> None:
        if not self.debug_log:
            return
        try:
            self.debug_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.debug_log, "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat()} {self.cfg.provedor}/{self.cfg.modelo}\n")
                f.write(json.dumps(corpo, ensure_ascii=False, indent=1) + "\n")
        except OSError:
            pass

    def conversar(self, mensagens: list[dict], json_mode: bool = False, temperatura: float = 0.3) -> str:
        """Envia as mensagens e devolve o texto da resposta. Não defina max_tokens: modelos de
        raciocínio gastam tokens pensando e a resposta pode vir vazia."""
        limpas = [{"role": m["role"], "content": self._limpar(m["content"])} for m in mensagens]
        corpo = {"model": self.cfg.modelo, "messages": limpas, "temperature": temperatura}
        corpo.update(self.cfg.extras)
        if json_mode:
            corpo["response_format"] = {"type": "json_object"}
        self._log(corpo)
        return self._enviar(corpo)

    def modelos(self) -> list[str]:
        url = f"{self.cfg.base_url}/models"
        try:
            r = self.sessao.get(url, headers=self._cabecalhos(), timeout=30)
        except requests.RequestException as e:
            raise ErroLLM(f"Não consegui falar com {self.cfg.nome_provedor}: {type(e).__name__}.") from None
        self._checar_status(r)
        ids = [m.get("id", "") for m in (r.json().get("data") or [])]
        return sorted(i.removeprefix("models/") for i in ids if i)

    # ------------------------------------------------------------------- interno
    def _enviar(self, corpo: dict) -> str:
        url = f"{self.cfg.base_url}/chat/completions"
        tentativas_429 = tentativas_5xx = tentativas_rede = 0
        while True:
            try:
                r = self.sessao.post(url, headers=self._cabecalhos(), json=corpo, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                tentativas_rede += 1
                if tentativas_rede > 2:
                    raise ErroLLM(
                        "A conexão com o provedor falhou ou demorou demais. Confira a internet e tente de novo."
                    ) from None
                self._dormir(3 * tentativas_rede)
                continue
            s = r.status_code
            if s == 200:
                return self._conteudo(r)
            if s == 400:
                # Alguns modelos rejeitam response_format ou parâmetros extras: tenta sem.
                if "response_format" in corpo:
                    corpo.pop("response_format")
                    continue
                if any(k in corpo for k in self.cfg.extras):
                    for k in self.cfg.extras:
                        corpo.pop(k, None)
                    continue
            if s == 429:
                tentativas_429 += 1
                if tentativas_429 > 4:
                    raise ErroLLM(
                        "Limite de uso do provedor atingido. No plano gratuito o limite por minuto é baixo: "
                        "espere cerca de um minuto e tente de novo."
                    )
                espera = self._espera_retry_after(r) or min(5 * 2 ** (tentativas_429 - 1), 60)
                self._dormir(espera)
                continue
            if s >= 500:
                tentativas_5xx += 1
                if tentativas_5xx > 3:
                    raise ErroLLM("O provedor está com problema no momento. Tente de novo em alguns minutos.")
                self._dormir(2 * 2 ** (tentativas_5xx - 1))
                continue
            self._checar_status(r)

    @staticmethod
    def _espera_retry_after(r) -> float | None:
        try:
            v = float(r.headers.get("Retry-After", ""))
            return min(max(v, 1), 90)
        except (TypeError, ValueError):
            return None

    def _checar_status(self, r) -> None:
        s = r.status_code
        if s == 200:
            return
        if s in (401, 403):
            raise ErroLLM("A chave de API foi recusada (inválida, expirada ou sem permissão). "
                          "Confira a chave no arquivo .env.")
        if s == 404:
            raise ErroLLM(f"O modelo '{self.cfg.modelo}' não existe nesse provedor. "
                          "Rode `python verificar.py --modelos` para ver os que a sua chave enxerga.")
        detalhe = ""
        try:
            erro = r.json().get("error", {})
            detalhe = erro.get("message", "") if isinstance(erro, dict) else str(erro)
        except Exception:
            pass
        raise ErroLLM(f"O provedor devolveu erro {s}. {detalhe[:200]}".strip())

    def _conteudo(self, r) -> str:
        try:
            msg = r.json()["choices"][0]["message"]
            texto = msg.get("content") or ""
        except (KeyError, IndexError, TypeError, ValueError):
            texto = ""
        texto = remover_raciocinio(texto)
        if not texto:
            raise ErroLLM("O modelo devolveu uma resposta vazia. Isso acontece quando ele gasta tudo "
                          "pensando ou o modelo é fraco demais. Tente de novo ou troque de modelo.")
        return texto


def completar_json(llm, mensagens: list[dict], temperatura: float = 0.2):
    """Pede JSON, tolera sujeira e faz UMA tentativa de reparo antes de desistir."""
    bruto = llm.conversar(mensagens, json_mode=True, temperatura=temperatura)
    try:
        return extrair_json(bruto)
    except ValueError:
        pass
    reparo = mensagens + [
        {"role": "assistant", "content": bruto},
        {"role": "user", "content": "A resposta anterior não era um JSON válido. "
                                    "Devolva somente o JSON, sem texto antes ou depois."},
    ]
    bruto = llm.conversar(reparo, json_mode=True, temperatura=0.0)
    try:
        return extrair_json(bruto)
    except ValueError:
        raise ErroLLM("O modelo não conseguiu devolver um JSON válido. "
                      "Tente de novo ou troque de modelo no arquivo .env.") from None
