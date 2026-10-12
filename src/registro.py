"""Leitura do registro de interações com a IA (gravado por llm.LLM em saidas/logs/AAAA-MM-DD.jsonl)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config


def ativo() -> bool:
    """O registro fica ligado, a menos que o .env tenha CV_LOG=0."""
    return os.environ.get("CV_LOG", "1").strip() not in ("0", "false", "nao", "não")


def pasta() -> Path:
    return config.logs_dir()


def arquivos(raiz: Path | None = None) -> list[Path]:
    """Arquivos do registro, do mais novo para o mais antigo."""
    raiz = raiz or pasta()
    return sorted(raiz.glob("*.jsonl"), reverse=True) if raiz.is_dir() else []


def ler(arquivo: Path) -> list[dict]:
    registros = []
    try:
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if isinstance(r, dict):
                registros.append(r)
    except OSError:
        pass
    return registros


def ultimos(n: int = 5, raiz: Path | None = None) -> list[dict]:
    """Os n registros mais recentes (do mais novo para o mais antigo)."""
    saida: list[dict] = []
    for arq in arquivos(raiz):
        saida += list(reversed(ler(arq)))
        if len(saida) >= n:
            break
    return saida[:n]


def resumo(r: dict) -> str:
    hora = str(r.get("quando", ""))[11:19]
    erro = f" ERRO: {r['erro']}" if r.get("erro") else ""
    return f"{hora} · {r.get('rotulo') or 'sem rótulo'} · {r.get('duracao_s', '?')}s{erro}"
