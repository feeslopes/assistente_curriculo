import json
import unittest
from pathlib import Path

from src import config, tailor
from src.kb import ErroBase
from src.llm import LLM, Configuracao
from tests.fakes import (RAIZ, SLUG_ASSIST, SLUG_ATUAL, SLUG_ESTAG, LLMFalso, SessaoFalsa, base_exemplo,
                         limpar, ok)
from tests.test_render import gerado_bom

VAGA_PT = (RAIZ / "exemplo" / "vagas" / "vaga_pt.txt").read_text(encoding="utf-8")
VAGA_EN = (RAIZ / "exemplo" / "vagas" / "vaga_en.txt").read_text(encoding="utf-8")


def analise_bruta():
    return {
        "titulo_vaga": "Analista de Marketing de Performance",
        "empresa": "Empresa Fictícia",
        "idioma_vaga": "pt",
        "palavras_chave": ["Google Ads", "Meta Ads", "Looker Studio", "SQL", "Google Analytics", "google ads"],
        "requisitos": [
            {"requisito": "Mídia paga no Google Ads e Meta Ads", "tipo": "obrigatorio", "termo_na_vaga": "Google Ads",
             "status": "coberto", "evidencias": ["habilidades#2", "id-falso#9"], "pergunta": ""},
            {"requisito": "Dashboards no Looker Studio", "tipo": "obrigatorio", "termo_na_vaga": "Looker Studio",
             "status": "coberto", "evidencias": ["id-falso#1"], "pergunta": "Você já criou dashboards? Em qual ferramenta?"},
            {"requisito": "SQL", "tipo": "desejavel", "termo_na_vaga": "SQL",
             "status": "parcial", "evidencias": ["habilidades#3"], "pergunta": "Para que você usa SQL?"},
            {"requisito": "Testes A/B", "tipo": "desejavel", "termo_na_vaga": "testes A/B",
             "status": "lacuna", "evidencias": [], "pergunta": "Já fez testes A/B?"},
        ],
        "observacoes": "",
    }


