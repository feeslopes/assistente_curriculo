import unittest

from src import config, render
from src.verify import cobertura_palavras, numeros_em, numeros_nao_suportados
from tests.fakes import SLUG_ASSIST, SLUG_ATUAL, SLUG_ESTAG, base_exemplo, limpar


def gerado_bom():
    return {
        "titulo": "Marketing Analyst",
        "resumo": {"texto": "Analista de marketing com foco em mídia paga e análise de dados.",
                   "fontes": ["perfil#1", "habilidades#2"]},
        "competencias": [{"grupo": "Mídia paga", "itens": "Google Ads, Meta Ads", "fontes": ["habilidades#2"]}],
        "experiencias": [
            {"id": SLUG_ATUAL, "bullets": [
                {"texto": "Estruturou o funil de aquisição de um produto com 12 mil usuários ativos.", "fontes": [f"{SLUG_ATUAL}#1"]},
                {"texto": "Reduziu o custo por lead em 18% ao reorganizar as campanhas por público.", "fontes": [f"{SLUG_ATUAL}#3"]}]},
            {"id": SLUG_ASSIST, "bullets": [
                {"texto": "Gerenciou o calendário de e-mail marketing para 40 mil clientes.", "fontes": [f"{SLUG_ASSIST}#1"]}]},
            {"id": SLUG_ESTAG, "bullets": [
                {"texto": "Apoiou um evento de lançamento com cerca de 150 convidados.", "fontes": [f"{SLUG_ESTAG}#2"]}]},
        ],
        "formacao": [{"texto": "Universidade Exemplo | Bacharelado em Publicidade e Propaganda | 2014 – 2018", "fontes": ["formacao#1"]}],
        "certificacoes": [{"texto": "Google Analytics Certification | Google | 2021", "fontes": ["certificacoes#1"]}],
        "idiomas": [{"texto": "Inglês: Avançado", "fontes": ["idiomas#2"]}],
    }


