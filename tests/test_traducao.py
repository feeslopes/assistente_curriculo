import json
import unittest

from src import config, render, tailor
from src.kb import KB
from tests.fakes import LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta

import shutil
import tempfile
from pathlib import Path


def base_ingles():
    """Base cujos fatos estão em inglês (como um CV em inglês importado)."""
    tmp = Path(tempfile.mkdtemp())
    kb = KB(tmp / "base")
    kb.salvar_contato({"nome": "Ana Test", "titulo_padrao_en": "Product Manager", "local": "São Paulo, Brazil"})
    slug = kb.criar_experiencia({"empresa": "Acme", "cargo": "Product Manager", "inicio": "2021-01",
                                 "fim": "atual", "local": "São Paulo, Brazil"})
    kb.adicionar_fatos(slug, [
        "Led the roadmap and prioritization of an internal analytics platform used by 40 analysts.",
        "Worked with Risk, Compliance and Legal teams to translate regulatory requirements into product features.",
        "Used Excel and SQL to track adoption and conversion metrics."])
    slug2 = kb.criar_experiencia({"empresa": "Beta", "cargo": "Product Intern", "inicio": "2019-01", "fim": "2020-12",
                                  "local": "São Carlos, Brazil"})
    kb.adicionar_fatos(slug2, ["Supported discovery interviews with customers of a corporate education product."])
    kb.adicionar_fatos("habilidades", ["Uses Excel and SQL for analysis and dashboards."])
    return kb, tmp, slug, slug2


def gerado_en(slug, slug2):
    return {
        "titulo": "Product Manager",
        "resumo": {"texto": "Gerente de produto com foco em plataformas de dados.", "fontes": [f"{slug}#1"]},
        "competencias": [{"grupo": "Dados", "itens": "Excel, SQL, Google Sheets, testes A/B",
                          "fontes": ["habilidades#1", f"{slug}#3"]}],
        "experiencias": [
            {"id": slug, "bullets": [
                {"texto": "Liderou o roadmap e a priorização de uma plataforma interna usada por 40 analistas.", "fontes": [f"{slug}#1"]},
                {"texto": "Atuou com Risco, Compliance e Jurídico para traduzir requisitos regulatórios em funcionalidades.", "fontes": [f"{slug}#2"]}]},
            {"id": slug2, "bullets": [
                {"texto": "Apoiou entrevistas de discovery com clientes de um produto de educação corporativa.", "fontes": [f"{slug2}#1"]}]}],
        "formacao": [], "certificacoes": [], "idiomas": [],
    }


