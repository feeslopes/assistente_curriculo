import tempfile
import unittest
from pathlib import Path

from src import config, relatorio, saidas, tailor
from tests.fakes import SLUG_ASSIST, SLUG_ATUAL, SLUG_ESTAG, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta


def gerado_com_adaptacao():
    g = gerado_bom()
    g["adaptacao"] = {
        "estrategia": "A vaga valoriza mídia paga e análise de dados, então destaquei Google Ads e Analytics.",
        "mudancas": [
            {"onde": "Resumo", "o_que": "Abri com mídia paga e Google Analytics.", "motivo": "São os dois primeiros requisitos."},
            {"onde": "Empresa Exemplo Digital", "o_que": "Priorizei o orçamento de mídia.", "motivo": ""}],
        "deixou_de_fora": ["Looker Studio: a base não comprova."],
    }
    return g


class TestRelatorio(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()
        self.analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())

    def tearDown(self):
        limpar(self.tmp)

    def gerar(self, gerado=None, idioma="pt"):
        return tailor.gerar(LLMFalso(gerado or gerado_com_adaptacao()), self.kb, "Vaga", self.analise, idioma, self.cfg,
                            verificar_ia=False)

    def test_gerar_devolve_o_relatorio(self):
        res = self.gerar()
        self.assertTrue(res.relatorio)
        self.assertEqual(res.relatorio["vaga"]["empresa"], "Empresa Fictícia")

    def test_encaixe_conta_requisitos_e_palavras(self):
        e = self.gerar().relatorio["encaixe"]
        # analise_bruta: 1 coberto e 1 coberto sem evidência (vira parcial), obrigatórios; SQL parcial e A/B lacuna, desejáveis
        self.assertEqual(e["obrigatorios"], {"total": 2, "coberto": 1, "parcial": 1, "lacuna": 0})
        self.assertEqual(e["desejaveis"], {"total": 2, "coberto": 0, "parcial": 1, "lacuna": 1})
        self.assertIn("Dashboards no Looker Studio", e["parciais_obrigatorias"])
        self.assertGreater(e["palavras"]["total"], 0)

    def test_cada_bullet_traz_o_fato_de_origem_e_as_palavras_da_vaga(self):
        rel = self.gerar().relatorio
        exp = next(x for x in rel["experiencias"] if x["rotulo"].startswith("Empresa Exemplo Digital"))
        b = next(x for x in exp["bullets"] if "funil" in x["final"])
        self.assertEqual(b["base"], ["Estruturou o funil de aquisição de um produto com 12 mil usuários ativos."])
        self.assertEqual(exp["limite"], 5)
        self.assertIn("a mais recente", exp["motivo"])

    def test_vocabulario_adotado_so_quando_a_palavra_nao_estava_no_fato(self):
        g = gerado_com_adaptacao()
        # reescreve o bullet usando "Google Ads", que NÃO está no fato #1 (funil), mas é palavra-chave da vaga
        g["experiencias"][0]["bullets"][0]["texto"] = "Estruturou o funil de aquisição com Google Ads para 12 mil usuários ativos."
        rel = self.gerar(g).relatorio
        exp = next(x for x in rel["experiencias"] if x["rotulo"].startswith("Empresa Exemplo Digital"))
        b = next(x for x in exp["bullets"] if "funil" in x["final"])
        self.assertIn("Google Ads", b["palavras"])
        self.assertIn("Google Ads", b["vocabulario_adotado"])

    def test_em_saida_traduzida_nao_afirma_diferenca_de_vocabulario(self):
        # base em português gerando em inglês: não dá para comparar palavras entre idiomas
        g = gerado_com_adaptacao()
        g["experiencias"][0]["bullets"] = [{"texto": "Structured the acquisition funnel with Google Ads for 12 thousand users.",
                                            "fontes": [f"{SLUG_ATUAL}#1"]}]
        rel = self.gerar(g, "en").relatorio
        exp = next(x for x in rel["experiencias"] if x["rotulo"].startswith("Empresa Exemplo Digital"))
        self.assertTrue(exp["bullets"])
        self.assertEqual(exp["bullets"][0]["vocabulario_adotado"], [])

    def test_explicacao_da_ia_e_exibida_mas_saneada(self):
        ia = self.gerar().relatorio["ia"]
        self.assertIn("mídia paga", ia["estrategia"])
        self.assertEqual(len(ia["mudancas"]), 2)
        self.assertEqual(ia["deixou_de_fora"], ["Looker Studio: a base não comprova."])
        g = gerado_com_adaptacao()
        g["adaptacao"] = {"estrategia": "x" * 5000, "mudancas": "lixo", "deixou_de_fora": [None, 3, "ok"]}
        ia2 = self.gerar(g).relatorio["ia"]
        self.assertLessEqual(len(ia2["estrategia"]), 900)
        self.assertEqual(ia2["mudancas"], [])
        self.assertEqual(ia2["deixou_de_fora"], ["3", "ok"])
        g["adaptacao"] = "texto solto"
        self.assertEqual(self.gerar(g).relatorio["ia"], {"estrategia": "", "mudancas": [], "deixou_de_fora": []})

    def test_palavras_chave_sustentadas_mostram_onde_entraram(self):
        g = gerado_com_adaptacao()
        g["resumo"]["texto"] = "Analista de marketing com Google Ads e análise de dados."
        rel = self.gerar(g).relatorio
        pb = {p["termo"]: p["onde"] for p in rel["palavras_base"]}
        self.assertIn("Resumo", pb["Google Ads"])
        self.assertTrue(any(o.startswith("Empresa Exemplo Digital") for o in pb["Google Ads"]) or "Competências" in pb["Google Ads"])
        self.assertEqual(pb["SQL"], [])        # a base sustenta, mas o currículo não usou
        md = relatorio.para_markdown(rel)
        self.assertIn("## Palavras-chave da vaga que a sua base sustenta, e onde entraram", md)
        self.assertIn("- SQL: não entrou no currículo (a base tem; dá para incluir editando)", md)

    def test_cabecalho_da_experiencia_mostra_usados_de_ate_o_limite(self):
        md = relatorio.para_markdown(self.gerar().relatorio)
        self.assertIn("#### Empresa Exemplo Digital · Analista de Marketing (2022 a atual): 2 de até 5 bullet(s), a mais recente", md)

    def test_o_que_ficou_de_fora(self):
        g = gerado_com_adaptacao()
        g["experiencias"][0]["bullets"].append({"texto": "Liderou dez pessoas.", "fontes": []})
        rel = self.gerar(g).relatorio
        self.assertTrue(any("Liderou dez pessoas." in r for r in rel["fora"]["removidos"]))
        self.assertIn("Looker Studio", rel["fora"]["palavras_sem_base"])
        self.assertTrue(any("Liderou" in a for a in rel["conferir"]))

    def test_markdown_do_relatorio(self):
        md = relatorio.para_markdown(self.gerar().relatorio)
        for trecho in ("# Relatório da adaptação", "## Encaixe com a vaga", "Requisitos obrigatórios: 1 de 2 cobertos",
                       "## Estratégia da adaptação (explicação da IA; não faz parte do currículo)",
                       "## Como cada parte foi escrita", "- Currículo: Estruturou o funil", "  - Base: Estruturou o funil",
                       "## O que ficou de fora e por quê", "## Pontos a conferir antes de enviar"):
            self.assertIn(trecho, md)
        self.assertNotIn("—", md)
        self.assertFalse(relatorio.para_markdown(self.gerar().relatorio, com_titulo=False).startswith("# Relatório"))

    def test_relatorio_sem_explicacao_da_ia_nao_mostra_a_secao(self):
        md = relatorio.para_markdown(self.gerar(gerado_bom()).relatorio)
        self.assertNotIn("Estratégia da adaptação", md)

    def test_experiencia_so_com_cabecalho_aparece_assim_no_relatorio(self):
        res = tailor.gerar(LLMFalso(gerado_com_adaptacao()), self.kb, "Vaga", self.analise, "pt", self.cfg,
                           verificar_ia=False, limites_manuais={SLUG_ESTAG: 0})
        md = relatorio.para_markdown(res.relatorio)
        self.assertIn("0 bullet(s), ajustado por você", md)
        self.assertIn("Só cargo, empresa e datas.", md)
        self.assertIn("Experiências resumidas", md)

    def test_salvar_saida_grava_o_relatorio(self):
        res = self.gerar()
        raiz = Path(tempfile.mkdtemp())
        pasta = saidas.salvar_saida("# cv", b"%PDF", b"docx", "vaga", self.analise, raiz,
                                    relatorio=relatorio.para_markdown(res.relatorio))
        self.assertIn("Relatório da adaptação", (pasta / "relatorio.md").read_text(encoding="utf-8"))
        pasta2 = saidas.salvar_saida("# cv", b"%PDF", b"docx", "vaga", self.analise, raiz)
        self.assertFalse((pasta2 / "relatorio.md").exists())


