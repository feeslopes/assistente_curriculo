"""Checagens determinísticas: números inventados e cobertura de palavras-chave."""
from __future__ import annotations

import re

from .texto import normalizar

_EXTENSO = {
    "dois": "2", "duas": "2", "tres": "3", "quatro": "4", "cinco": "5", "seis": "6", "sete": "7",
    "oito": "8", "nove": "9", "dez": "10",
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10",
}
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_MILHAR = {"mil", "k", "thousand"}
_MULTIPLICADOR = re.compile(r"(\d+(?:[.,]\d+)*)\s*(mil|k|thousand|milhao|milhoes|million)\b")
_MIL_PT = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_MIL_EN = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def _normalizar_numero(tok: str) -> str:
    if _MIL_PT.match(tok):
        return tok.replace(".", "")
    if _MIL_EN.match(tok):
        return tok.replace(",", "")
    tok = tok.replace(",", ".")
    if "." in tok:
        tok = tok.rstrip("0").rstrip(".")
    return tok.lstrip("0") or "0"


def numeros_em(texto: str) -> set[str]:
    """Números do texto, normalizados (separadores) e com os por extenso de 2 a 10 convertidos."""
    achados = {_normalizar_numero(t) for t in _NUM.findall(texto or "")}
    norm = normalizar(texto)
    for palavra in re.findall(r"[a-z]+", norm):
        if palavra in _EXTENSO:
            achados.add(_EXTENSO[palavra])
    # "80 mil", "80k" e "80,000" são o mesmo número: guarda também o valor expandido.
    for m in _MULTIPLICADOR.finditer(norm):
        try:
            valor = float(_normalizar_numero(m.group(1)).replace(",", ".")) * (1000 if m.group(2) in _MILHAR else 1_000_000)
        except ValueError:
            continue
        achados.add(str(int(round(valor))))
    return achados


def numeros_nao_suportados(texto: str, textos_base: list[str]) -> list[str]:
    """Números de `texto` que não existem em nenhum texto da base. Aviso, nunca bloqueio."""
    permitidos: set[str] = set()
    for t in textos_base:
        permitidos |= numeros_em(t)
    return sorted(numeros_em(texto) - permitidos, key=lambda x: (len(x), x))


_VAZIAS = {"de", "da", "do", "das", "dos", "e", "em", "com", "para", "the", "of", "and", "in", "to", "for", "com"}


def palavras_da_base(textos_base: list[str]) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalizar("\n".join(textos_base))))


def _sigla_norm(w: str) -> str:
    """Compara siglas entre idiomas: plural some e AI/IA se equivalem."""
    w = w.lower().rstrip("s") if len(w) > 3 else w.lower()
    return {"ai": "ia"}.get(w, w)


# Siglas (SQL), CamelCase (HubSpot) e tokens com letra e dígito (B2B, Web3). Número puro (000) não conta.
_TOKEN_NOME = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
                         r"|(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+)\b")


def termo_suportado(termo: str, base_palavras: set[str], estrito: bool = True) -> bool:
    """Todo termo de competência precisa ter respaldo na base.

    estrito (saída no mesmo idioma da base): cada palavra significativa do termo aparece na base
    (palavras de 5+ letras casam pelo prefixo de 5, para aceitar flexões).
    não estrito (saída traduzida): palavras comuns não são comparáveis entre idiomas, então só siglas,
    nomes em CamelCase e tokens com dígito (SQL, HubSpot, CRO, B2B) precisam existir na base.
    """
    if not estrito:
        base_s = {_sigla_norm(b) for b in base_palavras}
        return all(_sigla_norm(t) in base_s for t in _TOKEN_NOME.findall(termo))
    palavras = [p for p in re.findall(r"[a-z0-9]+", normalizar(termo)) if len(p) >= 3 and p not in _VAZIAS]
    if not palavras:
        return True
    for p in palavras:
        if len(p) >= 5:
            if not any(b.startswith(p[:5]) for b in base_palavras):
                return False
        elif p not in base_palavras:
            return False
    return True


def siglas_nao_suportadas(texto: str, base_palavras: set[str], estrito: bool = True) -> list[str]:
    """Siglas e nomes de ferramenta (CRM, HubSpot, SQL) do texto que a base não menciona."""
    texto = texto or ""
    achados = _TOKEN_NOME.findall(texto)
    if estrito:
        # Palavra capitalizada no meio da frase costuma ser nome próprio ou ferramenta (Salesforce, Looker).
        achados += re.findall(r"(?<=[a-zà-ú0-9,;:)] )([A-Z][a-zà-ú]{2,})\b", texto)
    base_s = {_sigla_norm(b) for b in base_palavras}
    saida = []
    for a in achados:
        if _sigla_norm(normalizar(a)) not in base_s and a not in saida:
            saida.append(a)
    return saida


def _contem(texto_norm: str, termo_norm: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(termo_norm)}(?![a-z0-9])", texto_norm))


def cobertura_palavras(palavras: list[str], texto_final: str, textos_base: list[str],
                       mesmo_idioma: bool = True) -> dict:
    """Retrato honesto para ATS.

    usadas: aparecem no currículo e a base também tem o termo.
    usadas_sem_base: aparecem no currículo mas a base não tem o termo (suspeito, conferir).
    fora_com_base: a base tem o termo, mas o currículo não usou (dá para melhorar).
    fora_sem_base: nem a base tem; ficaram de fora por falta de fato, e é assim que deve ser.
    usadas_indeterminadas / fora_indeterminadas: só em saída traduzida; palavras comuns que o código não
    consegue comparar com a base. A IA fiscal resolve (tailor._resolver_indeterminadas).
    """
    final = normalizar(texto_final)
    base = normalizar("\n".join(textos_base))
    usadas, com_base, sem_base, suspeitas, indeterminadas, usadas_ind = [], [], [], [], [], []
    vistas: set[str] = set()
    for p in palavras:
        n = normalizar(p)
        if not n or n in vistas:
            continue
        vistas.add(n)
        no_final, na_base = _contem(final, n), _contem(base, n)
        if not mesmo_idioma and not _TOKEN_NOME.search(p):
            # Palavra comum em saída traduzida: a base está em outro idioma e não dá para comparar.
            (usadas_ind if no_final else indeterminadas).append(p)
        elif no_final and na_base:
            usadas.append(p)
        elif no_final:
            suspeitas.append(p)
        elif na_base:
            com_base.append(p)
        else:
            sem_base.append(p)
    cob = {"usadas": usadas, "usadas_sem_base": suspeitas, "usadas_indeterminadas": usadas_ind,
           "fora_com_base": com_base, "fora_sem_base": sem_base, "fora_indeterminadas": indeterminadas}
    cob["percentual"] = percentual(cob)
    return cob


def percentual(cob: dict) -> int:
    """% das palavras-chave da vaga que o currículo usa COM respaldo na base."""
    total = sum(len(cob[k]) for k in ("usadas", "usadas_sem_base", "usadas_indeterminadas", "fora_com_base",
                                      "fora_sem_base", "fora_indeterminadas"))
    return round(100 * len(cob["usadas"]) / total) if total else 0