class TestTraducao(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp, self.s1, self.s2 = base_ingles()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def test_idioma_base_detectado(self):
        self.assertEqual(self.kb.idioma_base(), "en")
        self.assertFalse(self.kb.mistura_idiomas())

    def test_base_mista_e_detectada(self):
        kb, tmp = base_exemplo()   # base em português
        try:
            kb.adicionar_fatos("habilidades", [
                "Product vision, discovery, roadmap definition, prioritization, and end-to-end execution of products.",
                "Conversion and activation across regulated, user-centered digital journeys with operational complexity.",
                "Metrics and KPI definition, impact analysis, unit economics, ROI, dashboards, and SQL to support decisions.",
                "API-first products, scalable digital platforms, integrations with partners, and enablement of the business.",
                "Worked closely with the engineering team and the legal team to deliver the product to the customers."])
            self.assertTrue(kb.mistura_idiomas())
        finally:
            limpar(tmp)

    def test_cargo_sem_traducao_e_um_aviso_so_em_pt(self):
        cv = render.montar(self.kb, gerado_en(self.s1, self.s2), "pt", self.cfg)
        self.assertFalse(cv.mesmo_idioma)
        avisos = [a for a in cv.alertas if "cargo_pt" in a]
        self.assertEqual(len(avisos), 1)
        self.assertIn("Product Intern", avisos[0])

    def test_saida_no_idioma_da_base_usa_cargo_original_sem_aviso(self):
        cv = render.montar(self.kb, gerado_en(self.s1, self.s2), "en", self.cfg)
        self.assertTrue(cv.mesmo_idioma)
        self.assertFalse(any("cargo_en" in a for a in cv.alertas))

    def test_sugerir_so_sugere_e_aplicar_grava_o_que_foi_confirmado(self):
        llm = LLMFalso({"traducoes": [
            {"slug": self.s1, "cargo": "Gerente de Produto", "local": "São Paulo, Brasil"},
            {"slug": self.s2, "cargo": "Estagiário de Produto", "local": "São Carlos, Brasil"}]})
        sug = tailor.sugerir_traducoes(llm, self.kb, "pt")
        self.assertEqual([s["cargo"] for s in sug], ["Gerente de Produto", "Estagiário de Produto"])
        self.assertNotIn("cargo_pt", self.kb.ler_texto(self.s1))        # nada gravado ainda
        sug[1]["cargo"] = ""                                            # ela não confirmou esta
        self.assertEqual(tailor.aplicar_traducoes(self.kb, "pt", sug), 1)
        self.assertIn("cargo_pt: Gerente de Produto", self.kb.ler_texto(self.s1))
        self.assertIn("Led the roadmap", self.kb.ler_texto(self.s1))    # fatos preservados
        self.assertEqual(self.kb.fato(f"{self.s1}#1").status, "confirmado")
        cv = render.montar(self.kb, gerado_en(self.s1, self.s2), "pt", self.cfg)
        self.assertIn("_Gerente de Produto · Janeiro 2021 – Presente · São Paulo, Brasil_", cv.markdown)
        self.assertEqual(cv.titulo, "Gerente de Produto")
        self.assertIn("Product Intern", cv.markdown)                    # ainda sem tradução confirmada

    def test_sem_sugestao_quando_ja_esta_no_idioma_da_base(self):
        self.assertEqual(tailor.sugerir_traducoes(LLMFalso(), self.kb, "en"), [])

    def test_fiscal_remove_termo_e_alerta_frase(self):
        veredito = {
            "competências|Google Sheets": "Os fatos citam Excel, não Google Sheets.",
            "competências|testes A/B": "Nenhum fato fala de testes A/B.",
            f"experiência Acme|Atuou com Risco, Compliance e Jurídico para traduzir requisitos regulatórios em funcionalidades.":
                "ok mas exagerado"}
        cv = render.montar(self.kb, gerado_en(self.s1, self.s2), "pt", self.cfg, veredito=veredito)
        self.assertIn("Excel, SQL", cv.markdown)
        self.assertNotIn("Google Sheets", cv.markdown)
        self.assertNotIn("testes A/B", cv.markdown)
        self.assertTrue(any("verificação por IA" in a and "exagerado" in a for a in cv.alertas))
        self.assertIn("Atuou com Risco", cv.markdown)                   # frase suspeita fica, com alerta

    def test_gerar_chama_fiscal_e_aplica_veredito(self):
        itens = None
        llm = LLMFalso(gerado_en(self.s1, self.s2), "PLACEHOLDER")
        # resposta do fiscal depende dos índices; calculamos montando antes
        cv0 = render.montar(self.kb, gerado_en(self.s1, self.s2), "pt", self.cfg)
        idx = {it["chave"]: n for n, it in enumerate(cv0.itens_fiscal)}
        llm.fila[1] = json.dumps({
            "problemas": [{"n": idx["competências|Google Sheets"], "problema": "Excel não é Google Sheets"}],
            "palavras": []})
        analise = tailor.validar_analise({"palavras_chave": ["Excel"], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(llm, self.kb, "Vaga em português com Excel", analise, "pt", self.cfg)
        self.assertTrue(res.verificacao_ia)
        self.assertNotIn("Google Sheets", res.curriculo.markdown)
        self.assertEqual(len(llm.chamadas), 2)
        pedido = llm.chamadas[1]["mensagens"][1]["content"]
        self.assertIn("Led the roadmap", pedido)                        # fatos originais vão ao fiscal

    def test_fiscal_resolve_palavras_indeterminadas(self):
        itens = [{"chave": "k|x", "secao": "k", "tipo": "frase", "texto": "x", "fatos": ["fato"]}]
        llm = LLMFalso({"problemas": [], "palavras": [{"termo": "coaching", "na_base": False},
                                                       {"termo": "analytics", "na_base": True}]})
        v = tailor.verificar_com_ia(llm, self.kb, itens, ["coaching", "analytics", "outro"])
        self.assertEqual(v["palavras"], {"coaching": False, "analytics": True})
        cob = {"fora_indeterminadas": ["coaching", "analytics", "outro"], "fora_com_base": [], "fora_sem_base": [],
               "usadas": [], "usadas_sem_base": [], "usadas_indeterminadas": ["backlog", "roadmap"]}
        v["palavras"].update({"backlog": False, "roadmap": True})
        tailor._resolver_indeterminadas(cob, v["palavras"])
        self.assertEqual((cob["fora_com_base"], cob["fora_sem_base"], cob["fora_indeterminadas"]),
                         (["analytics"], ["coaching"], ["outro"]))
        self.assertEqual((cob["usadas"], cob["usadas_sem_base"]), (["roadmap"], ["backlog"]))
        self.assertEqual(cob["percentual"], 20)

    def test_numero_mil_e_milhar_com_virgula_sao_o_mesmo_numero(self):
        from src.verify import numeros_em, numeros_nao_suportados, siglas_nao_suportadas, palavras_da_base
        self.assertEqual(numeros_nao_suportados("budget of R$ 80,000, 12,000 users and 40k customers",
                                                ["R$ 80 mil", "12 mil usuários", "base de 40 mil clientes"]), [])
        self.assertIn("1500", numeros_em("1,5 mil"))
        self.assertEqual(numeros_nao_suportados("90,000 users", ["12 mil usuários"]), ["90000"])
        # "000" de um número nunca é sigla ou ferramenta; B2B é
        self.assertEqual(siglas_nao_suportadas("budget of R$ 80,000 in B2B", palavras_da_base(["B2B"])), [])
        self.assertEqual(siglas_nao_suportadas("budget of R$ 80,000 in B2C", palavras_da_base(["B2B"])), ["B2C"])

    def _gerado_com_termo_traduzido(self):
        g = gerado_en(self.s1, self.s2)
        g["competencias"] = [{"grupo": "Dados", "itens": "Excel, SQL, VLOOKUP, HubSpot", "fontes": ["habilidades#1", f"{self.s1}#3"]}]
        return g

    def test_saida_traduzida_com_ia_deixa_a_decisao_para_o_fiscal(self):
        # PROCV na base e VLOOKUP no texto: o código não sabe que é a mesma coisa; a IA decide
        self.kb.adicionar_fatos("habilidades", ["Usa PROCV e tabelas dinâmicas."])
        cv = render.montar(self.kb, self._gerado_com_termo_traduzido(), "pt", self.cfg, fiscal="pendente")
        self.assertIn("VLOOKUP", cv.markdown)
        self.assertIn("HubSpot", cv.markdown)   # só sai se o fiscal apontar
        cv = render.montar(self.kb, self._gerado_com_termo_traduzido(), "pt", self.cfg, fiscal="ok",
                           veredito={"competências|HubSpot": "nenhum fato cita HubSpot"})
        self.assertIn("VLOOKUP", cv.markdown)
        self.assertNotIn("HubSpot", cv.markdown)

    def test_sem_ia_o_codigo_volta_a_julgar_siglas(self):
        cv = render.montar(self.kb, self._gerado_com_termo_traduzido(), "pt", self.cfg, fiscal="ausente")
        self.assertNotIn("HubSpot", cv.markdown)

    def test_falha_do_fiscal_reaplica_a_regra_do_codigo(self):
        from src.llm import ErroLLM

        class Quebra(LLMFalso):
            def conversar(self, mensagens, json_mode=False, temperatura=0.3, rotulo=""):
                if self.chamadas:
                    raise ErroLLM("limite")
                return super().conversar(mensagens, json_mode, temperatura, rotulo)

        llm = Quebra(self._gerado_com_termo_traduzido())
        analise = tailor.validar_analise({"palavras_chave": [], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(llm, self.kb, "Vaga", analise, "pt", self.cfg)
        self.assertNotIn("HubSpot", res.curriculo.markdown)

    def test_fiscal_ignora_lixo_e_indices_invalidos(self):
        itens = [{"chave": "k|x", "secao": "k", "tipo": "frase", "texto": "x", "fatos": []}]
        llm = LLMFalso({"problemas": [{"n": 99, "problema": "x"}, {"n": "a"}, {"n": 0, "problema": ""}, "lixo"]})
        self.assertEqual(tailor.verificar_com_ia(llm, self.kb, itens, [])["problemas"], {})

    def test_falha_do_fiscal_vira_alerta_e_nao_derruba(self):
        from src.llm import ErroLLM

        class Quebra(LLMFalso):
            def conversar(self, mensagens, json_mode=False, temperatura=0.3, rotulo=""):
                if len(self.chamadas) >= 1:
                    raise ErroLLM("limite")
                return super().conversar(mensagens, json_mode, temperatura, rotulo)

        llm = Quebra(gerado_en(self.s1, self.s2))
        analise = tailor.validar_analise({"palavras_chave": [], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(llm, self.kb, "Vaga", analise, "pt", self.cfg)
        self.assertFalse(res.verificacao_ia)
        self.assertTrue(any("verificação por IA não rodou" in a for a in res.curriculo.alertas))
        self.assertIn("Excel, SQL", res.curriculo.markdown)


if __name__ == "__main__":
    unittest.main()
