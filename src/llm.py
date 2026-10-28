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

from . import custo
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
                 segredos: list[str] | None = None, log_dir: Path | None = None,
                 modelos_por_etapa: dict | None = None, guardar_conteudo: bool = True, ao_usar=None):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self._dormir = dormir
        self.timeout = timeout
        self.segredos: list[str] = []
        self.definir_segredos(segredos or [])
        self.log_dir = Path(log_dir) if log_dir else None
        # etapa (rotulo) -> modelo. Etapa sem entrada usa o modelo padrão da configuração.
        self.modelos_por_etapa = {str(k): str(v) for k, v in (modelos_por_etapa or {}).items() if v}
        # False no servidor: o registro guarda só metadados (etapa, tokens, custo), nunca o texto da pessoa.
        self.guardar_conteudo = guardar_conteudo
        # Chamado a cada resposta com os dados de uso (etapa, modelo, tokens, custo, duração). Falha nele não derruba nada.
        self.ao_usar = ao_usar
        self.uso_total = {"chamadas": 0, "entrada": 0, "saida": 0}
        self.custo_usd = 0.0
        self._uso: dict | None = None

    def modelo_da_etapa(self, rotulo: str) -> str:
        base = (rotulo or "").removesuffix("-reparo")
        return self.modelos_por_etapa.get(base) or self.cfg.modelo

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

    def _registrar(self, rotulo: str, mensagens: list[dict], json_mode: bool, resposta: str | None,
                   erro: str | None, duracao: float, modelo: str = "", uso: dict | None = None,
                   custo: float | None = None) -> None:
        """Uma linha por chamada em log_dir/AAAA-MM-DD.jsonl, para depurar e melhorar os prompts.

        Grava o que foi enviado DEPOIS da máscara de contato (então não guarda telefone nem e-mail) e a
        resposta recebida. A chave de API nunca entra. Com guardar_conteudo=False (servidor), grava só
        metadados: etapa, modelo, tokens, custo, duração e tamanhos, sem nenhum texto.
        Falha ao gravar o log nunca derruba o aplicativo.
        """
        if not self.log_dir:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            agora = datetime.now()
            registro = {
                "quando": agora.isoformat(timespec="seconds"), "provedor": self.cfg.provedor,
                "modelo": modelo or self.cfg.modelo, "rotulo": rotulo, "json_mode": json_mode,
                "duracao_s": round(duracao, 2), "uso": uso, "custo_usd": None if custo is None else round(custo, 6),
                "erro": erro,
            }
            if self.guardar_conteudo:
                registro.update({"mensagens": mensagens, "resposta": resposta})
            else:
                registro.update({"mensagens_n": len(mensagens),
                                 "chars_entrada": sum(len(m.get("content", "")) for m in mensagens),
                                 "chars_saida": len(resposta or "")})
            with open(self.log_dir / f"{agora:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    def conversar(self, mensagens: list[dict], json_mode: bool = False, temperatura: float = 0.3,
                  rotulo: str = "") -> str:
        """Envia as mensagens e devolve o texto da resposta. Não defina max_tokens: modelos de
        raciocínio gastam tokens pensando e a resposta pode vir vazia.

        `rotulo` só identifica a chamada no registro (entrevistador, extrator, gerador...)."""
        limpas = [{"role": m["role"], "content": self._limpar(m["content"])} for m in mensagens]
        modelo = self.modelo_da_etapa(rotulo)
        corpo = {"model": modelo, "messages": limpas, "temperature": temperatura}
        corpo.update(self.cfg.extras)
        if json_mode:
            corpo["response_format"] = {"type": "json_object"}
        inicio, resposta, erro = time.time(), None, None
        self._uso = None
        try:
            resposta = self._enviar(corpo)
            return resposta
        except ErroLLM as e:
            erro = str(e)
            raise
        finally:
            duracao = time.time() - inicio
            uso = custo.normalizar_uso(self._uso) if self._uso else None
            gasto = custo.custo_usd(modelo, self._uso) if self._uso else None
            if uso:
                self.uso_total["chamadas"] += 1
                self.uso_total["entrada"] += uso["entrada"]
                self.uso_total["saida"] += uso["saida"]
                self.custo_usd += gasto or 0.0
            self._registrar(rotulo, limpas, json_mode, resposta, erro, duracao, modelo, uso, gasto)
            if uso and self.ao_usar:
                try:
                    self.ao_usar({"rotulo": rotulo, "modelo": modelo, "uso": uso, "custo_usd": gasto,
                                  "duracao_s": round(duracao, 2), "erro": erro})
                except Exception:  # noqa: BLE001 - medir nunca pode derrubar a geração
                    pass

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
            corpo = r.json()
            msg = corpo["choices"][0]["message"]
            texto = msg.get("content") or ""
            usado = corpo.get("usage")
            self._uso = usado if isinstance(usado, dict) else None
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            texto = ""
        texto = remover_raciocinio(texto)
        if not texto:
            raise ErroLLM("O modelo devolveu uma resposta vazia. Isso acontece quando ele gasta tudo "
                          "pensando ou o modelo é fraco demais. Tente de novo ou troque de modelo.")
        return texto


def completar_json(llm, mensagens: list[dict], temperatura: float = 0.2, rotulo: str = ""):
    """Pede JSON, tolera sujeira e faz UMA tentativa de reparo antes de desistir."""
    bruto = llm.conversar(mensagens, json_mode=True, temperatura=temperatura, rotulo=rotulo)
    try:
        return extrair_json(bruto)
    except ValueError:
        pass
    reparo = mensagens + [
        {"role": "assistant", "content": bruto},
        {"role": "user", "content": "A resposta anterior não era um JSON válido. "
                                    "Devolva somente o JSON, sem texto antes ou depois."},
    ]
    bruto = llm.conversar(reparo, json_mode=True, temperatura=0.0, rotulo=f"{rotulo}-reparo")
    try:
        return extrair_json(bruto)
    except ValueError:
        raise ErroLLM("O modelo não conseguiu devolver um JSON válido. "
                      "Tente de novo ou troque de modelo no arquivo .env.") from None
