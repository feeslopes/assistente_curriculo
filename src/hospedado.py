"""Ponte entre o app (Streamlit) e o servidor de acesso, só no modo hospedado.

O proxy reverso repassa a identidade assinada pelo servidor de acesso no cabeçalho X-CV-Sessao. Aqui ela é conferida,
vira a pasta do usuário e o plano da cota. Sem identidade válida não existe pasta: o app para (falha fechada).
Nada deste módulo importa o Streamlit, para ser testável: quem chama entrega os cabeçalhos.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from servidor import seguranca
from servidor.banco import Banco

from . import config, cota

CABECALHO = "X-CV-Sessao"
INICIO_DEV = 1_700_000_000.0   # só para o usuário de desenvolvimento
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


class ErroDev(Exception):
    """CV_DEV_USUARIO definido fora do modo de desenvolvimento. O app se recusa a abrir."""


def dev_usuario() -> str | None:
    """E-mail do usuário fixo de desenvolvimento, ou None.

    Só vale com CV_ENV=dev. Se CV_DEV_USUARIO existir sem isso, levanta ErroDev: no servidor essa variável não pode
    existir, e um descuido não pode virar uma porta aberta.
    """
    email = (os.environ.get("CV_DEV_USUARIO") or "").strip()
    if not email:
        return None
    if (os.environ.get("CV_ENV") or "").strip().lower() != "dev":
        raise ErroDev("CV_DEV_USUARIO só pode ser usado com CV_ENV=dev. Remova a variável do ambiente do servidor.")
    return email


def _identidade_dev() -> dict | None:
    email = seguranca.normalizar_email(dev_usuario() or "")
    if not email:
        return None
    agora = time.time()
    plano = (os.environ.get("CV_DEV_PLANO") or "mensal").strip()
    try:
        teto = int(os.environ["CV_DEV_TETO"]) if os.environ.get("CV_DEV_TETO") else None
    except ValueError:
        teto = None
    # inicio fixo: as janelas de contagem da cota precisam ser as mesmas em toda requisição
    return {"uid": seguranca.uid_do_email(email), "plano": plano, "inicio": INICIO_DEV, "fim": agora + 30 * 86400,
            "teto": teto, "dev": True}


def reivindicacao(cabecalhos) -> dict | None:
    """Identidade assinada do cabeçalho, ou None. Nunca confia em outro campo da requisição.

    Em desenvolvimento (CV_ENV=dev com CV_DEV_USUARIO), sem cabeçalho válido, vale o usuário fixo de teste.
    """
    try:
        claim = seguranca.verificar(cabecalhos.get(CABECALHO) or cabecalhos.get(CABECALHO.lower()))
        return claim or _identidade_dev()
    except Exception:  # noqa: BLE001 - cabeçalhos estranhos ou dev mal configurado: sem identidade
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
