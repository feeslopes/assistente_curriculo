"""Ponte entre o app (Streamlit) e o servidor de acesso, só no modo hospedado.

O proxy reverso repassa a identidade assinada pelo servidor de acesso no cabeçalho X-CV-Sessao. Aqui ela é conferida,
vira a pasta do usuário e o plano da cota. Sem identidade válida não existe pasta: o app para (falha fechada).
Nada deste módulo importa o Streamlit, para ser testável: quem chama entrega os cabeçalhos.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from servidor import seguranca
from servidor.banco import Banco

from . import config, cota

CABECALHO = "X-CV-Sessao"
_UID = re.compile(r"[0-9a-f]{32}")
_bancos: dict[str, Banco] = {}


def pasta_de_dados() -> Path:
    return Path(os.environ.get("CV_DADOS_DIR", "dados")).expanduser().resolve()


def banco() -> Banco:
    """Um Banco por caminho, criado na primeira necessidade."""
    caminho = str(pasta_de_dados() / "servidor.db")
    if caminho not in _bancos:
        _bancos[caminho] = Banco(caminho)
    return _bancos[caminho]


def reivindicacao(cabecalhos) -> dict | None:
    """Identidade assinada do cabeçalho, ou None. Nunca confia em outro campo da requisição."""
    try:
        return seguranca.verificar(cabecalhos.get(CABECALHO) or cabecalhos.get(CABECALHO.lower()))
    except Exception:  # noqa: BLE001 - cabeçalhos estranhos: sem identidade
        return None


def raiz_do_usuario(claim: dict | None) -> Path | None:
    """Pasta do usuário (criada se faltar). Só vem de uma identidade verificada, e o uid é conferido de novo aqui."""
    if not claim:
        return None
    uid = str(claim.get("uid", ""))
    if not _UID.fullmatch(uid):
        return None
    raiz = (pasta_de_dados() / "usuarios" / uid).resolve()
    if pasta_de_dados() not in raiz.parents:
        return None
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


def instalar(obter_cabecalhos) -> None:
    """Liga o modo hospedado: config.base_dir() & cia passam a resolver a pasta pela identidade desta requisição."""
    def resolver() -> Path | None:
        return raiz_do_usuario(reivindicacao(obter_cabecalhos()))
    config.registrar_resolvedor_usuario(resolver)


def cota_do(claim: dict, cfg: dict | None = None) -> cota.Cota:
    cfg = cfg or config.carregar_config()
    plano = cota.plano_de(claim, cfg.get("planos") or {})
    return cota.Cota(raiz_do_usuario(claim), plano, cfg.get("limites_uso") or {})


def evento(claim: dict | None, nome: str, **dados) -> None:
    """Métrica de uso sem conteúdo. Falha ao registrar nunca afeta o usuário."""
    if not claim:
        return
    try:
        banco().registrar_evento(seguranca.uid_anonimo(claim["uid"]), nome, dados)
    except Exception:  # noqa: BLE001
        pass
