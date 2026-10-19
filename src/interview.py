"""Entrevista, extração de propostas e aplicação na base.

Regra central: nada vira [confirmado] sem uma ação explícita da pessoa. O extrator só PROPÕE.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date

from . import config
from .kb import ARQUIVOS_FATOS, KB, ErroBase, validar_meta_experiencia
from .llm import completar_json
from .texto import contem_contato, detectar_idioma, idioma_de_frase, mascarar_contato, mes_citado, normalizar

ABERTURA = (
    "Oi! Vou te fazer perguntas, uma de cada vez, para entender com precisão o que você já fez "
    "profissionalmente. Nada vai para o currículo sem a sua confirmação.\n\n"
    "Por favor, não digite telefone, e-mail nem endereço aqui.\n\n"
    "Para começar: qual é o seu trabalho atual (ou o mais recente) e o que você faz nele no dia a dia?"
)

NOMES_IDIOMA = {"pt": "português", "en": "inglês"}

MAX_TURNOS_CONTEXTO = 40  # mensagens enviadas ao modelo; o resto já foi para a base ou fica para a próxima rodada


@dataclass
class FatoProposto:
    texto: str
    origem: str  # dito | sugerido

    @property
    def marcado_por_padrao(self) -> bool:
        return self.origem == "dito"


@dataclass
class Proposta:
    destino: str
    fatos: list[FatoProposto]
    meta: dict = field(default_factory=dict)
    problemas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- entrevista

PERGUNTA_POR_SECAO = {
    "formacao": "qual é a sua formação (curso, instituição e ano)?",
    "idiomas": "quais idiomas você fala e em que nível?",
    "habilidades": "quais ferramentas e métodos você usa no dia a dia de trabalho?",
    "perfil": "que tipo de vaga você busca agora?",
}


def abertura(kb: KB) -> str:
    """Abertura da conversa, montada sem chamar a IA. Com a base já preenchida, não repete o básico."""
    if not kb.fatos():
        return ABERTURA
    exps = kb.experiencias()
    lacunas = kb.lacunas()
    n_exp, n_info = len(exps), len(kb.fatos("confirmado"))
    texto = (f"Oi! O seu histórico já tem {n_exp} {'experiência' if n_exp == 1 else 'experiências'} e "
             f"{n_info} {'informação' if n_info == 1 else 'informações'}, então não vou repetir o que já está lá. ")
    if not lacunas:
        return texto + ("Ele parece completo. Se quiser, escolha uma experiência para aprofundar, ou vá para "
                        "Currículo para uma vaga.")
    texto += "O que ainda falta: " + "; ".join(l["rotulo"] for l in lacunas[:3]) + ".\n\nPara começar: "
    p = lacunas[0]
    if p["tipo"] in ("poucos_fatos", "sem_numeros"):
        return texto + (f"na experiência de {p['cargo']} na {p['empresa']}, qual resultado concreto você alcançou? "
                        "De preferência com um número, mesmo que seja estimativa.")
    if p["tipo"] == "sem_experiencias":
        return texto + "qual é o seu trabalho atual (ou o mais recente) e o que você faz nele no dia a dia?"
    return texto + PERGUNTA_POR_SECAO[p["slug"]]


def _sistema_entrevistador(kb: KB, pendentes: list[str] | None = None) -> str:
    partes = [config.ler_prompt("entrevistador"), "## Resumo da base atual\n" + kb.resumo_entrevista()]
    lacunas = kb.lacunas()
    partes.append("## O que ainda falta na base (pergunte SÓ sobre isto)\n"
                  + ("\n".join(f"- {l['rotulo']}" for l in lacunas) if lacunas else
                     "- Nada essencial. Pergunte apenas se a pessoa quiser aprofundar algo."))
    if pendentes:
        partes.append("## Já informado, aguardando a revisão da pessoa (NÃO pergunte de novo)\n"
                      + "\n".join(f"- {t[:200]}" for t in pendentes[:80]))
    return "\n\n".join(partes)


def responder(llm, kb: KB, historico: list[dict], mensagem: str, pendentes: list[str] | None = None) -> str:
    """Uma rodada do chat. `historico` tem dicts {role, content} (sem a abertura estática).

    `pendentes`: textos de fatos que a pessoa ainda não revisou (por exemplo, de um currículo importado).
    O entrevistador os trata como já informados, para não perguntar de novo.
    """
    msgs = [{"role": "system", "content": _sistema_entrevistador(kb, pendentes)}]
    msgs.append({"role": "assistant", "content": abertura(kb)})
    msgs += [{"role": m["role"], "content": m["content"]} for m in historico[-MAX_TURNOS_CONTEXTO:]]
    msgs.append({"role": "user", "content": mascarar_contato(mensagem)})
    return llm.conversar(msgs, temperatura=0.5, rotulo="entrevistador")


# ---------------------------------------------------------------------- extração

def _entrada_extrator(kb: KB, material: str, origem: str) -> list[dict]:
    exps = [f"- {a.slug}: {a.meta['empresa']} | {a.meta['cargo']} | {a.meta['inicio']} a {a.meta['fim']}"
            for a in kb.experiencias(True)]
    destinos = ", ".join(ARQUIVOS_FATOS)
    idioma = detectar_idioma(material)
    dica = (f"## Idioma do material\nO material está em {NOMES_IDIOMA[idioma]}. Escreva TODOS os fatos em "
            f"{NOMES_IDIOMA[idioma]}, mesmo que estas instruções estejam em português. Não traduza.\n\n"
            if idioma else "")
    usuario = (
        dica +
        f"## Origem do material\n{origem}\n\n"
        f"## Destinos fixos\n{destinos}\n\n"
        "## Experiências existentes (use o slug como destino)\n" + ("\n".join(exps) or "(nenhuma)") + "\n\n"
        f"## Base atual (não repita estes fatos)\n{kb.resumo_entrevista()}\n\n"
        f"## Material para extrair\n{mascarar_contato(material)}"
    )
    return [{"role": "system", "content": config.ler_prompt("extrator")},
            {"role": "user", "content": usuario}]


def transcricao(historico: list[dict]) -> str:
    nomes = {"user": "PESSOA", "assistant": "ENTREVISTADOR"}
    return "\n\n".join(f"{nomes.get(m['role'], m['role'])}: {m['content']}" for m in historico)


def extrair(llm, kb: KB, material: str, origem: str = "entrevista") -> list[Proposta]:
    """origem: 'entrevista', 'curriculo importado' ou 'respostas'."""
    bruto = completar_json(llm, _entrada_extrator(kb, material, origem), rotulo="extrator")
    return validar_propostas(bruto, kb, detectar_idioma(material), material)


def extrair_da_conversa(llm, kb: KB, historico: list[dict]) -> list[Proposta]:
    return extrair(llm, kb, transcricao(historico), "entrevista")


def validar_propostas(bruto, kb: KB, idioma_material: str | None = None,
                      material: str | None = None) -> list[Proposta]:
    """Descarta o que não presta: destino inválido, fato vazio, repetido ou com contato."""
    lista = bruto.get("propostas", []) if isinstance(bruto, dict) else (bruto if isinstance(bruto, list) else [])
    slugs = {a.slug for a in kb.experiencias(True)}
    existentes: dict[str, set[str]] = {}
    for f in kb.fatos():
        existentes.setdefault(f.slug, set()).add(_chave(f.texto))
    propostas: list[Proposta] = []
    for item in lista:
        if not isinstance(item, dict):
            continue
        destino = str(item.get("destino", "")).strip()
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        problemas: list[str] = []
        if destino == "nova_experiencia":
            meta, avisos_data = _conferir_datas(dict(meta), material)
            problemas += avisos_data
            try:
                meta = validar_meta_experiencia(meta)
            except ErroBase as e:
                if not avisos_data:   # o aviso de data já explica; não repetir
                    problemas.append(f"Complete os dados da experiência antes de salvar. {e}")
            # Parece uma experiência que já existe (mesma empresa escrita de outro jeito, ou o mesmo período)? Quase
            # sempre é o mesmo cargo vindo de outro currículo ou de outro idioma. O código avisa; não depende do modelo.
            for a in kb.experiencias(True):
                motivo = parecida_com(a.meta, meta)
                if motivo == "mesmo período":
                    problemas.append(f"Acontece no mesmo período de {a.meta['cargo']} na {a.meta['empresa']}, que você já "
                                     "tem. Se for a mesma experiência com outro nome, desmarque os itens daqui. Se foram "
                                     "dois trabalhos ao mesmo tempo, pode salvar.")
                    break
                if motivo:
                    problemas.append(f"Parece a experiência que você já tem: {a.meta['cargo']} na {a.meta['empresa']} "
                                     f"({motivo}). Se for a mesma, desmarque os itens daqui para não duplicar.")
                    break
        elif destino in ARQUIVOS_FATOS or destino in slugs:
            meta = {}
        else:
            continue
        vistos = set(existentes.get(destino, set()))
        fatos: list[FatoProposto] = []
        for f in item.get("fatos", []) or []:
            texto = " ".join(str((f or {}).get("texto", "") if isinstance(f, dict) else f).split())
            texto = _SEM_DADO.sub("", texto).strip(" |")
            if not texto or contem_contato(texto):
                continue
            chave = _chave(texto)
            if chave in vistos:
                continue
            vistos.add(chave)
            origem = (f.get("origem") if isinstance(f, dict) else "") or ""
            # Conservador: só "dito" vem marcado. Qualquer outra coisa é inferência.
            fatos.append(FatoProposto(texto, "dito" if str(origem).lower() == "dito" else "sugerido"))
        juntos = " ".join(f.texto for f in fatos)
        achado = detectar_idioma(juntos, min_palavras=12) if fatos else None
        # frases curtas de currículo quase não têm "de" e "the": para elas, a detecção que olha acentos e terminações
        curto = idioma_de_frase(juntos) if fatos else None
        if achado and idioma_material and achado != idioma_material:
            problemas.append(f"Estes itens parecem estar em {NOMES_IDIOMA[achado]}, mas o material está em "
                             f"{NOMES_IDIOMA[idioma_material]}. A IA pode ter traduzido: confira o texto.")
        elif curto and destino in slugs and existentes.get(destino) and curto != kb.idioma_base():
            # itens novos numa experiência que já existe, em outro idioma: costumam ser os mesmos itens traduzidos
            problemas.append(f"Estes itens estão em {NOMES_IDIOMA[curto]} e o seu histórico em "
                             f"{NOMES_IDIOMA[kb.idioma_base()]}. Se forem os mesmos que você já tem, só traduzidos, "
                             "desmarque para não duplicar.")
        if fatos:
            propostas.append(Proposta(destino, fatos, meta, problemas))
    return propostas


_SUFIXOS_EMPRESA = {"sa", "s", "a", "ltda", "ltd", "inc", "llc", "corp", "corporation", "company", "co", "grupo",
                    "group", "me", "eireli", "holding", "brasil", "brazil", "do", "da", "de"}


def _nucleo_empresa(nome: str) -> str:
    """Nome da empresa sem pontuação, sufixos societários e espaços: "Itaú Unibanco S.A." vira "itauunibanco"."""
    partes = [p for p in re.findall(r"[a-z0-9]+", normalizar(nome)) if p not in _SUFIXOS_EMPRESA]
    return "".join(partes)


def _meses(aaaa_mm: str) -> int | None:
    m = re.match(r"^(\d{4})(?:-(\d{2}))?", str(aaaa_mm or ""))
    return int(m.group(1)) * 12 + (int(m.group(2) or 6) - 1) if m else None


def parecida_com(existente: dict, nova: dict) -> str:
    """Motivo, em português, de a experiência nova parecer uma que já existe. Vazio se não parece.

    Empresa: mesmo nome sem sufixos e espaços, ou um contido no outro ("Itaú" e "Itaú Unibanco S.A."); nomes só
    parecidos ("Mercado Livre" e "MercadoLibre") contam como indício mais fraco. Período: começos com até 3 meses de
    diferença (ou no mesmo ano, quando um dos lados não tem mês) e a maior parte de um dentro do outro.
    Sempre exige o período coincidir (ou não haver data para comparar): a mesma empresa em outra época é outro cargo,
    e apelidos ("Magalu" e "Magazine Luiza") só o período pega.
    """
    a, b = _nucleo_empresa(existente.get("empresa", "")), _nucleo_empresa(nova.get("empresa", ""))
    forte = bool(a and b and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))))
    fraca = bool(a and b and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)
    ini_a, ini_b = str(existente.get("inicio") or ""), str(nova.get("inicio") or "")
    m_a, m_b = _meses(ini_a), _meses(ini_b)
    hoje = date.today().year * 12 + date.today().month - 1

    def fim(meta):
        f = str(meta.get("fim") or "").lower()
        return hoje if f in ("atual", "presente", "present", "current") else _meses(f)
    f_a, f_b = fim(existente), fim(nova)
    if m_a is None or m_b is None:
        comeca_junto = None                     # não há como comparar
    elif len(ini_a) == 4 or len(ini_b) == 4:     # só o ano de um dos lados
        comeca_junto = ini_a[:4] == ini_b[:4]
    else:
        comeca_junto = abs(m_a - m_b) <= 3
    sobrepoe = None
    if None not in (m_a, m_b, f_a, f_b):
        comum = min(f_a, f_b) - max(m_a, m_b)
        sobrepoe = comum / max(1, min(f_a - m_a, f_b - m_b)) >= 0.6
    periodo = bool(comeca_junto) and sobrepoe is not False
    sem_data = comeca_junto is None
    if forte and (periodo or sem_data):
        return "mesma empresa, no mesmo período" if periodo else "mesma empresa"
    if fraca and periodo:
        return "empresa com nome parecido, no mesmo período"
    if periodo and sobrepoe:
        return "mesmo período"
    return ""


def _conferir_datas(meta: dict, material: str | None) -> tuple[dict, list[str]]:
    """Só aceita mês que aparece no material. Se a pessoa disse só o ano, o modelo não pode completar o mês."""
    avisos = []
    if not material:
        return meta, avisos
    for campo, rotulo in (("inicio", "início"), ("fim", "fim")):
        v = str(meta.get(campo, "") or "").strip()
        if re.match(r"^\d{4}-\d{2}$", v) and not mes_citado(material, v):
            meta[campo] = v[:4]
            avisos.append(f"O mês de {rotulo} não aparece no que foi dito, só o ano. Deixei só {v[:4]}; se você "
                          "lembrar o mês, corrija (AAAA-MM).")
    return meta, avisos


_SEM_DADO = re.compile(r"\s*\|\s*(?:sem data|sem ano|n/d|n/a|não informado)\s*$", re.I)


def _chave(texto: str) -> str:
    return re.sub(r"[^\w\s%]", "", normalizar(texto)).strip()


# ---------------------------------------------------------------------- aplicação

def aplicar(kb: KB, propostas: list[Proposta], marcados: set[tuple[int, int]], guardar_resto: bool) -> dict:
    """Grava na base. `marcados` = {(i_proposta, i_fato)} que a pessoa marcou.

    Marcados viram [confirmado]. Se guardar_resto, os demais entram como [sugerido].
    Propostas de nova_experiencia com meta incompleta levantam ErroBase.
    """
    total = {"confirmados": 0, "pendentes": 0, "ignorados": 0, "experiencias_criadas": 0}
    erros = []
    for p in propostas:
        if p.destino == "nova_experiencia" and p.fatos:
            try:
                validar_meta_experiencia(p.meta)
            except ErroBase as e:
                nome = " na ".join(x for x in (p.meta.get("cargo"), p.meta.get("empresa")) if x) or "uma experiência nova"
                erros.append(f"{nome}: {e}")
    if erros:
        raise ErroBase("Nada foi salvo ainda. Corrija antes: " + " ".join(erros))
    for i, p in enumerate(propostas):
        sim = [f.texto for j, f in enumerate(p.fatos) if (i, j) in marcados]
        nao = [f.texto for j, f in enumerate(p.fatos) if (i, j) not in marcados] if guardar_resto else []
        if not sim and not nao:
            continue
        destino = p.destino
        if destino == "nova_experiencia":
            destino = kb.criar_experiencia(p.meta)
            total["experiencias_criadas"] += 1
        if sim:
            r = kb.adicionar_fatos(destino, sim, "confirmado")
            total["confirmados"] += r["adicionados"] + r["promovidos"]
            total["ignorados"] += r["ignorados"]
        if nao:
            r = kb.adicionar_fatos(destino, nao, "sugerido")
            total["pendentes"] += r["adicionados"]
            total["ignorados"] += r["ignorados"]
    return total
