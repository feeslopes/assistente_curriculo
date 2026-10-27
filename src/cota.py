"""Teto de uso do servidor: gerações por período do plano, regerações por vaga e velocidade.

Unidade de uso: uma geração de currículo (por vaga ou geral). Regerar a mesma vaga também conta, mas só até
`regeracoes_por_vaga` vezes além da primeira. Editar o texto à mão não chama a IA e não entra na conta.

O plano (tipo, início, fim, teto) vem da identidade assinada pelo servidor de acesso, nunca de campo da tela.
O registro das gerações fica na pasta do usuário (cota.json). O app local não usa nada disto.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .kb import ErroBase

DIA = 86400
_TRAVA = threading.Lock()
GUARDA_DIAS = 120   # eventos mais antigos que isso são descartados


class ErroCota(ErroBase):
    """Limite de uso atingido ou plano vencido. A mensagem já está em português e vai direto para a tela."""


@dataclass(frozen=True)
class Plano:
    tipo: str
    inicio: float      # epoch: começo do plano (define as janelas)
    fim: float         # epoch: validade
    geracoes: int      # teto por janela
    dias: int          # tamanho da janela
    aviso_em: int = 0


def plano_de(reivindicacao: dict, planos_cfg: dict) -> Plano:
    """Monta o Plano a partir do que o servidor de acesso assinou, completando com o config.yaml."""
    tipo = str(reivindicacao.get("plano") or "")
    base = (planos_cfg or {}).get(tipo) or {}
    teto = int(reivindicacao.get("teto") or base.get("geracoes") or 0)
    dias = int(base.get("dias") or 30)
    return Plano(tipo=tipo, inicio=float(reivindicacao.get("inicio") or 0), fim=float(reivindicacao.get("fim") or 0),
                 geracoes=teto, dias=dias, aviso_em=int(base.get("aviso_em") or 0))


def id_da_vaga(texto: str) -> str:
    norma = " ".join((texto or "").lower().split())[:4000]
    return hashlib.sha256(norma.encode("utf-8")).hexdigest()[:16]


def _data(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


class Cota:
    def __init__(self, raiz: Path, plano: Plano, limites: dict | None = None, agora=time.time):
        self.arquivo = Path(raiz) / "cota.json"
        self.plano = plano
        lim = limites or {}
        self.regeracoes_por_vaga = int(lim.get("regeracoes_por_vaga", 3))
        self.por_hora = int(lim.get("geracoes_por_hora", 10))
        self._agora = agora

    # ---------------------------------------------------------------- armazenamento
    def _ler(self) -> list[dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            eventos = dados.get("eventos", [])
            return [e for e in eventos if isinstance(e, dict) and isinstance(e.get("t"), (int, float))]
        except (OSError, ValueError, AttributeError):
            return []

    def _gravar(self, eventos: list[dict]) -> None:
        corte = self._agora() - GUARDA_DIAS * DIA
        eventos = [e for e in eventos if e["t"] >= corte]
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps({"eventos": eventos}), encoding="utf-8")
        os.replace(tmp, self.arquivo)

    # ---------------------------------------------------------------------- janelas
    def janela(self) -> tuple[float, float]:
        """Início e fim da janela de contagem atual (blocos de `dias` a partir do início do plano)."""
        agora, p = self._agora(), self.plano
        passo = max(p.dias, 1) * DIA
        n = max(int((agora - p.inicio) // passo), 0)
        ini = p.inicio + n * passo
        return ini, ini + passo

    def situacao(self) -> dict:
        ini, fim = self.janela()
        usadas = sum(1 for e in self._ler() if ini <= e["t"] < fim)
        teto = self.plano.geracoes
        return {"plano": self.plano.tipo, "usadas": usadas, "teto": teto, "restantes": max(teto - usadas, 0),
                "aviso": bool(self.plano.aviso_em) and usadas >= self.plano.aviso_em, "renova_em": fim,
                "vence_em": self.plano.fim}

    # ---------------------------------------------------------------------- regras
    def autorizar(self, vaga_texto: str) -> None:
        agora, p = self._agora(), self.plano
        if p.geracoes <= 0 or not p.tipo:
            raise ErroCota("Seu acesso não tem um plano ativo. Fale com a gente para contratar.")
        if agora > p.fim:
            raise ErroCota(f"Seu plano venceu em {_data(p.fim)}. Fale com a gente para renovar.")
        ini, fim = self.janela()
        with _TRAVA:
            eventos = self._ler()
        na_janela = [e for e in eventos if ini <= e["t"] < fim]
        if len(na_janela) >= p.geracoes:
            raise ErroCota(f"Você usou as {p.geracoes} gerações do seu plano {p.tipo}. "
                           f"O limite renova em {_data(fim)}. Editar o texto à mão continua liberado.")
        vaga = id_da_vaga(vaga_texto)
        desta_vaga = sum(1 for e in na_janela if e.get("vaga") == vaga)
        if desta_vaga >= 1 + self.regeracoes_por_vaga:
            raise ErroCota(f"Você já regerou esta vaga {self.regeracoes_por_vaga} vezes. "
                           "Ajuste o texto à mão ou revise o seu histórico para melhorar o resultado.")
        ultima_hora = sorted(e["t"] for e in eventos if e["t"] > agora - 3600)
        if len(ultima_hora) >= self.por_hora:
            espera = max(int((ultima_hora[0] + 3600 - agora) // 60) + 1, 1)
            raise ErroCota(f"Muitas gerações em pouco tempo. Tente de novo em cerca de {espera} minuto(s).")

    def registrar(self, vaga_texto: str) -> None:
        with _TRAVA:
            eventos = self._ler()
            vaga = id_da_vaga(vaga_texto)
            ini, fim = self.janela()
            repetida = any(e.get("vaga") == vaga and ini <= e["t"] < fim for e in eventos)
            eventos.append({"t": self._agora(), "vaga": vaga, "tipo": "regeracao" if repetida else "nova"})
            self._gravar(eventos)
