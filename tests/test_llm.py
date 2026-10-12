import unittest

import requests

from src.llm import LLM, Configuracao, ErroConfig, ErroLLM, completar_json
from tests.fakes import LLMFalso, Resp, SessaoFalsa, ok

MSG = [{"role": "user", "content": "a"}]


def cfg(prov="gemini", extras=None):
    return Configuracao(prov, "chave-secreta-123", "m", "https://x.test/v1", extras or {})


def montar(*respostas, prov="gemini", extras=None, segredos=None):
    s = SessaoFalsa(*respostas)
    esperas = []
    return LLM(cfg(prov, extras), sessao=s, dormir=esperas.append, segredos=segredos), s, esperas


class TestLLM(unittest.TestCase):
    def test_sucesso_e_think(self):
        l, s, _ = montar(ok("<think>hmm</think>Oi"))
        self.assertEqual(l.conversar(MSG), "Oi")
        self.assertEqual(s.posts[0]["url"], "https://x.test/v1/chat/completions")
        self.assertNotIn("max_tokens", s.posts[0]["json"])

    def test_429_com_retry_after_e_depois_sucesso(self):
        l, s, esperas = montar(Resp(429, headers={"Retry-After": "7"}), ok("ok"))
        self.assertEqual(l.conversar(MSG), "ok")
        self.assertEqual(esperas, [7.0])

    def test_429_esgota_com_backoff(self):
        l, s, esperas = montar(*[Resp(429)] * 6)
        with self.assertRaises(ErroLLM) as c:
            l.conversar(MSG)
        self.assertIn("Limite", str(c.exception))
        self.assertEqual(esperas[:3], [5, 10, 20])

    def test_400_cai_para_sem_response_format(self):
        l, s, _ = montar(Resp(400, {"error": {"message": "x"}}), ok('{"a":1}'))
        l.conversar(MSG, json_mode=True)
        self.assertIn("response_format", s.posts[0]["json"])
        self.assertNotIn("response_format", s.posts[1]["json"])

    def test_400_tira_extras_do_provedor(self):
        l, s, _ = montar(Resp(400), ok("ok"), prov="deepseek", extras={"thinking": {"type": "disabled"}})
        l.conversar(MSG)
        self.assertIn("thinking", s.posts[0]["json"])
        self.assertNotIn("thinking", s.posts[1]["json"])

    def test_400_sem_saida_vira_erro(self):
        l, _, _ = montar(Resp(400, {"error": {"message": "pedido ruim"}}))
        with self.assertRaises(ErroLLM) as c:
            l.conversar(MSG)
        self.assertIn("400", str(c.exception))

    def test_erros_em_portugues_sem_vazar_chave(self):
        for status, trecho in ((401, "chave"), (403, "chave"), (404, "verificar.py --modelos")):
            l, _, _ = montar(Resp(status))
            with self.assertRaises(ErroLLM) as c:
                l.conversar(MSG)
            self.assertIn(trecho, str(c.exception))
            self.assertNotIn("chave-secreta-123", str(c.exception))

    def test_5xx_retry_e_desiste(self):
        l, _, _ = montar(Resp(503), ok("ok"))
        self.assertEqual(l.conversar(MSG), "ok")
        l, _, _ = montar(*[Resp(500)] * 5)
        with self.assertRaises(ErroLLM):
            l.conversar(MSG)

    def test_resposta_vazia(self):
        l, _, _ = montar(ok(""))
        with self.assertRaises(ErroLLM) as c:
            l.conversar(MSG)
        self.assertIn("vazia", str(c.exception))

    def test_timeout_desiste(self):
        l, _, _ = montar(requests.Timeout(), requests.Timeout(), requests.Timeout())
        with self.assertRaises(ErroLLM):
            l.conversar(MSG)

    def test_timeout_e_recupera(self):
        l, _, _ = montar(requests.Timeout(), ok("ok"))
        self.assertEqual(l.conversar(MSG), "ok")

    def test_mascara_e_segredos_no_payload(self):
        l, s, _ = montar(ok("ok"), segredos=["Mariana Exemplo"])
        l.conversar([{"role": "user", "content": "Sou Mariana Exemplo, a@b.com, +55 11 90000-0000"}])
        enviado = s.posts[0]["json"]["messages"][0]["content"]
        for x in ("Mariana", "a@b.com", "90000"):
            self.assertNotIn(x, enviado)

    def test_completar_json_repara_uma_vez(self):
        f = LLMFalso("isto não é json", '{"ok": 1}')
        self.assertEqual(completar_json(f, MSG), {"ok": 1})
        self.assertEqual(len(f.chamadas), 2)

    def test_completar_json_desiste(self):
        f = LLMFalso("nada", "ainda nada")
        with self.assertRaises(ErroLLM) as c:
            completar_json(f, MSG)
        self.assertIn("modelo", str(c.exception))

    def test_config_ambiente(self):
        c = Configuracao.do_ambiente({"PROVEDOR": "gemini", "GEMINI_API_KEY": "k"})
        self.assertEqual(c.modelo, "gemini-3.8-flash")
        d = Configuracao.do_ambiente({"PROVEDOR": "deepseek", "DEEPSEEK_API_KEY": "k"})
        self.assertEqual(d.modelo, "deepseek-flash")
        self.assertEqual(d.extras, {"thinking": {"type": "disabled"}})
        with self.assertRaises(ErroConfig):
            Configuracao.do_ambiente({"PROVEDOR": "gemini"})
        with self.assertRaises(ErroConfig) as e:
            Configuracao.do_ambiente({"PROVEDOR": "openrouter", "OPENROUTER_API_KEY": "k"})
        self.assertIn("MODELO", str(e.exception))

    def test_modelos(self):
        l, _, _ = montar(Resp(200, {"data": [{"id": "models/b"}, {"id": "models/a"}]}))
        self.assertEqual(l.modelos(), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
