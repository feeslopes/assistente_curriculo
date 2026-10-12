"""Base fictícia de exemplo, para testar e demonstrar o aplicativo."""
from __future__ import annotations

import shutil

from . import config
from .kb import KB


def copiar_exemplo(kb: KB) -> bool:
    """Copia exemplo/base para a base SÓ se ela estiver vazia. Devolve True se copiou."""
    origem = config.RAIZ / "exemplo" / "base"
    if not origem.exists():
        return False
    if kb.base.exists() and any(p.name != ".gitkeep" for p in kb.base.iterdir()):
        return False
    shutil.copytree(origem, kb.base, dirs_exist_ok=True)
    return True


def vaga_de_exemplo(idioma: str) -> str:
    caminho = config.RAIZ / "exemplo" / "vagas" / f"vaga_{idioma}.txt"
    return caminho.read_text(encoding="utf-8-sig") if caminho.exists() else ""
