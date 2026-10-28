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
    "experiencias_antigas": {"ativo": True, "anos": 10, "mais_antigas": 2, "max_bullets": 1, "max_bullets_relevante": 3},
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


class SemUsuario(Exception):
    """Modo hospedado sem usuário autenticado na requisição. O app para: nunca cai em uma pasta padrão."""


_resolvedor_usuario = None


def modo_hospedado() -> bool:
    """CV_MODO=hospedado liga o servidor multiusuário. Qualquer outro valor é o aplicativo local de sempre."""
    return os.environ.get("CV_MODO", "").strip().lower() == "hospedado"


def registrar_resolvedor_usuario(funcao) -> None:
    """Quem diz, a cada chamada, qual a pasta do usuário desta requisição (ou None se não houver)."""
    global _resolvedor_usuario
    _resolvedor_usuario = funcao


def raiz_usuario() -> Path:
    """Pasta do usuário autenticado (só no modo hospedado). Falha fechada: sem usuário, levanta SemUsuario."""
    raiz = _resolvedor_usuario() if _resolvedor_usuario else None
    if not raiz:
        raise SemUsuario("Não há usuário autenticado nesta requisição.")
    return Path(raiz)


def base_dir() -> Path:
    if modo_hospedado():
        # CV_BASE_DIR é ignorado de propósito: no servidor, a pasta só vem da identidade verificada.
        return raiz_usuario() / "base"
    valor = os.environ.get("CV_BASE_DIR", "").strip()
    return Path(valor).expanduser() if valor else RAIZ / "base"


def saidas_dir() -> Path:
    if modo_hospedado():
        return raiz_usuario() / "saidas"
    return RAIZ / "saidas"


def logs_dir() -> Path:
    """Registro das interações com a IA. Local: dentro de saidas/, que o Git ignora. Hospedado: pasta do usuário."""
    if modo_hospedado():
        return raiz_usuario() / "logs"
    return saidas_dir() / "logs"


def modelos_por_etapa() -> dict:
    """Modelo de cada etapa (rotulo da chamada) lido do config.yaml. Vazio = tudo no modelo padrão do .env."""
    try:
        valor = carregar_config().get("modelos_por_etapa") or {}
    except (ValueError, OSError):
        return {}
    return {str(k): str(v) for k, v in valor.items()} if isinstance(valor, dict) else {}


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
