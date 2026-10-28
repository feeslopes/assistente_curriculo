"""Entradas hostis: arquivos enviados e caminhos que podem vir da saída da IA."""
import io
import unittest
import zipfile

from src import texto
from src.kb import ErroBase
from tests.fakes import base_exemplo, limpar


class TestUploads(unittest.TestCase):
    def test_arquivo_grande_demais(self):
        with self.assertRaises(texto.ErroArquivo) as e:
            texto.ler_arquivo("cv.txt", b"a" * (texto.MAX_BYTES_ARQUIVO + 1))
        self.assertIn("MB", str(e.exception))

    def test_pdf_corrompido_vira_mensagem_simples(self):
        with self.assertRaises(texto.ErroArquivo) as e:
            texto.ler_arquivo("cv.pdf", b"%PDF-1.4 isto nao e um pdf de verdade")
        self.assertNotIn("Traceback", str(e.exception))
        self.assertNotIn("pypdf", str(e.exception).lower())

    def test_docx_corrompido(self):
        with self.assertRaises(texto.ErroArquivo):
            texto.ler_arquivo("cv.docx", b"nao sou um zip")

    def test_docx_com_zip_bomb_e_recusado_sem_descomprimir(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"0" * (texto.MAX_DOCX_DESCOMPRIMIDO + 1024))   # comprime para quase nada
        dados = buf.getvalue()
        self.assertLess(len(dados), texto.MAX_BYTES_ARQUIVO)
        with self.assertRaises(texto.ErroArquivo) as e:
            texto.ler_arquivo("cv.docx", dados)
        self.assertIn("grande demais", str(e.exception))

    def test_texto_comum_continua_funcionando(self):
        self.assertEqual(texto.ler_arquivo("v.txt", "Vaga de analista".encode()), "Vaga de analista")
        self.assertEqual(texto.ler_arquivo("v.md", "Olá".encode("cp1252")), "Olá")


class TestCaminhos(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_slug_com_traversal_nao_vira_caminho(self):
        for slug in ("../perfil", "..", "../../x", "a/b", "a\\b", "", "A", "x" * 200, "perfil/../../x"):
            self.assertIsNone(self.kb._caminho(slug), slug)
        self.assertIsNotNone(self.kb._caminho("perfil"))

    def test_experiencia_legitima_continua_acessivel(self):
        slug = self.kb.experiencias()[0].slug
        self.assertIsNotNone(self.kb._caminho(slug))

    def test_destino_malicioso_da_ia_nao_escreve_fora_da_base(self):
        fora = self.tmp / "fora.md"
        with self.assertRaises(ErroBase):
            self.kb.adicionar_fatos("../../fora", ["- fato qualquer"], "confirmado")
        self.assertFalse(fora.exists())
        self.assertFalse(list(self.tmp.rglob("fora*")))

    def test_proposta_da_ia_com_destino_estranho_e_descartada(self):
        from src.interview import validar_propostas
        bruto = {"propostas": [
            {"destino": "../../fora", "meta": {}, "fatos": [{"texto": "Fato inventado pela IA", "origem": "dito"}]},
            {"destino": "..\fora", "meta": {}, "fatos": [{"texto": "Outro fato", "origem": "dito"}]},
            {"destino": "habilidades", "meta": {}, "fatos": [{"texto": "Usa Power BI em relatórios semanais", "origem": "dito"}]}]}
        propostas = validar_propostas(bruto, self.kb)
        self.assertEqual([p.destino for p in propostas], ["habilidades"])


if __name__ == "__main__":
    unittest.main()
