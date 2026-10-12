import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import registro, sessao
from src.exemplo import copiar_exemplo
from src.interview import FatoProposto, Proposta
from src.kb import KB
from src.llm import LLM, Configuracao, ErroLLM
from tests.fakes import Resp, SessaoFalsa, ok


def props():
    return [Proposta("nova_experiencia", [FatoProposto("Cuida das campanhas.", "dito"),
                                          FatoProposto("Lidera o time.", "sugerido")],
                     {"empresa": "Acme", "cargo": "Analista", "inicio": "", "fim": "atual"},
                     ["O mês não foi dito."])]


class TestSessao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base = self.tmp / "base"

    def test_ida_e_volta(self):
        chat = [{"role": "user", "content": "Sou analista"}, {"role": "assistant", "content": "Onde?"}]
        sessao.salvar(self.base, chat, props(), None)
        lido = sessao.carregar(self.base)
        self.assertEqual(lido["chat"], chat)
        p = lido["rev_importacao"][0]
        self.assertEqual((p.destino, p.meta["empresa"], p.problemas), ("nova_experiencia", "Acme", ["O mês não foi dito."]))
        self.assertEqual([(f.texto, f.origem) for f in p.fatos], [("Cuida das campanhas.", "dito"), ("Lidera o time.", "sugerido")])
        self.assertTrue(p.fatos[0].marcado_por_padrao and not p.fatos[1].marcado_por_padrao)
        self.assertEqual(lido["rev_entrevista"], [])

    def test_sem_nada_remove_o_arquivo(self):
        sessao.salvar(self.base, [{"role": "user", "content": "oi"}], None, None)
        self.assertTrue((self.base / ".sessao" / "sessao.json").exists())
        sessao.salvar(self.base, [], None, None)
        self.assertFalse((self.base / ".sessao" / "sessao.json").exists())

    def test_arquivo_estragado_ou_ausente_nao_derruba(self):
        self.assertEqual(sessao.carregar(self.base), {"chat": [], "rev_importacao": [], "rev_entrevista": []})
        (self.base / ".sessao").mkdir(parents=True)
        for conteudo in ("{ isto nao e json", "[1, 2]", '{"chat": "x", "rev_importacao": [1, {"destino": 5}]}'):
            (self.base / ".sessao" / "sessao.json").write_text(conteudo, encoding="utf-8")
            r = sessao.carregar(self.base)
            self.assertEqual(r["chat"], [])

    def test_item_estragado_nao_impede_recuperar_o_resto(self):
        (self.base / ".sessao").mkdir(parents=True)
        bom = {"destino": "perfil", "fatos": [{"texto": "Fato bom.", "origem": "dito"}]}
        (self.base / ".sessao" / "sessao.json").write_text(
            json.dumps({"chat": [{"role": "user", "content": "oi"}, {"role": "x", "content": "ignorada"}],
                        "rev_importacao": [{"quebrado": True}, bom]}), encoding="utf-8")
        r = sessao.carregar(self.base)
        self.assertEqual(len(r["chat"]), 1)
        self.assertEqual(r["rev_importacao"][0].fatos[0].texto, "Fato bom.")

    def test_pasta_da_sessao_nao_atrapalha_a_base(self):
        sessao.salvar(self.base, [{"role": "user", "content": "oi"}], None, None)
        kb = KB(self.base)
        self.assertEqual(kb.fatos(), [])
        self.assertEqual(kb.erros, [])
        self.assertTrue(copiar_exemplo(kb))      # ainda conta como base vazia
        self.assertTrue((self.base / "contato.yaml").exists())


