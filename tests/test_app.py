"""Testes da interface com um streamlit falso: fluxos, cliques e o que é gravado.

O comportamento visual de verdade (layout, gráficos) precisa ser conferido rodando o aplicativo.
"""
import importlib
import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

import altair  # noqa: F401  carregado uma vez: o patch de sys.modules não pode forçar um segundo import do numpy

from src import config
from src.interview import FatoProposto, Proposta
from src.kb import KB
from tests import streamlit_stub as stub
from tests.fakes import RAIZ, SLUG_ATUAL, SLUG_ESTAG, LLMFalso, base_exemplo, limpar
from tests.test_render import gerado_bom
from tests.test_tailor import analise_bruta

VAGA_PT = (RAIZ / "exemplo" / "vagas" / "vaga_pt.txt").read_text(encoding="utf-8")
ENV_COM_CHAVE = {"PROVEDOR": "deepseek", "DEEPSEEK_API_KEY": "chave-de-teste", "MODELO": "m"}
CV_PT = "Ana Souza\nAnalista\nana@exemplo.com | +55 11 98888-7777\n" + "Trabalhou com análise de dados e relatórios. " * 5
CV_EN = "Mariana Example\nMarketing Analyst\n" + "Worked with the team on paid media campaigns and reporting for the company. " * 4
FISCAL_OK = {"itens": [], "palavras": []}


def proposta(*fatos, destino="habilidades"):
    return {"propostas": [{"destino": destino, "meta": {}, "fatos": [{"texto": t, "origem": o} for t, o in fatos]}]}


