import unittest

from src import interview
from src.interview import FatoProposto, Proposta
from src.kb import ErroBase
from tests.fakes import SLUG_ATUAL, LLMFalso, base_exemplo, limpar


def bruto():
    return {"propostas": [
        {"destino": SLUG_ATUAL, "meta": {}, "fatos": [
            {"texto": "Treinou dois analistas juniores.", "origem": "dito"},
            {"texto": "Lidera uma equipe de analistas.", "origem": "sugerido"},
            {"texto": "Estruturou o funil de aquisição de um produto com 12 mil usuários ativos.", "origem": "dito"},  # repetido
            {"texto": "Ligue para ana@x.com para detalhes.", "origem": "dito"},                                   # contato
            {"texto": "", "origem": "dito"},
            {"texto": "Sem origem declarada.", "origem": "talvez"}]},
        {"destino": "nova_experiencia",
         "meta": {"empresa": "Café Central", "cargo": "Barista", "inicio": "2015-01", "fim": "2016-12", "local": "Recife, Brasil"},
         "fatos": [{"texto": "Preparava cerca de 100 cafés por turno (estimativa).", "origem": "dito"}]},
        {"destino": "nova_experiencia", "meta": {"empresa": "Sem datas", "cargo": "X"},
         "fatos": [{"texto": "Fez algo.", "origem": "dito"}]},
        {"destino": "destino_que_nao_existe", "fatos": [{"texto": "Lixo.", "origem": "dito"}]},
        {"destino": "idiomas", "fatos": ["Francês: Básico"]},
    ]}


