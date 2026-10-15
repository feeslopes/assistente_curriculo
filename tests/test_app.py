"""Teste de fumaça do app.py com streamlit falso. Pega erro de import, de nome e de desempacotamento."""
import importlib
import json
import os
import sys
import unittest
from unittest import mock

from tests import streamlit_stub as stub
from tests.fakes import RAIZ, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta

VAGA_PT = (RAIZ / "exemplo" / "vagas" / "vaga_pt.txt").read_text(encoding="utf-8")
ENV_COM_CHAVE = {"PROVEDOR": "deepseek", "DEEPSEEK_API_KEY": "chave-de-teste", "MODELO": "m"}


class TestApp(unittest.TestCase):
    def setUp(self):
        self.st = stub.FakeStreamlit()
        self.patch_mod = mock.patch.dict(sys.modules, {"streamlit": self.st})
        self.patch_mod.start()
        sys.modules.pop("app", None)
        self.app = importlib.import_module("app")
        self.kb, self.tmp = base_exemplo()
        self.env = mock.patch.dict(os.environ, {**ENV_COM_CHAVE, "CV_BASE_DIR": str(self.kb.base)}, clear=False)
        self.env.start()
        self.sem_env = mock.patch.object(self.app.config, "carregar_env", lambda: None)
        self.sem_env.start()
        # nunca ler nem gravar a pasta saidas/ real do projeto (tem logs do uso de verdade)
        self.saidas = mock.patch.object(self.app.config, "saidas_dir", lambda: self.tmp / "saidas")
        self.saidas.start()

    def tearDown(self):
        self.saidas.stop()
        self.sem_env.stop()
        self.env.stop()
        self.patch_mod.stop()
        sys.modules.pop("app", None)
        limpar(self.tmp)

    def rodar(self):
        """Uma execução do script. st.rerun() interrompe, como no Streamlit de verdade."""
        try:
            self.app.main()
        except stub.Parar:
            pass

    def usar_llm(self, *respostas):
        llm = LLMFalso(*respostas)
        p = mock.patch.object(self.app, "obter_llm", lambda kb: llm)
        p.start()
        self.addCleanup(p.stop)
        return llm

    def textos(self, nome):
        return " ".join(str(c[1][0]) for c in self.st.chamadas if c[0] == nome and c[1])

    # ------------------------------------------------------------------ casos
    def test_tela_inicial_com_base_de_exemplo(self):
        self.rodar()
        self.assertEqual(self.st.session_state["rev_id"], 0)

    def test_sem_chave_mostra_configuracao_e_aba_base_continua(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "PROVEDOR": "deepseek"}):
            self.rodar()
        self.assertIn("ainda não está ligado", self.textos("warning"))

    def test_base_vazia(self):
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "vazia")}):
            self.rodar()
            self.assertIn("ainda não tem fatos confirmados", self.textos("info"))

    def test_copiar_exemplo_so_se_vazia(self):
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "nova")}):
            self.st.cliques = {"btn_exemplo"}
            self.rodar()
            self.assertTrue((self.tmp / "nova" / "contato.yaml").exists())
            self.rodar()  # segundo clique: base já tem dados
        self.st.cliques = {"btn_exemplo"}
        self.rodar()
        self.assertIn("já tem dados", json.dumps(self.st.session_state.get("msg") or "", ensure_ascii=False))

    def test_fluxo_analisar_e_gerar(self):
        llm = self.usar_llm(analise_bruta(), gerado_bom(), {"problemas": [], "palavras": []})
        self.st.valores["vaga_texto"] = VAGA_PT
        self.st.cliques = {"btn_analisar"}
        self.rodar()
        self.assertIsNotNone(self.st.session_state["analise"])
        self.st.cliques = {"btn_gerar"}
        self.rodar()
        res = self.st.session_state["resultado"]
        self.assertIsNotNone(res)
        self.assertIn("Mariana Exemplo", self.st.session_state[f"md_{self.st.session_state['gen_id']}"])
        self.st.cliques = set()
        self.rodar()   # mostra resultado, alertas, cobertura e botões de download
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertEqual(nomes[-3:], ["Baixar PDF", "Baixar DOCX", "Baixar Markdown"])
        self.assertEqual(len(llm.chamadas), 3)

    def test_salvar_saida(self):
        self.usar_llm(analise_bruta(), gerado_bom(), {"problemas": [], "palavras": []})
        self.st.valores["vaga_texto"] = VAGA_PT
        self.st.cliques = {"btn_analisar"}
        self.rodar()
        self.st.cliques = {"btn_gerar"}
        self.rodar()
        with mock.patch.object(self.app.config, "saidas_dir", lambda: self.tmp / "saidas"):
            self.st.cliques = {"btn_salvar_saida"}
            self.rodar()
        pastas = list((self.tmp / "saidas").iterdir())
        self.assertEqual(len(pastas), 1)
        self.assertTrue(all((pastas[0] / f).exists() for f in ("curriculo.pdf", "curriculo.docx", "curriculo.md",
                                                                 "vaga.txt", "analise.json")))

    def test_indice_aparece_no_resultado_e_o_historico_lista_a_vaga_salva(self):
        self.usar_llm(analise_bruta(), gerado_bom(), {"problemas": [], "palavras": []})
        self.st.valores["vaga_texto"] = VAGA_PT
        self.st.cliques = {"btn_analisar"}
        self.rodar()
        self.st.cliques = {"btn_gerar"}
        self.rodar()
        self.st.cliques = set()
        self.rodar()
        self.assertIn("Índice de aderência à vaga", self.textos("markdown"))
        metricas = {c[1][0]: c[1][1] for c in self.st.chamadas if c[0] == "metric"}
        self.assertIn("Teto com a sua base atual", metricas)
        self.assertIn("inventar", self.textos("info"))      # o aviso de que o índice não sobe por inventar
        self.st.cliques = {"btn_salvar_saida"}
        self.rodar()
        pasta = next((self.tmp / "saidas").iterdir())
        indice = json.loads((pasta / "indice.json").read_text(encoding="utf-8"))
        self.assertTrue(0 <= indice["depois"] <= 100 and indice["teto"] >= indice["depois"])
        self.st.cliques = set()
        self.st.chamadas.clear()
        self.rodar()
        self.assertIn("Vagas salvas", self.textos("markdown"))
        self.assertTrue(any(c[0] == "dataframe" and len(c[1][0]) == 1 for c in self.st.chamadas))

    def test_historico_vazio_orienta_a_salvar(self):
        self.rodar()
        self.assertIn("Salvar na pasta de saídas", self.textos("info"))

    def test_chat_e_encerrar_rodada(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {},
                                   "fatos": [{"texto": "Usa Notion para documentar processos.", "origem": "dito"}]}]}
        self.usar_llm("Qual foi o resultado?", proposta)
        self.st.chat = ["Trabalho com marketing"]
        self.rodar()
        self.assertEqual([m["role"] for m in self.st.session_state["chat"]], ["user", "assistant"])
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.assertEqual(len(self.st.session_state["rev_entrevista"]), 1)
        # revisão: marca e salva
        self.st.cliques = {"Salvar marcados como confirmados"}
        self.rodar()
        textos = [f.texto for f in self.kb.fatos("confirmado")]
        self.assertIn("Usa Notion para documentar processos.", textos)
        self.assertIsNone(self.st.session_state["rev_entrevista"])

    def test_revisao_nao_marcado_nao_entra(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {}, "fatos": [
            {"texto": "Fato dito.", "origem": "dito"}, {"texto": "Fato inferido pela IA.", "origem": "sugerido"}]}]}
        self.usar_llm("ok", proposta)
        self.st.chat = ["oi"]
        self.rodar()
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.st.cliques = {"Salvar marcados como confirmados"}
        self.rodar()
        textos = [f.texto for f in self.kb.fatos()]
        self.assertIn("Fato dito.", textos)
        self.assertNotIn("Fato inferido pela IA.", textos)

    def test_importar_curriculo(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {},
                                   "fatos": [{"texto": "Domina Excel avançado.", "origem": "dito"}]}]}
        self.usar_llm(proposta)
        cv = ("Ana Souza\nAnalista\nana@exemplo.com | +55 11 98888-7777\n" + "Trabalhou com análise de dados e relatórios. " * 5)
        kb2_dir = self.tmp / "outra"
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(kb2_dir)}):
            self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv.txt", cv.encode("utf-8"))
            self.st.cliques = {"btn_importar"}
            self.rodar()
        from src.kb import KB
        contato = KB(kb2_dir).contato()
        self.assertEqual(contato["email"], "ana@exemplo.com")
        self.assertEqual(contato["nome"], "Ana Souza")
        self.assertEqual(len(self.st.session_state["rev_importacao"]), 1)

    def test_importacao_nao_some_quando_a_conversa_encerra_a_rodada(self):
        """Bug real: a revisão do CV importado era substituída pela revisão da conversa."""
        imp = {"propostas": [{"destino": "habilidades", "meta": {},
                              "fatos": [{"texto": "Domina Excel avançado.", "origem": "dito"}]}]}
        conv = {"propostas": [{"destino": "habilidades", "meta": {},
                               "fatos": [{"texto": "Usa Notion para documentar.", "origem": "dito"}]}]}
        llm = self.usar_llm(imp, "Qual foi o resultado?", conv)
        cv = "Ana Souza\nAnalista\n" + "Trabalhou com análise de dados e relatórios. " * 5
        self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv.txt", cv.encode("utf-8"))
        self.st.cliques = {"btn_importar"}
        self.rodar()
        self.assertEqual(len(self.st.session_state["rev_importacao"]), 1)
        self.st.cliques = set()
        self.st.chat = ["Trabalho com marketing"]
        self.rodar()
        # o entrevistador soube do que está aguardando revisão e não vai perguntar de novo
        sistema = llm.chamadas[1]["mensagens"][0]["content"]
        self.assertIn("aguardando a revisão", sistema)
        self.assertIn("Domina Excel avançado.", sistema)
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.assertEqual(len(self.st.session_state["rev_importacao"]), 1)    # continua lá
        self.assertEqual(len(self.st.session_state["rev_entrevista"]), 1)    # e a da conversa é outra
        self.st.cliques = {"Salvar marcados como confirmados"}
        self.rodar()
        textos = [f.texto for f in self.kb.fatos("confirmado")]
        self.assertIn("Domina Excel avançado.", textos)

    def test_encerrar_bloqueado_enquanto_ha_revisao_da_conversa_pendente(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {},
                                   "fatos": [{"texto": "Fato novo.", "origem": "dito"}]}]}
        llm = self.usar_llm("ok", proposta)
        self.st.chat = ["oi"]
        self.rodar()
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.st.cliques = {"btn_encerrar"}   # segundo clique: o botão está desabilitado
        self.rodar()
        self.assertEqual(len(llm.chamadas), 2)

    def test_descartar_revisao(self):
        self.usar_llm("ok", {"propostas": [{"destino": "habilidades", "meta": {},
                                            "fatos": [{"texto": "Fato novo.", "origem": "dito"}]}]})
        self.st.chat = ["oi"]
        self.rodar()
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.st.cliques = {"btn_descartar_ent"}
        self.rodar()
        self.assertIsNone(self.st.session_state["rev_entrevista"])
        self.assertNotIn("Fato novo.", [f.texto for f in self.kb.fatos()])

    def test_aba_vaga_avisa_base_incompleta_e_revisao_nao_salva(self):
        from src.interview import FatoProposto, Proposta
        self.st.session_state["rev_importacao"] = [Proposta("habilidades", [FatoProposto("Fato.", "dito")])]
        self.rodar()
        avisos = self.textos("warning")
        self.assertIn("aguardando a sua revisão", avisos)
        self.assertIn("pendente", avisos)     # a base de exemplo tem 2 fatos [sugerido]

    def reiniciar(self):
        """Simula fechar e abrir o aplicativo: memória nova, mesma pasta de base."""
        self.st = stub.FakeStreamlit()
        sys.modules["streamlit"] = self.st
        sys.modules.pop("app", None)
        self.app = importlib.import_module("app")

    def test_conversa_e_revisoes_sobrevivem_a_fechar_o_aplicativo(self):
        proposta = {"propostas": [{"destino": "habilidades", "meta": {},
                                   "fatos": [{"texto": "Usa Notion para documentar.", "origem": "dito"}]}]}
        self.usar_llm("Qual foi o resultado?", proposta)
        self.st.chat = ["Trabalho com marketing"]
        self.rodar()
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        antes = self.st.session_state["chat"]
        self.assertTrue(self.st.session_state["rev_entrevista"])
        # fecha e abre de novo
        self.reiniciar()
        self.rodar()
        self.assertEqual(self.st.session_state["chat"], antes)
        self.assertEqual(self.st.session_state["rev_entrevista"][0].fatos[0].texto, "Usa Notion para documentar.")
        self.assertEqual(self.st.session_state["msg"][0] if self.st.session_state["msg"] else "info", "info")
        self.assertIn("Recuperei", " ".join(str(c[1][0]) for c in self.st.chamadas if c[0] == "info"))
        # e a revisão recuperada ainda pode ser salva
        self.st.cliques = {"Salvar marcados como confirmados"}
        self.rodar()
        self.assertIn("Usa Notion para documentar.", [f.texto for f in self.kb.fatos("confirmado")])
        # depois de salvar não sobra nada para recuperar
        self.assertFalse((self.kb.base / ".sessao" / "sessao.json").exists())

    def test_importacao_nao_salva_sobrevive_a_reiniciar(self):
        imp = {"propostas": [{"destino": "habilidades", "meta": {},
                              "fatos": [{"texto": "Domina Excel avançado.", "origem": "dito"}]}]}
        self.usar_llm(imp)
        cv = "Ana Souza\nAnalista\n" + "Trabalhou com análise de dados e relatórios. " * 5
        self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv.txt", cv.encode("utf-8"))
        self.st.cliques = {"btn_importar"}
        self.rodar()
        self.reiniciar()
        self.rodar()
        self.assertEqual(self.st.session_state["rev_importacao"][0].fatos[0].texto, "Domina Excel avançado.")

    def test_conversa_nova_apaga_so_a_conversa(self):
        self.usar_llm("ok", {"propostas": [{"destino": "habilidades", "meta": {},
                                            "fatos": [{"texto": "Fato novo.", "origem": "dito"}]}]})
        self.st.chat = ["oi"]
        self.rodar()
        self.st.cliques = {"btn_encerrar"}
        self.rodar()
        self.st.cliques = {"btn_nova_conversa"}
        self.rodar()
        self.assertEqual(self.st.session_state["chat"], [])
        self.assertTrue(self.st.session_state["rev_entrevista"])      # a revisão fica
        self.reiniciar()
        self.rodar()
        self.assertEqual(self.st.session_state["chat"], [])
        self.assertTrue(self.st.session_state["rev_entrevista"])

    def test_aba_base_mostra_o_registro_quando_ha_chamadas(self):
        from src import config
        logs = self.tmp / "saidas" / "logs"
        logs.mkdir(parents=True)
        (logs / "2026-10-12.jsonl").write_text(
            json.dumps({"quando": "2026-10-12T10:00:00", "rotulo": "gerador", "duracao_s": 3.2, "erro": None},
                       ensure_ascii=False) + chr(10), encoding="utf-8")
        with mock.patch.object(config, "saidas_dir", lambda: self.tmp / "saidas"):
            self.rodar()
        self.assertIn("gerador", self.textos("write"))
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertTrue(any("Baixar o registro" in n for n in nomes))

    def test_painel_de_espaco_por_experiencia_e_ajuste_manual(self):
        from tests.fakes import SLUG_ESTAG
        llm = self.usar_llm(analise_bruta(), gerado_bom(), {"problemas": [], "palavras": []})
        self.st.valores["vaga_texto"] = VAGA_PT
        self.st.cliques = {"btn_analisar"}
        self.rodar()
        aid = self.st.session_state["analise_id"]
        self.st.cliques = set()
        self.rodar()     # o rerun da análise interrompe a execução; o painel aparece na seguinte
        # o painel existe e vem preenchido pela regra (a base de exemplo é recente: segue a posição)
        self.assertEqual(self.st.session_state[f"lim_{aid}_{SLUG_ESTAG}"], 3)
        self.st.valores[f"lim_{aid}_{SLUG_ESTAG}"] = 0
        self.st.cliques = {"btn_gerar"}
        self.rodar()
        res = self.st.session_state["resultado"]
        self.assertEqual(res.limites[SLUG_ESTAG]["limite"], 0)
        self.assertEqual(res.limites[SLUG_ESTAG]["motivo"], "ajustado por você")
        self.assertIn(f"{SLUG_ESTAG}: 0 (ajustado por você)", llm.chamadas[1]["mensagens"][0]["content"])
        self.assertIn("**Loja Modelo**", res.curriculo.markdown)
        self.assertNotIn("Apoiou um evento de lançamento", res.curriculo.markdown)
        self.st.cliques = set()
        self.rodar()     # a tela de resultado traz o relatório, com o espaço de cada experiência
        relatorio_na_tela = self.textos("markdown")
        self.assertIn("Como cada parte foi escrita", relatorio_na_tela)
        self.assertIn("0 bullet(s), ajustado por você", relatorio_na_tela)
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertIn("Baixar o relatório", nomes)

    def test_aba_base_acoes(self):
        self.st.valores["ed_arquivo"] = "perfil"
        self.st.cliques = {"conf_empresa-exemplo-digital-analista-de-marketing#6"}
        self.rodar()
        self.assertEqual(self.kb.fato("empresa-exemplo-digital-analista-de-marketing#6").status, "confirmado")

    def test_aba_base_nova_experiencia_invalida_mostra_erro(self):
        v = self.st.session_state.get("base_v", 0)
        self.rodar()
        v = self.st.session_state["base_v"]
        self.st.valores.update({f"ne_emp_{v}": "Acme", f"ne_cargo_{v}": "X", f"ne_ini_{v}": "2020", f"ne_fim_{v}": "atual"})
        self.st.cliques = {"Criar experiência"}
        self.rodar()
        self.assertIn("AAAA-MM", self.textos("error"))

    def test_aba_vaga_traducao_de_cargos(self):
        # base em português gerando em inglês: pede tradução dos cargos que faltam
        t = self.kb.ler_texto("loja-modelo-estagiaria-de-marketing").replace("cargo_en: Marketing Intern\n", "")
        self.kb.salvar_texto("loja-modelo-estagiaria-de-marketing", t)
        self.usar_llm(analise_bruta(), {"traducoes": [{"slug": "loja-modelo-estagiaria-de-marketing",
                                                        "cargo": "Marketing Intern", "local": "São Paulo, Brazil"}]})
        self.st.valores["vaga_texto"] = VAGA_PT
        self.st.cliques = {"btn_analisar"}
        self.rodar()
        aid = self.st.session_state["analise_id"]
        self.st.valores[f"idioma_{aid}"] = "en"
        self.st.cliques = {"btn_sugerir_trad"}
        self.rodar()
        self.assertIsNotNone(self.st.session_state["trad"])
        self.st.cliques = {"btn_confirmar_trad"}
        self.rodar()
        self.assertIn("cargo_en: Marketing Intern", self.kb.ler_texto("loja-modelo-estagiaria-de-marketing"))

    def test_erro_do_provedor_vira_mensagem_e_nao_derruba(self):
        from src.llm import ErroLLM

        class Quebra:
            def conversar(self, *a, **k):
                raise ErroLLM("Limite de uso do provedor atingido.")

        p = mock.patch.object(self.app, "obter_llm", lambda kb: Quebra())
        p.start()
        self.addCleanup(p.stop)
        self.st.chat = ["oi"]
        self.rodar()
        self.assertIn("Limite de uso", self.textos("error"))
        self.assertEqual(self.st.session_state["chat"], [])

    CV_EN = ("Mariana Example\nMarketing Analyst\n" + "Worked with the team on paid media campaigns and reporting for the company. " * 4)

    def test_aviso_fixo_na_area_de_importacao(self):
        self.rodar()
        legendas = " ".join(str(c[1][0]) for c in self.st.chamadas if c[0] == "caption")
        self.assertIn("um** idioma só", legendas)

    def test_cv_em_outro_idioma_que_a_base_gera_aviso_de_duplicacao(self):
        self.usar_llm({"propostas": [{"destino": "habilidades", "meta": {},
                                      "fatos": [{"texto": "Uses Excel for reporting.", "origem": "dito"}]}]})
        self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv_en.txt", self.CV_EN.encode("utf-8"))
        self.st.cliques = {"btn_importar"}
        self.rodar()
        tipo, texto = self.st.session_state["msg"]
        self.assertEqual(tipo, "warning")
        self.assertIn("descarte esta revisão", texto)
        self.assertIn("português", texto)
        self.assertIn("inglês", texto)

    def test_cv_no_mesmo_idioma_da_base_so_informa(self):
        cv_pt = ("Ana Souza\nAnalista\n" + "Trabalhou com a equipe em campanhas de mídia paga e relatórios para a empresa. " * 4)
        self.usar_llm({"propostas": [{"destino": "habilidades", "meta": {},
                                      "fatos": [{"texto": "Domina Excel.", "origem": "dito"}]}]})
        self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv_pt.txt", cv_pt.encode("utf-8"))
        self.st.cliques = {"btn_importar"}
        self.rodar()
        self.assertEqual(self.st.session_state["msg"][0], "info")

    def test_primeira_importacao_em_base_vazia_nao_avisa(self):
        self.usar_llm({"propostas": [{"destino": "habilidades", "meta": {},
                                      "fatos": [{"texto": "Uses Excel.", "origem": "dito"}]}]})
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "vazia")}):
            self.st.uploads["up_curriculo"] = stub.ArquivoFalso("cv_en.txt", self.CV_EN.encode("utf-8"))
            self.st.cliques = {"btn_importar"}
            self.rodar()
        self.assertEqual(self.st.session_state["msg"][0], "info")


if __name__ == "__main__":
    unittest.main()
