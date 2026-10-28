import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src import custo
from src.llm import LLM, Configuracao
from tests.fakes import Resp, SessaoFalsa, limpar

MSG = [{"role": "user", "content": "Currículo da Maria, vaga de analista"}]


def com_uso(conteudo, **uso):
    return Resp(200, {"choices": [{"message": {"content": conteudo}}], "usage": uso})


def montar(*respostas, **kw):
    cfg = Configuracao("deepseek", "chave-secreta", "deepseek-v4-pro", "https://x.test", {})
    s = SessaoFalsa(*respostas)
    return LLM(cfg, sessao=s, dormir=lambda _: None, **kw), s


SEG_FORA = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)    # sábado
SEG_PICO = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)     # segunda, 06h-10h UTC


class TestCusto(unittest.TestCase):
    def test_pico_e_fora_do_pico(self):
        self.assertTrue(custo.em_pico(SEG_PICO))
        self.assertTrue(custo.em_pico(datetime(2026, 10, 27, 1, 30, tzinfo=timezone.utc)))
        self.assertFalse(custo.em_pico(SEG_FORA))
        self.assertFalse(custo.em_pico(datetime(2026, 10, 26, 13, 0, tzinfo=timezone.utc)))   # comercial no Brasil
        self.assertFalse(custo.em_pico(datetime(2026, 10, 26, 4, 0, tzinfo=timezone.utc)))    # 04h já é fora

    def test_custo_pro_fora_do_pico(self):
        uso = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 400_000, "prompt_cache_miss_tokens": 600_000,
               "completion_tokens": 1_000_000}
        # 0,4M*0,022 + 0,6M*0,66 + 1M*1,98
        self.assertAlmostEqual(custo.custo_usd("deepseek-v4-pro", uso, SEG_FORA), 0.0088 + 0.396 + 1.98, places=6)

    def test_pico_dobra_o_preco(self):
        uso = {"prompt_tokens": 1000, "completion_tokens": 1000}
        self.assertAlmostEqual(custo.custo_usd("deepseek-flash", uso, SEG_PICO),
                               2 * custo.custo_usd("deepseek-flash", uso, SEG_FORA))

    def test_sem_info_de_cache_conta_tudo_como_miss(self):
        u = custo.normalizar_uso({"prompt_tokens": 500, "completion_tokens": 20})
        self.assertEqual((u["cache_hit"], u["cache_miss"], u["entrada"], u["saida"]), (0, 500, 500, 20))

    def test_alias_antigo_cobra_como_flash_e_modelo_desconhecido_nao_tem_custo(self):
        uso = {"prompt_tokens": 1000, "completion_tokens": 1000}
        self.assertEqual(custo.custo_usd("deepseek-v4-flash", uso, SEG_FORA), custo.custo_usd("deepseek-flash", uso, SEG_FORA))
        self.assertIsNone(custo.custo_usd("gemini-3.8-flash", uso, SEG_FORA))

    def test_uso_lixo_nao_quebra(self):
        self.assertEqual(custo.normalizar_uso({"prompt_tokens": "x", "completion_tokens": None})["saida"], 0)
        self.assertEqual(custo.normalizar_uso(None)["entrada"], 0)

    def test_cambio_vem_do_ambiente(self):
        import os
        antigo = os.environ.get("CV_CAMBIO_BRL")
        try:
            os.environ["CV_CAMBIO_BRL"] = "6,1"
            self.assertEqual(custo.cambio(), 6.1)
            os.environ["CV_CAMBIO_BRL"] = "lixo"
            self.assertEqual(custo.cambio(), custo.CAMBIO_PADRAO)
        finally:
            if antigo is None:
                os.environ.pop("CV_CAMBIO_BRL", None)
            else:
                os.environ["CV_CAMBIO_BRL"] = antigo


class TestLLMUso(unittest.TestCase):
    def test_acumula_tokens_e_chama_callback(self):
        eventos = []
        l, _ = montar(com_uso("a", prompt_tokens=100, completion_tokens=10),
                      com_uso("b", prompt_tokens=50, completion_tokens=5), ao_usar=eventos.append)
        l.conversar(MSG, rotulo="gerador")
        l.conversar(MSG, rotulo="analisador")
        self.assertEqual(l.uso_total, {"chamadas": 2, "entrada": 150, "saida": 15})
        self.assertGreater(l.custo_usd, 0)
        self.assertEqual([e["rotulo"] for e in eventos], ["gerador", "analisador"])
        self.assertEqual(eventos[0]["uso"]["entrada"], 100)

    def test_callback_com_erro_nao_derruba(self):
        def explode(_):
            raise RuntimeError("boom")
        l, _ = montar(com_uso("a", prompt_tokens=1, completion_tokens=1), ao_usar=explode)
        self.assertEqual(l.conversar(MSG), "a")

    def test_resposta_sem_usage_nao_conta(self):
        l, _ = montar(Resp(200, {"choices": [{"message": {"content": "oi"}}]}))
        l.conversar(MSG)
        self.assertEqual(l.uso_total["chamadas"], 0)

    def test_modelo_por_etapa(self):
        l, s = montar(com_uso("a", prompt_tokens=1, completion_tokens=1), com_uso("b", prompt_tokens=1, completion_tokens=1),
                      com_uso("c", prompt_tokens=1, completion_tokens=1),
                      modelos_por_etapa={"analisador": "deepseek-flash"})
        l.conversar(MSG, rotulo="analisador")
        l.conversar(MSG, rotulo="analisador-reparo")     # reparo herda o modelo da etapa
        l.conversar(MSG, rotulo="gerador")
        self.assertEqual([p["json"]["model"] for p in s.posts], ["deepseek-flash", "deepseek-flash", "deepseek-v4-pro"])

    def test_log_com_conteudo_por_padrao_e_so_metadados_no_servidor(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            for guardar, pasta in ((True, "local"), (False, "servidor")):
                l, _ = montar(com_uso("Resposta com dados da Maria", prompt_tokens=10, completion_tokens=3),
                              log_dir=tmp / pasta, guardar_conteudo=guardar)
                l.conversar(MSG, rotulo="gerador")
            local = json.loads(next((tmp / "local").glob("*.jsonl")).read_text(encoding="utf-8"))
            servidor_txt = next((tmp / "servidor").glob("*.jsonl")).read_text(encoding="utf-8")
            servidor = json.loads(servidor_txt)
            self.assertIn("mensagens", local)
            self.assertNotIn("mensagens", servidor)
            self.assertNotIn("resposta", servidor)
            self.assertNotIn("Maria", servidor_txt)
            self.assertEqual(servidor["uso"]["entrada"], 10)
            self.assertEqual(servidor["rotulo"], "gerador")
            self.assertGreater(servidor["chars_entrada"], 0)
        finally:
            limpar(tmp)


if __name__ == "__main__":
    unittest.main()
