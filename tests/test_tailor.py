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
        self.assertIn(f"{SLUG_ATUAL}: 5", sistema)
        self.assertIn(f"{SLUG_ESTAG}: 3", sistema)
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


class TestLimitesPorExperiencia(unittest.TestCase):
    """Experiências antigas ficam resumidas; a vaga pode torná-las relevantes; dá para ajustar à mão."""

    def setUp(self):
        from src.kb import KB
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.kb = KB(self.tmp / "base")
        self.cfg = config.carregar_config()
        # do mais recente para o mais antigo: atual, 2019-2021 (já com mais de 10 anos? não), 2005-2008, 2000-2003
        self.s = {}
        for chave, (emp, ini, fim) in {"atual": ("Atual SA", "2023-01", "atual"), "meio": ("Meio SA", "2019-01", "2022-12"),
                                      "velha": ("Velha SA", "2005-01", "2008-12"), "velhissima": ("Antiga SA", "2000-01", "2003-12")}.items():
            self.s[chave] = self.kb.criar_experiencia({"empresa": emp, "cargo": "Analista", "inicio": ini, "fim": fim})
            self.kb.adicionar_fatos(self.s[chave], [f"Fez a coisa 1 em {emp}.", f"Fez a coisa 2 em {emp}.", f"Fez a coisa 3 em {emp}."])

    def tearDown(self):
        limpar(self.tmp)

    def lim(self, analise=None, hoje=None):
        from datetime import date
        return tailor.limites_por_experiencia(self.kb, self.cfg, analise, hoje or date(2026, 10, 13))

    def analise(self, *evidencias, tipo="obrigatorio", status="coberto"):
        return {"requisitos": [{"requisito": "x", "tipo": tipo, "status": status, "evidencias": list(evidencias)}]}

    def test_recentes_seguem_a_posicao_e_antigas_irrelevantes_encolhem(self):
        r = {k: self.lim()[v]["limite"] for k, v in self.s.items()}
        self.assertEqual(r["atual"], 5)
        self.assertEqual(r["meio"], 4)
        self.assertEqual(r["velha"], 1)        # terminou há 17 anos e a vaga não a usa
        self.assertEqual(r["velhissima"], 1)   # base 2, teto de antigas 1
        self.assertIn("resumida", self.lim()[self.s["velha"]]["motivo"])

    def test_vaga_que_torna_a_antiga_relevante_devolve_espaco(self):
        a = self.analise(f"{self.s['velha']}#1")       # requisito obrigatório coberto por esta experiência
        r = self.lim(a)
        self.assertEqual(r[self.s["velha"]]["limite"], 3)
        self.assertIn("relevante", r[self.s["velha"]]["motivo"])
        self.assertEqual(r[self.s["velhissima"]]["limite"], 1)    # a outra continua resumida

    def test_relevancia_exige_peso_dois(self):
        # um requisito desejável (peso 1) não basta; dois desejáveis (peso 2) bastam
        um = self.analise(f"{self.s['velha']}#1", tipo="desejavel")
        self.assertEqual(self.lim(um)[self.s["velha"]]["limite"], 1)
        dois = {"requisitos": um["requisitos"] * 2}
        self.assertEqual(self.lim(dois)[self.s["velha"]]["limite"], 3)

    def test_requisito_lacuna_nao_conta_como_relevancia(self):
        a = self.analise(f"{self.s['velha']}#1", status="lacuna")
        self.assertEqual(self.lim(a)[self.s["velha"]]["limite"], 1)

    def test_recente_relevante_ganha_um_a_mais_ate_o_topo(self):
        a = self.analise(f"{self.s['meio']}#1")
        r = self.lim(a)
        self.assertEqual(r[self.s["meio"]]["limite"], 5)          # 4 + 1, não passa do limite da mais recente
        self.assertEqual(r[self.s["atual"]]["limite"], 5)

    def test_regra_pode_ser_desligada_ou_ajustada(self):
        self.cfg["experiencias_antigas"] = {"ativo": False}
        self.assertEqual(self.lim()[self.s["velha"]]["limite"], 3)             # volta ao limite por posição
        self.cfg["experiencias_antigas"] = {"ativo": True, "anos": 10, "max_bullets": 0}
        self.assertEqual(self.lim()[self.s["velha"]]["limite"], 0)             # só cabeçalho
        self.cfg["experiencias_antigas"] = {"ativo": True, "anos": 25, "max_bullets": 0}
        self.assertEqual(self.lim()[self.s["velha"]]["limite"], 3)             # ainda não é "antiga"

    def test_gerar_usa_os_limites_no_prompt_e_no_curriculo(self):
        gerado = {"experiencias": [
            {"id": self.s["atual"], "bullets": [{"texto": "Fez a coisa 1 em Atual SA.", "fontes": [f"{self.s['atual']}#1"]}]},
            {"id": self.s["velha"], "bullets": [
                {"texto": "Fez a coisa 1 em Velha SA.", "fontes": [f"{self.s['velha']}#1"]},
                {"texto": "Fez a coisa 2 em Velha SA.", "fontes": [f"{self.s['velha']}#2"]}]}]}
        llm = LLMFalso(gerado)
        analise = tailor.validar_analise({"palavras_chave": [], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(llm, self.kb, "Vaga", analise, "pt", self.cfg, verificar_ia=False)
        sistema = llm.chamadas[0]["mensagens"][0]["content"]
        self.assertIn(f"{self.s['velha']}: 1 (", sistema)
        self.assertIn("RESUMO", sistema)
        self.assertEqual(res.limites[self.s["velha"]]["limite"], 1)
        md = res.curriculo.markdown
        self.assertIn("Fez a coisa 1 em Velha SA.", md)
        self.assertNotIn("Fez a coisa 2 em Velha SA.", md)         # cortado pelo limite 1
        self.assertTrue(any("cortado" in a for a in res.curriculo.alertas))

    def test_limite_zero_mostra_so_cabecalho_sem_alerta_de_buraco(self):
        gerado = {"experiencias": [
            {"id": self.s["atual"], "bullets": [{"texto": "Fez a coisa 1 em Atual SA.", "fontes": [f"{self.s['atual']}#1"]}]},
            {"id": self.s["velha"], "bullets": [{"texto": "Fez a coisa 1 em Velha SA.", "fontes": [f"{self.s['velha']}#1"]}]}]}
        analise = tailor.validar_analise({"palavras_chave": [], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(LLMFalso(gerado), self.kb, "Vaga", analise, "pt", self.cfg, verificar_ia=False,
                           limites_manuais={self.s["velha"]: 0})
        md = res.curriculo.markdown
        self.assertIn("**Velha SA**", md)
        self.assertIn("_Analista · Janeiro 2005 – Dezembro 2008", md)       # cargo e datas continuam
        self.assertNotIn("Fez a coisa 1 em Velha SA.", md)
        self.assertFalse(any("Velha SA" in a and "buraco" in a for a in res.curriculo.alertas))   # limite 0 é escolha
        self.assertTrue(any("Meio SA" in a and "buraco" in a for a in res.curriculo.alertas))     # omissão do modelo ainda avisa
        self.assertEqual(res.limites[self.s["velha"]]["motivo"], "ajustado por você")

    def test_ajuste_manual_pode_aumentar_o_espaco(self):
        gerado = {"experiencias": [{"id": self.s["velha"], "bullets": [
            {"texto": f"Fez a coisa {n} em Velha SA.", "fontes": [f"{self.s['velha']}#{n}"]} for n in (1, 2, 3)]}]}
        analise = tailor.validar_analise({"palavras_chave": [], "requisitos": []}, self.kb.ids_confirmados())
        res = tailor.gerar(LLMFalso(gerado), self.kb, "Vaga", analise, "pt", self.cfg, verificar_ia=False,
                           limites_manuais={self.s["velha"]: 3})
        self.assertEqual(res.curriculo.markdown.count("em Velha SA."), 3)

    def test_inicio_de_carreira_resume_as_mais_antigas_quando_ha_historico(self):
        # histórico com 6 experiências, todas recentes (nenhuma passa de 10 anos): as 2 mais antigas encolhem
        from src.kb import KB
        kb = KB(self.tmp / "longa")
        slugs = []
        for i, (ini, fim) in enumerate([("2024-01", "atual"), ("2022-01", "2023-12"), ("2020-01", "2021-12"),
                                        ("2018-01", "2019-12"), ("2016-01", "2017-12"), ("2014-01", "2015-12")]):
            sl = kb.criar_experiencia({"empresa": f"E{i}", "cargo": "Analista", "inicio": ini, "fim": fim})
            kb.adicionar_fatos(sl, ["a", "b", "c"])
            slugs.append(sl)
        from datetime import date
        r = tailor.limites_por_experiencia(kb, self.cfg, None, date(2026, 10, 13))
        self.assertEqual([r[s]["limite"] for s in slugs], [5, 4, 3, 2, 1, 1])   # só as 2 mais antigas encolhem
        self.assertIn("início de carreira", r[slugs[-2]]["motivo"])        # terminou há 9 anos: só o critério de carreira vale
        self.assertIn("terminou há 11 anos", r[slugs[-1]]["motivo"])        # esta passa dos 10 anos
        self.assertEqual(r[slugs[2]]["limite"], 3)                  # as 3 recentes mais antigas continuam completas

    def test_inicio_de_carreira_nao_age_em_historico_curto_nem_quando_a_vaga_o_valoriza(self):
        from src.kb import KB
        from datetime import date
        kb = KB(self.tmp / "curta")
        for i in range(4):
            sl = kb.criar_experiencia({"empresa": f"C{i}", "cargo": "A", "inicio": f"{2024 - 2 * i}-01",
                                       "fim": "atual" if i == 0 else f"{2025 - 2 * i}-12"})
            kb.adicionar_fatos(sl, ["a", "b", "c"])
        r = tailor.limites_por_experiencia(kb, self.cfg, None, date(2026, 10, 13))
        self.assertEqual([v["limite"] for v in r.values()], [5, 4, 3, 2])      # 4 - 2 < 3: ninguém encolhe
        # com histórico longo, a vaga que pede a experiência antiga a devolve
        kb2 = KB(self.tmp / "longa2")
        slugs = []
        for i in range(6):
            sl = kb2.criar_experiencia({"empresa": f"L{i}", "cargo": "A", "inicio": f"{2024 - 2 * i}-01",
                                        "fim": "atual" if i == 0 else f"{2025 - 2 * i}-12"})
            kb2.adicionar_fatos(sl, ["a", "b", "c"])
            slugs.append(sl)
        a = self.analise(f"{slugs[-1]}#1")
        r2 = tailor.limites_por_experiencia(kb2, self.cfg, a, date(2026, 10, 13))
        self.assertEqual(r2[slugs[-1]]["limite"], 3)
        self.assertEqual(r2[slugs[-2]]["limite"], 1)
