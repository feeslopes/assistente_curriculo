"""Servidor de acesso: landing, login por link mágico, aceite dos termos e verificação de sessão para o proxy.

Fluxo: o proxy reverso (Caddy) pergunta a /auth/verificar, a cada requisição ao app, se a sessão é válida. Se for, esta
camada devolve a identidade assinada (X-CV-Sessao) e o proxy a repassa ao Streamlit. Requisição sem sessão válida nunca
chega ao app. /auth/* não deve ser exposto ao público: é só para o proxy.

Rodar:  CV_MODO=hospedado uvicorn --factory servidor.gateway:app_do_ambiente --host 127.0.0.1 --port 8081
"""
from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote, urlsplit

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src import config

from . import envio, seguranca
from .banco import Banco

log = logging.getLogger("cv.gateway")
SITE = Path(__file__).resolve().parent.parent / "site"
COOKIE = "cv_sessao"
PLANOS_WHATSAPP = {"semanal": "o plano semanal", "mensal": "o plano mensal"}
MAX_CORPO = 4096

CSP = ("default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")
MSG_PEDIDO = "Se esse e-mail tiver acesso, enviamos um link. Ele vale por 15 minutos e só funciona uma vez."


@dataclass
class Config:
    url_publica: str = "http://localhost:8080"
    cookie_seguro: bool = True
    whatsapp_numero: str = ""
    versao_termos: str = "2026-10-28"
    email_contato: str = ""
    confiar_proxy: bool = False
    preco_semanal: str = "7"
    preco_mensal: str = "15"
    nome_produto: str = "Assistente Currículo"
    url_app: str = "/app/"

    @classmethod
    def do_ambiente(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            url_publica=(env.get("CV_URL_PUBLICA") or cls.url_publica).rstrip("/"),
            cookie_seguro=(env.get("CV_ENV") or "").strip().lower() != "dev",
            whatsapp_numero="".join(ch for ch in (env.get("WHATSAPP_NUMERO") or "") if ch.isdigit()),
            versao_termos=(env.get("CV_VERSAO_TERMOS") or cls.versao_termos).strip(),
            email_contato=(env.get("CV_EMAIL_CONTATO") or "").strip(),
            confiar_proxy=(env.get("CV_CONFIAR_PROXY") or "").strip() == "1",
            preco_semanal=(env.get("PRECO_SEMANAL") or cls.preco_semanal).strip(),
            preco_mensal=(env.get("PRECO_MENSAL") or cls.preco_mensal).strip(),
            nome_produto=(env.get("NOME_PRODUTO") or cls.nome_produto).strip(),
        )


def _aviso(texto: str, erro: bool = False) -> str:
    return f'<div class="aviso{" erro" if erro else ""}">{html.escape(texto)}</div>' if texto else ""


def _pagina(nome: str, **valores) -> str:
    """Lê site/<nome>.html e troca $campos por valores já escapados.

    `mensagem` e `erro` viram blocos de aviso prontos (`$mensagem_html`, `$erro_html`); `mensagem_erro=True` pinta de erro.
    """
    modelo = Template((SITE / f"{nome}.html").read_text(encoding="utf-8"))
    subst = {k: html.escape(str(v)) for k, v in valores.items() if k not in ("mensagem", "erro", "mensagem_erro")}
    subst["mensagem_html"] = _aviso(str(valores.get("mensagem", "")), bool(valores.get("mensagem_erro")))
    subst["erro_html"] = _aviso(str(valores.get("erro", "")), True)
    return modelo.safe_substitute(subst)


def _limites_do_plano() -> dict:
    """Tetos e regerações lidos do config.yaml, para a landing mostrar o mesmo número que o app aplica."""
    try:
        cfg = config.carregar_config()
        planos = cfg.get("planos") or {}
        return {"teto_semanal": (planos.get("semanal") or {}).get("geracoes", 15),
                "teto_mensal": (planos.get("mensal") or {}).get("geracoes", 60),
                "regeracoes": (cfg.get("limites_uso") or {}).get("regeracoes_por_vaga", 3)}
    except (ValueError, OSError):
        return {"teto_semanal": 15, "teto_mensal": 60, "regeracoes": 3}


