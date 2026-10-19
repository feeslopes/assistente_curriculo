"""Funções criadas para a interface nova: editar itens no cartão, pastas por empresa e termos parecidos."""
import json
import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from src import aderencia, config, historico, saidas, tailor
from src.kb import ErroBase
from tests.fakes import SLUG_ATUAL, SLUG_ESTAG, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta


class TestEditarNoCartao(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_substituir_fatos_preserva_linhas_livres_e_remove_duplicados(self):
        caminho = self.kb.base / "experiencias" / f"{SLUG_ESTAG}.md"
        caminho.write_text(caminho.read_text(encoding="utf-8") + "\nAnotação livre que não é fato.\n", encoding="utf-8")
        self.kb.substituir_fatos(SLUG_ESTAG, [("Fez A.", "confirmado"), ("Fez  A.", "confirmado"),
                                              ("Talvez B.", "sugerido")])
        texto = self.kb.ler_texto(SLUG_ESTAG)
        self.assertIn("Anotação livre que não é fato.", texto)
        fatos = next(a for a in self.kb.experiencias() if a.slug == SLUG_ESTAG).fatos()
        self.assertEqual([(f.texto, f.status) for f in fatos], [("Fez A.", "confirmado"), ("Talvez B.", "sugerido")])

    def test_substituir_fatos_cria_secao_que_nao_existia(self):
        os.remove(self.kb.base / "certificacoes.md")
        self.kb.substituir_fatos("certificacoes", [("PMP | PMI | 2020", "confirmado")])
        self.assertEqual([f.texto for f in self.kb.fatos() if f.slug == "certificacoes"], ["PMP | PMI | 2020"])

    def test_atualizar_experiencia_valida_e_preserva_os_itens(self):
        antes = [f.texto for f in self.kb.fatos() if f.slug == SLUG_ATUAL]
        self.kb.atualizar_experiencia(SLUG_ATUAL, {"cargo": "Analista de Marketing Pleno", "ocultar": True})
        exp = next(a for a in self.kb.experiencias(True) if a.slug == SLUG_ATUAL)
        self.assertEqual(exp.meta["cargo"], "Analista de Marketing Pleno")
        self.assertTrue(exp.meta["ocultar"])
        self.assertEqual([f.texto for f in exp.fatos()], antes)
        with self.assertRaises(ErroBase):
            self.kb.atualizar_experiencia(SLUG_ATUAL, {"inicio": "03/2022"})

    def test_remover_experiencia(self):
        self.kb.remover_experiencia(SLUG_ESTAG)
        self.assertNotIn(SLUG_ESTAG, [a.slug for a in self.kb.experiencias(True)])
        with self.assertRaises(ErroBase):
            self.kb.remover_experiencia("perfil")       # só experiências podem ser excluídas assim


class TestPastas(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        limpar(self.tmp)

    def test_pasta_por_empresa_e_mes(self):
        hoje = date(2026, 10, 18)
        self.assertEqual(saidas.pasta_da_saida("QuintoAndar", "PM", self.tmp, hoje).name, "QuintoAndar_2026-10")
        self.assertEqual(saidas.pasta_da_saida("", "PM", self.tmp, hoje).name, "Vaga sem empresa_2026-10")
        self.assertEqual(saidas.pasta_da_saida('Acme: "S/A"', "PM", self.tmp, hoje).name, "Acme S A_2026-10")

    def test_outra_vaga_na_mesma_empresa_e_mes_ganha_o_titulo(self):
        hoje = date(2026, 10, 18)
        (self.tmp / "Acme_2026-10").mkdir()
        self.assertEqual(saidas.pasta_da_saida("Acme", "Analista Sênior", self.tmp, hoje).name,
                         "Acme_2026-10_Analista Sênior")
        (self.tmp / "Acme_2026-10_Analista Sênior").mkdir()
        self.assertEqual(saidas.pasta_da_saida("Acme", "Analista Sênior", self.tmp, hoje).name,
                         "Acme_2026-10_Analista Sênior_2")

    def test_nome_do_arquivo_tem_o_nome_da_pessoa(self):
        self.assertEqual(saidas.nome_do_arquivo("Mariana Exemplo"), "Curriculo_Mariana_Exemplo")
        self.assertEqual(saidas.nome_do_arquivo("Mariana Exemplo", "en"), "Curriculo_Mariana_Exemplo_EN")
        self.assertEqual(saidas.nome_do_arquivo(""), "Curriculo")

    def test_salvar_na_mesma_pasta_regrava(self):
        analise = {"empresa": "Acme", "titulo_vaga": "PM"}
        p1 = saidas.salvar_saida("# a", b"1", b"1", "vaga", analise, raiz=self.tmp, nome_arquivo="Curriculo_X")
        p2 = saidas.salvar_saida("# b", b"2", b"2", "vaga", analise, pasta=p1, nome_arquivo="Curriculo_X")
        self.assertEqual(p1, p2)
        self.assertEqual((p1 / "Curriculo_X.md").read_text(encoding="utf-8"), "# b")

    def test_historico_le_pastas_novas_e_antigas(self):
        antiga = self.tmp / "2026-09-01-velha-analista"
        antiga.mkdir()
        (antiga / "analise.json").write_text(json.dumps({"empresa": "Velha"}), encoding="utf-8")
        (antiga / "curriculo.pdf").write_bytes(b"%PDF")
        time.sleep(0.05)
        nova = saidas.salvar_saida("# x", b"%PDF", b"docx", "vaga", {"empresa": "Nova", "titulo_vaga": "PM"},
                                   raiz=self.tmp, nome_arquivo="Curriculo_Ana",
                                   indice={"antes": 40, "depois": 70, "teto": 80, "idioma": "pt"})
        entradas = historico.listar(self.tmp)
        self.assertEqual([e["empresa"] for e in entradas], ["Nova", "Velha"])      # a mais recente primeiro
        self.assertEqual(entradas[0]["pdf"], nova / "Curriculo_Ana.pdf")
        self.assertEqual(entradas[0]["data"], date.today().isoformat())
        self.assertEqual(entradas[1]["data"], "2026-09-01")
        self.assertEqual(entradas[1]["pdf"].name, "curriculo.pdf")


class TestTermosParecidos(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def test_termo_ligado_a_um_vizinho_nao_e_sugerido_como_ja_comprovado(self):
        bruta = analise_bruta()
        bruta["palavras_chave"].append("Google Sheets")
        # o modelo diz que o fato sobre planilhas (habilidades#1) sustenta "Google Sheets": não sustenta
        bruta["palavras_chave_base"].append({"termo": "Google Sheets", "evidencias": ["habilidades#1"]})
        analise = tailor.validar_analise(bruta, self.kb.ids_confirmados())
        res = tailor.gerar(LLMFalso(gerado_bom()), self.kb, "Vaga", analise, "pt", self.cfg, verificar_ia=False)
        det = res.aderencia["depois"]["componentes"]["palavras"]["detalhe"]
        self.assertIn("Google Sheets", det["parecidas_ausentes"])
        self.assertNotIn("Google Sheets", det["sustentadas_ausentes"])
        ms = res.aderencia["melhorias"]
        usar = [i for m in ms if m["tipo"] == "usar_base" for i in m["itens"]]
        self.assertNotIn("Google Sheets", usar)
        parecidas = next(m for m in ms if "Parecidas" in m["titulo"])
        self.assertEqual(parecidas["tipo"], "confirmar")
        self.assertIn("SQL", usar)                    # o que os fatos dizem com as mesmas palavras continua lá

    def test_em_idiomas_diferentes_nao_ha_como_comparar_e_nada_vira_parecida(self):
        bruta = analise_bruta()
        bruta["idioma_vaga"] = "en"
        analise = tailor.validar_analise(bruta, self.kb.ids_confirmados())
        ind = aderencia.calcular(analise, "# x\n\n## Resumo\n\ntexto\n", [], self.kb, self.cfg, "en")
        self.assertEqual(ind["componentes"]["palavras"]["detalhe"]["parecidas_ausentes"], [])


class TestDuplicatas(unittest.TestCase):
    """Mesmo cargo vindo de outro currículo: nome da empresa escrito de outro jeito, data só com ano, outro idioma."""

    def caso(self, a, b):
        from src.interview import parecida_com
        return parecida_com(a, b)

    def test_pega_variacoes_de_nome_e_de_data(self):
        self.assertTrue(self.caso({"empresa": "Mercado Livre", "inicio": "2021-03", "fim": "atual"},
                                  {"empresa": "MercadoLibre", "inicio": "2021-02", "fim": "atual"}))
        self.assertTrue(self.caso({"empresa": "Itaú Unibanco S.A.", "inicio": "2015-01", "fim": "2017-12"},
                                  {"empresa": "Itaú", "inicio": "2015-03", "fim": "2017-10"}))
        self.assertTrue(self.caso({"empresa": "Magazine Luiza S.A.", "inicio": "2018-01", "fim": "2021-02"},
                                  {"empresa": "Magalu", "inicio": "2018", "fim": "2021"}))

    def test_nao_confunde_empresas_ou_epocas_diferentes(self):
        self.assertFalse(self.caso({"empresa": "Banco do Brasil", "inicio": "2016-01", "fim": "2018-12"},
                                   {"empresa": "Banco Inter", "inicio": "2019-01", "fim": "2020-12"}))
        self.assertFalse(self.caso({"empresa": "Itaú Unibanco", "inicio": "2010-01", "fim": "2012-12"},
                                   {"empresa": "Itaú", "inicio": "2019-01", "fim": "2020-12"}))
        self.assertFalse(self.caso({"empresa": "Nubank", "inicio": "2020-01", "fim": "atual"},
                                   {"empresa": "Freelancer", "inicio": "2022-05", "fim": "atual"}))

    def test_itens_em_outro_idioma_numa_experiencia_existente_geram_aviso(self):
        from src import interview
        kb, tmp = base_exemplo()
        try:
            bruto = {"propostas": [{"destino": SLUG_ATUAL, "meta": {}, "fatos": [
                {"texto": "Led the acquisition funnel for a product with twelve thousand active users across the region.",
                 "origem": "dito"}]}]}
            props = interview.validar_propostas(bruto, kb, "en", "material em inglês")
            self.assertTrue(any("só traduzidos" in p for p in props[0].problemas))
        finally:
            limpar(tmp)


class TestIdiomaDeFraseCurta(unittest.TestCase):
    def test_frases_curtas_de_curriculo(self):
        from src.texto import idioma_de_frase
        self.assertEqual(idioma_de_frase("Negotiated return pickup windows with 4 carrier partners."), "en")
        self.assertEqual(idioma_de_frase("Treinou 15 operadores no novo processo de triagem."), "pt")
        self.assertEqual(idioma_de_frase("Cuida da agenda de 6 médicos."), "pt")
        self.assertIsNone(idioma_de_frase("Power BI"))                    # sem sinal: não arrisca

    def test_item_curto_em_ingles_numa_experiencia_em_portugues_avisa(self):
        from src import interview
        kb, tmp = base_exemplo()
        try:
            bruto = {"propostas": [{"destino": SLUG_ATUAL, "meta": {}, "fatos": [
                {"texto": "Negotiated return pickup windows with 4 carrier partners.", "origem": "dito"}]}]}
            props = interview.validar_propostas(bruto, kb, "en", "material")
            self.assertTrue(any("só traduzidos" in p for p in props[0].problemas))
        finally:
            limpar(tmp)


class TestIdiomaDoTrecho(unittest.TestCase):
    def test_resumo_no_idioma_errado_vira_alerta(self):
        from src import render
        kb, tmp = base_exemplo()
        try:
            g = gerado_bom()
            g["resumo"]["texto"] = ("Analista de marketing com experiência em mídia paga e análise de dados para "
                                    "empresas de produto digital.")
            cv = render.montar(kb, g, "en", config.carregar_config())
            self.assertTrue(any("saiu em português" in a for a in cv.alertas))
            cv_pt = render.montar(kb, g, "pt", config.carregar_config())
            self.assertFalse(any("saiu em" in a for a in cv_pt.alertas))
        finally:
            limpar(tmp)


class TestConsistencia(unittest.TestCase):
    """Achados do teste com uma pessoa fictícia: o mesmo termo tratado de jeitos diferentes em partes do app."""

    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def test_palavra_do_cargo_nao_vira_sigla_inventada(self):
        from src import render
        self.kb.atualizar_experiencia(SLUG_ATUAL, {"cargo": "Analista de Marketing Sênior"})
        g = gerado_bom()
        g["resumo"]["texto"] = "Analista de Marketing Sênior com foco em mídia paga e análise de dados."
        cv = render.montar(self.kb, g, "pt", self.cfg)
        self.assertFalse(any("Sênior" in a and "Sigla" in a for a in cv.alertas))

    def test_competencia_que_a_analise_ligou_a_um_fato_fica_e_vai_para_o_fiscal(self):
        from src import render
        g = gerado_bom()
        g["competencias"] = [{"grupo": "Aquisição", "itens": "Growth, Google Ads",
                              "fontes": [f"{SLUG_ATUAL}#1", "habilidades#2"]}]
        sem = render.montar(self.kb, g, "pt", self.cfg)
        self.assertIn("Growth", [r["texto"] for r in sem.removidos])          # o filtro de palavras sozinho tira
        com = render.montar(self.kb, g, "pt", self.cfg, sustentadas={"growth": {f"{SLUG_ATUAL}#1"}}, fiscal="pendente")
        self.assertNotIn("Growth", [r["texto"] for r in com.removidos])       # com fato citado pela análise, fica
        self.assertIn("competências|Growth", [i["chave"] for i in com.itens_fiscal])   # e o fiscal confere

    def test_nome_de_grupo_apontado_pelo_fiscal_sai(self):
        from src import render
        g = gerado_bom()
        g["competencias"][0]["grupo"] = "Liderança de equipes"
        cv = render.montar(self.kb, g, "pt", self.cfg, fiscal="pendente")
        self.assertIn("competências-grupo|Liderança de equipes", [i["chave"] for i in cv.itens_fiscal])
        cv2 = render.montar(self.kb, g, "pt", self.cfg, fiscal="ok",
                            veredito={"competências-grupo|Liderança de equipes": "os fatos não falam em liderar equipes"})
        self.assertNotIn("Liderança de equipes", cv2.markdown)
        self.assertIn("Google Ads, Meta Ads", cv2.markdown)                   # os itens continuam

    def test_frase_apontada_pelo_fiscal_nao_conta_no_indice(self):
        analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())
        cv = tailor.gerar(LLMFalso(gerado_bom()), self.kb, "Vaga", analise, "pt", self.cfg, verificar_ia=False).curriculo
        normal = aderencia.calcular(analise, cv.markdown, cv.rastro, self.kb, self.cfg, "pt")
        # o fiscal apontou as duas frases que trazem "Google Ads" (resumo e competências)
        suspeitos = [r["texto"] for r in cv.rastro if r["secao"] in ("resumo", "competências")]
        sem = aderencia.calcular(analise, cv.markdown, cv.rastro, self.kb, self.cfg, "pt", suspeitos=suspeitos)
        self.assertLess(sem["total"], normal["total"])
        self.assertNotIn("Google Ads", sem["componentes"]["palavras"]["detalhe"]["usadas"])


class TestNaoPiorar(unittest.TestCase):
    """A versão adaptada não pode pontuar abaixo da versão sem adaptar."""

    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()
        self.analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())

    def tearDown(self):
        limpar(self.tmp)

    @staticmethod
    def magro():
        """Um currículo que perde quase tudo: só um bullet, sem resumo nem competências."""
        g = gerado_bom()
        g["resumo"], g["competencias"] = {"texto": "", "fontes": []}, []
        g["experiencias"] = g["experiencias"][:1]
        g["experiencias"][0]["bullets"] = g["experiencias"][0]["bullets"][:1]
        return g

    def test_pontuacao_antes_de_gerar_nao_usa_ia(self):
        orig = aderencia.indice_original(self.kb, self.analise, self.cfg)
        self.assertTrue(0 <= orig["indice"]["total"] <= orig["indice"]["teto"] <= 100)
        self.assertIn("## Experiência Profissional", orig["markdown"])

    def test_versao_pior_ganha_segunda_chance_com_o_que_perdeu(self):
        fiscal = {"itens": [], "palavras": []}
        llm = LLMFalso(self.magro(), fiscal, gerado_bom(), fiscal)
        res = tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg)
        geracoes = [c for c in llm.chamadas if c["rotulo"] == "gerador"]
        self.assertEqual(len(geracoes), 2)
        pedido = geracoes[1]["mensagens"][1]["content"]
        self.assertIn("Correção (segunda tentativa)", pedido)
        self.assertIn("Google Ads", pedido)                 # o que a versão sem adaptar mostrava e a primeira perdeu
        self.assertTrue(res.segunda_tentativa)
        self.assertIn("Google Ads", res.curriculo.markdown)

    def test_se_continuar_pior_a_tela_e_avisada(self):
        fiscal = {"itens": [], "palavras": []}
        res = tailor.gerar(LLMFalso(self.magro(), fiscal, self.magro(), fiscal), self.kb, "Vaga", self.analise, "pt", self.cfg)
        self.assertTrue(res.abaixo_do_original)
        self.assertIn("## Experiência Profissional", res.aderencia["markdown_antes"])   # a versão sem adaptar fica à mão

    def test_sem_ia_nao_ha_segunda_tentativa(self):
        llm = LLMFalso(self.magro())
        res = tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertEqual(len(llm.chamadas), 1)
        self.assertTrue(res.abaixo_do_original)