class TestTailor(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()
        self.cfg = config.carregar_config()

    def tearDown(self):
        limpar(self.tmp)

    def test_analise_rebaixa_coberto_sem_evidencia_e_descarta_ids_falsos(self):
        llm = LLMFalso(analise_bruta())
        a = tailor.analisar(llm, self.kb, VAGA_PT)
        r = {x["requisito"]: x for x in a["requisitos"]}
        self.assertEqual(r["Mídia paga no Google Ads e Meta Ads"]["status"], "coberto")
        self.assertEqual(r["Mídia paga no Google Ads e Meta Ads"]["evidencias"], ["habilidades#2"])
        self.assertEqual(r["Dashboards no Looker Studio"]["status"], "parcial")   # coberto sem evidência válida
        self.assertEqual(r["Dashboards no Looker Studio"]["evidencias"], [])
        self.assertEqual(a["palavras_chave"].count("Google Ads"), 1)
        self.assertEqual(len(a["palavras_chave"]), 5)  # "google ads" duplicado caiu

    def test_analise_recebe_so_confirmados(self):
        llm = LLMFalso(analise_bruta())
        tailor.analisar(llm, self.kb, VAGA_PT)
        user = llm.chamadas[0]["mensagens"][1]["content"]
        self.assertIn("[habilidades#2]", user)
        self.assertNotIn("Conhece HubSpot", user)
        self.assertTrue(llm.chamadas[0]["json_mode"])

    def test_analise_base_vazia_ou_vaga_vazia(self):
        from src.kb import KB
        with self.assertRaises(ErroBase):
            tailor.analisar(LLMFalso(), KB(self.tmp / "vazia"), VAGA_PT)
        with self.assertRaises(ErroBase):
            tailor.analisar(LLMFalso(), self.kb, "   ")

    def test_perguntas_de_lacuna(self):
        a = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())
        perguntas = [p["requisito"] for p in tailor.perguntas_lacuna(a)]
        self.assertEqual(perguntas, ["Dashboards no Looker Studio", "Testes A/B", "SQL"])  # obrigatórios primeiro

    def test_recomendar_idioma(self):
        self.assertEqual(tailor.recomendar_idioma(VAGA_PT, None, self.cfg), "pt")
        self.assertEqual(tailor.recomendar_idioma(VAGA_EN, None, self.cfg), "en")
        self.assertEqual(tailor.recomendar_idioma("SQL", {"idioma_vaga": "en"}, self.cfg), "en")
        self.assertEqual(tailor.recomendar_idioma("SQL", {"idioma_vaga": "es"}, self.cfg), "pt")

    def test_ponta_a_ponta_com_llm_falso(self):
        gerado = gerado_bom()
        gerado["experiencias"][0]["bullets"].append(
            {"texto": "Criou dashboards no Looker Studio para a diretoria.", "fontes": []})
        llm = LLMFalso(analise_bruta(), gerado)
        analise = tailor.analisar(llm, self.kb, VAGA_PT)
        res = tailor.gerar(llm, self.kb, VAGA_PT, analise, "pt", self.cfg, verificar_ia=False)
        md = res.curriculo.markdown
        self.assertNotIn("Looker Studio para a diretoria", md)            # lacuna não vira texto
        self.assertTrue(any("Looker" in a for a in res.curriculo.alertas))
        self.assertIn("Google Ads", res.cobertura["usadas"])
        self.assertIn("Looker Studio", res.cobertura["fora_sem_base"])
        self.assertIn("SQL", res.cobertura["fora_com_base"])
        sistema = llm.chamadas[1]["mensagens"][0]["content"]
        self.assertIn("Guidelines de escrita", sistema)
        self.assertIn(f"{SLUG_ATUAL}=5", sistema)
        self.assertIn(f"{SLUG_ESTAG}=3", sistema)
        usuario = llm.chamadas[1]["mensagens"][1]["content"]
        self.assertIn("Português do Brasil", usuario)
        self.assertNotIn("Conhece HubSpot", usuario)

    def test_titulo_do_usuario_vai_ao_prompt_e_ao_curriculo(self):
        llm = LLMFalso(gerado_bom())
        analise = tailor.validar_analise(analise_bruta(), self.kb.ids_confirmados())
        res = tailor.gerar(llm, self.kb, VAGA_EN, analise, "en", self.cfg, titulo_usuario="Growth Specialist", verificar_ia=False)
        self.assertIn("Growth Specialist", llm.chamadas[0]["mensagens"][1]["content"])
        self.assertEqual(res.curriculo.titulo, "Growth Specialist")

    def test_respostas_de_lacuna_passam_pelo_extrator(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {},
                                   "fatos": [{"texto": "Criou dashboards no Looker Studio para acompanhar campanhas.", "origem": "dito"}]}]}
        llm = LLMFalso(proposta)
        props = tailor.extrair_respostas(llm, self.kb, [
            ("Já criou dashboards?", "Sim, no Looker Studio, para acompanhar campanhas.", False),
            ("Já fez testes A/B?", "", True),
            ("Usa SQL?", "não tenho", True)])
        self.assertEqual(len(props), 1)
        msg = llm.chamadas[0]["mensagens"][1]["content"]
        self.assertIn("respostas", msg)
        self.assertNotIn("testes A/B", msg)
        self.assertEqual(tailor.extrair_respostas(LLMFalso(), self.kb, [("p", "", True)]), [])

    def test_contato_nunca_chega_na_api(self):
        """Fim a fim pela camada HTTP: nada de contato no payload, mesmo se estiver em um fato."""
        self.kb.adicionar_fatos("perfil", ["Pode ser contatada em outra@pessoa.com ou pelo +55 21 98888-7777."])
        sessao = SessaoFalsa(ok(json.dumps(analise_bruta())), ok(json.dumps(gerado_bom())))
        llm = LLM(Configuracao("gemini", "k", "m", "https://x.test", {}), sessao=sessao,
                  dormir=lambda s: None, segredos=self.kb.segredos())
        analise = tailor.analisar(llm, self.kb, VAGA_PT + "\nEnvie para vagas@empresa.com")
        tailor.gerar(llm, self.kb, VAGA_PT, analise, "pt", self.cfg, verificar_ia=False)
        tudo = json.dumps([p["json"] for p in sessao.posts], ensure_ascii=False)
        for sensivel in ("mariana.exemplo@example.com", "outra@pessoa.com", "vagas@empresa.com",
                         "90000-0000", "98888-7777", "linkedin.com/in/mariana", "Mariana"):
            self.assertNotIn(sensivel, tudo)


if __name__ == "__main__":
    unittest.main()
