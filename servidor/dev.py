"""Sobe o servidor de acesso no seu computador, só para olhar a landing e o login (dados de teste, e-mail no log).

    python -m servidor.dev            # http://localhost:8080

Cria um banco temporário em dados_dev/ (fora do Git) com um acesso de teste: teste@exemplo.com. Não use em produção.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("CV_ENV", "dev")
os.environ.setdefault("CV_SEGREDO", "dev-" + "x" * 44)
os.environ.setdefault("CV_URL_PUBLICA", "http://localhost:8080")
os.environ.setdefault("WHATSAPP_NUMERO", "5511900000000")
os.environ.setdefault("CV_DADOS_DIR", str(Path(__file__).resolve().parent.parent / "dados_dev"))


def main() -> None:
    import uvicorn

    from .banco import Banco
    from .gateway import app_do_ambiente

    if os.environ.get("CV_ENV") != "dev":
        sys.exit("servidor.dev só roda com CV_ENV=dev.")
    Banco(Path(os.environ["CV_DADOS_DIR"]) / "servidor.db").liberar("teste@exemplo.com", "mensal", 30)
    uvicorn.run(app_do_ambiente(), host="127.0.0.1", port=int(os.environ.get("PORT", "8080")), log_level="info")


if __name__ == "__main__":
    main()