class TestCaberNasPaginas(unittest.TestCase):
    """Passou do limite de páginas: o gerador condensa, e a nota máxima não é puxada para baixo por isso."""

    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = {**config.carregar_config(), "max_paginas": 1}
        self.analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())
        self.fiscal = {"itens": [], "palavras": []}

    def tearDown(self):
        limpar(self.tmp)

    @staticmethod
    def curto():
        g = gerado_bom()
        g["competencias"] = [{"grupo": "Mídia paga e dados", "itens": "Google Ads, Meta Ads, SQL",
                              "fontes": ["habilidades#2", "habilidades#3"]}]
        return g

    @classmethod
    def comprido(cls):
        g = cls.curto()
        enchimento = " ".join(["detalhe"] * 160)
        for exp in g["experiencias"]:
            for b in exp["bullets"]:
                b["texto"] += " " + enchimento
        return g

    def gerar(self, *respostas):
        llm = LLMFalso(*respostas)
        return llm, tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg)

    def test_passou_do_limite_pede_texto_mais_curto_e_fica_com_o_que_cabe(self):
        llm, res = self.gerar(self.comprido(), self.fiscal, self.curto(), self.fiscal)
        geracoes = [c for c in llm.chamadas if c["rotulo"] == "gerador"]
        self.assertEqual(len(geracoes), 2)
        self.assertIn("Correção (tamanho)", geracoes[1]["mensagens"][1]["content"])
        self.assertTrue(res.condensada)
        self.assertEqual(res.aderencia["depois"]["paginas"], 1)

    def test_o_pedido_de_geracao_informa_o_limite_de_paginas(self):
        llm = LLMFalso(self.curto())
        tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertIn("caber em 1 página", llm.chamadas[0]["mensagens"][0]["content"])

    def test_se_nao_couber_mesmo_assim_o_aviso_fica_e_nao_ha_terceira_chamada_sem_fim(self):
        llm, res = self.gerar(self.comprido(), self.fiscal, self.comprido(), self.fiscal, self.comprido(), self.fiscal)
        self.assertLessEqual(len([c for c in llm.chamadas if c["rotulo"] == "gerador"]), 3)
        self.assertGreater(res.aderencia["depois"]["paginas"], 1)

    def test_a_segunda_tentativa_de_corte_tira_um_bullet_da_experiencia_que_menos_pesa(self):
        llm, _ = self.gerar(self.comprido(), self.fiscal, self.comprido(), self.fiscal, self.comprido(), self.fiscal)
        geracoes = [c for c in llm.chamadas if c["rotulo"] == "gerador"]
        self.assertEqual(len(geracoes), 3)
        antes = geracoes[1]["mensagens"][0]["content"]
        depois = geracoes[2]["mensagens"][0]["content"]
        self.assertNotEqual(antes, depois)

    def test_sem_ia_nao_ha_condensacao(self):
        llm = LLMFalso(self.comprido())
        res = tailor.gerar(llm, self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        self.assertEqual(len(llm.chamadas), 1)
        self.assertFalse(res.condensada)

    def test_o_maximo_nao_perde_pontos_pelo_limite_de_paginas(self):
        res = tailor.gerar(LLMFalso(gerado_bom()), self.kb, "Vaga", self.analise, "pt", self.cfg, verificar_ia=False)
        md, rastro = res.curriculo.markdown, res.curriculo.rastro
        cabe = aderencia.calcular(self.analise, md, rastro, self.kb, self.cfg, "pt", paginas=1)
        estoura = aderencia.calcular(self.analise, md, rastro, self.kb, self.cfg, "pt", paginas=3)
        self.assertLess(estoura["total"], cabe["total"])      # a nota cai
        self.assertEqual(estoura["teto"], cabe["teto"])       # o máximo, não

    def test_estimativa_de_tamanho_cresce_com_os_bullets_e_a_vaga_ordena_os_fatos(self):
        poucos = {e.slug: 1 for e in self.kb.experiencias()}
        muitos = {e.slug: 5 for e in self.kb.experiencias()}
        self.assertLess(aderencia.estimar_palavras(self.kb, self.cfg, poucos),
                        aderencia.estimar_palavras(self.kb, self.cfg, muitos))
        self.analise["palavras_chave_base"].append({"termo": "funil", "evidencias": [f"{SLUG_ATUAL}#1"]})
        valorizados = tailor.fatos_valorizados_por_experiencia(self.kb, self.analise)
        self.assertTrue(all(0 <= v <= t for v, t in valorizados.values()))
        self.assertTrue(any(v for v, _ in valorizados.values()))


if __name__ == "__main__":
    unittest.main()
