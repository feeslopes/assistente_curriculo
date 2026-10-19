import json
import tempfile
import unittest
from pathlib import Path

from src import aderencia, config, historico, saidas, tailor
from tests.fakes import SLUG_ATUAL, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta


class TestAderencia(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()
        self.analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())

    def tearDown(self):
        limpar(self.tmp)

    def gerar(self, gerado=None, idioma="pt"):
        return tailor.gerar(LLMFalso(gerado or gerado_bom()), self.kb, "Vaga", self.analise, idioma, self.cfg,
                            verificar_ia=False)

    def calc(self, res, **kw):
        return aderencia.calcular(self.analise, res.curriculo.markdown, res.curriculo.rastro, self.kb, self.cfg,
                                  kw.pop("idioma", "pt"), **kw)

    # ------------------------------------------------------------------ antes
    def test_curriculo_base_nao_usa_ia_e_respeita_os_limites(self):
        cv = aderencia.curriculo_base(self.kb, self.cfg)
        self.assertIn("## Experiência Profissional", cv.markdown)
        self.assertTrue(cv.rastro)
        # todo item tem fonte válida: o "antes" também só diz o que a base diz
        self.assertTrue(all(r["fontes_validas"] for r in cv.rastro))
        n_atual = sum(1 for r in cv.rastro if r["fontes_validas"][0].startswith(SLUG_ATUAL))
        self.assertLessEqual(n_atual, self.cfg["bullets_por_experiencia"][0])

    # ------------------------------------------------------------------ cálculo
    def test_total_fica_entre_0_e_100_e_tem_os_componentes(self):
        ind = self.calc(self.gerar())
        self.assertTrue(0 <= ind["total"] <= 100)
        self.assertEqual(set(ind["componentes"]), {"palavras", "obrigatorios", "desejaveis", "estrutura"})
        self.assertAlmostEqual(sum(c["peso"] for c in ind["componentes"].values()), 100, delta=0.5)

    def test_palavra_com_base_no_texto_conta_e_a_sem_base_nao(self):
        res = self.gerar()   # competências traz Google Ads (sustentada); Looker Studio não é sustentada
        det = self.calc(res)["componentes"]["palavras"]["detalhe"]
        self.assertIn("Google Ads", det["usadas"])
        self.assertIn("SQL", det["sustentadas_ausentes"])      # a base sustenta, o texto não usa
        self.assertIn("Looker Studio", det["sem_base"])

    def test_inventar_uma_palavra_nao_aumenta_o_indice(self):
        res = self.gerar()
        antes = self.calc(res)
        md = res.curriculo.markdown + "\n* Dashboards em Looker Studio e HubSpot.\n"
        depois = aderencia.calcular(self.analise, md, res.curriculo.rastro, self.kb, self.cfg, "pt")
        self.assertEqual(antes["total"], depois["total"])
        self.assertIn("Looker Studio", depois["componentes"]["palavras"]["detalhe"]["sem_base_usadas"])

    def test_requisito_so_conta_quando_o_fato_de_apoio_esta_no_texto(self):
        res = self.gerar()
        obrig = self.calc(res)["componentes"]["obrigatorios"]["detalhe"]["itens"]
        midia = next(x for x in obrig if x["requisito"].startswith("Mídia paga"))
        self.assertTrue(midia["no_curriculo"])
        # tira do texto o que cita habilidades#2 (resumo e competências): o requisito deixa de ser refletido
        md = res.curriculo.markdown.replace("Google Ads, Meta Ads", "").replace("mídia paga e análise de dados", "")
        sem = aderencia.calcular(self.analise, md, res.curriculo.rastro, self.kb, self.cfg, "pt")
        midia2 = next(x for x in sem["componentes"]["obrigatorios"]["detalhe"]["itens"] if x["requisito"].startswith("Mídia paga"))
        self.assertFalse(midia2["no_curriculo"])
        self.assertLess(sem["total"], self.calc(res)["total"])

    def test_teto_nunca_fica_abaixo_do_total(self):
        ind = self.calc(self.gerar())
        self.assertGreaterEqual(ind["teto"], ind["total"])
        self.assertLessEqual(ind["teto"], 100)

    def test_idioma_diferente_da_vaga_estima_pelos_fatos(self):
        self.analise["idioma_vaga"] = "en"
        res = self.gerar()
        ind = self.calc(res, idioma="pt")
        self.assertTrue(ind["estimado"])
        self.assertTrue(ind["componentes"]["palavras"]["detalhe"]["estimado"])
        # Google Ads está na competência (habilidades#2): contado pelo fato mesmo sem casar o texto
        self.assertIn("Google Ads", ind["componentes"]["palavras"]["detalhe"]["usadas"])

    def test_estrutura_avisa_de_pagina_acima_do_limite_e_falta_de_contato(self):
        res = self.gerar()
        ind = self.calc(res, paginas=5)
        checks = {c["nome"]: c for c in ind["componentes"]["estrutura"]["detalhe"]["checks"]}
        self.assertFalse(checks["Páginas dentro do limite"]["ok"])
        md = "# Fulana\n**Analista**\n\n" + res.curriculo.corpo
        sem_contato = aderencia.calcular(self.analise, md, res.curriculo.rastro, self.kb, self.cfg, "pt")
        c2 = {c["nome"]: c for c in sem_contato["componentes"]["estrutura"]["detalhe"]["checks"]}
        self.assertFalse(c2["Contato no cabeçalho"]["ok"])
        self.assertIn("Dados pessoais", c2["Contato no cabeçalho"]["dica"])

    def test_sem_desejaveis_os_pesos_se_reescalam(self):
        self.analise["requisitos"] = [r for r in self.analise["requisitos"] if r["tipo"] == "obrigatorio"]
        ind = self.calc(self.gerar())
        self.assertNotIn("desejaveis", ind["componentes"])
        self.assertAlmostEqual(sum(c["peso"] for c in ind["componentes"].values()), 100, delta=0.5)

    # ------------------------------------------------------------------ antes e depois
    def test_gerar_traz_a_comparacao_antes_e_depois(self):
        a = self.gerar().aderencia
        self.assertTrue(0 <= a["antes"]["total"] <= 100 and 0 <= a["depois"]["total"] <= 100)
        self.assertIn("inventar", a["aviso"].lower())
        self.assertEqual(a["idioma_antes"], self.kb.idioma_base())
        self.assertIsNotNone(a["depois"]["paginas"])

    # ------------------------------------------------------------------ melhorias
    def test_melhorias_separam_o_que_a_base_ja_tem_do_que_exige_confirmar(self):
        ms = self.gerar().aderencia["melhorias"]
        tipos = {m["tipo"] for m in ms}
        self.assertIn("usar_base", tipos)
        self.assertIn("confirmar", tipos)
        usar = next(m for m in ms if m["tipo"] == "usar_base" and "SQL" in m["itens"])
        self.assertGreater(usar["ganho"], 0)
        confirmar = next(m for m in ms if m["tipo"] == "confirmar" and "Looker Studio" in m["itens"])
        self.assertIn("deixe de fora", confirmar["detalhe"].lower())   # a saída honesta é sempre oferecida
        self.assertEqual([m["ganho"] for m in ms], sorted((m["ganho"] for m in ms), reverse=True))

    def test_melhoria_de_palavra_sem_base_usada_nao_promete_ganho(self):
        res = self.gerar()
        md = res.curriculo.markdown + "\n* Dashboards em Looker Studio.\n"
        ind = aderencia.calcular(self.analise, md, res.curriculo.rastro, self.kb, self.cfg, "pt")
        item = next(m for m in aderencia.melhorias(self.analise, ind) if "Looker Studio" in m["itens"] and m["ganho"] == 0)
        self.assertIn("Confira", item["detalhe"])


