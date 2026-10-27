import unittest

from evals import casos, comparar, metricas, rodar
from evals.casos import Caso
from src.kb import KB
from tests.fakes import LLMFalso
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta

FISCAL_OK = {"itens": [], "palavras": []}


class TestCasos(unittest.TestCase):
    def test_todas_as_bases_e_vagas_existem_e_as_bases_carregam(self):
        for caso in casos.CASOS:
            self.assertTrue(casos.BASES[caso.base].is_dir(), caso.id)
            self.assertGreater(len(caso.texto_vaga.strip()), 100, caso.id)
            kb = KB(casos.BASES[caso.base])
            self.assertTrue(kb.ids_confirmados(), caso.id)

    def test_armadilhas_nao_estao_na_base_do_caso(self):
        """Uma armadilha só vale se a base realmente não sustenta o termo."""
        for caso in casos.CASOS:
            if not caso.armadilhas:
                continue
            base = " ".join(KB(casos.BASES[caso.base]).textos_confirmados())
            for termo in caso.armadilhas:
                self.assertFalse(metricas.termo_presente(base, termo), f"{caso.id}: '{termo}' existe na base")

    def test_armadilhas_estao_na_vaga(self):
        for caso in casos.CASOS:
            for termo in caso.armadilhas:
                self.assertTrue(metricas.termo_presente(caso.texto_vaga, termo), f"{caso.id}: '{termo}' não está na vaga")

    def test_ids_unicos_e_selecao(self):
        ids = [c.id for c in casos.CASOS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([c.id for c in casos.selecionar(["mkt-pt"])], ["mkt-pt"])
        with self.assertRaises(SystemExit):
            casos.selecionar(["nao-existe"])


class TestMetricas(unittest.TestCase):
    def test_termo_presente_so_palavra_inteira(self):
        self.assertTrue(metricas.termo_presente("Domínio de SAP e Excel", "SAP"))
        self.assertFalse(metricas.termo_presente("Visitou o sapato", "SAP"))
        self.assertTrue(metricas.termo_presente("Operações de M&A", "m&a"))
        self.assertTrue(metricas.termo_presente("Modelos de Valuation", "valuation"))
        self.assertFalse(metricas.termo_presente("", "SAP"))
        self.assertTrue(metricas.termo_presente("analise de credito", "Análise"))     # acento não atrapalha

    def test_classifica_alertas(self):
        c = metricas.classificar_alertas([
            'Número(s) 85% não aparece(m) na base: "x". Confira antes de usar.',
            'Sigla(s) ou ferramenta(s) SAP não aparece(m) na base: "y".',
            'Mantido em \'experiencia\' SEM fato confirmado de apoio: "z".',
            "Algo qualquer"])
        self.assertEqual((c["numero_sem_base"], c["sigla_sem_base"], c["sem_fonte"], c["total"]), (1, 1, 1, 4))


class TestRodarCaso(unittest.TestCase):
    def test_caso_ponta_a_ponta_com_llm_falso(self):
        llm = LLMFalso(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        r = rodar.rodar_caso(llm, Caso("t", "marketing", "marketing_pt", "pt"), rodar.Coletor())
        m = r["metricas"]
        self.assertIn("aprovado", m)
        self.assertIsInstance(m["paginas"], int)
        self.assertEqual(m["falhas_duras"]["armadilhas_vazadas"], [])
        self.assertIn("Mariana", r["markdown"])
        self.assertEqual(r["custo_usd"], 0)

    def test_armadilha_vazada_reprova(self):
        llm = LLMFalso(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        caso = Caso("t", "marketing", "marketing_pt", "pt", armadilhas=("Google Ads",))   # a base TEM isso: vai "vazar"
        r = rodar.rodar_caso(llm, caso, rodar.Coletor())
        self.assertEqual(r["metricas"]["falhas_duras"]["armadilhas_vazadas"], ["Google Ads"])
        self.assertFalse(r["metricas"]["aprovado"])

    def test_nao_deixa_rastro_em_disco(self):
        import tempfile
        antes = set(__import__("pathlib").Path(tempfile.gettempdir()).iterdir())
        llm = LLMFalso(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        rodar.rodar_caso(llm, Caso("t", "marketing", "marketing_pt", "pt"), rodar.Coletor())
        novos = [p for p in set(__import__("pathlib").Path(tempfile.gettempdir()).iterdir()) - antes if p.is_dir() and (p / "base").exists()]
        self.assertEqual(novos, [])

    def test_coletor_soma_por_etapa(self):
        c = rodar.Coletor()
        uso = {"entrada": 100, "cache_hit": 0, "cache_miss": 100, "saida": 10}
        c({"rotulo": "gerador", "modelo": "deepseek-v4-pro", "uso": uso, "custo_usd": 0.01})
        c({"rotulo": "gerador", "modelo": "deepseek-v4-pro", "uso": uso, "custo_usd": 0.02})
        c({"rotulo": "analisador", "modelo": "deepseek-flash", "uso": uso, "custo_usd": None})
        r = c.resumo()
        self.assertEqual(r["etapas"]["gerador"]["chamadas"], 2)
        self.assertEqual(r["custo_usd"], 0.03)
        self.assertEqual(r["entrada"], 300)
        self.assertEqual(r["etapas"]["analisador"]["modelos"], ["deepseek-flash"])

    def test_etapas_da_linha_de_comando(self):
        self.assertEqual(rodar._etapas("analisador=deepseek-flash, verificador = deepseek-flash"),
                         {"analisador": "deepseek-flash", "verificador": "deepseek-flash"})
        self.assertEqual(rodar._etapas(""), {})
        with self.assertRaises(SystemExit):
            rodar._etapas("sem-igual")


def resultado(aprovado=True, vazadas=(), numeros=0, ader=70, custo=0.1, fid=None):
    return {"caso": "x", "custo_usd": custo, "juiz": None if fid is None else {"fidelidade": fid, "relevancia": 4, "clareza": 4,
                                                                          "traducao": 5, "afirmacoes_sem_base": []},
            "metricas": {"aprovado": aprovado, "falhas_duras": {"armadilhas_vazadas": list(vazadas), "numeros_sem_base": numeros,
                                                                "itens_sem_fonte_mantidos": 0},
                         "aderencia_depois": ader, "ganho": 10, "paginas": 2, "n_correcoes": 1, "alertas": {"total": 2}}}


def rodada(*resultados, rotulo="r"):
    return {"rotulo": rotulo, "quando": "2026-10-26", "etapas": {}, "resumo": rodar.resumir(list(resultados))}


class TestComparar(unittest.TestCase):
    def test_resumo(self):
        r = rodar.resumir([resultado(), resultado(aprovado=False, vazadas=["SAP"], numeros=1, ader=60)])
        self.assertEqual((r["casos"], r["aprovados"], r["armadilhas_vazadas"], r["numeros_sem_base"]), (2, 1, 1, 1))
        self.assertEqual(r["aderencia_depois"], 65)
        self.assertEqual(r["custo_usd"], 0.2)
        self.assertIsNone(r["juiz_fidelidade"])

    def test_sem_regressao(self):
        a, b = rodada(resultado(), resultado()), rodada(resultado(custo=0.05), resultado(custo=0.05), rotulo="b")
        c = comparar.comparar(a, b)
        self.assertEqual(c["regressoes"], [])
        self.assertIn("Sem regressões", comparar.formatar(a, b, c))

    def test_armadilha_nova_e_regressao(self):
        c = comparar.comparar(rodada(resultado()), rodada(resultado(aprovado=False, vazadas=["SAP"])))
        self.assertTrue(any("armadilhas_vazadas" in x for x in c["regressoes"]))
        self.assertTrue(any("aprovados" in x for x in c["regressoes"]))

    def test_queda_de_aderencia_acima_do_limite(self):
        self.assertTrue(comparar.comparar(rodada(resultado(ader=80)), rodada(resultado(ader=70)))["regressoes"])
        self.assertEqual(comparar.comparar(rodada(resultado(ader=80)), rodada(resultado(ader=78)))["regressoes"], [])

    def test_queda_de_fidelidade_do_juiz(self):
        c = comparar.comparar(rodada(resultado(fid=4.5)), rodada(resultado(fid=3.5)))
        self.assertTrue(any("fidelidade" in x for x in c["regressoes"]))

    def test_custo_menor_nao_e_regressao_mas_aparece_no_delta(self):
        c = comparar.comparar(rodada(resultado(custo=0.2)), rodada(resultado(custo=0.1)))
        linha = next(l for l in c["linhas"] if l["campo"] == "custo_usd_por_caso")
        self.assertAlmostEqual(linha["delta"], -0.1)
        self.assertEqual(c["regressoes"], [])


if __name__ == "__main__":
    unittest.main()
