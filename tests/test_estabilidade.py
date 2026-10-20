"""Nota estável: plano de conteúdo, regra única de "você tem esta palavra" e julgamento dos termos na análise."""
import unittest

from src import aderencia, config, plano, tailor
from tests.fakes import SLUG_ASSIST, SLUG_ATUAL, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta


class Base(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()
        self.analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())

    def tearDown(self):
        limpar(self.tmp)

    def limites(self, n=2):
        return {e.slug: n for e in self.kb.experiencias()}


class TestPlano(Base):
    def setUp(self):
        super().setUp()
        # "funil" só está num fato da experiência atual; "e-mail marketing" só num fato da anterior
        self.analise["palavras_chave"] += ["funil", "e-mail marketing"]
        self.analise["palavras_chave_base"] += [{"termo": "funil", "evidencias": [f"{SLUG_ATUAL}#1"]},
                                                {"termo": "e-mail marketing", "evidencias": [f"{SLUG_ASSIST}#1"]}]

    def montar(self, limites=None):
        return plano.montar(self.kb, self.analise, limites or self.limites(),
                            aderencia.palavras_sustentadas(self.kb, self.analise))

    def test_mesmo_historico_mesmo_plano(self):
        self.assertEqual(self.montar(), self.montar())

    def test_escolhe_o_fato_que_comprova_a_palavra_e_pede_o_termo_exato(self):
        p = self.montar()
        self.assertIn(f"{SLUG_ATUAL}#1", p["experiencias"][SLUG_ATUAL])
        self.assertIn("funil", p["termos"][f"{SLUG_ATUAL}#1"])
        self.assertIn(f"{SLUG_ASSIST}#1", p["experiencias"][SLUG_ASSIST])

    def test_respeita_o_limite_de_cada_experiencia(self):
        p = self.montar({**self.limites(1), SLUG_ATUAL: 3})
        self.assertEqual(len(p["experiencias"][SLUG_ATUAL]), 3)
        self.assertTrue(all(len(ids) <= 1 for slug, ids in p["experiencias"].items() if slug != SLUG_ATUAL))

    def test_palavra_que_nao_cabe_nos_bullets_vai_para_resumo_ou_competencias(self):
        p = self.montar(self.limites(0))
        fora = {x["nome"] for x in p["fora_das_experiencias"]}
        self.assertIn("funil", fora)
        self.assertIn("Google Ads", fora)          # comprovada por habilidades: competências
        texto = plano.para_prompt(p)
        self.assertIn("funil", texto)
        self.assertIn("nenhum bullet", texto)

    def test_so_pede_o_que_a_base_comprova(self):
        texto = plano.para_prompt(self.montar())
        self.assertNotIn("Looker Studio", texto)   # a vaga pede, a base não tem
        self.assertNotIn("HubSpot", texto)

    def test_cortar_bullets_tira_de_onde_vale_menos_e_nunca_zera(self):
        lim = {**self.limites(2), SLUG_ATUAL: 4}
        menos = plano.cortar_bullets(self.kb, self.analise, lim, aderencia.palavras_sustentadas(self.kb, self.analise), 2)
        self.assertEqual(sum(menos.values()), sum(lim.values()) - 2)
        self.assertTrue(all(v >= 1 for v in menos.values()))
        # o fato que comprova "funil" continua no plano
        p = plano.montar(self.kb, self.analise, menos, aderencia.palavras_sustentadas(self.kb, self.analise))
        self.assertIn(f"{SLUG_ATUAL}#1", p["experiencias"][SLUG_ATUAL])

    def test_o_gerador_recebe_o_plano(self):
        llm = LLMFalso(gerado_bom())
        tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertIn("Plano de conteúdo", llm.chamadas[0]["mensagens"][0]["content"])

    def test_curriculo_geral_nao_tem_plano(self):
        llm = LLMFalso(gerado_bom())
        tailor.gerar(llm, self.kb, "Geral", tailor.analise_geral("pt"), "pt", self.cfg, verificar_ia=False)
        self.assertNotIn("Plano de conteúdo", llm.chamadas[0]["mensagens"][0]["content"])


class TestCorrecaoPeloPlano(Base):
    def test_palavra_comprovada_que_o_texto_esqueceu_volta_a_ser_pedida(self):
        g = gerado_bom()
        g["competencias"] = [{"grupo": "Mídia paga", "itens": "Google Ads, Meta Ads, SQL",
                              "fontes": ["habilidades#2", "habilidades#3"]}]
        sem_sql = gerado_bom()
        fiscal = {"itens": [], "palavras": []}
        llm = LLMFalso(sem_sql, fiscal, g, fiscal)
        res = tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg)
        pedidos = [c["mensagens"][1]["content"] for c in llm.chamadas if c["rotulo"] == "gerador"][1:]
        self.assertTrue(any("SQL" in p for p in pedidos))
        self.assertIn("SQL", res.curriculo.markdown)

    def test_nunca_mais_que_duas_correcoes(self):
        llm = LLMFalso(gerado_bom(), {"itens": [], "palavras": []})   # o "modelo" nunca corrige nada
        tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", {**self.cfg, "max_paginas": 1})
        self.assertLessEqual(sum(c["rotulo"] == "gerador" for c in llm.chamadas), 3)


