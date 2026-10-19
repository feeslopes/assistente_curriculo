import unittest

from src.kb import KB, ErroBase
from tests.fakes import SLUG_ASSIST, SLUG_ATUAL, SLUG_ESTAG, base_exemplo, limpar


class TestKB(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_ids_e_status(self):
        f = self.kb.fato(f"{SLUG_ATUAL}#1")
        self.assertEqual(f.status, "confirmado")
        self.assertIn("12 mil", f.texto)
        # o 6º fato marcado é o sugerido; a anotação solta não ganha id
        self.assertEqual(self.kb.fato(f"{SLUG_ATUAL}#6").status, "sugerido")
        self.assertIsNone(self.kb.fato(f"{SLUG_ATUAL}#7"))

    def test_ordenacao_por_data(self):
        slugs = [e.slug for e in self.kb.experiencias()]
        self.assertEqual(slugs, [SLUG_ATUAL, SLUG_ASSIST, SLUG_ESTAG])

    def test_para_prompt_so_confirmados_sem_contato(self):
        p = self.kb.para_prompt()
        self.assertNotIn("Reduziu o custo por lead em cerca de 20%", p)  # sugerido
        self.assertNotIn("HubSpot", p)                                    # sugerido
        self.assertNotIn("Anotação solta", p)                             # sem marca
        for c in ("mariana.exemplo@example.com", "90000", "linkedin.com", "Mariana"):
            self.assertNotIn(c, p)
        self.assertIn(f"[{SLUG_ATUAL}#1]", p)

    def test_linhas_sem_marca(self):
        self.assertEqual(self.kb.linhas_sem_marca(), 1)

    def test_adicionar_preserva_texto_livre_e_deduplica(self):
        r = self.kb.adicionar_fatos(SLUG_ATUAL, ["Montou o relatório semanal de desempenho em planilha e o apresenta para a diretoria comercial.",
                                                 "Treinou dois analistas juniores."])
        self.assertEqual((r["adicionados"], r["ignorados"]), (1, 1))
        texto = self.kb.ler_texto(SLUG_ATUAL)
        self.assertIn("Anotação solta da Mariana", texto)
        self.assertIn("- [confirmado] Treinou dois analistas juniores.", texto)

    def test_adicionar_promove_sugerido(self):
        r = self.kb.adicionar_fatos(SLUG_ATUAL, ["Reduziu o custo por lead em cerca de 20% (estimativa, confirmar como foi medido)."])
        self.assertEqual(r["promovidos"], 1)
        self.assertEqual(self.kb.fato(f"{SLUG_ATUAL}#6").status, "confirmado")

    def test_confirmar_e_remover(self):
        self.kb.confirmar(f"{SLUG_ATUAL}#6")
        self.assertEqual(self.kb.fato(f"{SLUG_ATUAL}#6").status, "confirmado")
        self.kb.remover(f"{SLUG_ATUAL}#6")
        self.assertIsNone(self.kb.fato(f"{SLUG_ATUAL}#6"))
        self.assertIn("Anotação solta", self.kb.ler_texto(SLUG_ATUAL))
        with self.assertRaises(ErroBase):
            self.kb.remover("nao-existe#1")

    def test_criar_experiencia(self):
        slug = self.kb.criar_experiencia({"empresa": "Café & Cia", "cargo": "Barista", "inicio": "2010-01", "fim": "2011-05"})
        self.assertEqual(slug, "cafe-cia-barista")
        slug2 = self.kb.criar_experiencia({"empresa": "Café & Cia", "cargo": "Barista", "inicio": "2012-01", "fim": "atual"})
        self.assertEqual(slug2, "cafe-cia-barista-2")
        self.kb.adicionar_fatos(slug, ["Preparava bebidas."])
        self.assertEqual(self.kb.fato(f"{slug}#1").texto, "Preparava bebidas.")

    def test_meta_invalida(self):
        for meta in ({"empresa": "", "cargo": "x", "inicio": "2020-01", "fim": "atual"},
                     {"empresa": "A", "cargo": "x", "inicio": "03/2020", "fim": "atual"},
                     {"empresa": "A", "cargo": "x", "inicio": "2020-13", "fim": "atual"},
                     {"empresa": "A", "cargo": "x", "inicio": "2020-05", "fim": "2020-01"},
                     {"empresa": "A", "cargo": "x", "inicio": "2020", "fim": "2019"}):
            with self.assertRaises(ErroBase):
                self.kb.criar_experiencia(meta)

    def test_data_so_com_ano_e_aceita(self):
        """Currículo real costuma ter só o ano. Exigir o mês obrigaria a pessoa a inventar um."""
        slug = self.kb.criar_experiencia({"empresa": "Transportadora", "cargo": "Assistente", "inicio": "2016",
                                          "fim": "2017"})
        self.kb.criar_experiencia({"empresa": "B", "cargo": "y", "inicio": "2016", "fim": "2016-05"})   # mesmo ano
        exp = next(a for a in self.kb.experiencias() if a.slug == slug)
        self.assertEqual((exp.meta["inicio"], exp.meta["fim"]), ("2016", "2017"))

    def test_frontmatter_invalido_vai_para_erros(self):
        p = self.kb.base / "experiencias" / "quebrada.md"
        p.write_text("---\nempresa: [aberta\n---\n- [confirmado] x\n", encoding="utf-8")
        slugs = [e.slug for e in self.kb.experiencias()]
        self.assertNotIn("quebrada", slugs)
        self.assertTrue(any("quebrada.md" in e for e in self.kb.erros))

    def test_salvar_texto_valida_frontmatter(self):
        original = self.kb.ler_texto(SLUG_ATUAL)
        with self.assertRaises(ErroBase):
            self.kb.salvar_texto(SLUG_ATUAL, "---\nempresa: X\n---\n- [confirmado] a")
        self.assertEqual(self.kb.ler_texto(SLUG_ATUAL), original)
        self.kb.salvar_texto(SLUG_ATUAL, original + "- [confirmado] Novo fato.\n")
        self.assertIn("Novo fato", self.kb.ler_texto(SLUG_ATUAL))

    def test_experiencia_oculta_fora_do_prompt_e_dos_ids(self):
        t = self.kb.ler_texto(SLUG_ESTAG).replace("---\n- [confirmado]", "ocultar: true\n---\n- [confirmado]", 1)
        self.kb.salvar_texto(SLUG_ESTAG, t)
        self.assertNotIn("Estagiária", self.kb.para_prompt())
        self.assertNotIn(f"{SLUG_ESTAG}#1", self.kb.ids_confirmados())

    def test_contato_e_segredos(self):
        self.assertEqual(self.kb.contato()["nome"], "Mariana Exemplo")
        self.assertIn("Mariana Exemplo", self.kb.segredos())
        self.kb.salvar_contato({"nome": "Outra", "email": "o@x.com"})
        self.assertEqual(self.kb.contato(), {"nome": "Outra", "email": "o@x.com"})

    def test_resumo_entrevista_inclui_pendentes_marcados(self):
        r = self.kb.resumo_entrevista()
        self.assertIn("(pendente)", r)
        self.assertIn("Estruturou o funil", r)

    def test_base_vazia(self):
        vazia = KB(self.tmp / "vazia")
        self.assertTrue(vazia.vazia())
        self.assertIn("vazia", vazia.resumo_entrevista())
        self.assertIn("ainda não tem fatos", vazia.para_prompt())


if __name__ == "__main__":
    unittest.main()


class TestLacunas(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_base_de_exemplo_so_falta_resultado_medido_nas_experiencias_sem_numero(self):
        tipos = {(l["tipo"], l["slug"] or l["rotulo"]) for l in self.kb.lacunas()}
        self.assertNotIn(("secao_vazia", "formacao"), tipos)
        # estagiária tem 2 fatos: poucos detalhes
        self.assertIn(("poucos_fatos", "loja-modelo-estagiaria-de-marketing"), tipos)

    def test_secoes_vazias_e_base_vazia(self):
        from src.kb import KB
        vazia = KB(self.tmp / "vazia")
        tipos = [l["tipo"] for l in vazia.lacunas()]
        self.assertIn("sem_experiencias", tipos)
        self.assertEqual(tipos.count("secao_vazia"), 4)

    def test_diagnostico_aponta_pendentes_e_secoes_vazias(self):
        self.assertTrue(any("a confirmar" in a for a in self.kb.diagnostico()))
        import os
        os.remove(self.kb.base / "formacao.md")
        self.assertTrue(any("formação" in a for a in self.kb.diagnostico()))

    def test_base_incompleta_de_importacao_perdida_e_detectada(self):
        """O caso do usuário: só duas experiências e nada de formação, habilidades, idiomas ou perfil."""
        from src.kb import KB
        kb = KB(self.tmp / "parcial")
        s1 = kb.criar_experiencia({"empresa": "A", "cargo": "X", "inicio": "2020-01", "fim": "atual"})
        kb.adicionar_fatos(s1, ["Fez algo com 10 pessoas.", "Fez outra coisa.", "E mais uma."])
        av = " ".join(kb.diagnostico())
        self.assertIn("formação", av)
        self.assertIn("menos de duas experiências", av)