class TestRender(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def montar(self, gerado, idioma="pt", titulo=None, cfg=None):
        return render.montar(self.kb, gerado, idioma, cfg or self.cfg, titulo)

    def test_caminho_feliz_pt(self):
        cv = self.montar(gerado_bom())
        self.assertEqual(cv.alertas, [])
        md = cv.markdown
        self.assertTrue(md.startswith("# Mariana Exemplo  \n**Analista de Marketing**  \nSão Paulo, Brasil  \n"))
        self.assertIn("+55 11 90000-0000 | mariana.exemplo@example.com | linkedin.com/in/mariana-exemplo", md)
        self.assertIn("_Analista de Marketing · Março 2022 – Presente · São Paulo, Brasil_", md)
        self.assertIn("* **Universidade Exemplo** | Bacharelado", md)
        self.assertIn("* **Mídia paga:** Google Ads, Meta Ads", md)
        ordem = [md.index(f"## {t}") for t in ("Resumo", "Competências", "Experiência Profissional", "Formação", "Certificações", "Idiomas")]
        self.assertEqual(ordem, sorted(ordem))

    def test_datas_em_ingles_e_titulo(self):
        cv = self.montar(gerado_bom(), "en")
        self.assertIn("_Marketing Analyst · March 2022 – Present · São Paulo, Brazil_", cv.markdown)
        self.assertIn("**Marketing Analyst**", cv.markdown)
        self.assertIn("## Professional Experience", cv.markdown)

    def test_empresa_agrupada(self):
        md = self.montar(gerado_bom()).markdown
        self.assertEqual(md.count("**Loja Modelo**"), 1)
        self.assertIn("_Estagiária de Marketing", md)
        self.assertLess(md.index("_Assistente de Marketing"), md.index("_Estagiária de Marketing"))

    def test_item_sem_fonte_e_removido_e_listado(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"].append({"texto": "Liderou uma equipe de dez pessoas.", "fontes": []})
        g["experiencias"][0]["bullets"].append({"texto": "Inventou algo.", "fontes": ["nao-existe#9"]})
        cv = self.montar(g)
        self.assertNotIn("Liderou", cv.markdown)
        self.assertNotIn("Inventou", cv.markdown)
        textos = [r["texto"] for r in cv.removidos]
        self.assertIn("Liderou uma equipe de dez pessoas.", textos)
        self.assertTrue(any("Liderou" in a for a in cv.alertas))

    def test_fonte_sugerida_nao_conta(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"].append({"texto": "Reduziu o custo por lead em cerca de 20%.", "fontes": [f"{SLUG_ATUAL}#6"]})
        cv = self.montar(g)
        self.assertNotIn("cerca de 20%", cv.markdown)

    def test_fonte_de_outra_experiencia_nao_conta(self):
        g = gerado_bom()
        g["experiencias"][1]["bullets"].append({"texto": "Estruturou o funil de aquisição.", "fontes": [f"{SLUG_ATUAL}#1"]})
        cv = self.montar(g)
        self.assertEqual(cv.markdown.count("Estruturou o funil"), 1)  # só o da experiência certa

    def test_manter_com_aviso(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"].append({"texto": "Item sem fonte.", "fontes": []})
        cfg = dict(self.cfg, bullets_sem_fonte="manter_com_aviso")
        cv = self.montar(g, cfg=cfg)
        self.assertIn("Item sem fonte.", cv.markdown)
        self.assertTrue(any("SEM fato" in a for a in cv.alertas))

    def test_numero_inventado_gera_aviso(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"][1]["texto"] = "Reduziu o custo por lead em 95% ao reorganizar as campanhas."
        cv = self.montar(g)
        self.assertTrue(any("95" in a for a in cv.alertas))
        self.assertIn("95%", cv.markdown)  # aviso, nunca bloqueio

    def test_numero_por_extenso_e_formatos(self):
        self.assertEqual(numeros_nao_suportados("Equipe de 7 pessoas", ["Liderou sete pessoas"]), [])
        self.assertEqual(numeros_nao_suportados("Atendeu 2.000 clientes", ["Atendeu 2000 clientes"]), [])
        self.assertEqual(numeros_nao_suportados("Cresceu 1,5%", ["Cresceu 1.5%"]), [])
        self.assertEqual(numeros_nao_suportados("Três campanhas", ["Fez 3 campanhas"]), [])
        self.assertEqual(numeros_nao_suportados("Fez 9 campanhas", ["Fez 3 campanhas"]), ["9"])
        self.assertIn("7", numeros_em("sete e seven"))

    def test_titulo_promovido_cai_no_padrao(self):
        g = gerado_bom()
        g["titulo"] = "Senior Marketing Manager"
        cv = self.montar(g, "pt")
        self.assertEqual(cv.titulo, "Analista de Marketing")
        self.assertTrue(any("Senior Marketing Manager" in a for a in cv.alertas))

    def test_titulo_do_usuario_e_respeitado_sem_aviso(self):
        cv = self.montar(gerado_bom(), "pt", titulo="Especialista em Growth")
        self.assertEqual(cv.titulo, "Especialista em Growth")
        self.assertFalse(any("título" in a.lower() for a in cv.alertas))

    def test_titulo_cargo_da_base_aceito(self):
        g = gerado_bom()
        g["titulo"] = "Assistente de Marketing"
        self.assertEqual(self.montar(g).titulo, "Assistente de Marketing")

    def test_experiencia_omitida_gera_aviso(self):
        g = gerado_bom()
        g["experiencias"] = g["experiencias"][:2]
        cv = self.montar(g)
        self.assertTrue(any("Estagiária" in a and "buraco" in a for a in cv.alertas))
        self.assertNotIn("Estagiária", cv.markdown)

    def test_experiencia_inventada_ignorada(self):
        g = gerado_bom()
        g["experiencias"].append({"id": "google-ceo", "bullets": [{"texto": "Dirigiu o Google.", "fontes": ["x#1"]}]})
        cv = self.montar(g)
        self.assertNotIn("Google.", cv.markdown)
        self.assertTrue(any("google-ceo" in a for a in cv.alertas))

    def test_limite_de_bullets_por_posicao(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"] += [
            {"texto": "Montou o relatório semanal de desempenho em planilha.", "fontes": [f"{SLUG_ATUAL}#4"]},
            {"texto": "Trabalha com as equipes de produto e de vendas.", "fontes": [f"{SLUG_ATUAL}#5"]}]
        cfg = dict(self.cfg, bullets_por_experiencia=[2, 1])
        cv = self.montar(g, cfg=cfg)
        self.assertEqual(cv.markdown.count("Montou o relatório"), 0)
        self.assertTrue(any("cortado" in a for a in cv.alertas))

    def test_travessao_longo_vira_hifen(self):
        g = gerado_bom()
        g["resumo"]["texto"] = "Analista de marketing — mídia paga e dados."
        md = self.montar(g).markdown
        self.assertNotIn("—", md)
        self.assertIn("marketing - mídia", md)

    def test_limite_de_resumo_corta_por_frase(self):
        g = gerado_bom()
        g["resumo"]["texto"] = "Analista de marketing com foco em mídia paga. " + "Domina análise de dados e relatórios. " * 5
        cv = self.montar(g, cfg=dict(self.cfg, resumo_max_palavras=15))
        corpo = cv.markdown.split("## Resumo")[1].split("##")[0]
        self.assertLessEqual(len(corpo.split()), 15)

    def test_limite_de_grupos(self):
        g = gerado_bom()
        g["competencias"] = [{"grupo": f"G{i}", "itens": "Google Ads", "fontes": ["habilidades#2"]} for i in range(4)]
        cv = self.montar(g, cfg=dict(self.cfg, max_grupos_competencias=2))
        self.assertEqual(cv.markdown.count("* **G"), 2)

    def test_lixo_do_modelo_nao_derruba(self):
        for g in (None, [], {}, {"experiencias": "x", "resumo": 5, "competencias": [1, None]}):
            cv = self.montar(g)
            self.assertIn("# Mariana Exemplo", cv.markdown)

    def test_competencia_sem_respaldo_na_base_e_removida(self):
        g = gerado_bom()
        g["competencias"] = [{"grupo": "Dados", "itens": "Google Ads, Google Sheets, testes A/B, CRO, SQL básico",
                              "fontes": ["habilidades#1", "habilidades#2"]}]
        cv = self.montar(g)
        self.assertIn("* **Dados:** Google Ads, SQL básico", cv.markdown)
        for inventado in ("Google Sheets", "testes A/B", "CRO"):
            self.assertNotIn(inventado, cv.markdown)
        self.assertEqual({r["texto"] for r in cv.removidos}, {"Google Sheets", "testes A/B", "CRO"})
        self.assertTrue(any("Google Sheets" in a for a in cv.alertas))

    def test_grupo_de_competencias_sem_nenhum_termo_valido_some(self):
        g = gerado_bom()
        g["competencias"] = [{"grupo": "CRM", "itens": "Salesforce, HubSpot", "fontes": ["habilidades#1"]}]
        self.assertNotIn("## Competências", self.montar(g).markdown)

    def test_sigla_ou_ferramenta_fora_da_base_gera_aviso(self):
        g = gerado_bom()
        g["experiencias"][0]["bullets"][0]["texto"] = "Estruturou o funil de aquisição no Salesforce com 12 mil usuários ativos."
        cv = self.montar(g)
        self.assertTrue(any("Salesforce" in a for a in cv.alertas))

    def test_saida_em_ingles_nao_destroi_competencias_traduzidas(self):
        """Base em português, currículo em inglês: palavras comuns não são comparáveis."""
        g = gerado_bom()
        g["competencias"] = [{"grupo": "Paid Media", "itens": "Google Ads, campaign optimization, budget management, SQL",
                              "fontes": ["habilidades#2"]}]
        cv = self.montar(g, "en")
        self.assertIn("* **Paid Media:** Google Ads, campaign optimization, budget management, SQL", cv.markdown)
        self.assertFalse(any("Native" in a or "Advanced" in a for a in cv.alertas))
        g["competencias"][0]["itens"] = "Google Ads, HubSpot, CRO, SQL"
        cv = self.montar(g, "en")
        self.assertNotIn("HubSpot", cv.markdown)
        self.assertNotIn("CRO", cv.markdown)
        self.assertIn("Google Ads, SQL", cv.markdown)

    def test_ia_e_ai_se_equivalem(self):
        from src.verify import palavras_da_base, siglas_nao_suportadas
        base = palavras_da_base(["Usa IA e POCs em discovery"])
        self.assertEqual(siglas_nao_suportadas("Used AI and POC", base, estrito=False), [])

    def test_cargos_sem_traducao_viram_um_aviso_so(self):
        t = self.kb.ler_texto(SLUG_ESTAG).replace("cargo_en: Marketing Intern\n", "")
        self.kb.salvar_texto(SLUG_ESTAG, t)
        cv = self.montar(gerado_bom(), "en")
        avisos = [a for a in cv.alertas if "cargo_en" in a]
        self.assertEqual(len(avisos), 1)
        self.assertIn("Estagiária de Marketing", avisos[0])

    def test_cobertura_em_saida_traduzida_nao_afirma_o_que_nao_sabe(self):
        cob = cobertura_palavras(["product vision", "SQL", "CRO", "coaching"],
                                 "Product vision and SQL", ["Visão de produto e SQL"], mesmo_idioma=False)
        self.assertEqual(cob["usadas"], ["SQL"])
        self.assertEqual(cob["usadas_indeterminadas"], ["product vision"])   # usada, mas o código não compara idiomas
        self.assertEqual(cob["fora_indeterminadas"], ["coaching"])
        self.assertEqual(cob["fora_sem_base"], ["CRO"])   # sigla é comparável entre idiomas

    def test_cobertura_separa_termo_usado_sem_base(self):
        cob = cobertura_palavras(["CRO", "Google Ads"], "Experiência com CRO e Google Ads", ["Usa Google Ads"])
        self.assertEqual(cob["usadas"], ["Google Ads"])
        self.assertEqual(cob["usadas_sem_base"], ["CRO"])

    def test_cobertura(self):
        base = self.kb.textos_confirmados()
        cob = cobertura_palavras(["Google Ads", "SQL", "Looker Studio", "google ads", "funil"], "Usa Google Ads e funil de vendas", base)
        self.assertEqual(cob["usadas"], ["Google Ads", "funil"])
        self.assertEqual(cob["fora_com_base"], ["SQL"])
        self.assertEqual(cob["fora_sem_base"], ["Looker Studio"])


if __name__ == "__main__":
    unittest.main()
