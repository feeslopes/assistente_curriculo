"""Atualização automática a partir das versões publicadas no GitHub (Releases).

Roda no `iniciar`, antes de abrir o aplicativo. Usa só a biblioteca padrão do Python, para funcionar mesmo que os
pacotes do aplicativo estejam com problema.

Regras:
- Só atualiza para uma versão PUBLICADA (Release com tag vX.Y.Z), nunca para qualquer mudança na main.
- Nunca toca nos dados: base/, saidas/, backups/, .env e .venv/ não são lidos nem escritos pela atualização.
- Antes de trocar o código, guarda uma cópia do código atual e uma do histórico (base/) em backups/.
- Qualquer erro no meio desfaz tudo e o aplicativo abre na versão de antes.
- Sem internet, sem versão nova, ou numa pasta de desenvolvimento (com .git), não faz nada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO = "feeslopes/assistente_curriculo"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ARQ_VERSAO = "VERSAO"                     # versão do código, versionada no repositório
ARQ_INSTALADA = ".versao_instalada"       # versão que o atualizador instalou (vale mais que VERSAO)
ARQ_MANIFESTO = ".manifesto"              # arquivos da versão instalada, para apagar os que saírem na próxima
ARQ_AVISO = ".atualizacao.json"           # o aplicativo mostra uma vez "atualizado para a versão X"
# pastas e arquivos que a atualização nunca lê nem escreve
PROTEGIDOS = ("base", "saidas", "backups", ".venv", ".env", ".git", ".claude", "__pycache__")
# scripts de início: o Windows lê o .bat aos pedaços enquanto ele roda; a troca acontece no próximo início
LANCADORES = ("iniciar.bat", "iniciar.sh")
LIMITE_DOWNLOAD = 50 * 1024 * 1024
CRLF, LF = bytes([13, 10]), bytes([10])
BACKUPS_GUARDADOS = 3


class ErroAtualizacao(Exception):
    pass


def numero(tag: str) -> tuple[int, ...]:
    """'v1.2.10' -> (1, 2, 10). Tag sem número vira (0,)."""
    partes = re.findall(r"\d+", str(tag or ""))
    return tuple(int(p) for p in partes) or (0,)


def protegido(rel: str) -> bool:
    primeira = rel.replace("\\", "/").split("/")[0]
    return primeira in PROTEGIDOS or "__pycache__" in rel or rel.endswith(".pyc")


def versao_local(raiz: Path) -> str:
    for nome in (ARQ_INSTALADA, ARQ_VERSAO):
        p = raiz / nome
        if p.exists():
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
    return "0"


def _baixar(url: str, abrir, timeout: int, limite: int | None = None) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": "curriculo-sob-medida",
                                                  "Accept": "application/vnd.github+json"})
    with abrir(pedido, timeout=timeout) as r:
        dados = r.read(limite + 1) if limite else r.read()
    if limite and len(dados) > limite:
        raise ErroAtualizacao("O arquivo da versão nova é grande demais.")
    return dados


def ultima_versao(abrir=urllib.request.urlopen, timeout: int = 6) -> dict | None:
    """A última versão publicada: {"tag", "zip", "notas", "nome"}. None sem internet ou sem versão publicada."""
    try:
        d = json.loads(_baixar(API, abrir, timeout).decode("utf-8"))
    except Exception:   # sem internet, GitHub fora, limite de consultas: segue com a versão atual
        return None
    if not isinstance(d, dict) or not d.get("tag_name") or not d.get("zipball_url"):
        return None
    return {"tag": d["tag_name"], "zip": d["zipball_url"], "notas": str(d.get("body") or "").strip(),
            "nome": str(d.get("name") or d["tag_name"])}


def _arquivos(pasta: Path) -> set[str]:
    return {p.relative_to(pasta).as_posix() for p in pasta.rglob("*")
            if p.is_file() and not protegido(p.relative_to(pasta).as_posix())}


def _extrair(dados: bytes, destino: Path) -> Path:
    """Extrai o zip do GitHub (uma pasta raiz dentro) com proteção contra caminhos que saem da pasta."""
    destino.mkdir(parents=True, exist_ok=True)
    zip_path = destino / "versao.zip"
    zip_path.write_bytes(dados)
    with zipfile.ZipFile(zip_path) as z:
        for nome in z.namelist():
            alvo = (destino / "x" / nome).resolve()
            if not str(alvo).startswith(str((destino / "x").resolve())):
                raise ErroAtualizacao("O arquivo da versão nova tem um caminho inválido.")
        z.extractall(destino / "x")
    raizes = [p for p in (destino / "x").iterdir() if p.is_dir()]
    if len(raizes) != 1 or not (raizes[0] / "app.py").exists():
        raise ErroAtualizacao("O arquivo da versão nova não parece ser do aplicativo.")
    return raizes[0]


def _texto(p: Path) -> str:
    """Conteúdo para comparar versões, sem diferença de fim de linha (Windows grava CRLF, o GitHub entrega LF)."""
    return p.read_bytes().replace(CRLF, LF).decode("utf-8", "replace") if p.exists() else ""


def _limpar_backups(pasta: Path, prefixo: str) -> None:
    antigos = sorted(p for p in pasta.glob(f"{prefixo}-*") if p.is_dir())
    for p in antigos[:-BACKUPS_GUARDADOS]:
        shutil.rmtree(p, ignore_errors=True)


def _pip(raiz: Path) -> None:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(raiz / "requirements.txt")],
                       cwd=raiz)
    if r.returncode != 0:
        raise ErroAtualizacao("Não consegui instalar as bibliotecas da versão nova.")


def aplicar(raiz: Path, dados_zip: bytes, tag: str, notas: str = "", pip=_pip, agora: datetime | None = None) -> dict:
    """Troca o código pela versão do zip, preservando os dados. Desfaz tudo se algo falhar."""
    agora = agora or datetime.now()
    carimbo = agora.strftime("%Y%m%d-%H%M%S")
    de = versao_local(raiz)
    backups = raiz / "backups"
    copia_codigo = backups / f"codigo-{carimbo}"
    escritos: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        nova = _extrair(dados_zip, Path(tmp))
        novos = _arquivos(nova)
        atuais = _arquivos(raiz)
        # 1) cópias de segurança: o código de agora e o histórico
        for rel in atuais:
            (copia_codigo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raiz / rel, copia_codigo / rel)
        if (raiz / "base").is_dir():
            shutil.copytree(raiz / "base", backups / f"base-{carimbo}", dirs_exist_ok=True)
        req_antes = _texto(raiz / "requirements.txt")
        manifesto = raiz / ARQ_MANIFESTO
        anteriores = set(manifesto.read_text(encoding="utf-8").split("\n")) - {""} if manifesto.exists() else set()
        try:
            # 2) arquivos novos e alterados
            for rel in sorted(novos):
                origem, alvo = nova / rel, raiz / rel
                if rel in LANCADORES and alvo.exists():
                    if _texto(alvo) != _texto(origem):
                        shutil.copy2(origem, alvo.with_name(alvo.name + ".novo"))
                        escritos.append(rel + ".novo")
                    continue
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, alvo)
                escritos.append(rel)
            # 3) arquivos que a versão anterior instalou e a nova não tem mais
            for rel in sorted(anteriores - novos):
                if not protegido(rel) and (raiz / rel).is_file():
                    (raiz / rel).unlink()
            # 4) bibliotecas, só se mudaram
            if _texto(raiz / "requirements.txt") != req_antes:
                pip(raiz)
        except Exception:
            _desfazer(raiz, copia_codigo, atuais, escritos)
            raise
    manifesto.write_text("\n".join(sorted(novos)) + "\n", encoding="utf-8")
    (raiz / ARQ_INSTALADA).write_text(tag + "\n", encoding="utf-8")
    aviso = {"de": de, "para": tag, "notas": notas[:2000], "data": agora.isoformat(timespec="seconds"),
             "mostrado": False}
    (raiz / ARQ_AVISO).write_text(json.dumps(aviso, ensure_ascii=False, indent=1), encoding="utf-8")
    _limpar_backups(backups, "codigo")
    _limpar_backups(backups, "base")
    return aviso


def _desfazer(raiz: Path, copia: Path, atuais: set[str], escritos: list[str]) -> None:
    """Volta o código para como estava: restaura a cópia e apaga o que a versão nova acrescentou."""
    for rel in escritos:
        if rel not in atuais and (raiz / rel).is_file():
            (raiz / rel).unlink()
    for rel in atuais:
        (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copia / rel, raiz / rel)


def verificar_e_atualizar(raiz: Path, abrir=urllib.request.urlopen, pip=_pip, saida=print) -> str:
    """O que o `iniciar` chama. Nunca levanta exceção: no pior caso, abre a versão de antes. Devolve o que fez."""
    if (raiz / ".git").exists():
        return "pasta de desenvolvimento (git): atualize com git pull"
    if os.environ.get("CV_NAO_ATUALIZAR", "").strip() == "1":
        return "atualização desligada (CV_NAO_ATUALIZAR=1)"
    ultima = ultima_versao(abrir)
    if not ultima:
        return "sem informação de versão nova (sem internet ou nada publicado)"
    atual = versao_local(raiz)
    if numero(ultima["tag"]) <= numero(atual):
        return f"já está na versão mais recente ({atual})"
    saida(f"Há uma versão nova ({ultima['tag']}). Atualizando, isso leva um minuto...")
    try:
        dados = _baixar(ultima["zip"], abrir, 60, LIMITE_DOWNLOAD)
        aplicar(raiz, dados, ultima["tag"], ultima["notas"], pip)
    except Exception as e:  # noqa: BLE001 - qualquer falha: a versão de antes continua de pé
        saida(f"Não consegui atualizar agora ({e}). O aplicativo abre na versão de antes.")
        return f"falhou: {e}"
    saida(f"Pronto: versão {ultima['tag']} instalada. O seu histórico não foi alterado.")
    return f"atualizado para {ultima['tag']}"


def aviso_pendente(raiz: Path) -> dict | None:
    """Para o aplicativo: a atualização recente que ainda não foi mostrada (e marca como mostrada)."""
    p = raiz / ARQ_AVISO
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("mostrado"):
        return None
    d["mostrado"] = True
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d