class TestHistorico(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        limpar(self.tmp)

    def salvar(self, analise, indice=None):
        return saidas.salvar_saida("# x", b"pdf", b"docx", "vaga", analise, raiz=self.tmp, indice=indice)

    def test_salvar_grava_o_indice_e_listar_le(self):
        comp = {"antes": {"total": 40, "componentes": {"palavras": {"pontos": 10.0}}, "estimado": False},
                "depois": {"total": 70, "teto": 85, "estimado": False,
                           "componentes": {"palavras": {"pontos": 30.0, "peso": 45, "detalhe": {"sem_base": ["CRO"]}}}},
                "idioma_antes": "pt", "idioma_depois": "en"}
        analise = {"empresa": "Acme", "titulo_vaga": "PM"}
        pasta = self.salvar(analise, historico.dados_do_indice(analise, comp))
        self.assertTrue((pasta / "indice.json").exists())
        [e] = historico.listar(self.tmp)
        self.assertEqual((e["antes"], e["depois"], e["teto"], e["idioma"]), (40, 70, 85, "en"))
        self.assertEqual(e["empresa"], "Acme")
        self.assertTrue(e["tem_indice"])

    def test_saida_antiga_sem_indice_aparece_sem_nota(self):
        self.salvar({"empresa": "Velha", "titulo_vaga": "Analista"})
        [e] = historico.listar(self.tmp)
        self.assertFalse(e["tem_indice"])
        self.assertIsNone(e["depois"])

    def test_pasta_inexistente_ou_sem_analise_e_ignorada(self):
        self.assertEqual(historico.listar(self.tmp / "nao-existe"), [])
        (self.tmp / "solta").mkdir()
        self.assertEqual(historico.listar(self.tmp), [])

    def test_lacunas_recorrentes_contam_uma_vez_por_vaga(self):
        a1 = {"palavras_chave": ["SQL", "CRO", "cro"], "palavras_chave_base": [{"termo": "SQL", "evidencias": ["x#1"]}],
              "requisitos": [{"requisito": "Testes A/B", "termo_na_vaga": "A/B", "tipo": "obrigatorio", "status": "lacuna"}]}
        a2 = {"palavras_chave": ["CRO", "SQL"], "palavras_chave_base": [],
              "requisitos": [{"requisito": "Testes A/B", "termo_na_vaga": "A/B", "tipo": "obrigatorio", "status": "lacuna"}]}
        antiga = {"palavras_chave": ["CRO"], "requisitos": []}   # sem palavras_chave_base: não dá para saber
        r = historico.lacunas_recorrentes([{"analise": a} for a in (a1, a2, antiga)])
        self.assertEqual(r["palavras"], [("CRO", 2)])
        self.assertEqual(r["requisitos"], [("A/B", 2)])
        self.assertEqual(r["vagas"], 3)


if __name__ == "__main__":
    unittest.main()
