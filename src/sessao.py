"""Persistência da conversa e das revisões pendentes.

Antes, tudo isso vivia só na memória do aplicativo: fechar a janela ou reiniciar apagava a conversa e a
revisão ainda não salva do currículo importado. Agora o estado vai para base/.sessao/sessao.json (dentro da
base, que o Git ignora) e volta quando o aplicativo abre de novo.
"""
from __future__ import annotations

import json
from pathlib import Path

from .interview import FatoProposto, Proposta

NOME = "sessao.json"


def _caminho(base: Path) -> Path:
    return Path(base) / ".sessao" / NOME


def _proposta_para_dict(p: Proposta) -> dict:
    return {"destino": p.destino, "meta": p.meta, "problemas": p.problemas,
            "fatos": [{"texto": f.texto, "origem": f.origem} for f in p.fatos]}


def _proposta_de_dict(d: dict) -> Proposta:
    return Proposta(str(d["destino"]), [FatoProposto(str(f["texto"]), str(f.get("origem", "sugerido")))
                                        for f in d.get("fatos", [])],
                    dict(d.get("meta") or {}), [str(x) for x in d.get("problemas", [])])


def _lista_de_propostas(brutas) -> list[Proposta]:
    saida = []
    for d in brutas or []:
        try:
            saida.append(_proposta_de_dict(d))
        except (KeyError, TypeError, AttributeError):
            continue   # um item estragado não impede de recuperar o resto
    return saida


def salvar(base: Path, chat: list[dict], rev_importacao, rev_entrevista) -> None:
    """Grava o estado. Se não há nada a guardar, remove o arquivo. Nunca levanta erro de disco."""
    caminho = _caminho(base)
    try:
        if not (chat or rev_importacao or rev_entrevista):
            caminho.unlink(missing_ok=True)
            return
        dados = {
            "chat": [{"role": m["role"], "content": m["content"]} for m in chat],
            "rev_importacao": [_proposta_para_dict(p) for p in rev_importacao or []],
            "rev_entrevista": [_proposta_para_dict(p) for p in rev_entrevista or []],
        }
        texto = json.dumps(dados, ensure_ascii=False, indent=1)
        if caminho.exists() and caminho.read_text(encoding="utf-8") == texto:
            return
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_suffix(".tmp")
        tmp.write_text(texto, encoding="utf-8", newline="\n")
        tmp.replace(caminho)
    except (OSError, KeyError, TypeError):
        pass


def carregar(base: Path) -> dict:
    """Devolve {"chat", "rev_importacao", "rev_entrevista"} (vazios se não há nada ou o arquivo está ruim)."""
    vazio = {"chat": [], "rev_importacao": [], "rev_entrevista": []}
    try:
        dados = json.loads(_caminho(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vazio
    if not isinstance(dados, dict):
        return vazio
    chat = [{"role": m["role"], "content": str(m["content"])} for m in dados.get("chat", [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and "content" in m]
    return {"chat": chat,
            "rev_importacao": _lista_de_propostas(dados.get("rev_importacao")),
            "rev_entrevista": _lista_de_propostas(dados.get("rev_entrevista"))}
