"""O app no modo hospedado, com o streamlit falso: sem identidade nada abre, cada usuário vê só a sua pasta."""
import importlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import altair  # noqa: F401

from servidor import seguranca
from src import config, cota, hospedado
from tests import streamlit_stub as stub
from tests.fakes import RAIZ, limpar

os.environ.setdefault("CV_SEGREDO", "x" * 48)
UID_A = seguranca.uid_do_email("a@exemplo.com")
UID_B = seguranca.uid_do_email("b@exemplo.com")


def cabecalhos(uid, plano="mensal", fim=9e12, inicio=0, teto=None):
    return {hospedado.CABECALHO: seguranca.assinar({"uid": uid, "plano": plano, "inicio": inicio, "fim": fim, "teto": teto})}


def _descarregar():
    for nome in [m for m in sys.modules if m == "app" or m == "interface" or m.startswith("interface.")]:
        sys.modules.pop(nome, None)


class TestAppHospedado(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = stub.FakeStreamlit()
        self.atual = {}
        self.st.context = types.SimpleNamespace(headers=types.SimpleNamespace(get=lambda k, d=None: self.atual.get(k, d)))
        self.patch_mod = mock.patch.dict(sys.modules, {"streamlit": self.st})
        self.patch_mod.start()
        _descarregar()
        self.app = importlib.import_module("app")
        self.env = mock.patch.dict(os.environ, {"CV_MODO": "hospedado", "CV_DADOS_DIR": str(self.tmp),
                                                "PROVEDOR": "deepseek", "DEEPSEEK_API_KEY": "k", "MODELO": "m"})
        self.env.start()
        self.sem_env = mock.patch.object(config, "carregar_env", lambda: None)
        self.sem_env.start()
        hospedado._bancos.clear()

    def tearDown(self):
        config.registrar_resolvedor_usuario(None)
        self.sem_env.stop()
        self.env.stop()
        self.patch_mod.stop()
        _descarregar()
        limpar(self.tmp)

    def rodar(self):
        try:
            self.app.main()
        except stub.Parar:
            pass

    def textos(self, nome):
        return " ".join(str(c[1][0]) for c in self.st.chamadas if c[0] == nome and c[1])

    def test_sem_identidade_nada_abre_e_nenhuma_pasta_e_criada(self):
        for cab in ({}, {hospedado.CABECALHO: "forjado"}, {"X-CV-User": UID_A}):
            self.atual = cab
            self.st.chamadas.clear()
            self.rodar()
            self.assertIn("Sua sessão não foi encontrada", self.textos("markdown"))
            self.assertTrue(any(c[0] == "link_button" and c[1][1] == "/login" for c in self.st.chamadas))
            self.assertNotIn("Vamos montar o seu currículo", self.textos("markdown"))
        self.assertFalse((self.tmp / "usuarios").exists())

    def test_com_identidade_abre_na_pasta_do_usuario_e_sem_itens_locais(self):
        self.atual = cabecalhos(UID_A)
        self.rodar()
        self.assertIn("Vamos montar o seu currículo", self.textos("markdown"))
        self.assertTrue((self.tmp / "usuarios" / UID_A).is_dir())
        legendas = self.textos("caption")
        self.assertNotIn("só no seu computador", legendas)
        self.assertIn("DeepSeek", legendas)
        self.assertNotIn("Só quer ver como funciona", self.textos("markdown"))

    def test_um_usuario_nao_ve_a_base_do_outro(self):
        base_a = self.tmp / "usuarios" / UID_A / "base"
        shutil.copytree(RAIZ / "exemplo" / "base", base_a)
        self.atual = cabecalhos(UID_A)
        self.rodar()
        self.assertNotIn("Vamos montar o seu currículo", self.textos("markdown"))   # A já tem histórico
        self.st.chamadas.clear()
        self.st.session_state.clear()
        self.atual = cabecalhos(UID_B)
        self.rodar()
        self.assertIn("Vamos montar o seu currículo", self.textos("markdown"))      # B começa do zero
        self.assertFalse((self.tmp / "usuarios" / UID_B / "base" / "perfil.md").exists())

    def test_identidade_expirada_nao_entra(self):
        self.atual = {hospedado.CABECALHO: seguranca.assinar({"uid": UID_A}, validade_s=-5)}
        self.rodar()
        self.assertIn("Sua sessão não foi encontrada", self.textos("markdown"))


class TestCotaNaGeracao(TestAppHospedado):
    def comum(self):
        return sys.modules["interface.comum"]

    def test_gera_registra_e_bloqueia_no_teto(self):
        self.atual = cabecalhos(UID_A, teto=2)
        hospedado.instalar(lambda: self.atual)
        comum = self.comum()
        self.assertEqual(comum.gerar_com_cota("vaga 1", lambda: "ok"), "ok")
        self.assertEqual(comum.gerar_com_cota("vaga 2", lambda: "ok"), "ok")
        with self.assertRaises(cota.ErroCota):
            comum.gerar_com_cota("vaga 3", lambda: "nao deveria rodar")

    def test_geracao_que_falha_nao_consome_a_cota(self):
        self.atual = cabecalhos(UID_A, teto=1)
        hospedado.instalar(lambda: self.atual)
        comum = self.comum()

        def falha():
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            comum.gerar_com_cota("vaga", falha)
        self.assertEqual(comum.gerar_com_cota("vaga", lambda: "ok"), "ok")

    def test_plano_vencido_bloqueia(self):
        self.atual = cabecalhos(UID_A, fim=1)
        hospedado.instalar(lambda: self.atual)
        with self.assertRaises(cota.ErroCota):
            self.comum().gerar_com_cota("vaga", lambda: "ok")

    def test_sem_identidade_bloqueia(self):
        self.atual = {}
        hospedado.instalar(lambda: self.atual)
        with self.assertRaises(cota.ErroCota):
            self.comum().gerar_com_cota("vaga", lambda: "ok")

    def test_local_nao_tem_teto(self):
        with mock.patch.dict(os.environ, {"CV_MODO": ""}):
            for _ in range(100):
                self.assertEqual(self.comum().gerar_com_cota("v", lambda: 1), 1)

    def test_cotas_de_usuarios_diferentes_sao_independentes(self):
        comum = self.comum()
        self.atual = cabecalhos(UID_A, teto=1)
        hospedado.instalar(lambda: self.atual)
        comum.gerar_com_cota("v", lambda: 1)
        self.atual = cabecalhos(UID_B, teto=1)
        self.assertEqual(comum.gerar_com_cota("v", lambda: 1), 1)     # B tem a sua própria conta


if __name__ == "__main__":
    unittest.main()