class TestRegraUnicaDePalavras(Base):
    def test_sinonimo_aceito_na_analise_nao_vira_falta_de_base_depois_de_gerar(self):
        # "mídia programática" não está escrito no histórico, mas a análise ligou a um fato (sinônimo aceito)
        self.analise["palavras_chave"].append("mídia paga digital")
        self.analise["palavras_chave_base"].append({"termo": "mídia paga digital", "evidencias": ["habilidades#2"]})
        self.analise["palavras_julgadas"], self.analise["palavras_rejeitadas"] = ["mídia paga digital"], []
        res = tailor.gerar(LLMFalso(gerado_bom()), self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertNotIn("mídia paga digital", res.cobertura["fora_sem_base"])
        self.assertIn("mídia paga digital", res.cobertura["fora_com_base"])
        self.assertIn("mídia paga digital", aderencia.palavras_sustentadas(self.kb, self.analise))

    def test_termo_rejeitado_na_analise_nao_conta_em_lugar_nenhum(self):
        self.analise["palavras_julgadas"], self.analise["palavras_rejeitadas"] = ["SQL"], ["SQL"]
        self.assertNotIn("sql", aderencia.palavras_sustentadas(self.kb, self.analise))
        llm = LLMFalso(gerado_bom())
        res = tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertIn("SQL", res.termos_rejeitados)
        pedidas = [t for ts in res.plano["termos"].values() for t in ts]
        pedidas += [x["nome"] for x in res.plano["fora_das_experiencias"] if x["tipo"] == "palavra"]
        self.assertNotIn("SQL", pedidas)


class TestMaximoEstavel(Base):
    def test_o_maximo_so_depende_do_historico_e_da_analise(self):
        res = tailor.gerar(LLMFalso(gerado_bom()), self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        md, rastro = res.curriculo.markdown, res.curriculo.rastro
        cheio = aderencia.calcular(self.analise, md, rastro, self.kb, self.cfg, "pt", paginas=1)
        # a mesma versão com uma frase apontada pelo fiscal: a nota pode cair, o máximo não muda
        frase = next(l[2:] for l in md.splitlines() if "Google Ads" in l and l.startswith("* "))
        apontado = aderencia.calcular(self.analise, md, rastro, self.kb, self.cfg, "pt", paginas=1, suspeitos=[frase])
        self.assertLessEqual(apontado["total"], cheio["total"])
        self.assertEqual(apontado["teto"], cheio["teto"])


class TestJulgarNaAnalise(Base):
    def test_analise_julga_os_termos_duvidosos_uma_vez(self):
        bruta = analise_bruta()
        bruta["palavras_chave"].append("gestão de campanhas")
        bruta["palavras_chave_base"].append({"termo": "gestão de campanhas", "evidencias": ["habilidades#2"]})
        fiscal = {"itens": [{"n": 0, "veredito": "sem_respaldo", "problema": "não diz gestão"}], "palavras": []}
        llm = LLMFalso(bruta, fiscal)
        a = tailor.analisar(llm, self.kb, "Vaga")
        self.assertEqual([c["rotulo"] for c in llm.chamadas], ["analisador", "verificador"])
        self.assertIn("gestão de campanhas", a["palavras_julgadas"])
        self.assertEqual(a["palavras_rejeitadas"], ["gestão de campanhas"])
        # o fiscal recebeu o termo com os fatos dele, não a base inteira
        enviado = llm.chamadas[1]["mensagens"][1]["content"]
        self.assertIn("gestão de campanhas", enviado)
        self.assertIn("Gerencia campanhas pagas", enviado)
        # e a geração não julga de novo
        llm2 = LLMFalso(gerado_bom(), {"itens": [], "palavras": []})
        tailor._gerar_uma_vez(llm2, self.kb, "Vaga", a, "pt", self.cfg, None, True, None, None)
        if len(llm2.chamadas) > 1:
            self.assertNotIn("PALAVRAS-CHAVE da vaga para classificar\n- gestão de campanhas",
                             llm2.chamadas[1]["mensagens"][1]["content"])

    def test_sem_termos_duvidosos_nao_chama_o_fiscal(self):
        llm = LLMFalso(analise_bruta())
        a = tailor.analisar(llm, self.kb, "Vaga")
        self.assertEqual(len(llm.chamadas), 1)
        self.assertEqual(a["palavras_rejeitadas"], [])


if __name__ == "__main__":
    unittest.main()
