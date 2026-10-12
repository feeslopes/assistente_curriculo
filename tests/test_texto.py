import unittest

from src import texto


class TestTexto(unittest.TestCase):
    def test_idioma(self):
        pt = ("Estamos buscando uma pessoa para atuar com a nossa equipe de marketing, com experiência "
              "em mídia paga e conhecimento de análise de dados.")
        en = ("We are looking for someone to join our team with experience in paid media and "
              "knowledge of data analysis for the company.")
        self.assertEqual(texto.detectar_idioma(pt), "pt")
        self.assertEqual(texto.detectar_idioma(en), "en")
        self.assertIsNone(texto.detectar_idioma("SQL Python"))

    def test_json_com_cerca_e_virgula(self):
        bruto = 'Claro!\n```json\n{"a": [1, 2,], "b": "x",}\n```\nFim.'
        self.assertEqual(texto.extrair_json(bruto), {"a": [1, 2], "b": "x"})

    def test_json_com_texto_em_volta_e_think(self):
        self.assertEqual(texto.extrair_json('<think>{"x":1}</think> Aqui: {"ok": true} obrigado'), {"ok": True})

    def test_json_invalido(self):
        with self.assertRaises(ValueError):
            texto.extrair_json("sem json nenhum")

    def test_mascara_contato(self):
        t = ("Fale comigo: ana@exemplo.com, +55 11 90000-0000, (11) 98888-7777, 11 97777-6666, "
             "linkedin.com/in/ana e https://ana.dev/portfolio")
        m = texto.mascarar_contato(t)
        for sensivel in ("ana@", "90000", "98888", "97777", "linkedin.com", "ana.dev"):
            self.assertNotIn(sensivel, m)

    def test_mascara_preserva_anos_e_numeros(self):
        for t in ("Cursou de 2016 2021", "Entre 2016-2021 na empresa", "Atendeu 2.000 clientes",
                  "Gerou R$ 80 mil", "Cresceu 18% em 2022", "Base de 40 mil clientes"):
            self.assertEqual(texto.mascarar_contato(t), t)

    def test_slugify(self):
        self.assertEqual(texto.slugify("Empresa São João & Cia"), "empresa-sao-joao-cia")

    def test_contato_local(self):
        c = texto.extrair_contato_local("Ana\nana@x.com\n+55 11 90000-0000\nlinkedin.com/in/ana-silva")
        self.assertEqual(c["email"], "ana@x.com")
        self.assertIn("90000", c["telefone"])
        self.assertEqual(c["linkedin"], "linkedin.com/in/ana-silva")

    def test_ler_txt(self):
        self.assertEqual(texto.ler_arquivo("a.txt", "Olá ção".encode("utf-8")), "Olá ção")
        self.assertEqual(texto.ler_arquivo("a.txt", "Olá ção".encode("cp1252")), "Olá ção")


if __name__ == "__main__":
    unittest.main()


class TestMesCitado(unittest.TestCase):
    def test_formatos(self):
        t = ("Serasa Experian, Julho 2025 - Presente. ClearSale: junho de 2023 a 06/2025. "
             "Beta: Apr 2021 until 2022-02. Marketing 2019.")
        for ok in ("2025-07", "2023-06", "2025-06", "2021-04", "2022-02"):
            self.assertTrue(texto.mes_citado(t, ok), ok)
        for nao in ("2025-01", "2019-03", "2021-05"):
            self.assertFalse(texto.mes_citado(t, nao), nao)   # "Marketing 2019" não é março

    def test_so_o_ano_nao_basta(self):
        self.assertFalse(texto.mes_citado("Sou analista desde 2022 na Empresa Teste.", "2022-01"))
