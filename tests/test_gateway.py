import os
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from servidor import envio, seguranca
from servidor.banco import Banco
from servidor.gateway import Config, criar_app
from tests import asgi
from tests.fakes import limpar

os.environ.setdefault("CV_SEGREDO", "x" * 48)


class EnviadorFalso(envio.Enviador):
    def __init__(self):
        self.enviados = []

    def enviar(self, para, assunto, texto):
        self.enviados.append((para, assunto, texto))

    def ultimo_token(self):
        return parse_qs(urlsplit(re.search(r"https?://\S+", self.enviados[-1][2]).group(0)).query)["t"][0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.relogio = [1_800_000_000.0]
        self.banco = Banco(self.tmp / "s.db", agora=lambda: self.relogio[0])
        self.env = EnviadorFalso()
        self.cfg = Config(url_publica="http://localhost:8080", cookie_seguro=True, whatsapp_numero="5511999990000",
                          versao_termos="v1")
        self.app = criar_app(self.banco, self.env, self.cfg)
        self.banco.liberar("Maria@Exemplo.com", "mensal", 30)

    def tearDown(self):
        limpar(self.tmp)

    def entrar(self):
        asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        r = asgi.get(self.app, "/entrar", f"t={self.env.ultimo_token()}")
        return r, re.match(r"cv_sessao=([^;]+)", r.cookie("cv_sessao")).group(1)


class TestLogin(Base):
    def test_resposta_igual_para_quem_tem_e_quem_nao_tem_acesso(self):
        a = asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        b = asgi.post(self.app, "/login", {"email": "estranho@exemplo.com"})
        c = asgi.post(self.app, "/login", {"email": "isso nao e email"})
        self.assertEqual((a.status, b.status, c.status), (200, 200, 200))
        norm = lambda t: re.sub(r"\s+", " ", t)
        self.assertEqual(norm(a.texto).count("Se esse e-mail tiver acesso"), 1)
        self.assertEqual(norm(a.texto), norm(b.texto))
        self.assertEqual([e[0] for e in self.env.enviados], ["maria@exemplo.com"])

    def test_acesso_vencido_ou_revogado_nao_recebe_link(self):
        self.banco.revogar("maria@exemplo.com")
        asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        self.assertEqual(self.env.enviados, [])
        self.banco.liberar("maria@exemplo.com", "mensal", 30)
        self.relogio[0] += 31 * 86400
        asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        self.assertEqual(self.env.enviados, [])

    def test_limite_de_pedidos_por_email(self):
        for _ in range(5):
            asgi.post(self.app, "/login", {"email": "maria@exemplo.com"}, ip="198.51.100.9")
        self.assertEqual(len(self.env.enviados), 3)

    def test_link_funciona_uma_vez_e_define_cookie_seguro(self):
        asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        t = self.env.ultimo_token()
        r = asgi.get(self.app, "/entrar", f"t={t}")
        self.assertEqual((r.status, r.local), (303, "/termos"))
        c = r.cookie("cv_sessao")
        self.assertIn("HttpOnly", c)
        self.assertIn("Secure", c)
        self.assertRegex(c.lower(), r"samesite=lax")
        r2 = asgi.get(self.app, "/entrar", f"t={t}")
        self.assertEqual(r2.status, 400)
        self.assertIn("inválido", r2.texto)

    def test_link_expira(self):
        asgi.post(self.app, "/login", {"email": "maria@exemplo.com"})
        t = self.env.ultimo_token()
        self.relogio[0] += 901
        self.assertEqual(asgi.get(self.app, "/entrar", f"t={t}").status, 400)

    def test_token_lixo(self):
        self.assertEqual(asgi.get(self.app, "/entrar", "t=abc").status, 400)
        self.assertEqual(asgi.get(self.app, "/entrar").status, 400)

    def test_origem_estranha_e_recusada(self):
        r = asgi.post(self.app, "/login", {"email": "maria@exemplo.com"}, headers={"origin": "https://malvado.example"})
        self.assertEqual(r.status, 403)
        self.assertEqual(self.env.enviados, [])


class TestSessaoETermos(Base):
    def test_verificar_sem_cookie_redireciona_e_streamlit_recebe_401(self):
        r = asgi.get(self.app, "/auth/verificar", headers={"x-forwarded-uri": "/app/"})
        self.assertEqual((r.status, r.local), (302, "/login"))
        self.assertEqual(asgi.get(self.app, "/auth/verificar", headers={"x-forwarded-uri": "/app/_stcore/stream"}).status, 401)

    def test_sem_aceite_dos_termos_nao_entra_e_depois_entra_com_identidade_assinada(self):
        _, sessao = self.entrar()
        ck = {"cookie": f"cv_sessao={sessao}"}
        r = asgi.get(self.app, "/auth/verificar", headers={**ck, "x-forwarded-uri": "/app/"})
        self.assertEqual((r.status, r.local), (302, "/termos"))
        self.assertEqual(asgi.post(self.app, "/termos", {}, headers=ck).status, 400)        # sem marcar
        self.assertEqual(asgi.post(self.app, "/termos", {"aceito": "sim"}, headers=ck).local, "/app/")
        ok = asgi.get(self.app, "/auth/verificar", headers=ck)
        self.assertEqual(ok.status, 200)
        claim = seguranca.verificar(ok.cab("x-cv-sessao")[0])
        self.assertEqual(claim["plano"], "mensal")
        self.assertEqual(claim["uid"], seguranca.uid_do_email("maria@exemplo.com"))
        self.assertNotIn("maria", ok.cab("x-cv-sessao")[0])

    def test_aceite_fica_registrado_com_versao(self):
        _, sessao = self.entrar()
        asgi.post(self.app, "/termos", {"aceito": "sim"}, headers={"cookie": f"cv_sessao={sessao}"}, ip="198.51.100.7")
        uid = seguranca.uid_do_email("maria@exemplo.com")
        self.assertTrue(self.banco.aceitou(uid, "v1"))
        self.assertFalse(self.banco.aceitou(uid, "v2"))

    def test_nova_versao_dos_termos_pede_novo_aceite(self):
        _, sessao = self.entrar()
        ck = {"cookie": f"cv_sessao={sessao}"}
        asgi.post(self.app, "/termos", {"aceito": "sim"}, headers=ck)
        app2 = criar_app(self.banco, self.env, Config(url_publica="http://localhost:8080", versao_termos="v2"))
        self.assertEqual(asgi.get(app2, "/auth/verificar", headers=ck).local, "/termos")

    def test_acesso_revogado_derruba_a_sessao(self):
        _, sessao = self.entrar()
        ck = {"cookie": f"cv_sessao={sessao}"}
        asgi.post(self.app, "/termos", {"aceito": "sim"}, headers=ck)
        self.banco.revogar("maria@exemplo.com")
        self.assertEqual(asgi.get(self.app, "/auth/verificar", headers=ck).status, 302)

    def test_sair_encerra_a_sessao(self):
        _, sessao = self.entrar()
        ck = {"cookie": f"cv_sessao={sessao}"}
        asgi.post(self.app, "/termos", {"aceito": "sim"}, headers=ck)
        r = asgi.post(self.app, "/sair", {}, headers=ck)
        self.assertEqual(r.local, "/")
        self.assertEqual(asgi.get(self.app, "/auth/verificar", headers=ck).status, 302)

    def test_cookie_falso_nao_entra(self):
        self.assertEqual(asgi.get(self.app, "/auth/verificar", headers={"cookie": "cv_sessao=inventado"}).status, 302)

    def test_sessao_expira(self):
        _, sessao = self.entrar()
        ck = {"cookie": f"cv_sessao={sessao}"}
        asgi.post(self.app, "/termos", {"aceito": "sim"}, headers=ck)
        self.relogio[0] += 8 * 86400
        self.banco.liberar("maria@exemplo.com", "mensal", 30)   # acesso ainda válido, mas a sessão venceu
        self.assertEqual(asgi.get(self.app, "/auth/verificar", headers=ck).status, 302)


class TestPaginas(Base):
    def test_landing_mostra_precos_e_limites_sem_sobras_de_template(self):
        r = asgi.get(self.app, "/")
        self.assertEqual(r.status, 200)
        self.assertIn("R$ 7", r.texto)
        self.assertIn("R$ 15", r.texto)
        self.assertIn("até 60 currículos por mês".lower(), r.texto.lower())
        self.assertNotRegex(r.texto, r"\$[a-z_]+")
        self.assertNotIn("—", r.texto)

    def test_paginas_publicas_sem_placeholders(self):
        for caminho in ("/login", "/privacidade"):
            r = asgi.get(self.app, caminho)
            self.assertEqual(r.status, 200, caminho)
            self.assertNotRegex(r.texto, r"\$[a-z_]+", caminho)
            self.assertNotIn("—", r.texto)

    def test_cabecalhos_de_seguranca(self):
        r = asgi.get(self.app, "/login")
        self.assertIn("default-src 'none'", r.cab("content-security-policy")[0])
        self.assertEqual(r.cab("x-content-type-options"), ["nosniff"])
        self.assertEqual(r.cab("x-frame-options"), ["DENY"])
        self.assertIn("max-age", r.cab("strict-transport-security")[0])
        self.assertEqual(r.cab("cache-control"), ["no-store"])

    def test_whatsapp_por_plano_conta_clique_sem_cookie(self):
        r = asgi.get(self.app, "/go/semanal")
        self.assertEqual(r.status, 302)
        self.assertTrue(r.local.startswith("https://wa.me/5511999990000?text="))
        self.assertIn("semanal", r.local)
        self.assertEqual(r.cab("set-cookie"), [])
        with self.banco._con() as c:
            self.assertEqual(c.execute("SELECT SUM(n) FROM cliques WHERE plano='semanal'").fetchone()[0], 1)

    def test_whatsapp_nao_configurado_e_plano_invalido(self):
        app = criar_app(self.banco, self.env, Config(url_publica="http://localhost:8080"))
        self.assertEqual(asgi.get(app, "/go/mensal").status, 503)
        self.assertEqual(asgi.get(self.app, "/go/../../etc").status, 404)
        self.assertEqual(asgi.get(self.app, "/go/qualquer").status, 404)

    def test_politica_de_referrer_permite_a_checagem_de_origem(self):
        # Com no-referrer o navegador manda "Origin: null" nos formulários e o próprio site seria recusado.
        r = asgi.get(self.app, "/login")
        self.assertEqual(r.cab("referrer-policy"), ["same-origin"])
        ok = asgi.post(self.app, "/login", {"email": "maria@exemplo.com"}, headers={"origin": "http://localhost:8080"})
        self.assertEqual(ok.status, 200)
        nulo = asgi.post(self.app, "/login", {"email": "maria@exemplo.com"}, headers={"origin": "null"})
        self.assertEqual(nulo.status, 403)

    def test_html_nao_executa_entrada(self):
        r = asgi.post(self.app, "/login", {"email": '"><script>alert(1)</script>@x.com'})
        self.assertNotIn("<script>alert", r.texto)

    def test_visita_conta_sem_guardar_ip(self):
        asgi.get(self.app, "/")
        asgi.get(self.app, "/")
        with self.banco._con() as c:
            self.assertEqual(c.execute("SELECT SUM(n) FROM visitas").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