class TestRegistro(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = Configuracao("deepseek", "chave-secreta-xyz", "m", "https://x.test", {})

    def llm(self, *respostas, **k):
        return LLM(self.cfg, sessao=SessaoFalsa(*respostas), dormir=lambda s: None, log_dir=self.tmp / "logs", **k)

    def linhas(self):
        arqs = registro.arquivos(self.tmp / "logs")
        self.assertEqual(len(arqs), 1)
        return registro.ler(arqs[0])

    def test_grava_envio_resposta_rotulo_e_duracao(self):
        self.llm(ok("Qual foi o resultado?")).conversar([{"role": "user", "content": "oi"}], rotulo="entrevistador")
        (r,) = self.linhas()
        self.assertEqual((r["rotulo"], r["resposta"], r["erro"], r["provedor"], r["modelo"]),
                         ("entrevistador", "Qual foi o resultado?", None, "deepseek", "m"))
        self.assertEqual(r["mensagens"], [{"role": "user", "content": "oi"}])
        self.assertIn("duracao_s", r)

    def test_registro_nao_guarda_contato_nem_chave(self):
        l = self.llm(ok("ok"), segredos=["Mariana Exemplo"])
        l.conversar([{"role": "user", "content": "Sou Mariana Exemplo, a@b.com, +55 11 90000-0000"}])
        bruto = (registro.arquivos(self.tmp / "logs")[0]).read_text(encoding="utf-8")
        for sensivel in ("Mariana", "a@b.com", "90000", "chave-secreta-xyz"):
            self.assertNotIn(sensivel, bruto)

    def test_erro_tambem_e_registrado_e_continua_levantando(self):
        l = self.llm(Resp(401))
        with self.assertRaises(ErroLLM):
            l.conversar([{"role": "user", "content": "oi"}], rotulo="gerador")
        (r,) = self.linhas()
        self.assertIsNone(r["resposta"])
        self.assertIn("chave", r["erro"])

    def test_sem_log_dir_nao_grava_nada(self):
        LLM(self.cfg, sessao=SessaoFalsa(ok("x")), dormir=lambda s: None).conversar([{"role": "user", "content": "oi"}])
        self.assertFalse((self.tmp / "logs").exists())

    def test_falha_ao_gravar_o_log_nao_derruba(self):
        l = self.llm(ok("resposta"))
        (self.tmp / "logs").write_text("arquivo no lugar da pasta", encoding="utf-8")   # mkdir vai falhar
        self.assertEqual(l.conversar([{"role": "user", "content": "oi"}]), "resposta")

    def test_ultimos_e_resumo(self):
        l = self.llm(ok("a"), ok("b"), ok("c"))
        for rot in ("x", "y", "z"):
            l.conversar([{"role": "user", "content": "oi"}], rotulo=rot)
        ult = registro.ultimos(2, self.tmp / "logs")
        self.assertEqual([r["rotulo"] for r in ult], ["z", "y"])    # do mais novo para o mais antigo
        self.assertIn("z", registro.resumo(ult[0]))

    def test_ativo_respeita_cv_log(self):
        with mock.patch.dict(os.environ, {"CV_LOG": "0"}):
            self.assertFalse(registro.ativo())
        with mock.patch.dict(os.environ, {"CV_LOG": "1"}):
            self.assertTrue(registro.ativo())
        with mock.patch.dict(os.environ):
            os.environ.pop("CV_LOG", None)
            self.assertTrue(registro.ativo())

    def test_rotulos_chegam_ao_log_pelos_fluxos(self):
        from tests.fakes import LLMFalso, base_exemplo, limpar
        from src import interview, tailor
        kb, tmp = base_exemplo()
        try:
            llm = LLMFalso("Pergunta?", {"propostas": []}, {"requisitos": []})
            interview.responder(llm, kb, [], "oi")
            interview.extrair(llm, kb, "texto qualquer do currículo", "curriculo importado")
            tailor.analisar(llm, kb, "vaga qualquer")
            self.assertEqual([c["rotulo"] for c in llm.chamadas], ["entrevistador", "extrator", "analisador"])
        finally:
            limpar(tmp)


if __name__ == "__main__":
    unittest.main()