def _descarregar():
    for nome in [m for m in sys.modules if m == "app" or m == "interface" or m.startswith("interface.")]:
        sys.modules.pop(nome, None)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.st = stub.FakeStreamlit()
        self.patch_mod = mock.patch.dict(sys.modules, {"streamlit": self.st})
        self.patch_mod.start()
        _descarregar()
        self.app = importlib.import_module("app")
        self.kb, self.tmp = base_exemplo()
        self.env = mock.patch.dict(os.environ, {**ENV_COM_CHAVE, "CV_BASE_DIR": str(self.kb.base)}, clear=False)
        self.env.start()
        self.sem_env = mock.patch.object(config, "carregar_env", lambda: None)
        self.sem_env.start()
        # nunca ler nem gravar a pasta saidas/ real do projeto (tem currículos e logs de uso de verdade)
        self.saidas = mock.patch.object(config, "saidas_dir", lambda: self.tmp / "saidas")
        self.saidas.start()
        self.abrir = mock.patch("interface.comum.abrir_pasta", lambda p: True)   # não abrir janelas nos testes
        self.abrir.start()

    def tearDown(self):
        self.abrir.stop()
        self.saidas.stop()
        self.sem_env.stop()
        self.env.stop()
        self.patch_mod.stop()
        _descarregar()
        limpar(self.tmp)

    # ------------------------------------------------------------------ apoio
    def rodar(self):
        """Uma execução do script. st.rerun() interrompe, como no Streamlit de verdade."""
        try:
            self.app.main()
        except stub.Parar:
            pass

    def usar_llm(self, *respostas):
        llm = LLMFalso(*respostas)
        p = mock.patch.object(sys.modules["interface.comum"], "obter_llm", lambda kb: llm)
        p.start()
        self.addCleanup(p.stop)
        return llm

    def textos(self, nome):
        return " ".join(str(c[1][0]) for c in self.st.chamadas if c[0] == nome and c[1])

    def chamou(self, nome):
        return any(c[0] == nome for c in self.st.chamadas)

    def ir(self, area, vista=None):
        self.st.session_state["area"] = area
        if vista:
            self.st.session_state["vista_historico"] = vista

    def clicar(self, *botoes):
        self.st.cliques = set(botoes)
        self.rodar()
        self.st.cliques = set()

    def reiniciar(self):
        """Simula fechar e abrir o aplicativo: memória nova, mesma pasta de base."""
        self.st = stub.FakeStreamlit()
        sys.modules["streamlit"] = self.st
        _descarregar()
        self.app = importlib.import_module("app")

    def gerar_para_a_vaga(self, *extras):
        """Analisa a vaga de exemplo, avança para o passo 3 e gera. Devolve o LLM falso.

        O currículo fictício de teste pontua abaixo da versão sem adaptar, então o app faz a segunda tentativa:
        por isso a fila tem duas gerações (e dois fiscais).
        """
        llm = self.usar_llm(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK, *extras)
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.st.valores.pop("vaga_texto")
        self.clicar("btn_para_gerar")
        self.clicar("btn_gerar")
        return llm

    # ------------------------------------------------------------------ primeiro uso
    def test_primeiro_uso_mostra_boas_vindas_sem_menu(self):
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "vazia")}):
            self.rodar()
        self.assertIn("Vamos montar o seu currículo", self.textos("markdown"))
        self.assertNotIn("area", [c[2].get("key") for c in self.st.chamadas if c[2]])
        self.assertNotIn("area", self.st.session_state.get("_desenhados", []))

    def test_sem_chave_explica_como_ligar_e_o_historico_continua(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "PROVEDOR": "deepseek"}):
            self.ir("historico")
            self.rodar()                       # Meu histórico funciona sem IA
            self.assertIn("Experiências", self.textos("metric"))
            self.ir("vaga")
            self.rodar()
        self.assertIn("Falta ligar a IA", self.textos("markdown"))

    def test_dados_de_exemplo_no_primeiro_uso(self):
        nova = self.tmp / "nova"
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(nova)}):
            self.clicar("btn_exemplo")
            self.assertTrue((nova / "contato.yaml").exists())
            self.rodar()
        self.assertEqual(self.st.session_state["area"], "historico")
        self.assertIn("Experiências", self.textos("markdown"))

    # ------------------------------------------------------------------ ler o currículo
    def test_ler_curriculo_no_primeiro_uso_preenche_os_dados_e_abre_a_conferencia(self):
        self.usar_llm(proposta(("Domina Excel avançado.", "dito")))
        vazia = self.tmp / "vazia"
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(vazia)}):
            self.st.uploads["up_inicio"] = stub.ArquivoFalso("cv.txt", CV_PT.encode("utf-8"))
            self.clicar("btn_up_inicio")
            contato = KB(vazia).contato()
            self.assertEqual((contato["email"], contato["nome"]), ("ana@exemplo.com", "Ana Souza"))
            self.assertEqual(len(self.st.session_state["rev_importacao"]), 1)
            self.rodar()          # a conferência: dados pessoais já preenchidos, para ela ver e corrigir
        rev = self.st.session_state["rev_id"]
        self.assertEqual(self.st.session_state[f"rc_{rev}_email"], "ana@exemplo.com")
        self.assertIn("Confira o que eu entendi do seu currículo", self.textos("markdown"))

    def test_conferencia_salva_marcados_e_guarda_o_resto_para_confirmar(self):
        self.usar_llm(proposta(("Domina Excel avançado.", "dito"), ("Lidera reuniões com clientes.", "sugerido")))
        vazia = self.tmp / "vazia"
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(vazia)}):
            self.st.uploads["up_inicio"] = stub.ArquivoFalso("cv.txt", CV_PT.encode("utf-8"))
            self.clicar("btn_up_inicio")
            rev = self.st.session_state["rev_id"]
            self.st.valores[f"rc_{rev}_telefone"] = "+55 11 91111-2222"
            self.clicar("Salvar")
            kb = KB(vazia)
            por_status = {f.texto: f.status for f in kb.fatos()}
            self.assertEqual(kb.contato()["telefone"], "+55 11 91111-2222")
        self.assertEqual(por_status["Domina Excel avançado."], "confirmado")
        self.assertEqual(por_status["Lidera reuniões com clientes."], "sugerido")   # guardado, fora dos currículos
        self.assertIsNone(self.st.session_state["rev_importacao"])
        self.assertIn("guardada(s) para confirmar depois", self.st.session_state["msg"][1])

    def test_descartar_a_leitura(self):
        self.ir("historico")
        self.usar_llm(proposta(("Fato novo.", "dito")))
        self.st.uploads["up_dialogo"] = stub.ArquivoFalso("cv.txt", CV_PT.encode("utf-8"))
        self.clicar("btn_ler_cv", "btn_up_dialogo")
        self.clicar("btn_descartar_imp")
        self.assertIsNone(self.st.session_state["rev_importacao"])
        self.assertNotIn("Fato novo.", [f.texto for f in self.kb.fatos()])

    def test_leitura_pendente_avisa_nas_outras_areas(self):
        self.st.session_state["rev_importacao"] = [Proposta("habilidades", [FatoProposto("Fato.", "dito")])]
        self.ir("vaga")
        self.rodar()
        self.assertIn("esperando você conferir", self.textos("warning"))
        self.clicar("btn_ir_revisao")
        self.rodar()
        self.assertEqual(self.st.session_state["area"], "historico")

    def test_curriculo_em_outro_idioma_avisa_duplicacao(self):
        self.ir("historico")
        self.usar_llm(proposta(("Uses Excel for reporting.", "dito")))
        self.st.uploads["up_dialogo"] = stub.ArquivoFalso("cv_en.txt", CV_EN.encode("utf-8"))
        self.clicar("btn_ler_cv", "btn_up_dialogo")
        tipo, texto = self.st.session_state["msg"]
        self.assertEqual(tipo, "warning")
        self.assertIn("Descartar esta leitura", texto)

    def test_primeira_leitura_em_base_vazia_nao_avisa_idioma(self):
        self.usar_llm(proposta(("Uses Excel.", "dito")))
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "vazia")}):
            self.st.uploads["up_inicio"] = stub.ArquivoFalso("cv_en.txt", CV_EN.encode("utf-8"))
            self.clicar("btn_up_inicio")
        self.assertIsNone(self.st.session_state["msg"])

    # ------------------------------------------------------------------ meu histórico
    def test_cartoes_mostram_os_itens_sem_menu_escondido(self):
        self.ir("historico")
        self.rodar()
        texto = self.textos("markdown")
        self.assertIn("Estruturou o funil de aquisição", texto)      # item de uma experiência, à vista
        self.assertFalse(any(c[0] == "expander" for c in self.st.chamadas))

    def test_confirmar_um_item_no_cartao(self):
        self.ir("historico")
        self.clicar(f"conf_{SLUG_ATUAL}#6")
        self.assertEqual(self.kb.fato(f"{SLUG_ATUAL}#6").status, "confirmado")

    def test_editar_experiencia_no_cartao(self):
        self.ir("historico")
        self.clicar(f"ed_{SLUG_ESTAG}")
        self.assertEqual(self.st.session_state["editando"], SLUG_ESTAG)
        v = self.st.session_state["base_v"]
        self.st.valores[f"itens_{SLUG_ESTAG}_{v}"] = "Atualizava as redes sociais da loja.\nCriou o calendário de posts."
        self.clicar("Salvar")
        textos = [f.texto for f in self.kb.fatos("confirmado") if f.slug == SLUG_ESTAG]
        self.assertEqual(textos, ["Atualizava as redes sociais da loja.", "Criou o calendário de posts."])
        self.assertIsNone(self.st.session_state["editando"])

    def test_nova_experiencia_com_data_invalida_mostra_erro(self):
        self.ir("historico")
        self.st.valores.update({"ne_cargo": "Analista", "ne_empresa": "Acme", "ne_inicio": "03/2020", "ne_fim": "atual"})
        self.clicar("btn_nova_exp", "Adicionar")
        self.assertIn("AAAA-MM", self.textos("error"))

    def test_nova_experiencia_com_itens(self):
        self.ir("historico")
        self.st.valores.update({"ne_cargo": "Analista", "ne_empresa": "Acme", "ne_inicio": "2015-01",
                                "ne_fim": "2016-02", "ne_itens": "Fez relatórios.\nAtendeu clientes."})
        self.clicar("btn_nova_exp", "Adicionar")
        nova = next(a for a in self.kb.experiencias() if a.meta["empresa"] == "Acme")
        self.assertEqual([f.texto for f in nova.fatos()], ["Fez relatórios.", "Atendeu clientes."])

    def test_registro_fica_em_avancado(self):
        logs = self.tmp / "saidas" / "logs"
        logs.mkdir(parents=True)
        (logs / "2026-10-12.jsonl").write_text(
            json.dumps({"quando": "2026-10-12T10:00:00", "rotulo": "gerador", "duracao_s": 3.2, "erro": None}) + chr(10),
            encoding="utf-8")
        self.ir("historico", "avancado")
        self.rodar()
        self.assertIn("gerador", self.textos("write"))

    # ------------------------------------------------------------------ conversa
    def test_conversar_e_salvar_o_que_contou(self):
        self.usar_llm("Qual foi o resultado?", proposta(("Usa Notion para documentar.", "dito"),
                                                        ("Organiza bem o time.", "sugerido")))
        self.ir("historico", "conversa")
        self.st.chat = ["Trabalho com marketing"]
        self.rodar()
        self.assertEqual([m["role"] for m in self.st.session_state["chat"]], ["user", "assistant"])
        self.clicar("btn_encerrar")
        self.assertEqual(len(self.st.session_state["rev_entrevista"]), 1)
        self.clicar("Salvar")
        por_status = {f.texto: f.status for f in self.kb.fatos()}
        self.assertEqual(por_status["Usa Notion para documentar."], "confirmado")
        self.assertEqual(por_status["Organiza bem o time."], "sugerido")
        self.assertEqual(self.st.session_state["chat"], [])

    def test_descartar_a_conferencia_da_conversa(self):
        self.usar_llm("ok", proposta(("Fato novo.", "dito")))
        self.ir("historico", "conversa")
        self.st.chat = ["oi"]
        self.rodar()
        self.clicar("btn_encerrar")
        self.clicar("btn_descartar_ent")
        self.assertIsNone(self.st.session_state["rev_entrevista"])
        self.assertNotIn("Fato novo.", [f.texto for f in self.kb.fatos()])

    def test_conversa_e_conferencia_sobrevivem_a_fechar_o_aplicativo(self):
        self.usar_llm("Qual foi o resultado?", proposta(("Usa Notion para documentar.", "dito")))
        self.ir("historico", "conversa")
        self.st.chat = ["Trabalho com marketing"]
        self.rodar()
        self.clicar("btn_encerrar")
        antes = self.st.session_state["chat"]
        self.reiniciar()
        self.rodar()
        self.assertEqual(self.st.session_state["chat"], antes)
        self.assertIn("Continuei de onde você parou", self.textos("info"))
        self.ir("historico", "conversa")
        self.clicar("Salvar")
        self.assertIn("Usa Notion para documentar.", [f.texto for f in self.kb.fatos("confirmado")])
        self.assertFalse((self.kb.base / ".sessao" / "sessao.json").exists())

    def test_erro_do_provedor_vira_mensagem_e_nao_derruba(self):
        from src.llm import ErroLLM

        class Quebra:
            def conversar(self, *a, **k):
                raise ErroLLM("Limite de uso do provedor atingido.")

        p = mock.patch.object(sys.modules["interface.comum"], "obter_llm", lambda kb: Quebra())
        p.start()
        self.addCleanup(p.stop)
        self.ir("historico", "conversa")
        self.st.chat = ["oi"]
        self.rodar()
        self.assertIn("Limite de uso", self.textos("error"))
        self.assertEqual(self.st.session_state["chat"], [])

    # ------------------------------------------------------------------ currículo para uma vaga
    def test_passos_da_vaga(self):
        self.usar_llm(analise_bruta())
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.assertEqual(self.st.session_state["passo_vaga"], 2)
        self.rodar()
        self.assertIn("requisitos obrigatórios", self.textos("markdown"))
        self.assertIn("Comprovado", self.textos("markdown"))
        self.clicar("btn_para_gerar")
        self.assertEqual(self.st.session_state["passo_vaga"], 3)
        self.clicar("btn_voltar_2")          # voltar ao encaixe
        self.assertEqual(self.st.session_state["passo_vaga"], 2)
        self.clicar("btn_voltar_1")          # trocar de vaga volta ao passo 1 e limpa a análise
        self.assertIsNone(self.st.session_state["analise"])

    def test_gerar_salva_sozinho_na_pasta_da_empresa_e_mostra_aderencia(self):
        llm = self.gerar_para_a_vaga()
        self.assertEqual(len(llm.chamadas), 5)       # análise, geração, fiscal e a segunda tentativa
        pasta = self.tmp / "saidas" / f"Empresa Fictícia_{date.today():%Y-%m}"
        self.assertTrue(pasta.is_dir())
        for nome in ("Curriculo_Mariana_Exemplo.pdf", "Curriculo_Mariana_Exemplo.docx", "Curriculo_Mariana_Exemplo.md",
                     "vaga.txt", "analise.json", "relatorio.md", "indice.json"):
            self.assertTrue((pasta / nome).exists(), nome)
        self.rodar()
        self.assertIn("Aderência à vaga", self.textos("metric"))
        self.assertTrue(self.chamou("altair_chart"))
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertIn("Baixar PDF", nomes)
        self.assertIn("Baixar Word", nomes)

    def test_gerar_de_novo_regrava_a_mesma_pasta(self):
        self.gerar_para_a_vaga(gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        self.clicar("btn_gerar_de_novo")
        self.clicar("btn_gerar")
        self.assertEqual(len([p for p in (self.tmp / "saidas").iterdir() if p.is_dir()]), 1)

    def test_editar_o_texto_e_salvar_a_versao(self):
        self.gerar_para_a_vaga()
        gid = self.st.session_state["gen_id"]
        editado = self.st.session_state[f"texto_{gid}"].replace("Mariana Exemplo", "Mariana E. Exemplo")
        self.st.valores[f"editar_{gid}"] = True
        self.st.valores[f"editor_{gid}_0"] = editado
        self.rodar()
        self.clicar("btn_salvar_edicao")
        pasta = next((self.tmp / "saidas").iterdir())
        self.assertIn("Mariana E. Exemplo", (pasta / "Curriculo_Mariana_Exemplo.md").read_text(encoding="utf-8"))

    def test_pontuacao_de_hoje_aparece_antes_de_gerar(self):
        self.usar_llm(analise_bruta())
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.rodar()
        metricas = self.textos("metric")
        self.assertIn("Seu currículo hoje, para esta vaga", metricas)
        self.assertIn("Máximo com o seu histórico", metricas)

    def test_versao_abaixo_da_original_oferece_a_sem_adaptar(self):
        from tests.test_redesenho import TestNaoPiorar
        magro = TestNaoPiorar.magro
        self.usar_llm(analise_bruta(), magro(), FISCAL_OK, magro(), FISCAL_OK)
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.st.valores.pop("vaga_texto")
        self.clicar("btn_para_gerar")
        self.clicar("btn_gerar")
        self.rodar()
        self.assertIn("ficou abaixo do seu currículo sem adaptar", self.textos("warning"))
        self.clicar("btn_usar_original")
        gid = self.st.session_state["gen_id"]
        res = self.st.session_state["resultado"]
        self.assertEqual(self.st.session_state[f"texto_{gid}"], res.aderencia["markdown_antes"])
        self.st.chamadas.clear()
        self.rodar()
        self.assertIn("versão sem adaptar", self.textos("info"))
        self.clicar("btn_salvar_edicao")           # e dá para guardar essa versão em Minhas vagas
        pasta = next((self.tmp / "saidas").iterdir())
        self.assertEqual((pasta / "Curriculo_Mariana_Exemplo.md").read_text(encoding="utf-8"), res.aderencia["markdown_antes"])

    def test_vistas_do_resultado(self):
        self.gerar_para_a_vaga()
        self.rodar()         # primeira tela depois de gerar: abre na vista do currículo
        for vista, esperado in (("mudou", "Como cada parte foi escrita"), ("melhorar", "Palavras-chave da vaga neste currículo")):
            self.st.session_state["vista_resultado"] = vista
            self.st.chamadas.clear()
            self.rodar()
            self.assertIn(esperado, self.textos("markdown"))
        self.st.session_state["vista_resultado"] = "melhorar"
        self.rodar()
        self.assertIn("inventar", self.textos("info"))

    def test_lacunas_respondidas_vao_para_conferencia_e_atualizam_o_encaixe(self):
        resposta = proposta(("Criou dashboards no Looker Studio para a diretoria.", "dito"), destino=SLUG_ATUAL)
        llm = self.usar_llm(analise_bruta(), resposta, analise_bruta())
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        aid = self.st.session_state["analise_id"]
        self.st.valores[f"lac_{aid}_0"] = "Criei dashboards no Looker Studio para a diretoria."
        self.rodar()
        self.clicar("btn_lacunas")
        self.assertTrue(self.st.session_state["rev_lacuna"])
        self.clicar("Salvar")
        self.assertIn("Criou dashboards no Looker Studio para a diretoria.", [f.texto for f in self.kb.fatos("confirmado")])
        self.assertEqual(self.st.session_state["analise_id"], aid + 1)      # reanalisou sozinho
        self.assertEqual(len(llm.chamadas), 3)

    def test_espaco_por_experiencia_e_ajuste_manual(self):
        llm = self.usar_llm(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        aid = self.st.session_state["analise_id"]
        self.clicar("btn_para_gerar")
        self.rodar()
        self.assertEqual(self.st.session_state[f"lim_{aid}_{SLUG_ESTAG}"], 3)
        self.st.valores[f"lim_{aid}_{SLUG_ESTAG}"] = 0
        self.clicar("btn_gerar")
        res = self.st.session_state["resultado"]
        self.assertEqual(res.limites[SLUG_ESTAG]["motivo"], "ajustado por você")
        self.assertIn(f"{SLUG_ESTAG}: 0 (ajustado por você)", llm.chamadas[1]["mensagens"][0]["content"])
        self.assertNotIn("Apoiou um evento de lançamento", res.curriculo.markdown)

    def test_traducao_de_cargos(self):
        t = self.kb.ler_texto("loja-modelo-estagiaria-de-marketing").replace("cargo_en: Marketing Intern\n", "")
        self.kb.salvar_texto("loja-modelo-estagiaria-de-marketing", t)
        self.usar_llm(analise_bruta(), {"traducoes": [{"slug": "loja-modelo-estagiaria-de-marketing",
                                                        "cargo": "Marketing Intern", "local": "São Paulo, Brazil"}]})
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        aid = self.st.session_state["analise_id"]
        self.clicar("btn_para_gerar")
        self.st.valores[f"idioma_{aid}"] = "en"
        self.clicar("btn_sugerir_trad")
        self.assertIsNotNone(self.st.session_state["trad"])
        self.clicar("btn_confirmar_trad")
        self.assertIn("cargo_en: Marketing Intern", self.kb.ler_texto("loja-modelo-estagiaria-de-marketing"))

    def test_vaga_que_nao_combina_avisa_que_o_curriculo_vai_sair_fraco(self):
        bruta = analise_bruta()
        for r in bruta["requisitos"]:
            r.update(status="lacuna", evidencias=[])
        bruta["observacoes"] = "A base não tem experiência na área da vaga."
        self.usar_llm(bruta)
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.rodar()
        self.assertIn("vai sair fraco", self.textos("warning"))
        self.assertIn("A base não tem experiência na área da vaga.", self.textos("info"))

    def test_falta_de_dados_pessoais_aparece_antes_de_gerar_e_no_historico(self):
        self.ir("historico")
        self.kb.salvar_contato({})
        self.rodar()
        self.assertIn("Faltam seus dados pessoais", self.textos("warning"))
        self.clicar("btn_ir_dados")
        self.rodar()
        self.assertEqual(self.st.session_state["vista_historico"], "dados")
        self.usar_llm(analise_bruta())
        self.ir("vaga")
        self.st.valores["vaga_texto"] = VAGA_PT
        self.clicar("btn_analisar")
        self.clicar("btn_para_gerar")
        self.rodar()
        self.assertIn("Faltam seu nome ou seu contato", self.textos("warning"))

    def test_recomecar_a_conversa_pede_confirmacao(self):
        self.usar_llm("Qual foi o resultado?")
        self.ir("historico", "conversa")
        self.st.chat = ["oi"]
        self.rodar()
        self.assertTrue(self.st.session_state["chat"])
        self.clicar("btn_nova_conversa")      # o botão só existe dentro da confirmação
        self.assertEqual(self.st.session_state["chat"], [])

    # ------------------------------------------------------------------ início, candidaturas e currículo geral
    def test_quem_volta_cai_no_inicio_com_as_duas_acoes(self):
        self.rodar()
        texto = self.textos("markdown")
        self.assertIn("Olá, Mariana", texto)
        self.assertIn("Currículo para uma vaga", texto)
        self.assertIn("Currículo geral", texto)
        self.assertIn("Nenhuma candidatura ainda", self.textos("caption"))
        # o histórico de exemplo tem 2 itens a confirmar e uma experiência com poucos detalhes
        self.assertIn("2 informação(ões) do seu histórico ainda a confirmar", texto)
        self.assertIn("ponto(s) a completar", texto)

    def test_curriculo_geral_pelo_inicio(self):
        llm = self.usar_llm(gerado_bom(), FISCAL_OK)
        self.clicar("ini_geral")
        self.rodar()
        self.assertEqual((self.st.session_state["area"], self.st.session_state["modo_curriculo"]), ("vaga", "geral"))
        self.clicar("btn_gerar_geral")
        self.assertEqual([c["rotulo"] for c in llm.chamadas], ["gerador", "verificador"])
        pasta = next((self.tmp / "saidas").iterdir())
        self.assertTrue(pasta.name.startswith("Geral_"))
        self.st.chamadas.clear()
        self.rodar()
        self.assertNotIn("Aderência à vaga", self.textos("metric"))      # sem vaga, sem aderência
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertIn("Baixar PDF", nomes)

    def test_marcar_situacao_e_anotacao_no_cartao(self):
        self.gerar_para_a_vaga()
        pasta = next((self.tmp / "saidas").iterdir())
        self.ir("vagas")
        self.st.valores[f"sit_{pasta.name}"] = "enviado"
        self.st.valores[f"nota_{pasta.name}"] = "Recrutadora: Ana"
        self.rodar()
        from src import candidaturas
        d = candidaturas.ler(pasta)
        self.assertEqual((d["situacao"], d["anotacao"]), ("enviado", "Recrutadora: Ana"))
        self.assertTrue(d["enviado_em"])

    def test_inicio_sugere_sem_retorno_e_marca_com_um_clique(self):
        self.gerar_para_a_vaga()
        pasta = next((self.tmp / "saidas").iterdir())
        (pasta / "candidatura.json").write_text(json.dumps({"situacao": "enviado", "enviado_em": "2026-01-01",
                                                           "historico": []}), encoding="utf-8")
        self.ir("inicio")
        self.rodar()
        self.assertIn("sem resposta registrada", self.textos("markdown"))
        self.clicar(f"ini_sr_{pasta.name}")
        from src import candidaturas
        self.assertEqual(candidaturas.ler(pasta)["situacao"], "sem_retorno")

    def test_inicio_mostra_onde_se_desenvolver(self):
        self.gerar_para_a_vaga(analise_bruta(), gerado_bom(), FISCAL_OK, gerado_bom(), FISCAL_OK)
        self.clicar("btn_outra_vaga")                    # segunda vaga, com as mesmas lacunas
        self.st.valores["vaga_texto"] = VAGA_PT + "\nOutra empresa."
        self.clicar("btn_analisar")
        self.st.valores.pop("vaga_texto")
        self.clicar("btn_para_gerar")
        self.clicar("btn_gerar")
        self.ir("inicio")
        self.st.chamadas.clear()
        self.rodar()
        texto = self.textos("markdown")
        self.assertIn("Onde se desenvolver para aumentar suas chances", texto)
        self.assertIn("Looker Studio", texto)
        self.assertIn("pedido em 2 de 2 vagas", texto)
        self.assertIn("Ainda não tem?", texto)

    def test_taxa_de_resposta_nao_aparece_com_poucos_dados(self):
        self.gerar_para_a_vaga()
        self.ir("inicio")
        self.rodar()
        self.assertIn("A taxa de resposta aparece a partir de 5", self.textos("caption"))

    def test_vaga_sem_historico_confirmado_orienta(self):
        with mock.patch.dict(os.environ, {"CV_BASE_DIR": str(self.tmp / "so-contato")}):
            KB(self.tmp / "so-contato").salvar_contato({"nome": "Ana"})
            self.ir("vaga")
            self.rodar()
        self.assertIn("monte o seu histórico", self.textos("info"))

    # ------------------------------------------------------------------ minhas vagas
    def test_minhas_vagas_vazia_orienta(self):
        self.ir("vagas")
        self.rodar()
        self.assertIn("Nenhuma candidatura ainda", self.textos("markdown"))

    def test_minhas_vagas_lista_com_grafico_e_downloads(self):
        self.gerar_para_a_vaga()
        self.ir("vagas")
        self.st.chamadas.clear()
        self.rodar()
        self.assertTrue(self.chamou("altair_chart"))
        self.assertIn("Empresa Fictícia", self.textos("markdown"))
        nomes = [c[1][0] for c in self.st.chamadas if c[0] == "download_button"]
        self.assertEqual(nomes[:2], ["PDF", "Word"])


if __name__ == "__main__":
    unittest.main()
