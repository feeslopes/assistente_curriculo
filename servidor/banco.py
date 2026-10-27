"""SQLite do modo hospedado: lista de acesso, links, sessões, aceite dos termos, limites, cliques e eventos.

Guarda só o necessário. Tokens ficam como hash. O e-mail aparece apenas na lista de acesso (precisa existir para enviar o
link). Sessões, links e eventos usam ids derivados, nunca o e-mail. O conteúdo dos currículos não passa por aqui.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import seguranca

DIA = 86400
_VALOR_SEGURO = re.compile(r"^[a-z0-9_\-.:/ ]{0,40}$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS acessos (
    email TEXT PRIMARY KEY, uid TEXT NOT NULL UNIQUE, plano TEXT NOT NULL, inicio REAL NOT NULL, fim REAL NOT NULL,
    teto INTEGER, criado REAL NOT NULL, revogado INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS links (hash TEXT PRIMARY KEY, uid TEXT NOT NULL, expira REAL NOT NULL, usado INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessoes (hash TEXT PRIMARY KEY, uid TEXT NOT NULL, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS aceites (uid TEXT NOT NULL, versao TEXT NOT NULL, quando REAL NOT NULL, ip TEXT, PRIMARY KEY (uid, versao));
CREATE TABLE IF NOT EXISTS pedidos (chave TEXT NOT NULL, t REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pedidos ON pedidos (chave, t);
CREATE TABLE IF NOT EXISTS cliques (dia TEXT NOT NULL, plano TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (dia, plano));
CREATE TABLE IF NOT EXISTS visitas (dia TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS eventos (t REAL NOT NULL, anon TEXT NOT NULL, nome TEXT NOT NULL, dados TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_eventos ON eventos (nome, t);
"""


