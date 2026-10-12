"""Diagnóstico: confere se tudo está pronto para usar o aplicativo.

Uso:
    python verificar.py              confere ambiente, chave, conexão e exportação
    python verificar.py --modelos    lista os modelos que a sua chave enxerga
    python verificar.py --sem-rede   pula os passos que falam com o provedor
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

falhas: list[str] = []


def ok(msg: str) -> None:
    print(f"[ok]     {msg}")


def falhou(msg: str, dica: str = "") -> None:
    falhas.append(msg)
    print(f"[FALHOU] {msg}")
    if dica:
        print(f"         {dica}")


def aviso(msg: str) -> None:
    print(f"[aviso]  {msg}")


def checar_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        falhou(f"Python {v.major}.{v.minor} é antigo demais.", "Instale o Python 3.10 ou mais novo em python.org.")


def checar_pacotes() -> bool:
    todos = True
    for modulo, pacote in (("streamlit", "streamlit"), ("requests", "requests"), ("yaml", "pyyaml"),
                           ("dotenv", "python-dotenv"), ("reportlab", "reportlab"), ("docx", "python-docx"),
                           ("pypdf", "pypdf")):
        try:
            __import__(modulo)
        except ImportError:
            todos = False
            falhou(f"Pacote '{pacote}' não está instalado.", "Rode: pip install -r requirements.txt")
    if todos:
        ok("Todos os pacotes necessários estão instalados")
    return todos


def checar_pastas() -> None:
    from src import config
    for nome, pasta in (("base", config.base_dir()), ("saidas", config.saidas_dir())):
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=pasta, delete=True):
                pass
            ok(f"Pasta '{nome}' pode ser gravada ({pasta})")
        except OSError as e:
            falhou(f"Não consegui gravar na pasta '{nome}' ({pasta}).", str(e))


def checar_exportacao() -> None:
    from src import config, export, render
    from src.kb import KB
    base = RAIZ / "exemplo" / "base"
    if not base.exists():
        aviso("Pasta 'exemplo' não encontrada: pulei o teste de exportação.")
        return
    kb = KB(base)
    ids = sorted(kb.ids_confirmados())
    exps = kb.experiencias()
    gerado = {
        "titulo": "", "resumo": {"texto": "Teste de exportação do currículo.", "fontes": [ids[0]]},
        "competencias": [], "formacao": [], "certificacoes": [], "idiomas": [],
        "experiencias": [{"id": e.slug, "bullets": [{"texto": "Texto de teste.", "fontes": [f"{e.slug}#1"]}]}
                         for e in exps],
    }
    cv = render.montar(kb, gerado, "pt", config.carregar_config())
    nome = kb.contato().get("nome", "")
    try:
        pdf, paginas = export.gerar_pdf(cv.markdown)
        texto = export.texto_do_pdf(pdf)
        faltando = [t for t in (nome, "Resumo", "Experiência Profissional") if t and t not in texto]
        if faltando:
            falhou(f"O PDF não trouxe como texto: {', '.join(faltando)}.", "Isso atrapalharia a leitura por ATS.")
        else:
            ok(f"PDF gerado ({paginas} página) e o texto é extraível (nome e seções aparecem)")
    except Exception as e:
        falhou(f"Falha ao gerar o PDF: {type(e).__name__}: {e}")
    try:
        from io import BytesIO
        from docx import Document
        doc = Document(BytesIO(export.gerar_docx(cv.markdown)))
        if any(p.style.name == "Heading 2" for p in doc.paragraphs):
            ok("DOCX gerado e relido, com títulos nativos")
        else:
            falhou("O DOCX saiu sem títulos de seção.")
    except Exception as e:
        falhou(f"Falha ao gerar o DOCX: {type(e).__name__}: {e}")


def checar_provedor(listar_modelos: bool, sem_rede: bool) -> None:
    from src import config
    from src.llm import LLM, Configuracao, ErroLLM, completar_json
    config.carregar_env()
    try:
        cfg = Configuracao.do_ambiente()
    except ErroLLM as e:
        falhou(str(e), "Abra o arquivo .env (copie de .env.example) e preencha a chave.")
        return
    ok(f"Provedor {cfg.nome_provedor}, modelo '{cfg.modelo}', chave configurada")
    if sem_rede:
        aviso("Pulei os testes que falam com o provedor (--sem-rede).")
        return
    llm = LLM(cfg)
    if listar_modelos:
        try:
            for m in llm.modelos():
                print("  ", m)
        except ErroLLM as e:
            falhou(str(e))
        return
    try:
        t0 = time.time()
        r = llm.conversar([{"role": "user", "content": "Responda somente com a palavra OK."}], temperatura=0)
        ok(f"Conexão funcionando ({time.time() - t0:.1f}s). Resposta: {r.strip()[:40]!r}")
    except ErroLLM as e:
        falhou(str(e))
        return
    try:
        j = completar_json(llm, [{"role": "user", "content": 'Devolva somente este JSON: {"ok": true}'}])
        if isinstance(j, dict) and j.get("ok") is True:
            ok("O modelo devolve JSON corretamente")
        else:
            aviso(f"O modelo devolveu JSON inesperado: {j!r}. O aplicativo pode errar mais com este modelo.")
    except ErroLLM as e:
        falhou(str(e), "Troque o modelo no arquivo .env (python verificar.py --modelos mostra as opções).")


def main() -> int:
    args = set(sys.argv[1:])
    if "--modelos" in args:
        checar_provedor(True, False)
        return 1 if falhas else 0
    checar_python()
    if not checar_pacotes():
        return 1
    checar_pastas()
    checar_exportacao()
    checar_provedor(False, "--sem-rede" in args)
    print()
    if falhas:
        print(f"{len(falhas)} problema(s) encontrado(s). Resolva os itens marcados [FALHOU] e rode de novo.")
        return 1
    print("Tudo certo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
