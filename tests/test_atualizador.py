"""Atualização automática: nunca perde dados, desfaz tudo se falhar, só atualiza para versão publicada mais nova."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from src import atualizador


def zip_da_versao(arquivos: dict[str, str], raiz_zip: str = "feeslopes-assistente_curriculo-abc123") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, conteudo in arquivos.items():
            z.writestr(f"{raiz_zip}/{rel}", conteudo)
    return buf.getvalue()


class Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def github_falso(tag: str, zip_bytes: bytes, notas: str = "Novidades."):
    """urlopen falso: a API devolve a release; o zipball devolve o zip."""
    def abrir(pedido, timeout=None):
        url = pedido.full_url
        if url == atualizador.API:
            return Resposta(json.dumps({"tag_name": tag, "zipball_url": "https://zip", "body": notas,
                                        "name": tag}).encode())
        if url == "https://zip":
            return Resposta(zip_bytes)
        raise AssertionError(url)
    return abrir


def sem_internet(pedido, timeout=None):
    raise OSError("sem rede")


NOVA = {"app.py": "print('nova')\n", "src/novo.py": "x = 2\n", "requirements.txt": "streamlit\n",
        "VERSAO": "v1.1.0\n", "iniciar.bat": "@echo off\nrem nova\n"}


class TestAtualizador(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        arquivos = {"app.py": "print('velha')\n", "src/velho.py": "x = 1\n", "requirements.txt": "streamlit\n",
                    "VERSAO": "v1.0.0\n", "iniciar.bat": "@echo off\nrem velha\n",
                    "base/perfil.md": "- [confirmado] Meu histórico.\n", "saidas/Acme_2026-10/Curriculo.md": "# eu\n",
                    ".env": "DEEPSEEK_API_KEY=segredo\n", ".venv/lib.txt": "pacotes\n"}
        for rel, c in arquivos.items():
            (self.raiz / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.raiz / rel).write_text(c, encoding="utf-8")
        # a instalação anterior registrou o que ela trouxe: src/velho.py saiu na versão nova e deve ser apagado
        (self.raiz / ".manifesto").write_text("app.py\nsrc/velho.py\nrequirements.txt\nVERSAO\niniciar.bat\n",
                                              encoding="utf-8")
        self.pip = mock.Mock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.raiz, ignore_errors=True)

    def ler(self, rel):
        return (self.raiz / rel).read_text(encoding="utf-8")

    def atualizar(self, abrir):
        return atualizador.verificar_e_atualizar(self.raiz, abrir=abrir, pip=self.pip, saida=lambda *_: None)

    def test_atualiza_o_codigo_e_preserva_os_dados(self):
        r = self.atualizar(github_falso("v1.1.0", zip_da_versao(NOVA)))
        self.assertEqual(r, "atualizado para v1.1.0")
        self.assertEqual(self.ler("app.py"), "print('nova')\n")
        self.assertTrue((self.raiz / "src/novo.py").exists())
        self.assertFalse((self.raiz / "src/velho.py").exists())            # saiu na versão nova
        self.assertEqual(self.ler("base/perfil.md"), "- [confirmado] Meu histórico.\n")
        self.assertEqual(self.ler("saidas/Acme_2026-10/Curriculo.md"), "# eu\n")
        self.assertEqual(self.ler(".env"), "DEEPSEEK_API_KEY=segredo\n")
        self.assertEqual(self.ler(".venv/lib.txt"), "pacotes\n")
        self.assertEqual(self.ler(".versao_instalada").strip(), "v1.1.0")
        self.pip.assert_not_called()                                       # requirements não mudou

    def test_guarda_copia_do_codigo_e_do_historico(self):
        self.atualizar(github_falso("v1.1.0", zip_da_versao(NOVA)))
        [codigo] = list((self.raiz / "backups").glob("codigo-*"))
        [base] = list((self.raiz / "backups").glob("base-*"))
        self.assertEqual((codigo / "app.py").read_text(encoding="utf-8"), "print('velha')\n")
        self.assertEqual((base / "perfil.md").read_text(encoding="utf-8"), "- [confirmado] Meu histórico.\n")
        self.assertFalse((codigo / ".env").exists())                         # a chave não vai para o backup

    def test_script_de_inicio_em_uso_nao_e_trocado_na_hora(self):
        self.atualizar(github_falso("v1.1.0", zip_da_versao(NOVA)))
        self.assertEqual(self.ler("iniciar.bat"), "@echo off\nrem velha\n")
        self.assertEqual(self.ler("iniciar.bat.novo"), "@echo off\nrem nova\n")

    def test_requirements_mudou_instala_e_se_falhar_desfaz_tudo(self):
        nova = {**NOVA, "requirements.txt": "streamlit\nnovo-pacote\n"}
        self.pip.side_effect = atualizador.ErroAtualizacao("pip falhou")
        r = self.atualizar(github_falso("v1.1.0", zip_da_versao(nova)))
        self.assertTrue(r.startswith("falhou"))
        self.assertEqual(self.ler("app.py"), "print('velha')\n")
        self.assertTrue((self.raiz / "src/velho.py").exists())
        self.assertFalse((self.raiz / "src/novo.py").exists())
        self.assertFalse((self.raiz / "iniciar.bat.novo").exists())
        self.assertFalse((self.raiz / ".versao_instalada").exists())
        self.assertEqual(self.ler("base/perfil.md"), "- [confirmado] Meu histórico.\n")

    def test_so_atualiza_para_versao_mais_nova(self):
        self.assertIn("mais recente", self.atualizar(github_falso("v1.0.0", zip_da_versao(NOVA))))
        self.assertIn("mais recente", self.atualizar(github_falso("v0.9.9", zip_da_versao(NOVA))))
        self.assertEqual(atualizador.numero("v1.10.0") > atualizador.numero("v1.9.3"), True)

    def test_sem_internet_ou_em_pasta_de_desenvolvimento_nao_faz_nada(self):
        self.assertIn("sem internet", self.atualizar(sem_internet))
        (self.raiz / ".git").mkdir()
        self.assertIn("git pull", self.atualizar(github_falso("v9.0.0", zip_da_versao(NOVA))))
        self.assertEqual(self.ler("app.py"), "print('velha')\n")

    def test_zip_estranho_nao_e_aplicado(self):
        r = self.atualizar(github_falso("v1.1.0", zip_da_versao({"leia.txt": "não é o app"})))
        self.assertTrue(r.startswith("falhou"))
        self.assertEqual(self.ler("app.py"), "print('velha')\n")

    def test_aviso_aparece_uma_vez(self):
        self.atualizar(github_falso("v1.1.0", zip_da_versao(NOVA), notas="Painel novo."))
        aviso = atualizador.aviso_pendente(self.raiz)
        self.assertEqual((aviso["de"], aviso["para"], aviso["notas"]), ("v1.0.0", "v1.1.0", "Painel novo."))
        self.assertIsNone(atualizador.aviso_pendente(self.raiz))

    def test_guarda_so_os_ultimos_backups(self):
        from datetime import datetime, timedelta
        for i in range(5):
            atualizador.aplicar(self.raiz, zip_da_versao({**NOVA, "VERSAO": f"v1.{i + 1}.0\n"}), f"v1.{i + 1}.0",
                                pip=self.pip, agora=datetime(2026, 10, 19) + timedelta(minutes=i))
        self.assertEqual(len(list((self.raiz / "backups").glob("codigo-*"))), atualizador.BACKUPS_GUARDADOS)


if __name__ == "__main__":
    unittest.main()
