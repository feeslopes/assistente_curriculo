import tempfile
import unittest
from pathlib import Path

from src.cota import DIA, Cota, ErroCota, Plano, id_da_vaga, plano_de
from tests.fakes import limpar

T0 = 1_800_000_000.0


class Relogio:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def montar(geracoes=60, dias=30, regeracoes=3, por_hora=10, fim_dias=30, relogio=None):
    tmp = Path(tempfile.mkdtemp())
    r = relogio or Relogio()
    plano = Plano("mensal", T0, T0 + fim_dias * DIA, geracoes, dias, aviso_em=max(geracoes - 10, 0))
    return Cota(tmp, plano, {"regeracoes_por_vaga": regeracoes, "geracoes_por_hora": por_hora}, agora=r), tmp, r


class TestCota(unittest.TestCase):
    def test_conta_e_bloqueia_no_teto(self):
        c, tmp, r = montar(geracoes=3, por_hora=99)
        try:
            for i in range(3):
                c.autorizar(f"vaga {i}")
                c.registrar(f"vaga {i}")
                r.t += 4000
            self.assertEqual(c.situacao()["usadas"], 3)
            with self.assertRaises(ErroCota) as e:
                c.autorizar("vaga nova")
            self.assertIn("usou as 3 gerações", str(e.exception))
        finally:
            limpar(tmp)

    def test_limite_de_regeracoes_por_vaga(self):
        c, tmp, r = montar(regeracoes=2, por_hora=99)
        try:
            for _ in range(3):                      # primeira + 2 regerações
                c.autorizar("Vaga de analista")
                c.registrar("Vaga de analista")
            with self.assertRaises(ErroCota) as e:
                c.autorizar("  vaga   de ANALISTA ")   # mesma vaga, texto normalizado
            self.assertIn("regerou", str(e.exception))
            c.autorizar("Outra vaga")                  # outra vaga segue livre
        finally:
            limpar(tmp)

    def test_limite_por_hora_libera_depois(self):
        c, tmp, r = montar(por_hora=2)
        try:
            for i in range(2):
                c.registrar(f"v{i}")
            with self.assertRaises(ErroCota) as e:
                c.autorizar("v9")
            self.assertIn("minuto", str(e.exception))
            r.t += 3601
            c.autorizar("v9")
        finally:
            limpar(tmp)

    def test_plano_vencido(self):
        c, tmp, r = montar(fim_dias=10)
        try:
            r.t = T0 + 11 * DIA
            with self.assertRaises(ErroCota) as e:
                c.autorizar("x")
            self.assertIn("venceu", str(e.exception))
        finally:
            limpar(tmp)

    def test_janela_renova_no_periodo_seguinte(self):
        c, tmp, r = montar(geracoes=1, dias=7, fim_dias=60, por_hora=99)
        try:
            c.registrar("a")
            with self.assertRaises(ErroCota):
                c.autorizar("b")
            r.t = T0 + 8 * DIA
            c.autorizar("b")
            self.assertEqual(c.situacao()["usadas"], 0)
        finally:
            limpar(tmp)

    def test_sem_plano_ativo_e_aviso(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(ErroCota):
                Cota(tmp, Plano("", 0, 0, 0, 30)).autorizar("x")
            c, tmp2, r = montar(geracoes=12, por_hora=99)
            try:
                for i in range(2):
                    c.registrar(f"v{i}")
                self.assertTrue(c.situacao()["aviso"])
            finally:
                limpar(tmp2)
        finally:
            limpar(tmp)

    def test_arquivo_corrompido_nao_derruba(self):
        c, tmp, r = montar()
        try:
            c.arquivo.write_text("{lixo", encoding="utf-8")
            c.autorizar("x")
            c.registrar("x")
            self.assertEqual(c.situacao()["usadas"], 1)
        finally:
            limpar(tmp)

    def test_plano_de_usa_o_teto_assinado_e_completa_com_config(self):
        cfg = {"mensal": {"dias": 30, "geracoes": 60, "aviso_em": 50}}
        p = plano_de({"plano": "mensal", "inicio": 10, "fim": 99}, cfg)
        self.assertEqual((p.geracoes, p.dias, p.aviso_em), (60, 30, 50))
        self.assertEqual(plano_de({"plano": "mensal", "teto": 100}, cfg).geracoes, 100)
        self.assertEqual(plano_de({"plano": "desconhecido"}, cfg).geracoes, 0)

    def test_id_da_vaga_normaliza(self):
        self.assertEqual(id_da_vaga("A  b\nC"), id_da_vaga("a b c"))
        self.assertNotEqual(id_da_vaga("a"), id_da_vaga("b"))


if __name__ == "__main__":
    unittest.main()