def _html(corpo: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(corpo, status_code=status)


class CabecalhosDeSeguranca(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool):
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request, call_next):
        r = await call_next(request)
        r.headers["Content-Security-Policy"] = CSP
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "same-origin"   # no-referrer faz o navegador mandar Origin: null nos formulários
        r.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        r.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(("/auth", "/entrar", "/login", "/termos", "/sair")):
            r.headers["Cache-Control"] = "no-store"
        if self.hsts:
            r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return r


def criar_app(banco: Banco, enviador: envio.Enviador, cfg: Config) -> Starlette:
    def ip_de(request: Request) -> str:
        if cfg.confiar_proxy:
            enc = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if enc:
                return enc[:64]
        return request.client.host if request.client else "?"

    def origem_ok(request: Request) -> bool:
        """POST só de páginas do próprio site (defesa extra além do SameSite do cookie)."""
        origem = request.headers.get("origin") or request.headers.get("referer")
        if not origem:
            return True
        return urlsplit(origem).netloc == urlsplit(cfg.url_publica).netloc or \
            urlsplit(origem).netloc == request.headers.get("host", "")

    async def formulario(request: Request) -> dict[str, str]:
        corpo = b""
        async for pedaco in request.stream():
            corpo += pedaco
            if len(corpo) > MAX_CORPO:
                return {}
        return {k: v[0] for k, v in parse_qs(corpo.decode("utf-8", "replace"), max_num_fields=10).items()}

    def comum() -> dict:
        contato = "o mesmo WhatsApp usado na contratação" + (f", ou o e-mail {cfg.email_contato}" if cfg.email_contato else "")
        return {"produto": cfg.nome_produto, "preco_semanal": cfg.preco_semanal, "preco_mensal": cfg.preco_mensal,
                "versao": cfg.versao_termos, "contato": contato, **_limites_do_plano()}

    # ------------------------------------------------------------------ páginas
    async def landing(request: Request) -> Response:
        banco.contar_visita()
        return _html(_pagina("index", **comum()))

    async def login_get(request: Request) -> Response:
        return _html(_pagina("login", mensagem="", **comum()))

    async def login_post(request: Request) -> Response:
        if not origem_ok(request):
            return PlainTextResponse("Requisição recusada.", status_code=403)
        dados = await formulario(request)
        email = seguranca.normalizar_email(dados.get("email", ""))
        tarefa = None
        permitido = banco.pode_pedir(seguranca.chave_limite("ip", ip_de(request)), 10, 900)
        if email and permitido and banco.pode_pedir(seguranca.chave_limite("email", email), 3, 900):
            acesso = banco.acesso_por_email(email)
            if banco.ativo(acesso):
                token = banco.criar_link(acesso["uid"])
                link = f"{cfg.url_publica}/entrar?t={quote(token)}"
                texto = (f"Seu link de acesso ao {cfg.nome_produto}:\n\n{link}\n\n"
                         "Ele vale por 15 minutos e só funciona uma vez. Se não foi você, ignore este e-mail.")
                tarefa = BackgroundTask(_enviar_sem_derrubar, enviador, email, f"Seu link de acesso ao {cfg.nome_produto}", texto)
        # A resposta é sempre a mesma, para ninguém descobrir quem é cliente (e o envio sai em segundo plano).
        resposta = _html(_pagina("login", mensagem=MSG_PEDIDO, **comum()))
        resposta.background = tarefa
        return resposta

    async def entrar(request: Request) -> Response:
        uid = banco.consumir_link(request.query_params.get("t", ""))
        acesso = banco.acesso_por_uid(uid) if uid else None
        if not uid or not banco.ativo(acesso):
            return _html(_pagina("login", mensagem="Link inválido, vencido ou já usado. Peça um novo.",
                                 mensagem_erro=True, **comum()), 400)
        token = banco.criar_sessao(uid)
        destino = cfg.url_app if banco.aceitou(uid, cfg.versao_termos) else "/termos"
        r = RedirectResponse(destino, status_code=303)
        r.set_cookie(COOKIE, token, max_age=7 * 86400, httponly=True, secure=cfg.cookie_seguro, samesite="lax", path="/")
        return r

    def uid_logado(request: Request) -> str | None:
        uid = banco.uid_da_sessao(request.cookies.get(COOKIE))
        return uid if uid and banco.ativo(banco.acesso_por_uid(uid)) else None

    async def termos_get(request: Request) -> Response:
        if not uid_logado(request):
            return RedirectResponse("/login", status_code=303)
        return _html(_pagina("termos", erro="", **comum()))

    async def termos_post(request: Request) -> Response:
        uid = uid_logado(request)
        if not uid:
            return RedirectResponse("/login", status_code=303)
        if not origem_ok(request):
            return PlainTextResponse("Requisição recusada.", status_code=403)
        dados = await formulario(request)
        if dados.get("aceito") != "sim":
            return _html(_pagina("termos", erro="Marque a caixa para continuar.", **comum()), 400)
        banco.registrar_aceite(uid, cfg.versao_termos, ip_de(request))
        return RedirectResponse(cfg.url_app, status_code=303)

    async def sair_get(request: Request) -> Response:
        return _html(_pagina("sair", **comum()))

    async def sair(request: Request) -> Response:
        if not origem_ok(request):
            return PlainTextResponse("Requisição recusada.", status_code=403)
        banco.encerrar_sessao(request.cookies.get(COOKIE))
        r = RedirectResponse("/", status_code=303)
        r.delete_cookie(COOKIE, path="/")
        return r

    async def pagina_estatica(nome: str) -> Response:
        return _html(_pagina(nome, **comum()))

    async def privacidade(request: Request) -> Response:
        return await pagina_estatica("privacidade")

    async def go(request: Request) -> Response:
        plano = request.path_params["plano"]
        if plano not in PLANOS_WHATSAPP:
            return PlainTextResponse("Não encontrado.", status_code=404)
        if not cfg.whatsapp_numero:
            return PlainTextResponse("A contratação está sendo configurada. Tente novamente em instantes.", status_code=503)
        banco.contar_clique(plano)
        texto = f"Oi, quero contratar {PLANOS_WHATSAPP[plano]} do {cfg.nome_produto}."
        return RedirectResponse(f"https://wa.me/{cfg.whatsapp_numero}?text={quote(texto)}", status_code=302)

    # ----------------------------------------------- verificação para o proxy (não público)
    async def verificar(request: Request) -> Response:
        uid = uid_logado(request)
        acesso = banco.acesso_por_uid(uid) if uid else None
        if uid and banco.aceitou(uid, cfg.versao_termos):
            claim = {"uid": uid, "plano": acesso["plano"], "inicio": acesso["inicio"], "fim": acesso["fim"],
                     "teto": acesso["teto"]}
            return Response(status_code=200, headers={"X-CV-Sessao": seguranca.assinar(claim)})
        uri = request.headers.get("x-forwarded-uri", "")
        if "_stcore" in uri or uri.startswith("/app/_"):       # conexões internas do Streamlit: sem redirecionar
            return Response(status_code=401)
        return RedirectResponse("/login" if not uid else "/termos", status_code=302)

    rotas = [
        Route("/", landing), Route("/login", login_get, methods=["GET"]), Route("/login", login_post, methods=["POST"]),
        Route("/entrar", entrar), Route("/termos", termos_get, methods=["GET"]),
        Route("/termos", termos_post, methods=["POST"]), Route("/sair", sair_get, methods=["GET"]),
        Route("/sair", sair, methods=["POST"]),
        Route("/privacidade", privacidade), Route("/go/{plano}", go),
        Route("/auth/verificar", verificar),
        Mount("/static", StaticFiles(directory=SITE / "static"), name="static"),
    ]
    app = Starlette(routes=rotas)
    app.add_middleware(CabecalhosDeSeguranca, hsts=cfg.cookie_seguro)
    return app


def _enviar_sem_derrubar(enviador: envio.Enviador, para: str, assunto: str, texto: str) -> None:
    try:
        enviador.enviar(para, assunto, texto)
    except Exception:  # noqa: BLE001 - falha de e-mail nunca pode mudar a resposta ao usuário
        log.exception("Falha ao enviar o link de acesso")


def app_do_ambiente() -> Starlette:
    """Ponto de entrada do uvicorn. Falha cedo se faltar segredo ou configuração de e-mail inválida."""
    seguranca.segredo()
    dados = Path(os.environ.get("CV_DADOS_DIR", "dados")).expanduser()
    return criar_app(Banco(dados / "servidor.db"), envio.do_ambiente(), Config.do_ambiente())

