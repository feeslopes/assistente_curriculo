"""Base de conhecimento em Markdown.

Cada fato é uma linha `- [confirmado] texto` ou `- [sugerido] texto`. O id é `slug#n`, onde n é a
ordem da linha marcada dentro do arquivo. Todas as operações agem por linha, para preservar qualquer
texto livre que a pessoa escreva à mão. Ids deslocam quando um fato é removido: não guarde ids.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .texto import detectar_idioma, normalizar, slugify

MARCA = re.compile(r"^(\s*[-*+]\s*)\[(confirmado|sugerido)\]\s*(.*\S)\s*$", re.I)
ARQUIVOS_FATOS = ("perfil", "habilidades", "formacao", "certificacoes", "idiomas")
DATA_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CHAVES_CONTATO = ("nome", "titulo_padrao", "titulo_padrao_en", "local", "telefone", "email", "linkedin", "site")


class ErroBase(Exception):
    """Problema na base, já em português."""


@dataclass
class Fato:
    id: str
    slug: str
    n: int
    status: str  # confirmado | sugerido
    texto: str
    linha: int   # índice da linha no arquivo


@dataclass
class Arquivo:
    slug: str
    caminho: Path
    linhas: list[str]
    corpo_ini: int
    meta: dict = field(default_factory=dict)

    @property
    def eh_experiencia(self) -> bool:
        return self.caminho.parent.name == "experiencias"

    def fatos(self) -> list[Fato]:
        saida, n = [], 0
        for i in range(self.corpo_ini, len(self.linhas)):
            m = MARCA.match(self.linhas[i])
            if m:
                n += 1
                saida.append(Fato(f"{self.slug}#{n}", self.slug, n, m.group(2).lower(), m.group(3).strip(), i))
        return saida

    def sem_marca(self) -> int:
        """Linhas de conteúdo que a IA ignora por não terem marca."""
        c = 0
        for i in range(self.corpo_ini, len(self.linhas)):
            t = self.linhas[i].strip()
            if not t or t.startswith("#") or t.startswith("<!--") or MARCA.match(self.linhas[i]):
                continue
            c += 1
        return c

    # ---------------------------------------------------------------- leitura/escrita
    @classmethod
    def ler(cls, caminho: Path, slug: str) -> "Arquivo":
        texto = caminho.read_text(encoding="utf-8-sig")
        linhas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        corpo_ini, meta = 0, {}
        if linhas and linhas[0].strip() == "---":
            fim = next((j for j in range(1, len(linhas)) if linhas[j].strip() == "---"), None)
            if fim is None:
                raise ErroBase(f"{caminho.name}: o cabeçalho (---) não foi fechado.")
            try:
                meta = yaml.safe_load("\n".join(linhas[1:fim])) or {}
            except yaml.YAMLError as e:
                raise ErroBase(f"{caminho.name}: cabeçalho inválido ({str(e).splitlines()[0]}).") from None
            if not isinstance(meta, dict):
                raise ErroBase(f"{caminho.name}: o cabeçalho precisa ter campos 'chave: valor'.")
            corpo_ini = fim + 1
        return cls(slug, caminho, linhas, corpo_ini, meta)

    def gravar(self) -> None:
        while self.linhas and self.linhas[-1].strip() == "":
            self.linhas.pop()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.linhas) + "\n")


def validar_meta_experiencia(meta: dict, nome: str = "") -> dict:
    """Normaliza e valida o cabeçalho de uma experiência. Levanta ErroBase."""
    prefixo = f"{nome}: " if nome else ""
    m = {k: ("" if v is None else v) for k, v in meta.items()}
    for campo in ("empresa", "cargo"):
        if not str(m.get(campo, "")).strip():
            raise ErroBase(f"{prefixo}falta o campo '{campo}'.")
        m[campo] = str(m[campo]).strip()
    m["inicio"] = str(m.get("inicio", "")).strip()
    if not DATA_RE.match(m["inicio"]):
        raise ErroBase(f"{prefixo}'inicio' precisa estar no formato AAAA-MM (ex.: 2022-03).")
    fim = str(m.get("fim", "")).strip().lower()
    if fim in ("atual", "presente", "present", "current"):
        fim = "atual"
    if fim != "atual" and not DATA_RE.match(fim):
        raise ErroBase(f"{prefixo}'fim' precisa ser AAAA-MM ou 'atual'.")
    m["fim"] = fim
    if fim != "atual" and fim < m["inicio"]:
        raise ErroBase(f"{prefixo}'fim' é anterior a 'inicio'.")
    for campo in ("local", "cargo_en", "local_en", "cargo_pt", "local_pt"):
        if campo in m:
            m[campo] = str(m[campo]).strip()
    m["ocultar"] = bool(m.get("ocultar", False))
    m["tipo"] = "experiencia"
    return m


def _norm_fato(texto: str) -> str:
    return re.sub(r"[^\w\s%]", "", normalizar(texto)).strip()


def montar_texto_experiencia(meta: dict, linhas: list[str] | None = None) -> str:
    ordem = ["tipo", "empresa", "cargo", "cargo_en", "cargo_pt", "inicio", "fim", "local", "local_en", "local_pt", "ocultar"]
    meta = dict(meta)
    meta.setdefault("tipo", "experiencia")
    ordenado = {k: meta[k] for k in ordem if k in meta and (meta[k] != "" or k in ("fim",))}
    for k, v in meta.items():
        if k not in ordenado and v != "":
            ordenado[k] = v
    cab = yaml.safe_dump(ordenado, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()
    corpo = "\n".join(linhas or [])
    return f"---\n{cab}\n---\n{corpo}\n"


class KB:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.erros: list[str] = []

    # --------------------------------------------------------------------- carga
    def _caminho(self, slug: str) -> Path | None:
        if slug in ARQUIVOS_FATOS:
            return self.base / f"{slug}.md"
        p = self.base / "experiencias" / f"{slug}.md"
        return p if p.exists() else None

    def arquivos(self) -> dict[str, Arquivo]:
        """Lê tudo do disco. Arquivos com problema vão para self.erros e ficam de fora."""
        self.erros = []
        saida: dict[str, Arquivo] = {}
        candidatos = [(s, self.base / f"{s}.md") for s in ARQUIVOS_FATOS]
        pasta = self.base / "experiencias"
        if pasta.is_dir():
            candidatos += [(p.stem, p) for p in sorted(pasta.glob("*.md"))]
        for slug, caminho in candidatos:
            if not caminho.exists():
                continue
            try:
                arq = Arquivo.ler(caminho, slug)
                if arq.eh_experiencia:
                    arq.meta = validar_meta_experiencia(arq.meta, caminho.name)
                saida[slug] = arq
            except ErroBase as e:
                self.erros.append(str(e))
        return saida

    def experiencias(self, incluir_ocultas: bool = False) -> list[Arquivo]:
        """Da mais recente para a mais antiga (cargo atual primeiro, depois por início)."""
        exps = [a for a in self.arquivos().values() if a.eh_experiencia]
        if not incluir_ocultas:
            exps = [a for a in exps if not a.meta.get("ocultar")]
        chave = lambda a: ("9999-99" if a.meta["fim"] == "atual" else a.meta["fim"], a.meta["inicio"])
        return sorted(exps, key=chave, reverse=True)

    def fatos(self, status: str | None = None) -> list[Fato]:
        saida = []
        for arq in self.arquivos().values():
            for f in arq.fatos():
                if status is None or f.status == status:
                    saida.append(f)
        return saida

    def ids_confirmados(self, incluir_ocultas: bool = False) -> set[str]:
        ocultos = set()
        if not incluir_ocultas:
            ocultos = {a.slug for a in self.experiencias(True) if a.meta.get("ocultar")}
        return {f.id for f in self.fatos("confirmado") if f.slug not in ocultos}

    def fato(self, id_: str) -> Fato | None:
        return next((f for f in self.fatos() if f.id == id_), None)

    def composicao_idiomas(self) -> dict:
        """Quantos fatos confirmados estão em cada idioma (heurística local; fato curto fica indefinido)."""
        cont = {"pt": 0, "en": 0, "indefinido": 0}
        for f in self.fatos("confirmado"):
            cont[detectar_idioma(f.texto, min_palavras=8) or "indefinido"] += 1
        return cont

    def idioma_base(self) -> str:
        """Idioma dominante dos fatos (pt se não der para saber)."""
        c = self.composicao_idiomas()
        if c["pt"] != c["en"]:
            return "pt" if c["pt"] > c["en"] else "en"
        return detectar_idioma(" ".join(self.textos_confirmados())) or "pt"

    def mistura_idiomas(self) -> bool:
        """True se a base tem uma quantidade relevante de fatos nos dois idiomas."""
        c = self.composicao_idiomas()
        menor, total = min(c["pt"], c["en"]), c["pt"] + c["en"]
        return total >= 5 and menor / total >= 0.2

    def linhas_sem_marca(self) -> int:
        return sum(a.sem_marca() for a in self.arquivos().values())

    def lacunas(self) -> list[dict]:
        """O que ainda falta na base, para o entrevistador perguntar só isso.

        Cada item: {"tipo", "slug", "rotulo", "empresa", "cargo"}. Tipos: sem_experiencias, poucos_fatos,
        sem_numeros (experiência sem nenhum número registrado) e secao_vazia (formação, idiomas...).
        """
        arqs = self.arquivos()
        exps = self.experiencias()
        saida: list[dict] = []
        if not exps:
            saida.append({"tipo": "sem_experiencias", "slug": "", "rotulo": "experiências profissionais",
                          "empresa": "", "cargo": ""})
        for a in exps:
            fs = a.fatos()
            base = {"slug": a.slug, "empresa": a.meta["empresa"], "cargo": a.meta["cargo"]}
            nome = f"{a.meta['cargo']} na {a.meta['empresa']}"
            if len(fs) < 3:
                saida.append({"tipo": "poucos_fatos", "rotulo": f"{nome}: poucos detalhes ({len(fs)} fato(s))", **base})
            elif not re.search(r"\d", " ".join(f.texto for f in fs)):
                saida.append({"tipo": "sem_numeros", "rotulo": f"{nome}: nenhum número ou resultado medido", **base})
        for slug, rotulo in (("formacao", "formação"), ("idiomas", "idiomas"),
                             ("habilidades", "ferramentas e habilidades"), ("perfil", "objetivo profissional")):
            a = arqs.get(slug)
            if not a or not a.fatos():
                saida.append({"tipo": "secao_vazia", "slug": slug, "rotulo": rotulo, "empresa": "", "cargo": ""})
        return saida

    def diagnostico(self) -> list[str]:
        """Avisos sobre uma base que provavelmente está incompleta (a análise de vaga só enxerga o confirmado)."""
        avisos = []
        confirmados = len(self.fatos("confirmado"))
        pendentes = len(self.fatos("sugerido"))
        if pendentes:
            avisos.append(f"{pendentes} fato(s) pendente(s) NÃO contam na análise. Confirme ou remova na aba Minha base.")
        vazias = [r["rotulo"] for r in self.lacunas() if r["tipo"] == "secao_vazia"]
        if vazias:
            avisos.append("A base não tem: " + ", ".join(vazias) + ". Se você importou um currículo, confira se salvou a revisão.")
        if len(self.experiencias()) < 2 and confirmados:
            avisos.append("A base tem menos de duas experiências. Se o seu histórico é maior, algo não foi salvo.")
        return avisos

    def vazia(self) -> bool:
        return not self.fatos() and not self.contato()

    # ------------------------------------------------------------------ escrita
    def adicionar_fatos(self, slug: str, textos: list[str], status: str = "confirmado") -> dict:
        """Acrescenta fatos ao fim do arquivo, deduplicando pelo texto normalizado.

        Se o fato já existe como [sugerido] e agora é confirmado, ele é promovido no lugar.
        """
        if status not in ("confirmado", "sugerido"):
            raise ErroBase(f"Status inválido: {status}")
        caminho = self._caminho(slug)
        if caminho is None:
            raise ErroBase(f"Destino desconhecido: '{slug}'. Crie a experiência antes de gravar fatos nela.")
        arq = Arquivo.ler(caminho, slug) if caminho.exists() else Arquivo(slug, caminho, [], 0, {})
        existentes = {_norm_fato(f.texto): f for f in arq.fatos()}
        res = {"adicionados": 0, "ignorados": 0, "promovidos": 0}
        for texto in textos:
            texto = " ".join(str(texto).split())
            if not texto:
                continue
            chave = _norm_fato(texto)
            ja = existentes.get(chave)
            if ja:
                if ja.status == "sugerido" and status == "confirmado":
                    self._trocar_marca(arq, ja.linha, "confirmado")
                    ja.status = "confirmado"
                    res["promovidos"] += 1
                else:
                    res["ignorados"] += 1
                continue
            while arq.linhas and arq.linhas[-1].strip() == "":
                arq.linhas.pop()
            arq.linhas.append(f"- [{status}] {texto}")
            novo = Fato("", slug, 0, status, texto, len(arq.linhas) - 1)
            existentes[chave] = novo
            res["adicionados"] += 1
        arq.gravar()
        return res

    @staticmethod
    def _trocar_marca(arq: Arquivo, linha: int, status: str) -> None:
        m = MARCA.match(arq.linhas[linha])
        arq.linhas[linha] = f"{m.group(1)}[{status}] {m.group(3).strip()}"

    def _localizar(self, id_: str) -> tuple[Arquivo, Fato]:
        slug = id_.split("#", 1)[0]
        caminho = self._caminho(slug)
        if caminho is None or not caminho.exists():
            raise ErroBase(f"Fato '{id_}' não encontrado.")
        arq = Arquivo.ler(caminho, slug)
        fato = next((f for f in arq.fatos() if f.id == id_), None)
        if not fato:
            raise ErroBase(f"Fato '{id_}' não encontrado.")
        return arq, fato

    def confirmar(self, id_: str) -> None:
        arq, f = self._localizar(id_)
        self._trocar_marca(arq, f.linha, "confirmado")
        arq.gravar()

    def remover(self, id_: str) -> None:
        arq, f = self._localizar(id_)
        del arq.linhas[f.linha]
        arq.gravar()

    def atualizar_texto(self, id_: str, texto: str) -> None:
        arq, f = self._localizar(id_)
        m = MARCA.match(arq.linhas[f.linha])
        arq.linhas[f.linha] = f"{m.group(1)}[{f.status}] {' '.join(texto.split())}"
        arq.gravar()

    def criar_experiencia(self, meta: dict) -> str:
        m = validar_meta_experiencia(meta)
        base_slug = slugify(f"{m['empresa']}-{m['cargo']}")
        slug, i = base_slug, 2
        while (self.base / "experiencias" / f"{slug}.md").exists():
            slug, i = f"{base_slug}-{i}", i + 1
        caminho = self.base / "experiencias" / f"{slug}.md"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "w", encoding="utf-8", newline="\n") as f:
            f.write(montar_texto_experiencia(m))
        return slug

    def definir_traducao(self, slug: str, idioma: str, cargo: str, local: str = "") -> None:
        """Grava cargo_<idioma> e local_<idioma> no cabeçalho de uma experiência, preservando os fatos."""
        if idioma not in ("pt", "en"):
            raise ErroBase(f"Idioma inválido: {idioma}")
        caminho = self._caminho(slug)
        if caminho is None or not caminho.exists():
            raise ErroBase(f"Experiência '{slug}' não encontrada.")
        arq = Arquivo.ler(caminho, slug)
        meta = validar_meta_experiencia(arq.meta, caminho.name)
        if cargo.strip():
            meta[f"cargo_{idioma}"] = cargo.strip()
        if local.strip():
            meta[f"local_{idioma}"] = local.strip()
        texto = montar_texto_experiencia(meta, arq.linhas[arq.corpo_ini:])
        with open(caminho, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto.rstrip("\n") + "\n")

    def ler_texto(self, slug: str) -> str:
        caminho = self._caminho(slug)
        if caminho is None or not caminho.exists():
            return ""
        return caminho.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

    def salvar_texto(self, slug: str, texto: str) -> None:
        """Salva o texto bruto de um arquivo, validando o cabeçalho das experiências."""
        caminho = self._caminho(slug)
        if caminho is None:
            raise ErroBase(f"Arquivo desconhecido: '{slug}'.")
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        tmp = caminho.with_name(f".{caminho.name}.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(texto.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        try:
            arq = Arquivo.ler(tmp, slug)
            if caminho.parent.name == "experiencias":
                validar_meta_experiencia(arq.meta, caminho.name)
        except ErroBase:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(caminho)

    # ------------------------------------------------------------------ contato
    def contato(self) -> dict:
        caminho = self.base / "contato.yaml"
        if not caminho.exists():
            return {}
        try:
            dados = yaml.safe_load(caminho.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError:
            raise ErroBase("contato.yaml está inválido.") from None
        return {k: str(v).strip() for k, v in dados.items() if v not in (None, "")} if isinstance(dados, dict) else {}

    def salvar_contato(self, dados: dict) -> None:
        limpo = {k: str(dados.get(k, "")).strip() for k in CHAVES_CONTATO}
        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.base / "contato.yaml", "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(limpo, f, allow_unicode=True, sort_keys=False)

    def segredos(self) -> list[str]:
        c = self.contato()
        return [c[k] for k in ("nome", "telefone", "email", "linkedin", "site") if c.get(k)]

    # ------------------------------------------------------------------- prompts
    @staticmethod
    def _cabecalho_exp(a: Arquivo) -> str:
        m = a.meta
        return f"{m['empresa']} | {m['cargo']} | {m['inicio']} a {m['fim']}" + (f" | {m['local']}" if m.get("local") else "")

    def para_prompt(self) -> str:
        """Só fatos [confirmado], com id. Sem contato e sem fatos pendentes. Experiências ocultas ficam de fora."""
        arqs = self.arquivos()
        blocos: list[str] = []
        for slug in ARQUIVOS_FATOS:
            a = arqs.get(slug)
            fs = [f for f in a.fatos() if f.status == "confirmado"] if a else []
            if fs:
                blocos.append(f"## {slug}\n" + "\n".join(f"- [{f.id}] {f.texto}" for f in fs))
        exps = []
        for a in self.experiencias():
            fs = [f for f in a.fatos() if f.status == "confirmado"]
            if fs:
                exps.append(f"### {a.slug}: {self._cabecalho_exp(a)}\n" + "\n".join(f"- [{f.id}] {f.texto}" for f in fs))
        if exps:
            blocos.append("## experiencias (da mais recente para a mais antiga)\n" + "\n\n".join(exps))
        return "\n\n".join(blocos) if blocos else "(a base ainda não tem fatos confirmados)"

    def resumo_entrevista(self) -> str:
        """Resumo da base para o entrevistador não repetir perguntas. Inclui pendentes, marcados como tal."""
        arqs = self.arquivos()
        partes: list[str] = []

        def lista(a: Arquivo) -> str:
            return "\n".join(
                f"  - {f.texto[:180]}" + (" (pendente)" if f.status == "sugerido" else "") for f in a.fatos())

        for slug in ARQUIVOS_FATOS:
            a = arqs.get(slug)
            if a and a.fatos():
                partes.append(f"{slug}:\n{lista(a)}")
        for a in self.experiencias(True):
            partes.append(f"experiência [{a.slug}] {self._cabecalho_exp(a)}:\n{lista(a) or '  (sem fatos ainda)'}")
        return "\n".join(partes) if partes else "A base está vazia. Nenhuma experiência foi registrada ainda."

    def textos_confirmados(self) -> list[str]:
        """Todos os textos confirmados mais os anos das experiências, para a checagem de números."""
        textos = [f.texto for f in self.fatos("confirmado")]
        for a in self.experiencias():
            textos.append(f"{a.meta['inicio'][:4]} {a.meta['fim'][:4]}")
        return textos
