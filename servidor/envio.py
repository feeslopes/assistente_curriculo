"""Envio do link de acesso por e-mail.

O serviço de envio ainda não está escolhido. Enquanto isso:
- com SMTP_HOST (e demais SMTP_*) no ambiente, envia por SMTP (qualquer serviço transacional serve);
- sem SMTP e com CV_ENV=dev, escreve o link no log do servidor, para testar no seu computador;
- sem SMTP e fora de dev, não envia e não registra o link em lugar nenhum (o aviso diz que o envio não está configurado).
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("cv.envio")


class Enviador:
    def enviar(self, para: str, assunto: str, texto: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEnviador(Enviador):
    """Só para desenvolvimento: o link aparece no log local."""

    def enviar(self, para: str, assunto: str, texto: str) -> None:
        log.warning("[dev] e-mail para %s: %s\n%s", para, assunto, texto)


class NuloEnviador(Enviador):
    def enviar(self, para: str, assunto: str, texto: str) -> None:
        log.error("Envio de e-mail não configurado (defina SMTP_HOST). Nenhum e-mail foi enviado.")


class SMTPEnviador(Enviador):
    def __init__(self, host: str, porta: int, usuario: str, senha: str, remetente: str):
        self.host, self.porta, self.usuario, self.senha, self.remetente = host, porta, usuario, senha, remetente

    def enviar(self, para: str, assunto: str, texto: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.remetente, para, assunto
        msg.set_content(texto)
        contexto = ssl.create_default_context()
        if self.porta == 465:
            with smtplib.SMTP_SSL(self.host, self.porta, context=contexto, timeout=20) as s:
                self._enviar(s, msg)
        else:
            with smtplib.SMTP(self.host, self.porta, timeout=20) as s:
                s.starttls(context=contexto)
                self._enviar(s, msg)

    def _enviar(self, s, msg) -> None:
        if self.usuario:
            s.login(self.usuario, self.senha)
        s.send_message(msg)


def do_ambiente(env=None) -> Enviador:
    env = os.environ if env is None else env
    host = (env.get("SMTP_HOST") or "").strip()
    if host:
        remetente = (env.get("SMTP_REMETENTE") or "").strip()
        if not remetente:
            raise ValueError("Defina SMTP_REMETENTE (endereço de quem envia) junto com SMTP_HOST.")
        return SMTPEnviador(host, int(env.get("SMTP_PORTA") or 587), (env.get("SMTP_USUARIO") or "").strip(),
                            env.get("SMTP_SENHA") or "", remetente)
    if (env.get("CV_ENV") or "").strip().lower() == "dev":
        return ConsoleEnviador()
    return NuloEnviador()
