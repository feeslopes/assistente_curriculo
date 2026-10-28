"""Administração do acesso, para o dono do serviço rodar no servidor.

    python -m servidor.admin liberar maria@exemplo.com --plano mensal          # depois de receber o Pix
    python -m servidor.admin liberar joao@exemplo.com --plano semanal --dias 7
    python -m servidor.admin listar
    python -m servidor.admin revogar maria@exemplo.com                           # derruba as sessões na hora
    python -m servidor.admin excluir maria@exemplo.com                           # LGPD: apaga conta, sessões e a pasta de dados
    python -m servidor.admin metricas                                            # cliques, visitas e uso agregado, sem conteúdo
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src import config, hospedado

from . import seguranca
from .banco import Banco


def _data(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y")


def _planos() -> dict:
    return config.carregar_config().get("planos") or {}


def liberar(banco: Banco, email: str, plano: str, dias: int | None, teto: int | None) -> dict:
    planos = _planos()
    if plano not in planos:
        raise SystemExit(f"Plano '{plano}' não existe. Use um de: {', '.join(planos) or '(nenhum no config.yaml)'}.")
    dias = dias or int(planos[plano].get("dias", 30))
    return banco.liberar(email, plano, dias, teto)


def excluir(banco: Banco, email: str, pasta_dados: Path) -> str | None:
    """Apaga o acesso e a pasta do usuário. Devolve o uid apagado, ou None se o e-mail não existe."""
    uid = banco.excluir_usuario(email)
    if uid:
        pasta = (pasta_dados / "usuarios" / uid).resolve()
        if pasta_dados.resolve() in pasta.parents and pasta.is_dir():
            shutil.rmtree(pasta, ignore_errors=False)
    return uid


def metricas(banco: Banco) -> dict:
    with banco._con() as c:
        eventos = c.execute("SELECT nome, COUNT(*) n FROM eventos GROUP BY nome ORDER BY n DESC").fetchall()
        custo = c.execute("SELECT dados FROM eventos WHERE nome='ia_chamada'").fetchall()
        cliques = c.execute("SELECT plano, SUM(n) n FROM cliques GROUP BY plano").fetchall()
        visitas = c.execute("SELECT COALESCE(SUM(n),0) n FROM visitas").fetchone()["n"]
        usuarios = c.execute("SELECT COUNT(DISTINCT anon) n FROM eventos").fetchone()["n"]
    gasto = sum(json.loads(r["dados"]).get("custo_usd") or 0 for r in custo)
    return {"visitas_landing": visitas, "cliques_whatsapp": {r["plano"]: r["n"] for r in cliques},
            "usuarios_com_atividade": usuarios, "eventos": {r["nome"]: r["n"] for r in eventos},
            "custo_ia_usd": round(gasto, 4)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("liberar", "revogar", "excluir"):
        p = sub.add_parser(nome)
        p.add_argument("email")
        if nome == "liberar":
            p.add_argument("--plano", required=True)
            p.add_argument("--dias", type=int)
            p.add_argument("--teto", type=int, help="substitui o teto de gerações do plano para este cliente")
    sub.add_parser("listar")
    sub.add_parser("metricas")
    a = ap.parse_args(argv)

    seguranca.segredo()
    banco = hospedado.banco()
    if a.cmd == "liberar":
        r = liberar(banco, a.email, a.plano, a.dias, a.teto)
        print(f"Liberado: {r['email']} no plano {r['plano']} até {_data(r['fim'])}" + (f" (teto {r['teto']})" if r["teto"] else ""))
    elif a.cmd == "revogar":
        print("Revogado." if banco.revogar(a.email) else "E-mail não encontrado.")
    elif a.cmd == "excluir":
        uid = excluir(banco, a.email, hospedado.pasta_de_dados())
        print("Conta e dados apagados." if uid else "E-mail não encontrado.")
    elif a.cmd == "listar":
        agora = datetime.now().timestamp()
        for r in banco.listar():
            estado = "revogado" if r["revogado"] else ("vencido" if r["fim"] < agora else "ativo")
            print(f"{r['email']:40} {r['plano']:8} até {_data(r['fim'])}  {estado}")
    elif a.cmd == "metricas":
        print(yaml.safe_dump(metricas(banco), allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    sys.exit(main())
