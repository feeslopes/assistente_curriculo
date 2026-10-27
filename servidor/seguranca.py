"""Segredos, identificadores pseudonimizados e identidade assinada entre o servidor de acesso e o app."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

SEGREDO_MIN = 32
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


class SegredoAusente(Exception):
    pass


def segredo() -> bytes:
    """CV_SEGREDO: valor longo e aleatório, só no servidor. Sem ele o modo hospedado não sobe."""
    valor = os.environ.get("CV_SEGREDO", "")
    if len(valor) < SEGREDO_MIN:
        raise SegredoAusente(f"Defina CV_SEGREDO com pelo menos {SEGREDO_MIN} caracteres aleatórios no ambiente do servidor.")
    return valor.encode("utf-8")


def normalizar_email(email: str) -> str | None:
    e = (email or "").strip().lower()
    return e if len(e) <= 254 and _EMAIL.match(e) else None


def _hmac(dominio: bytes, dado: bytes) -> str:
    return hmac.new(segredo(), dominio + b":" + dado, hashlib.sha256).hexdigest()


def uid_do_email(email: str) -> str:
    """Id estável do usuário, usado como nome de pasta. Não carrega o e-mail e não dá para inverter sem o segredo."""
    return _hmac(b"uid", email.encode("utf-8"))[:32]


def uid_anonimo(uid: str) -> str:
    """Id para as métricas de uso: outro valor derivado, para não ligar a tabela de eventos à pasta do usuário."""
    return _hmac(b"analytics", uid.encode("utf-8"))[:16]


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Só o hash do token fica no banco: quem lê o banco não consegue entrar com ele."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def chave_limite(prefixo: str, valor: str) -> str:
    return f"{prefixo}:{_hmac(b'limite', valor.encode('utf-8'))[:24]}"


def _b64(dado: bytes) -> str:
    return base64.urlsafe_b64encode(dado).decode("ascii").rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def assinar(reivindicacao: dict, validade_s: int = 120, agora: float | None = None) -> str:
    """Identidade que o servidor de acesso entrega ao app em cada requisição. Curta de propósito (replay limitado)."""
    dados = dict(reivindicacao)
    dados["exp"] = int((agora if agora is not None else time.time()) + validade_s)
    corpo = _b64(json.dumps(dados, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{corpo}.{_hmac(b'sessao', corpo.encode('ascii'))}"


def verificar(token: str | None, agora: float | None = None) -> dict | None:
    """Devolve a identidade se a assinatura e a validade estiverem corretas; senão None. Nunca levanta."""
    try:
        if not token or token.count(".") != 1:
            return None
        corpo, assinatura = token.split(".")
        if not hmac.compare_digest(assinatura, _hmac(b"sessao", corpo.encode("ascii"))):
            return None
        dados = json.loads(_desb64(corpo))
        if not isinstance(dados, dict) or float(dados.get("exp", 0)) < (agora if agora is not None else time.time()):
            return None
        if not re.fullmatch(r"[0-9a-f]{32}", str(dados.get("uid", ""))):
            return None
        return dados
    except (ValueError, TypeError, SegredoAusente):
        return None
