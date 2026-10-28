import os
import tempfile
import unittest
from pathlib import Path

from servidor import seguranca
from servidor.banco import Banco, dados_de_evento
from src import config, hospedado
from tests.fakes import limpar

os.environ.setdefault("CV_SEGREDO", "x" * 48)

UID_A = seguranca.uid_do_email("a@exemplo.com")
UID_B = seguranca.uid_do_email("b@exemplo.com")


def cab(uid, **extra):
    return {hospedado.CABECALHO: seguranca.assinar({"uid": uid, "plano": "mensal", "inicio": 0, "fim": 9e12, **extra})}


class Ambiente(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.antigo = {k: os.environ.get(k) for k in ("CV_DADOS_DIR", "CV_MODO", "CV_BASE_DIR")}
        os.environ["CV_DADOS_DIR"] = str(self.tmp)
        os.environ["CV_MODO"] = "hospedado"
        hospedado._bancos.clear()

    def tearDown(self):
        for k, v in self.antigo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.registrar_resolvedor_usuario(None)
        limpar(self.tmp)


class TestIdentidade(Ambiente):
    def test_assinatura_valida_e_adulterada(self):
        t = seguranca.assinar({"uid": UID_A})
        self.assertEqual(seguranca.verificar(t)["uid"], UID_A)
        corpo, sig = t.split(".")
        self.assertIsNone(seguranca.verificar(f"{corpo}.{'0' * len(sig)}"))
        outro = seguranca.assinar({"uid": UID_B}).split(".")[0]
        self.assertIsNone(seguranca.verificar(f"{outro}.{sig}"))          # corpo de outro usuário com a assinatura de A
        self.assertIsNone(seguranca.verificar(None))
        self.assertIsNone(seguranca.verificar("lixo"))
        self.assertIsNone(seguranca.verificar("a.b.c"))

    def test_expira(self):
        t = seguranca.assinar({"uid": UID_A}, validade_s=10, agora=1000)
        self.assertIsNotNone(seguranca.verificar(t, agora=1005))
        self.assertIsNone(seguranca.verificar(t, agora=1011))

    def test_uid_com_formato_estranho_e_recusado(self):
        for uid in ("../../etc", "A" * 32, "abc", UID_A + "/x", ""):
            t = seguranca.assinar({"uid": uid})
            self.assertIsNone(seguranca.verificar(t), uid)

    def test_segredo_curto_nao_sobe(self):
        antigo = os.environ["CV_SEGREDO"]
        os.environ["CV_SEGREDO"] = "curto"
        try:
            with self.assertRaises(seguranca.SegredoAusente):
                seguranca.segredo()
        finally:
            os.environ["CV_SEGREDO"] = antigo

    def test_uid_nao_revela_o_email_e_e_estavel(self):
        self.assertEqual(UID_A, seguranca.uid_do_email("a@exemplo.com"))
        self.assertNotEqual(UID_A, UID_B)
        self.assertNotIn("exemplo", UID_A)
        self.assertNotEqual(seguranca.uid_anonimo(UID_A), UID_A)


class TestIsolamento(Ambiente):
    def test_cada_usuario_tem_a_sua_pasta_e_sem_identidade_nao_ha_pasta(self):
        atual = {"cab": cab(UID_A)}
        hospedado.instalar(lambda: atual["cab"])
        a = config.base_dir()
        atual["cab"] = cab(UID_B)
        b = config.base_dir()
        self.assertNotEqual(a, b)
        self.assertEqual(a.parent.name, UID_A)
        self.assertEqual(b.parent.name, UID_B)
        self.assertEqual(config.saidas_dir().parent.name, UID_B)
        self.assertEqual(config.logs_dir().parent.name, UID_B)
        for cabecalhos in ({}, {hospedado.CABECALHO: "forjado"}, {"X-CV-User": UID_A}):
            atual["cab"] = cabecalhos
            with self.assertRaises(config.SemUsuario):
                config.base_dir()

    def test_cv_base_dir_e_ignorado_no_servidor(self):
        os.environ["CV_BASE_DIR"] = str(self.tmp / "outra")
        hospedado.instalar(lambda: cab(UID_A))
        self.assertEqual(config.base_dir().parent.name, UID_A)

    def test_sem_resolvedor_falha_fechada(self):
        config.registrar_resolvedor_usuario(None)
        with self.assertRaises(config.SemUsuario):
            config.saidas_dir()

    def test_modo_local_nao_muda(self):
        os.environ["CV_MODO"] = ""
        config.registrar_resolvedor_usuario(None)
        self.assertEqual(config.base_dir().name, "base")
        self.assertEqual(config.logs_dir(), config.saidas_dir() / "logs")

    def test_pasta_fica_dentro_da_pasta_de_dados(self):
        raiz = hospedado.raiz_do_usuario({"uid": UID_A})
        self.assertIn(self.tmp.resolve(), raiz.parents)
        self.assertIsNone(hospedado.raiz_do_usuario({"uid": "../" + UID_A[3:]}))
        self.assertIsNone(hospedado.raiz_do_usuario(None))


class TestEventosSemPII(Ambiente):
    def test_aceita_contagens_e_rotulos_curtos(self):
        self.assertEqual(dados_de_evento({"etapa": "gerador", "entrada": 1234, "custo_usd": 0.02, "ok": True, "x": None}),
                         {"etapa": "gerador", "entrada": 1234, "custo_usd": 0.02, "ok": True, "x": None})

    def test_recusa_texto_livre_e_nomes(self):
        for dados in ({"vaga": "Analista de Marketing na Empresa X"}, {"email": "a@b.com"}, {"nome": "Maria Souza"},
                      {"t": "x" * 41}, {"lista": [1, 2]}, {"Campo": 1}, {"a b": 1}):
            with self.assertRaises(ValueError, msg=str(dados)):
                dados_de_evento(dados)

    def test_registra_com_id_anonimo_sem_uid_nem_email(self):
        claim = seguranca.verificar(cab(UID_A)[hospedado.CABECALHO])
        hospedado.evento(claim, "geracao_ok", paginas=2, idioma="pt")
        with hospedado.banco()._con() as c:
            linhas = c.execute("SELECT * FROM eventos").fetchall()
        self.assertEqual(len(linhas), 1)
        bruto = str(tuple(linhas[0]))
        self.assertNotIn(UID_A, bruto)
        self.assertNotIn("exemplo", bruto)
        self.assertEqual(linhas[0]["anon"], seguranca.uid_anonimo(UID_A))

    def test_evento_invalido_nao_derruba_e_nao_grava(self):
        claim = seguranca.verificar(cab(UID_A)[hospedado.CABECALHO])
        hospedado.evento(claim, "geracao_ok", vaga="Texto livre da vaga com Empresa")
        hospedado.evento(None, "geracao_ok", paginas=1)
        with hospedado.banco()._con() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM eventos").fetchone()[0], 0)


class TestExclusao(Ambiente):
    def test_excluir_usuario_apaga_acesso_sessoes_aceite_e_eventos(self):
        b = hospedado.banco()
        b.liberar("a@exemplo.com", "mensal", 30)
        tok = b.criar_sessao(UID_A)
        b.registrar_aceite(UID_A, "v1", "1.2.3.4")
        b.registrar_evento(seguranca.uid_anonimo(UID_A), "x", {"n": 1})
        self.assertEqual(b.excluir_usuario("A@Exemplo.com"), UID_A)
        self.assertIsNone(b.uid_da_sessao(tok))
        self.assertFalse(b.aceitou(UID_A, "v1"))
        self.assertIsNone(b.acesso_por_email("a@exemplo.com"))
        with b._con() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM eventos").fetchone()[0], 0)
        self.assertIsNone(b.excluir_usuario("naoexiste@exemplo.com"))


class TestBanco(Ambiente):
    def test_token_guardado_so_como_hash(self):
        b = Banco(self.tmp / "t.db")
        b.liberar("a@exemplo.com", "mensal", 30)
        tok = b.criar_link(UID_A)
        with b._con() as c:
            guardado = c.execute("SELECT hash FROM links").fetchone()[0]
        self.assertNotEqual(guardado, tok)
        self.assertNotIn(tok, guardado)
        self.assertEqual(b.consumir_link(tok), UID_A)
        self.assertIsNone(b.consumir_link(tok))

    def test_liberar_exige_email_valido_e_renova(self):
        b = Banco(self.tmp / "t.db")
        with self.assertRaises(ValueError):
            b.liberar("nao-e-email", "mensal", 30)
        b.liberar("A@Exemplo.com", "semanal", 7)
        b.liberar("a@exemplo.com", "mensal", 30)
        self.assertEqual(len(b.listar()), 1)
        self.assertEqual(b.acesso_por_email("a@exemplo.com")["plano"], "mensal")


if __name__ == "__main__":
    unittest.main()


class TestAdmin(Ambiente):
    def test_liberar_listar_excluir_apaga_pasta(self):
        from servidor import admin
        b = hospedado.banco()
        r = admin.liberar(b, "Cliente@Exemplo.com", "semanal", None, None)
        self.assertEqual(r["plano"], "semanal")
        self.assertAlmostEqual((r["fim"] - b._agora()) / 86400, 7, delta=0.01)
        with self.assertRaises(SystemExit):
            admin.liberar(b, "x@exemplo.com", "inexistente", None, None)
        pasta = hospedado.raiz_do_usuario({"uid": r["uid"]})
        (pasta / "base").mkdir()
        (pasta / "base" / "perfil.md").write_text("- [confirmado] dado", encoding="utf-8")
        outro = hospedado.raiz_do_usuario({"uid": UID_B})
        self.assertEqual(admin.excluir(b, "cliente@exemplo.com", hospedado.pasta_de_dados()), r["uid"])
        self.assertFalse(pasta.exists())
        self.assertTrue(outro.exists())            # a pasta de outro usuário não é tocada

    def test_metricas_so_agregados(self):
        from servidor import admin
        b = hospedado.banco()
        claim = seguranca.verificar(cab(UID_A)[hospedado.CABECALHO])
        hospedado.evento(claim, "ia_chamada", etapa="gerador", custo_usd=0.03, entrada=100)
        hospedado.evento(claim, "geracao_ok", usadas=1)
        b.contar_visita()
        b.contar_clique("mensal")
        m = admin.metricas(b)
        self.assertEqual(m["visitas_landing"], 1)
        self.assertEqual(m["cliques_whatsapp"], {"mensal": 1})
        self.assertEqual(m["custo_ia_usd"], 0.03)
        self.assertEqual(m["usuarios_com_atividade"], 1)


class TestUsuarioDeDesenvolvimento(Ambiente):
    def setUp(self):
        super().setUp()
        self.vars = {k: os.environ.get(k) for k in ("CV_ENV", "CV_DEV_USUARIO", "CV_DEV_PLANO", "CV_DEV_TETO")}
        for k in self.vars:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.vars.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def test_sem_a_variavel_nada_muda(self):
        self.assertIsNone(hospedado.dev_usuario())
        self.assertIsNone(hospedado.reivindicacao({}))

    def test_com_cv_env_dev_vale_o_usuario_fixo(self):
        os.environ.update({"CV_ENV": "dev", "CV_DEV_USUARIO": "Teste@Exemplo.com", "CV_DEV_PLANO": "semanal", "CV_DEV_TETO": "3"})
        c = hospedado.reivindicacao({})
        self.assertEqual(c["uid"], seguranca.uid_do_email("teste@exemplo.com"))
        self.assertEqual((c["plano"], c["teto"], c["dev"]), ("semanal", 3, True))
        self.assertEqual(c["inicio"], hospedado.INICIO_DEV)         # estável: a cota acumula entre requisições
        self.assertEqual(hospedado.reivindicacao({})["inicio"], c["inicio"])

    def test_sem_cv_env_dev_recusa_e_nao_da_identidade(self):
        os.environ["CV_DEV_USUARIO"] = "teste@exemplo.com"
        with self.assertRaises(hospedado.ErroDev):
            hospedado.dev_usuario()
        self.assertIsNone(hospedado.reivindicacao({}))
        os.environ["CV_ENV"] = "producao"
        self.assertIsNone(hospedado.reivindicacao({}))

    def test_cabecalho_assinado_tem_prioridade(self):
        os.environ.update({"CV_ENV": "dev", "CV_DEV_USUARIO": "teste@exemplo.com"})
        c = hospedado.reivindicacao(cab(UID_B))
        self.assertEqual(c["uid"], UID_B)
        self.assertNotIn("dev", c)

    def test_email_invalido_nao_da_identidade(self):
        os.environ.update({"CV_ENV": "dev", "CV_DEV_USUARIO": "isso nao e email"})
        self.assertIsNone(hospedado.reivindicacao({}))

    def test_cota_acumula_para_o_usuario_dev(self):
        os.environ.update({"CV_ENV": "dev", "CV_DEV_USUARIO": "teste@exemplo.com", "CV_DEV_TETO": "2"})
        from src.cota import ErroCota
        for v in ("v1", "v2"):
            c = hospedado.cota_do(hospedado.reivindicacao({}))
            c.autorizar(v)
            c.registrar(v)
        with self.assertRaises(ErroCota):
            hospedado.cota_do(hospedado.reivindicacao({})).autorizar("v3")
