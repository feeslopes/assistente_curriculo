"""Cliente ASGI mínimo para testar o servidor de acesso sem httpx."""
import asyncio
from urllib.parse import urlencode


class Resposta:
    def __init__(self, status, cabecalhos, corpo):
        self.status = status
        self.cabecalhos = cabecalhos          # lista de (nome em minúsculas, valor)
        self.corpo = corpo
        self.texto = corpo.decode("utf-8", "replace")

    def cab(self, nome):
        nome = nome.lower()
        return [v for k, v in self.cabecalhos if k == nome]

    @property
    def local(self):
        v = self.cab("location")
        return v[0] if v else None

    def cookie(self, nome):
        for v in self.cab("set-cookie"):
            if v.startswith(nome + "="):
                return v
        return None


async def _chamar(app, metodo, caminho, query, corpo, headers, ip):
    cab = [(b"host", b"localhost:8080")] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    escopo = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": metodo, "scheme": "http",
              "path": caminho, "raw_path": caminho.encode(), "query_string": query.encode(), "root_path": "",
              "headers": cab, "client": (ip, 5000), "server": ("localhost", 8080)}
    pendentes = [{"type": "http.request", "body": corpo, "more_body": False}]
    saida = {"status": 0, "cab": [], "corpo": b""}

    async def receive():
        if pendentes:
            return pendentes.pop(0)
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            saida["status"] = msg["status"]
            saida["cab"] = [(k.decode().lower(), v.decode()) for k, v in msg["headers"]]
        elif msg["type"] == "http.response.body":
            saida["corpo"] += msg.get("body", b"")

    await app(escopo, receive, send)
    return Resposta(saida["status"], saida["cab"], saida["corpo"])


def get(app, caminho, query="", headers=None, ip="203.0.113.5"):
    return asyncio.run(_chamar(app, "GET", caminho, query, b"", headers, ip))


def post(app, caminho, dados=None, headers=None, ip="203.0.113.5"):
    h = {"content-type": "application/x-www-form-urlencoded", **(headers or {})}
    return asyncio.run(_chamar(app, "POST", caminho, "", urlencode(dados or {}).encode(), h, ip))