class TestInterview(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_validacao_das_propostas(self):
        props = interview.validar_propostas(bruto(), self.kb)
        destinos = [p.destino for p in props]
        self.assertEqual(destinos, [SLUG_ATUAL, "nova_experiencia", "nova_experiencia", "idiomas"])
        fatos = {f.texto: f.origem for f in props[0].fatos}
        self.assertEqual(list(fatos), ["Treinou dois analistas juniores.", "Lidera uma equipe de analistas.", "Sem origem declarada."])
        self.assertEqual(fatos["Sem origem declarada."], "sugerido")   # origem desconhecida nunca vem marcada
        self.assertFalse(props[0].fatos[1].marcado_por_padrao)
        self.assertTrue(props[0].fatos[0].marcado_por_padrao)
        self.assertEqual(props[1].problemas, [])
        self.assertEqual(props[1].meta["fim"], "2016-12")
        self.assertTrue(props[2].problemas)                              # meta incompleta é sinalizada
        self.assertEqual(props[3].fatos[0].texto, "Francês: Básico")

    def test_extrator_recebe_o_idioma_do_material(self):
        llm = LLMFalso({"propostas": []})
        en = ("Senior Product Manager with over five years of experience building data-driven products in "
              "regulated environments, working closely with the engineering team and the business.")
        interview.extrair(llm, self.kb, en, "curriculo importado")
        self.assertIn("O material está em inglês", llm.chamadas[0]["mensagens"][1]["content"])

    def test_alerta_quando_o_extrator_traduziu(self):
        en = ("Senior Product Manager with over five years of experience building data-driven products in "
              "regulated environments, working closely with the engineering team and the business.")
        b = {"propostas": [{"destino": "perfil", "fatos": [
            {"texto": "Gerente de produto sênior com mais de cinco anos de experiência na construção de produtos "
                      "orientados a dados em ambientes regulados, trabalhando com a equipe de engenharia e com o negócio.",
             "origem": "dito"}]}]}
        props = interview.validar_propostas(b, self.kb, interview.detectar_idioma(en))
        self.assertTrue(props[0].problemas)
        self.assertIn("traduzido", props[0].problemas[0])

    def test_remove_sem_data_do_fim_do_fato(self):
        b = {"propostas": [{"destino": "certificacoes", "fatos": [
            {"texto": "Open Innovation | Future Dojo | sem data", "origem": "dito"}]}]}
        self.assertEqual(interview.validar_propostas(b, self.kb)[0].fatos[0].texto, "Open Innovation | Future Dojo")

    def test_extrair_chama_modelo_com_base_e_mascara(self):
        llm = LLMFalso({"propostas": []})
        interview.extrair(llm, self.kb, "Meu e-mail é a@b.com. Trabalhei na Loja X.", "curriculo importado")
        msgs = llm.chamadas[0]["mensagens"]
        self.assertNotIn("a@b.com", msgs[1]["content"])
        self.assertIn(SLUG_ATUAL, msgs[1]["content"])
        self.assertIn("Estruturou o funil", msgs[1]["content"])  # base atual, para não repetir
        self.assertTrue(llm.chamadas[0]["json_mode"])

    def test_aplicar_so_marcados_viram_confirmados(self):
        props = interview.validar_propostas(bruto(), self.kb)
        r = interview.aplicar(self.kb, props[:1], {(0, 0)}, guardar_resto=False)
        self.assertEqual((r["confirmados"], r["pendentes"]), (1, 0))
        textos = [f.texto for f in self.kb.fatos()]
        self.assertIn("Treinou dois analistas juniores.", textos)
        self.assertNotIn("Lidera uma equipe de analistas.", textos)   # não marcado e sem guardar: nada é gravado

    def test_aplicar_guardando_o_resto_como_pendente(self):
        props = interview.validar_propostas(bruto(), self.kb)
        r = interview.aplicar(self.kb, props[:1], {(0, 0)}, guardar_resto=True)
        self.assertEqual((r["confirmados"], r["pendentes"]), (1, 2))
        lidera = next(f for f in self.kb.fatos() if f.texto.startswith("Lidera"))
        self.assertEqual(lidera.status, "sugerido")
        self.assertNotIn("Lidera", self.kb.para_prompt())             # pendente nunca vai ao prompt

    def test_aplicar_nova_experiencia(self):
        props = interview.validar_propostas(bruto(), self.kb)
        r = interview.aplicar(self.kb, [props[1]], {(0, 0)}, guardar_resto=False)
        self.assertEqual(r["experiencias_criadas"], 1)
        self.assertIn("cafe-central-barista", [e.slug for e in self.kb.experiencias()])

    def test_aplicar_experiencia_com_meta_incompleta_falha(self):
        props = interview.validar_propostas(bruto(), self.kb)
        with self.assertRaises(ErroBase):
            interview.aplicar(self.kb, [props[2]], {(0, 0)}, guardar_resto=False)

    def test_responder_mascara_mensagem_e_traz_resumo(self):
        llm = LLMFalso("Qual foi o resultado?")
        r = interview.responder(llm, self.kb, [{"role": "user", "content": "oi"}], "Meu telefone é +55 11 97777-6666")
        self.assertEqual(r, "Qual foi o resultado?")
        msgs = llm.chamadas[0]["mensagens"]
        self.assertIn("Resumo da base atual", msgs[0]["content"])
        self.assertIn("Estruturou o funil", msgs[0]["content"])
        self.assertNotIn("97777", msgs[-1]["content"])
        self.assertFalse(llm.chamadas[0]["json_mode"])

    def test_abertura_nao_chama_api(self):
        self.assertIn("uma de cada vez", interview.ABERTURA)
        self.assertNotIn("—", interview.ABERTURA)


if __name__ == "__main__":
    unittest.main()


class TestDatasInventadas(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def bruto(self):
        return {"propostas": [{"destino": "nova_experiencia",
                               "meta": {"empresa": "Empresa Teste", "cargo": "Analista", "inicio": "2022-01", "fim": "atual"},
                               "fatos": [{"texto": "Cuida das campanhas pagas.", "origem": "dito"}]}]}

    def test_mes_que_a_ia_completou_e_apagado(self):
        props = interview.validar_propostas(self.bruto(), self.kb, "pt", "Sou analista na Empresa Teste desde 2022.")
        self.assertEqual(props[0].meta["inicio"], "2022")      # fica só o ano: nada de mês inventado
        self.assertTrue(any("só o ano" in p for p in props[0].problemas))
        r = interview.aplicar(self.kb, props, {(0, 0)}, False)
        self.assertEqual(r["experiencias_criadas"], 1)

    def test_salvar_e_tudo_ou_nada(self):
        """Uma experiência com data inválida não pode deixar o resto salvo pela metade."""
        bruto = {"propostas": [
            {"destino": "habilidades", "meta": {}, "fatos": [{"texto": "Usa Power BI.", "origem": "dito"}]},
            {"destino": "nova_experiencia", "meta": {"empresa": "X", "cargo": "Y", "inicio": "", "fim": "atual"},
             "fatos": [{"texto": "Fez algo.", "origem": "dito"}]}]}
        props = interview.validar_propostas(bruto, self.kb)
        with self.assertRaises(ErroBase) as ctx:
            interview.aplicar(self.kb, props, {(0, 0), (1, 0)}, True)
        self.assertIn("Nada foi salvo", str(ctx.exception))
        self.assertNotIn("Usa Power BI.", [f.texto for f in self.kb.fatos()])

    def test_mes_dito_e_mantido(self):
        props = interview.validar_propostas(self.bruto(), self.kb, "pt", "Entrei na Empresa Teste em janeiro de 2022.")
        self.assertEqual(props[0].meta["inicio"], "2022-01")
        self.assertFalse(any("ano" in p or "mês" in p for p in props[0].problemas))


class TestAberturaDinamica(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def test_base_vazia_usa_a_abertura_padrao(self):
        from src.kb import KB
        self.assertEqual(interview.abertura(KB(self.tmp / "vazia")), interview.ABERTURA)

    def test_base_preenchida_nao_repete_o_basico(self):
        t = interview.abertura(self.kb)
        self.assertIn("não vou repetir", t)
        self.assertIn("3 experiências", t)
        self.assertNotIn("fato", t)          # sem jargão interno
        self.assertNotIn("qual é o seu trabalho atual", t)
        self.assertNotIn("—", t)

    def test_responder_inclui_o_que_falta_e_os_pendentes(self):
        llm = LLMFalso("Qual foi o resultado?")
        interview.responder(llm, self.kb, [], "oi", pendentes=["Domina Excel avançado."])
        sistema = llm.chamadas[0]["mensagens"][0]["content"]
        self.assertIn("O que ainda falta na base", sistema)
        self.assertIn("aguardando a revisão", sistema)
        self.assertIn("Domina Excel avançado.", sistema)
        self.assertNotEqual(llm.chamadas[0]["mensagens"][1]["content"], interview.ABERTURA)  # abertura dinâmica


class TestExperienciaDuplicada(unittest.TestCase):
    def setUp(self):
        self.kb, self.tmp = base_exemplo()

    def tearDown(self):
        limpar(self.tmp)

    def bruto(self, **meta):
        m = {"empresa": "Empresa Exemplo Digital", "cargo": "Marketing Analyst", "inicio": "2022-03", "fim": "atual"}
        m.update(meta)
        return {"propostas": [{"destino": "nova_experiencia", "meta": m,
                               "fatos": [{"texto": "Managed paid media campaigns.", "origem": "dito"}]}]}

    def test_mesma_empresa_e_inicio_em_outro_idioma_gera_aviso(self):
        props = interview.validar_propostas(self.bruto(), self.kb)
        self.assertTrue(any("Parece a experiência que você já tem" in p for p in props[0].problemas))
        self.assertTrue(any("Analista de Marketing" in p for p in props[0].problemas))

    def test_empresa_com_caixa_e_acento_diferentes_tambem_casa(self):
        props = interview.validar_propostas(self.bruto(empresa="EMPRESA EXEMPLO DIGITAL S.A."), self.kb)
        self.assertTrue(any("mesma empresa" in p for p in props[0].problemas))

    def test_nome_parecido_e_inicio_um_pouco_diferente_tambem_avisa(self):
        props = interview.validar_propostas(self.bruto(empresa="ExemploDigital", inicio="2022-01"), self.kb)
        self.assertTrue(any("Parece a experiência" in p for p in props[0].problemas))

    def test_empresa_nova_em_outro_periodo_nao_avisa(self):
        props = interview.validar_propostas(self.bruto(empresa="Outra Empresa", inicio="2012-01", fim="2013-01"), self.kb)
        self.assertEqual(props[0].problemas, [])

    def test_mesma_empresa_com_outro_inicio_nao_avisa(self):
        props = interview.validar_propostas(self.bruto(inicio="2015-01", fim="2016-01"), self.kb)
        self.assertEqual(props[0].problemas, [])

    def test_empresa_nova_no_mesmo_periodo_avisa_de_leve(self):
        """Pode ser a mesma com outro nome (apelido, outro idioma) ou dois trabalhos ao mesmo tempo: só pergunta."""
        props = interview.validar_propostas(self.bruto(empresa="Outra Empresa"), self.kb)
        self.assertTrue(any("Se foram dois trabalhos ao mesmo tempo, pode salvar" in p for p in props[0].problemas))
