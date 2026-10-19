"""Acompanhamento das candidaturas e currículo geral."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src import candidaturas, config, historico, saidas, tailor
from tests.fakes import LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom

CFG = {"candidaturas": {"dias_sem_retorno": 21, "minimo_para_taxas": 5, "minimo_para_relacao": 20}}


class TestSituacao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pasta = saidas.salvar_saida("# x", b"%PDF", b"d", "vaga", {"empresa": "Acme", "titulo_vaga": "PM"},
                                         raiz=self.tmp, indice={"antes": 40, "depois": 60, "teto": 70})

    def tearDown(self):
        limpar(self.tmp)

    def test_sem_arquivo_e_gerado(self):
        self.assertEqual(candidaturas.ler(self.pasta)["situacao"], "gerado")

    def test_enviar_registra_a_data_e_o_historico(self):
        d = candidaturas.definir_situacao(self.pasta, "enviado", date(2026, 10, 1))
        self.assertEqual(d["enviado_em"], "2026-10-01")
        d = candidaturas.definir_situacao(self.pasta, "entrevista", date(2026, 10, 9))
        self.assertEqual(d["enviado_em"], "2026-10-01")                 # a data de envio não muda
        self.assertEqual([h["situacao"] for h in d["historico"]], ["enviado", "entrevista"])
        d = candidaturas.definir_situacao(self.pasta, "gerado", date(2026, 10, 10))   # desfazer apaga o envio
        self.assertEqual(d["enviado_em"], "")
        with self.assertRaises(ValueError):
            candidaturas.definir_situacao(self.pasta, "contratada")

    def test_anotacao(self):
        candidaturas.anotar(self.pasta, "  Falar com a Ana,   recrutadora  ")
        self.assertEqual(candidaturas.ler(self.pasta)["anotacao"], "Falar com a Ana, recrutadora")

    def test_historico_traz_a_situacao(self):
        candidaturas.definir_situacao(self.pasta, "enviado")
        [e] = historico.listar(self.tmp)
        self.assertEqual(e["situacao"], "enviado")
        self.assertFalse(e["geral"])


def entrada(situacao, enviado_em="", depois=50, geral=False):
    return {"situacao": situacao, "enviado_em": enviado_em, "depois": depois, "geral": geral}


class TestResumo(unittest.TestCase):
    def test_sugere_sem_retorno_so_depois_do_prazo_e_so_para_enviadas(self):
        hoje = date(2026, 10, 30)
        velha = (hoje - timedelta(days=30)).isoformat()
        nova = (hoje - timedelta(days=10)).isoformat()
        es = [entrada("enviado", velha), entrada("enviado", nova), entrada("entrevista", velha), entrada("gerado")]
        sug = candidaturas.sugerir_sem_retorno(es, hoje, CFG)
        self.assertEqual(len(sug), 1)
        self.assertEqual(sug[0]["dias"], 30)

    def test_taxa_so_com_dados_suficientes(self):
        poucas = [entrada("enviado"), entrada("entrevista"), entrada("sem_retorno"), entrada("gerado")]
        r = candidaturas.resumo(poucas, CFG)
        self.assertIsNone(r["taxa_resposta"])
        self.assertEqual((r["enviadas"], r["faltam_para_taxas"]), (3, 2))
        cinco = poucas + [entrada("proposta"), entrada("nao_seguiu")]
        r = candidaturas.resumo(cinco, CFG)
        self.assertEqual(r["taxa_resposta"], 40)        # 2 respostas (entrevista e proposta) em 5 enviadas
        self.assertIsNone(r["relacao"])                 # comparar aderência e resultado só com 20

    def test_relacao_com_aderencia_so_com_20_enviadas(self):
        es = [entrada("entrevista", depois=80) for _ in range(5)] + [entrada("sem_retorno", depois=50) for _ in range(15)]
        r = candidaturas.resumo(es, CFG)
        self.assertEqual(r["relacao"]["media_com_resposta"], 80)
        self.assertEqual(r["relacao"]["media_sem_resposta"], 50)

    def test_curriculo_geral_nao_conta_como_candidatura(self):
        r = candidaturas.resumo([entrada("gerado", geral=True), entrada("enviado")], CFG)
        self.assertEqual(r["contagem"]["gerado"], 0)
        self.assertEqual(r["enviadas"], 1)


def vaga_com_lacunas(situacao, palavras, sustentadas=(), obrigatorios=()):
    analise = {"palavras_chave": list(palavras),
               "palavras_chave_base": [{"termo": t, "evidencias": ["x#1"]} for t in sustentadas],
               "requisitos": [{"requisito": r, "termo_na_vaga": r, "tipo": "obrigatorio", "status": "lacuna"}
                              for r in obrigatorios]}
    return {"situacao": situacao, "geral": False, "analise": analise}


class TestOndeSeDesenvolver(unittest.TestCase):
    def test_usa_as_enviadas_quando_ha_pelo_menos_duas(self):
        es = [vaga_com_lacunas("enviado", ["SQL", "Excel"], sustentadas=["Excel"]),
              vaga_com_lacunas("entrevista", ["SQL", "Power BI"]),
              vaga_com_lacunas("gerado", ["Power BI"]), vaga_com_lacunas("gerado", ["Power BI"])]
        p = historico.pontos_de_desenvolvimento(es)
        self.assertEqual((p["base"], p["total"]), ("enviadas", 2))
        self.assertEqual([(i["termo"], i["vagas"]) for i in p["itens"]], [("SQL", 2)])   # Power BI só nas não enviadas

    def test_sem_enviadas_usa_as_geradas(self):
        es = [vaga_com_lacunas("gerado", ["Power BI"]), vaga_com_lacunas("gerado", ["Power BI"])]
        p = historico.pontos_de_desenvolvimento(es)
        self.assertEqual((p["base"], p["total"]), ("geradas", 2))
        self.assertEqual(p["itens"][0]["termo"], "Power BI")

    def test_obrigatorio_primeiro_no_empate_e_sem_repetir_o_termo(self):
        es = [vaga_com_lacunas("enviado", ["Looker Studio", "CRO"], obrigatorios=["Looker Studio"]),
              vaga_com_lacunas("enviado", ["Looker Studio", "CRO"], obrigatorios=["Looker Studio"])]
        itens = historico.pontos_de_desenvolvimento(es)["itens"]
        self.assertEqual([(i["termo"], i["obrigatorio"]) for i in itens], [("Looker Studio", True), ("CRO", False)])

    def test_curriculo_geral_nao_entra(self):
        es = [{"situacao": "gerado", "geral": True, "analise": {"palavras_chave": [], "palavras_chave_base": []}}] * 3
        self.assertEqual(historico.pontos_de_desenvolvimento(es)["itens"], [])


class TestCurriculoGeral(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def test_gera_sem_vaga_com_as_mesmas_regras(self):
        llm = LLMFalso(gerado_bom(), {"itens": [], "palavras": []})
        res, analise, texto = tailor.gerar_geral(llm, self.kb, "pt", self.cfg, "Analista de marketing digital")
        self.assertTrue(analise["geral"])
        self.assertEqual(analise["palavras_chave"], [])
        self.assertIn("Foco: Analista de marketing digital", llm.chamadas[0]["mensagens"][1]["content"])
        self.assertIn("Mariana Exemplo", res.curriculo.markdown)
        self.assertTrue(any(c["rotulo"] == "verificador" for c in llm.chamadas))     # o fiscal roda igual

    def test_sem_foco_usa_o_objetivo_do_historico(self):
        self.assertIn("objetivo profissional", tailor.texto_geral(""))

    def test_pasta_do_curriculo_geral(self):
        analise = tailor.analise_geral("pt", "Analista")
        pasta = saidas.salvar_saida("# x", b"%PDF", b"d", "geral", analise, raiz=self.tmp / "saidas")
        self.assertTrue(pasta.name.startswith(f"Geral_{date.today():%Y-%m}"))
        [e] = historico.listar(self.tmp / "saidas")
        self.assertTrue(e["geral"])


if __name__ == "__main__":
    unittest.main()