def _dia(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def dados_de_evento(dados: dict | None) -> dict:
    """Só números, booleanos e rótulos curtos (letras minúsculas, dígitos e _-.:/). Texto livre é recusado.

    É a trava que impede um evento de carregar currículo, vaga, empresa ou nome por descuido de quem instrumenta.
    """
    limpo: dict = {}
    for k, v in (dados or {}).items():
        if not re.fullmatch(r"[a-z0-9_]{1,40}", str(k)):
            raise ValueError(f"Nome de campo de evento inválido: {k!r}")
        if isinstance(v, bool) or isinstance(v, (int, float)) or v is None:
            limpo[k] = v
        elif isinstance(v, str) and _VALOR_SEGURO.match(v):
            limpo[k] = v
        else:
            raise ValueError(f"Valor de evento não permitido em {k!r}: só números e rótulos curtos em minúsculas.")
    return limpo


class Banco:
    def __init__(self, caminho: Path | str, agora=time.time):
        self.caminho = Path(caminho)
        self._agora = agora
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.executescript(ESQUEMA)
        try:
            self.caminho.chmod(0o600)
        except OSError:  # Windows: sem efeito
            pass

    @contextmanager
    def _con(self):
        c = sqlite3.connect(self.caminho, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            yield c
            c.commit()
        finally:
            c.close()

    # --------------------------------------------------------------------- acessos
    def liberar(self, email: str, plano: str, dias: int, teto: int | None = None) -> dict:
        """Cria ou renova o acesso de um e-mail. Renovar recomeça a contagem de uso a partir de agora."""
        e = seguranca.normalizar_email(email)
        if not e:
            raise ValueError("E-mail inválido.")
        agora = self._agora()
        uid = seguranca.uid_do_email(e)
        with self._con() as c:
            c.execute(
                "INSERT INTO acessos (email, uid, plano, inicio, fim, teto, criado, revogado) VALUES (?,?,?,?,?,?,?,0) "
                "ON CONFLICT(email) DO UPDATE SET plano=excluded.plano, inicio=excluded.inicio, fim=excluded.fim, "
                "teto=excluded.teto, revogado=0",
                (e, uid, plano, agora, agora + dias * DIA, teto, agora))
        return {"email": e, "uid": uid, "plano": plano, "fim": agora + dias * DIA, "teto": teto}

    def acesso_por_email(self, email: str) -> sqlite3.Row | None:
        e = seguranca.normalizar_email(email)
        if not e:
            return None
        with self._con() as c:
            return c.execute("SELECT * FROM acessos WHERE email=?", (e,)).fetchone()

    def acesso_por_uid(self, uid: str) -> sqlite3.Row | None:
        with self._con() as c:
            return c.execute("SELECT * FROM acessos WHERE uid=?", (uid,)).fetchone()

    def ativo(self, acesso) -> bool:
        return bool(acesso) and not acesso["revogado"] and acesso["fim"] > self._agora()

    def revogar(self, email: str) -> bool:
        e = seguranca.normalizar_email(email)
        with self._con() as c:
            cur = c.execute("UPDATE acessos SET revogado=1 WHERE email=?", (e,))
            if cur.rowcount:
                uid = c.execute("SELECT uid FROM acessos WHERE email=?", (e,)).fetchone()["uid"]
                c.execute("DELETE FROM sessoes WHERE uid=?", (uid,))
                c.execute("DELETE FROM links WHERE uid=?", (uid,))
            return bool(cur.rowcount)

    def listar(self) -> list[sqlite3.Row]:
        with self._con() as c:
            return c.execute("SELECT * FROM acessos ORDER BY criado").fetchall()

    # ----------------------------------------------------------------------- links
    def criar_link(self, uid: str, ttl_s: int = 900) -> str:
        token = seguranca.novo_token()
        with self._con() as c:
            c.execute("DELETE FROM links WHERE expira < ?", (self._agora(),))
            c.execute("INSERT INTO links (hash, uid, expira, usado) VALUES (?,?,?,0)",
                      (seguranca.hash_token(token), uid, self._agora() + ttl_s))
        return token

    def consumir_link(self, token: str) -> str | None:
        """Uso único: devolve o uid e marca como usado, de forma atômica. Link expirado ou reutilizado devolve None."""
        h = seguranca.hash_token(token or "")
        with self._con() as c:
            cur = c.execute("UPDATE links SET usado=1 WHERE hash=? AND usado=0 AND expira>?", (h, self._agora()))
            if cur.rowcount != 1:
                return None
            return c.execute("SELECT uid FROM links WHERE hash=?", (h,)).fetchone()["uid"]

    # --------------------------------------------------------------------- sessões
    def criar_sessao(self, uid: str, dias: int = 7) -> str:
        token = seguranca.novo_token()
        with self._con() as c:
            c.execute("DELETE FROM sessoes WHERE expira < ?", (self._agora(),))
            c.execute("INSERT INTO sessoes (hash, uid, expira) VALUES (?,?,?)",
                      (seguranca.hash_token(token), uid, self._agora() + dias * DIA))
        return token

    def uid_da_sessao(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._con() as c:
            r = c.execute("SELECT uid FROM sessoes WHERE hash=? AND expira>?",
                          (seguranca.hash_token(token), self._agora())).fetchone()
            return r["uid"] if r else None

    def encerrar_sessao(self, token: str | None) -> None:
        if token:
            with self._con() as c:
                c.execute("DELETE FROM sessoes WHERE hash=?", (seguranca.hash_token(token),))

    # ---------------------------------------------------------------------- termos
    def registrar_aceite(self, uid: str, versao: str, ip: str | None) -> None:
        with self._con() as c:
            c.execute("INSERT OR IGNORE INTO aceites (uid, versao, quando, ip) VALUES (?,?,?,?)",
                      (uid, versao, self._agora(), ip))

    def aceitou(self, uid: str, versao: str) -> bool:
        with self._con() as c:
            return c.execute("SELECT 1 FROM aceites WHERE uid=? AND versao=?", (uid, versao)).fetchone() is not None

    # --------------------------------------------------------------------- limites
    def pode_pedir(self, chave: str, maximo: int, janela_s: int) -> bool:
        """Conta o pedido e diz se ainda está dentro do limite na janela. Pedido negado também conta."""
        agora = self._agora()
        with self._con() as c:
            c.execute("DELETE FROM pedidos WHERE t < ?", (agora - 86400,))
            n = c.execute("SELECT COUNT(*) AS n FROM pedidos WHERE chave=? AND t>?", (chave, agora - janela_s)).fetchone()["n"]
            c.execute("INSERT INTO pedidos (chave, t) VALUES (?,?)", (chave, agora))
            return n < maximo

    # -------------------------------------------------------------------- métricas
    def contar_visita(self) -> None:
        with self._con() as c:
            c.execute("INSERT INTO visitas (dia, n) VALUES (?,1) ON CONFLICT(dia) DO UPDATE SET n=n+1", (_dia(self._agora()),))

    def contar_clique(self, plano: str) -> None:
        with self._con() as c:
            c.execute("INSERT INTO cliques (dia, plano, n) VALUES (?,?,1) ON CONFLICT(dia, plano) DO UPDATE SET n=n+1",
                      (_dia(self._agora()), plano))

    def registrar_evento(self, anon: str, nome: str, dados: dict | None = None) -> None:
        if not re.fullmatch(r"[a-z0-9_]{1,40}", nome or ""):
            raise ValueError(f"Nome de evento inválido: {nome!r}")
        corpo = json.dumps(dados_de_evento(dados), separators=(",", ":"))
        with self._con() as c:
            c.execute("INSERT INTO eventos (t, anon, nome, dados) VALUES (?,?,?,?)", (self._agora(), anon, nome, corpo))

    # -------------------------------------------------------------------- exclusão
    def excluir_usuario(self, email: str) -> str | None:
        """Apaga acesso, sessões, links e aceite do usuário. Devolve o uid (para apagar a pasta de dados)."""
        e = seguranca.normalizar_email(email)
        with self._con() as c:
            r = c.execute("SELECT uid FROM acessos WHERE email=?", (e,)).fetchone()
            if not r:
                return None
            uid = r["uid"]
            for tabela in ("sessoes", "links", "aceites"):
                c.execute(f"DELETE FROM {tabela} WHERE uid=?", (uid,))  # noqa: S608 - nomes fixos acima
            c.execute("DELETE FROM eventos WHERE anon=?", (seguranca.uid_anonimo(uid),))
            c.execute("DELETE FROM acessos WHERE email=?", (e,))
            return uid
