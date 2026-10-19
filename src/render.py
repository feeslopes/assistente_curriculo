"""Do JSON do gerador para o Markdown do currículo, impondo as regras anti-invenção em código.

O que o modelo escreve é tratado como proposta. Aqui o código decide o que entra:
- item sem fonte válida (id existente e confirmado, da seção certa) é removido e listado;
- cabeçalho de experiência (empresa, cargo, datas, local) vem da base, nunca do modelo;
- títulos e números são conferidos contra a base;
- experiências omitidas, limites de bullets e de resumo são aplicados ou avisados;
- o veredito do fiscal (IA, ver tailor.verificar_com_ia) é aplicado aqui: termo de competência sem
  respaldo sai do currículo, frase suspeita vira alerta. O render continua sem chamar IA.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .kb import KB
from .texto import detectar_idioma, normalizar
from .verify import numeros_nao_suportados, palavras_da_base, siglas_nao_suportadas, termo_suportado

TRAVESSAO = re.compile(r"\s*[—―]\s*")
NOMES_IDIOMA = {"pt": "português", "en": "inglês"}


@dataclass
class Curriculo:
    markdown: str
    corpo: str                      # markdown sem o cabeçalho de contato (para cobertura de palavras-chave)
    titulo: str
    mesmo_idioma: bool = True       # idioma da saída = idioma da base (comparação de palavras é confiável)
    alertas: list[str] = field(default_factory=list)
    rastro: list[dict] = field(default_factory=list)    # item, fontes válidas e inválidas
    removidos: list[dict] = field(default_factory=list)  # o que foi tirado e por quê
    itens_fiscal: list[dict] = field(default_factory=list)  # o que a IA fiscal precisa conferir


def limpar(texto) -> str:
    t = TRAVESSAO.sub(" - ", str(texto or ""))
    return re.sub(r"\s+", " ", t).strip()


def _visivel(url: str) -> str:
    """Link como texto visível: parsers de PDF perdem o destino de [texto](url)."""
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/")


def formatar_data(aaaa_mm: str, idioma: str, cfg: dict) -> str:
    if len(aaaa_mm) == 4:          # só o ano: a pessoa não disse o mês, o currículo também não diz
        return aaaa_mm
    ano, mes = aaaa_mm.split("-")
    return f"{cfg['meses'][idioma][int(mes) - 1]} {ano}"


def _limite_bullets(cfg: dict, posicao: int) -> int:
    lim = cfg.get("bullets_por_experiencia", [5])
    if isinstance(lim, int):
        return lim
    return int(lim[min(posicao, len(lim) - 1)])


def _cortar_resumo(texto: str, max_palavras: int) -> str | None:
    """Corta por frases inteiras. None se não der para caber sem quebrar frase."""
    frases = re.split(r"(?<=[.!?])\s+", texto)
    saida: list[str] = []
    for f in frases:
        if len(" ".join(saida + [f]).split()) > max_palavras:
            break
        saida.append(f)
    return " ".join(saida) if saida and len(saida) < len(frases) else None


class _Montador:
    def __init__(self, kb: KB, idioma: str, cfg: dict, veredito: dict | None = None, fiscal: str = "ausente",
                 limites: dict | None = None, sustentadas: dict | None = None):
        self.kb, self.idioma, self.cfg = kb, idioma, cfg
        # termos da vaga que a análise ligou a fatos (termo normalizado -> ids). Sinônimo legítimo ("devoluções" e
        # "logística reversa") não passa no filtro de palavras; com fato citado, fica, e o fiscal por IA confere.
        self.sustentadas = sustentadas or {}
        self.limites = limites or {}   # slug -> máximo de bullets (0 = só cabeçalho); vazio = regra por posição
        self.fiscal = fiscal
        self.veredito = veredito or {}
        self.ids_ok = kb.ids_confirmados()
        self.textos_base = kb.textos_confirmados()
        self.texto_por_id = {f.id: f.texto for f in kb.fatos("confirmado")}
        # cargo, empresa e local também são da base: "Sênior" do cargo não é uma sigla inventada
        cabecalhos = [" ".join(str(e.meta.get(k, "")) for k in ("cargo", "cargo_en", "cargo_pt", "empresa", "local",
                                                                 "local_en", "local_pt")) for e in kb.experiencias()]
        self.base_palavras = palavras_da_base(self.textos_base + cabecalhos)
        # Comparar palavras só faz sentido quando a saída está no idioma da base.
        self.idioma_base = kb.idioma_base()
        self.estrito = self.idioma_base == idioma
        # Em saída traduzida, siglas e termos só são julgados pelo código quando NÃO há IA fiscal (PROCV e VLOOKUP
        # são a mesma coisa, e só um modelo percebe isso). Com a IA, quem decide é o veredito dela.
        self.regra_do_codigo = self.estrito or fiscal == "ausente"
        self.cargos_sem_traducao: list[str] = []
        self.alertas: list[str] = []
        self.rastro: list[dict] = []
        self.removidos: list[dict] = []
        self.itens_fiscal: list[dict] = []
        self.ultimas_fontes: list[str] = []
        self.remover_sem_fonte = cfg.get("bullets_sem_fonte", "remover") == "remover"

    # ------------------------------------------------------------------ itens
    def item(self, secao: str, texto, fontes, escopo: set[str] | None = None, checar_siglas: bool = True,
             fiscalizar: bool = True) -> str | None:
        """Valida um item. `escopo` restringe de quais arquivos os ids podem vir."""
        t = limpar(texto)
        self.ultimas_fontes = []
        if not t:
            return None
        brutas = [str(f).strip() for f in fontes] if isinstance(fontes, list) else []
        validas = [f for f in brutas if f in self.ids_ok and (escopo is None or f.split("#")[0] in escopo)]
        invalidas = [f for f in brutas if f not in validas]
        self.rastro.append({"secao": secao, "texto": t, "fontes_validas": validas, "fontes_invalidas": invalidas})
        if not validas:
            if self.remover_sem_fonte:
                self.removidos.append({"secao": secao, "texto": t,
                                       "motivo": "sem fato confirmado de apoio" if not brutas else "fontes inválidas"})
                self.alertas.append(f"Removido de '{secao}' por não ter fato confirmado de apoio: \"{t}\". "
                                    "Se isso é verdade, confirme essa informação em Meu histórico.")
                return None
            self.alertas.append(f"Mantido em '{secao}' SEM fato confirmado de apoio: \"{t}\".")
        elif invalidas:
            self.alertas.append(f"Fontes ignoradas em '{secao}' (inexistentes, pendentes ou de outra seção): "
                                f"{', '.join(invalidas)}.")
        self.ultimas_fontes = validas
        # Trecho no idioma errado (o modelo às vezes esquece de traduzir o resumo): o código percebe e avisa.
        idioma_t = detectar_idioma(t, min_palavras=8) if fiscalizar else None
        if idioma_t and idioma_t != self.idioma:
            self.alertas.append(f"Este trecho saiu em {NOMES_IDIOMA[idioma_t]}, mas o currículo é em "
                                f"{NOMES_IDIOMA[self.idioma]}: \"{t[:90]}{'...' if len(t) > 90 else ''}\". "
                                "Gere de novo ou corrija editando o texto.")
        nums = numeros_nao_suportados(t, self.textos_base)
        if nums:
            self.alertas.append(f"Número(s) {', '.join(nums)} não aparece(m) na base: \"{t}\". Confira antes de usar.")
        siglas = siglas_nao_suportadas(t, self.base_palavras, self.estrito) if (checar_siglas and self.regra_do_codigo) else []
        if siglas:
            self.alertas.append(f"Sigla(s) ou ferramenta(s) {', '.join(siglas)} não aparece(m) na base: \"{t}\". "
                                "Confira antes de usar.")
        if fiscalizar and validas:
            self._para_fiscal(secao, t, validas, "frase")
            problema = self.veredito.get(f"{secao}|{t}")
            if problema:
                self.alertas.append(f"A verificação por IA aponta algo sem respaldo nos fatos em '{secao}': "
                                    f"\"{t}\". Motivo: {problema}")
        return t

    def _para_fiscal(self, secao: str, texto: str, fontes: list[str], tipo: str) -> None:
        self.itens_fiscal.append({
            "chave": f"{secao}|{texto}", "secao": secao, "tipo": tipo, "texto": texto,
            "fatos": [self.texto_por_id[f] for f in fontes if f in self.texto_por_id]})

    # --------------------------------------------------------- campos por idioma
    def _campo(self, meta: dict, campo: str) -> tuple[str, bool]:
        """Valor de cargo/local no idioma da saída e se há tradução quando ela é necessária."""
        if self.idioma == self.idioma_base:
            return meta.get(campo, ""), True
        v = meta.get(f"{campo}_{self.idioma}", "")
        return (v, True) if v else (meta.get(campo, ""), False)

    # ------------------------------------------------------------- cabeçalho
    def cabecalho(self, titulo: str) -> list[str]:
        c = self.kb.contato()
        linhas: list[str] = []
        nome = c.get("nome")
        if not nome:
            self.alertas.append("O nome não está preenchido. Preencha seus dados em Meu histórico, Dados pessoais.")
        linhas.append(f"# {nome or 'Seu Nome'}  ")
        if titulo:
            linhas.append(f"**{titulo}**  ")
        if c.get("local"):
            linhas.append(f"{c['local']}  ")
        contatos = [c.get("telefone"), c.get("email"),
                    _visivel(c["linkedin"]) if c.get("linkedin") else None,
                    _visivel(c["site"]) if c.get("site") else None]
        contatos = [x for x in contatos if x]
        if contatos:
            linhas.append(" | ".join(contatos))
        else:
            self.alertas.append("Nenhum telefone, e-mail ou link preenchido no contato.")
        if linhas[-1].endswith("  "):
            linhas[-1] = linhas[-1].rstrip()
        return linhas

    # ----------------------------------------------------------------- título
    def titulo(self, sugerido, do_usuario: str | None) -> str:
        if do_usuario and do_usuario.strip():
            return limpar(do_usuario)  # digitado à mão: respeita sem aviso
        c = self.kb.contato()
        exps = self.kb.experiencias()
        chave = "titulo_padrao" if self.idioma == "pt" else "titulo_padrao_en"
        padrao = c.get(chave, "")
        if not padrao and exps:
            padrao = self._campo(exps[0].meta, "cargo")[0]
        if not padrao:
            padrao = c.get("titulo_padrao") or c.get("titulo_padrao_en", "")
        # Cada título real da base aponta para a sua versão no idioma da saída.
        permitidos: dict[str, str] = {}
        for e in exps:
            alvo = self._campo(e.meta, "cargo")[0]
            for k in ("cargo", "cargo_en", "cargo_pt"):
                if e.meta.get(k):
                    permitidos.setdefault(normalizar(e.meta[k]), alvo)
        for k in ("titulo_padrao", "titulo_padrao_en"):
            if c.get(k):
                permitidos.setdefault(normalizar(c[k]), padrao or c[k])
        s = limpar(sugerido)
        if s and normalizar(s) in permitidos:
            return permitidos[normalizar(s)]
        if s:
            self.alertas.append(f"O título sugerido pela IA (\"{s}\") não é um cargo da sua base e foi trocado por "
                                f"\"{padrao}\". Para usar outro, digite o título no campo próprio.")
        return padrao

    # ---------------------------------------------------------------- seções
    def resumo(self, dado) -> list[str]:
        if not isinstance(dado, dict):
            return []
        t = self.item("resumo", dado.get("texto"), dado.get("fontes"))
        if not t:
            return []
        maximo = int(self.cfg.get("resumo_max_palavras", 70))
        if len(t.split()) > maximo:
            cortado = _cortar_resumo(t, maximo)
            if cortado:
                self.alertas.append(f"O resumo passou de {maximo} palavras e foi encurtado por frases inteiras.")
                t = cortado
            else:
                self.alertas.append(f"O resumo tem {len(t.split())} palavras (limite {maximo}). Encurte na revisão.")
        return [t]

    def competencias(self, dado) -> list[str]:
        grupos = [g for g in (dado if isinstance(dado, list) else []) if isinstance(g, dict)]
        saida: list[str] = []
        maximo = int(self.cfg.get("max_grupos_competencias", 6))
        for g in grupos:
            itens = self.item("competências", g.get("itens"), g.get("fontes"), checar_siglas=False, fiscalizar=False)
            if not itens:
                continue
            fontes = self.ultimas_fontes
            # Uma fonte válida não basta: cada termo precisa ter respaldo. Primeiro o filtro de palavras
            # (confiável no idioma da base, só siglas fora dele), depois o veredito da IA fiscal.
            termos = [x.strip() for x in re.split(r"[,;]", itens) if x.strip()]
            bons: list[str] = []
            for x in termos:
                sustentado_pela_analise = bool(self.sustentadas.get(normalizar(x), set()) & set(fontes))
                if (self.regra_do_codigo and not termo_suportado(x, self.base_palavras, self.estrito)
                        and not sustentado_pela_analise):
                    self.removidos.append({"secao": "competências", "texto": x, "motivo": "termo sem respaldo na base"})
                elif f"competências|{x}" in self.veredito:
                    self.removidos.append({"secao": "competências", "texto": x,
                                           "motivo": "IA: " + self.veredito[f"competências|{x}"]})
                else:
                    bons.append(x)
            if len(bons) < len(termos):
                self.alertas.append("Competências removidas por não terem respaldo nos fatos: "
                                    + ", ".join(x for x in termos if x not in bons)
                                    + ". Se são verdade, confirme essa informação em Meu histórico.")
            for x in bons:
                self._para_fiscal("competências", x, fontes, "termo")
            if not bons:
                continue
            itens = ", ".join(bons)
            nome = limpar(g.get("grupo"))
            if nome:
                # o nome do grupo também afirma algo ("Liderança de equipes"): passa pelo fiscal
                self._para_fiscal("competências-grupo", nome, fontes, "termo")
                problema = self.veredito.get(f"competências-grupo|{nome}")
                if problema:
                    self.alertas.append(f"O nome do grupo de competências \"{nome}\" foi tirado: {problema}")
                    nome = ""
            if len(saida) >= maximo:
                self.alertas.append(f"Grupo de competências '{nome}' descartado: limite de {maximo} grupos.")
                continue
            saida.append(f"* **{nome}:** {itens}" if nome else f"* {itens}")
        return saida

    def simples(self, secao: str, dado, escopo: str, negrito_primeiro: bool = False) -> list[str]:
        saida = []
        for it in (dado if isinstance(dado, list) else []):
            if not isinstance(it, dict):
                continue
            t = self.item(secao, it.get("texto"), it.get("fontes"), {escopo})
            if not t:
                continue
            partes = [p.strip() for p in t.split(" | ")]
            if negrito_primeiro and len(partes) >= 2:
                partes[0] = f"**{partes[0]}**"
                t = " | ".join(partes)
            saida.append(f"* {t}")
        return saida

    def experiencias(self, dado) -> list[str]:
        modelo = {}
        for e in (dado if isinstance(dado, list) else []):
            if isinstance(e, dict) and e.get("id"):
                modelo[str(e["id"]).strip()] = e
        exps = self.kb.experiencias()
        for desconhecido in sorted(set(modelo) - {e.slug for e in exps}):
            self.alertas.append(f"A IA citou uma experiência que não existe na base ('{desconhecido}'). Ignorada.")
        blocos: list[tuple[dict, list[str]]] = []
        for pos, e in enumerate(exps):
            lim = self.limites[e.slug] if e.slug in self.limites else _limite_bullets(self.cfg, pos)
            if lim <= 0:
                # experiência antiga e resumida ao máximo: só cargo, empresa e datas. Não é buraco no histórico.
                blocos.append((e.meta, []))
                continue
            bullets = []
            brutos = (modelo.get(e.slug) or {}).get("bullets") or []
            for b in brutos:
                if not isinstance(b, dict):
                    continue
                t = self.item(f"experiência {e.meta['empresa']}", b.get("texto"), b.get("fontes"), {e.slug})
                if t:
                    bullets.append(t)
            if len(bullets) > lim:
                self.alertas.append(f"{len(bullets) - lim} bullet(s) de {e.meta['empresa']} cortado(s): "
                                    f"limite de {lim} para esta experiência.")
                bullets = bullets[:lim]
            if not bullets:
                self.alertas.append(f"A experiência em {e.meta['empresa']} ({e.meta['cargo']}) ficou de fora do "
                                    "currículo. Isso pode criar um buraco no seu histórico.")
                continue
            blocos.append((e.meta, bullets))
        linhas = self._escrever_experiencias(blocos)
        if self.cargos_sem_traducao:
            lista = ", ".join(dict.fromkeys(self.cargos_sem_traducao))
            self.alertas.append(f"Cargos sem versão em {NOMES_IDIOMA[self.idioma]} (campo cargo_{self.idioma}), "
                                f"mantidos no idioma original: {lista}. Confirme as traduções antes de enviar.")
        return linhas

    def _escrever_experiencias(self, blocos) -> list[str]:
        saida: list[str] = []
        anterior = None
        sep = f" {self.cfg.get('separador_datas', '–')} "
        for meta, bullets in blocos:
            if normalizar(meta["empresa"]) != anterior:
                if saida:
                    saida.append("")
                saida += [f"**{meta['empresa']}**", ""]
                anterior = normalizar(meta["empresa"])
            cargo, ok = self._campo(meta, "cargo")
            if not ok:
                self.cargos_sem_traducao.append(meta["cargo"])
            local = self._campo(meta, "local")[0]
            ini = formatar_data(meta["inicio"], self.idioma, self.cfg)
            fim = (self.cfg["atual"][self.idioma] if meta["fim"] == "atual"
                   else formatar_data(meta["fim"], self.idioma, self.cfg))
            partes = [cargo, f"{ini}{sep}{fim}"] + ([local] if local else [])
            if saida and saida[-1] != "":
                saida.append("")
            saida += ["_" + " · ".join(partes) + "_"]
            if bullets:
                saida += [""] + [f"* {b}" for b in bullets]
        return saida


def montar(kb: KB, gerado, idioma: str, cfg: dict, titulo_usuario: str | None = None,
           veredito: dict | None = None, fiscal: str = "ausente", limites: dict | None = None,
           sustentadas: dict | None = None) -> Curriculo:
    """Monta o currículo. `gerado` é o JSON do gerador, já parseado (qualquer lixo é tolerado).

    `veredito` (opcional): {"secao|texto": "problema"} vindo do fiscal por IA.
    `fiscal`: "ausente" (sem IA: o código julga siglas e termos), "pendente" ou "ok" (a IA fiscal decide).
    """
    if idioma not in ("pt", "en"):
        raise ValueError("Idioma precisa ser 'pt' ou 'en'.")
    g = gerado if isinstance(gerado, dict) else {}
    m = _Montador(kb, idioma, cfg, veredito, fiscal, limites, sustentadas)
    titulo = m.titulo(g.get("titulo"), titulo_usuario)

    secoes: dict[str, list[str]] = {
        "resumo": m.resumo(g.get("resumo")),
        "competencias": m.competencias(g.get("competencias")),
        "experiencia": m.experiencias(g.get("experiencias")),
        "formacao": m.simples("formação", g.get("formacao"), "formacao", negrito_primeiro=True),
        "certificacoes": m.simples("certificações", g.get("certificacoes"), "certificacoes"),
        "idiomas": m.simples("idiomas", g.get("idiomas"), "idiomas"),
    }
    titulos = cfg["titulos_secoes"][idioma]
    corpo: list[str] = []
    for chave in cfg.get("ordem_secoes", list(secoes)):
        linhas = secoes.get(chave)
        if not linhas:
            continue
        if corpo:
            corpo.append("")
        corpo += [f"## {titulos[chave]}", ""]
        corpo += linhas
    cabecalho = m.cabecalho(titulo)
    texto_corpo = "\n".join(corpo).strip() + "\n"
    markdown = "\n".join(cabecalho) + "\n\n" + texto_corpo
    return Curriculo(markdown, texto_corpo, titulo, m.estrito, m.alertas, m.rastro, m.removidos, m.itens_fiscal)