if __name__ == "__main__":
    unittest.main()


class TestCorrespondenciaDeTermos(unittest.TestCase):
    """O relatório e a cobertura não podem dizer que um termo 'não entrou' só porque está no plural."""

    def test_singular_e_plural_casam(self):
        from src.verify import contem_termo
        self.assertTrue(contem_termo("Experienced in leading product squads and OKRs", "product squad"))
        self.assertTrue(contem_termo("Cross-functional team leadership", "cross-functional teams"))
        self.assertTrue(contem_termo("Defined quarterly OKR planning", "OKRs"))
        self.assertTrue(contem_termo("Usa relatórios semanais", "relatório"))

    def test_continua_exigindo_palavra_inteira_e_ordem(self):
        from src.verify import contem_termo
        self.assertFalse(contem_termo("Worked on squadron tactics", "squad"))
        self.assertFalse(contem_termo("sql is great", "sq"))
        self.assertFalse(contem_termo("analytics team", "team analytics"))
        self.assertFalse(contem_termo("Looker", "Looker Studio"))

    def test_cobertura_considera_o_plural(self):
        from src.verify import cobertura_palavras
        cob = cobertura_palavras(["product squad", "SEO"], "Led product squads of 7 people",
                                 ["Atuou como Team Lead de uma squad. Product squad."])
        self.assertEqual(cob["usadas"], ["product squad"])
        self.assertEqual(cob["fora_sem_base"], ["SEO"])
