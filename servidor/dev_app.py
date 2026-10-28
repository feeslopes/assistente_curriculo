"""Abre o app completo em modo hospedado no seu computador, sem proxy e sem login, com um usuário de teste.

    python -m servidor.dev_app                  # http://localhost:8502, usuário teste@exemplo.com, plano mensal
    python -m servidor.dev_app --plano semanal --teto 3 --usuario outra@exemplo.com

Serve para testar teto de uso, isolamento entre usuários (rode com --usuario diferente), telas e o que some no servidor.
Os dados ficam em dados_dev/ (fora do Git). A IA é a do seu .env, então cada geração gasta tokens de verdade.
É um atalho que CONTORNA a autenticação: só funciona com CV_ENV=dev, e o app se recusa a abrir se CV_DEV_USUARIO
aparecer em qualquer outro ambiente.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usuario", default="teste@exemplo.com")
    ap.add_argument("--plano", default="mensal", choices=("mensal", "semanal"))
    ap.add_argument("--teto", type=int, help="teto de gerações do período (padrão: o do plano no config.yaml)")
    ap.add_argument("--porta", type=int, default=8502)
    a = ap.parse_args(argv)

    env = dict(os.environ)
    env.update({"CV_MODO": "hospedado", "CV_ENV": "dev", "CV_DEV_USUARIO": a.usuario, "CV_DEV_PLANO": a.plano,
                "CV_DADOS_DIR": str(RAIZ / "dados_dev")})
    env.setdefault("CV_SEGREDO", "dev-" + "x" * 44)
    if a.teto:
        env["CV_DEV_TETO"] = str(a.teto)
    print(f"Abrindo http://localhost:{a.porta} como {a.usuario} (plano {a.plano}). Ctrl+C para parar.")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", "app.py", "--server.address=127.0.0.1",
                            f"--server.port={a.porta}", "--server.maxUploadSize=8", "--client.showErrorDetails=none",
                            "--browser.gatherUsageStats=false"], cwd=RAIZ, env=env)


if __name__ == "__main__":
    sys.exit(main())
