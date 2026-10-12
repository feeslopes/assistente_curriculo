"""Caminhos e leitura de config.yaml, guidelines.md e prompts."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent

PADROES = {
    "idioma_padrao": "pt",
    "max_paginas": 2,
    "resumo_max_palavras": 70,
    "bullets_por_experiencia": [5, 4, 3, 2],
    "max_grupos_competencias": 6,
    "bullets_sem_fonte": "remover",
    "ordem_secoes": ["resumo", "competencias", "experiencia", "formacao", "certificacoes", "idiomas"],
    "titulos_secoes": {
        "pt": {"resumo": "Resumo", "competencias": "Competências", "experiencia": "Experiência Profissional",
               "formacao": "Formação", "certificacoes": "Certificações", "idiomas": "Idiomas"},
        "en": {"resumo": "Summary", "competencias": "Core Skills", "experiencia": "Professional Experience",
               "formacao": "Education", "certificacoes": "Certifications", "idiomas": "Languages"},
    },
    "meses": {
        "pt": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
               "Setembro", "Outubro", "Novembro", "Dezembro"],
        "en": ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"],
    },
    "atual": {"pt": "Presente", "en": "Present"},
    "separador_datas": "–",
}


def carregar_env() -> None:
    """Lê o .env da raiz, se existir. Não falha se python-dotenv faltar."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(RAIZ / ".env", override=False)


def base_dir() -> Path:
    valor = os.environ.get("CV_BASE_DIR", "").strip()
    return Path(valor).expanduser() if valor else RAIZ / "base"


def saidas_dir() -> Path:
    return RAIZ / "saidas"


def logs_dir() -> Path:
    """Registro das interações com a IA. Fica dentro de saidas/, que o Git ignora."""
    return saidas_dir() / "logs"


def carregar_config(caminho: Path | None = None) -> dict:
    """config.yaml sobre os padrões. Lido a cada chamada, de propósito."""
    caminho = caminho or RAIZ / "config.yaml"
    cfg = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in PADROES.items()}
    if caminho.exists():
        lido = yaml.safe_load(caminho.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(lido, dict):
            raise ValueError("config.yaml precisa ser um mapa de chaves e valores.")
        cfg.update(lido)
    return cfg


def ler_guidelines() -> str:
    caminho = RAIZ / "guidelines.md"
    return caminho.read_text(encoding="utf-8-sig") if caminho.exists() else ""


def ler_prompt(nome: str) -> str:
    caminho = RAIZ / "prompts" / f"{nome}.md"
    if not caminho.exists():
        raise FileNotFoundError(f"Prompt não encontrado: prompts/{nome}.md")
    return caminho.read_text(encoding="utf-8-sig")
