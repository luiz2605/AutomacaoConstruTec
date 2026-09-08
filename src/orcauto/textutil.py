# -*- coding: utf-8 -*-
"""Normalização de texto e números no padrão brasileiro."""
from __future__ import annotations

import difflib
import re
import unicodedata

_SPACES = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str | None) -> str:
    """Maiúsculas, sem acento, sem pontuação e com espaços colapsados."""
    if not text:
        return ""
    return _SPACES.sub(" ", _NON_ALNUM.sub(" ", strip_accents(str(text)).upper())).strip()


def similarity(a: str | None, b: str | None) -> float:
    """Similaridade 0..1 entre duas descrições, já normalizadas."""
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def parse_number(value: str | float | int | None) -> float | None:
    """Converte '1.799,61' -> 1799.61. Aceita já-numérico e devolve None se vazio."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\xa0", "").replace(" ", "")
    if "," in text:                       # 1.799,61  ->  1799.61
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def format_number(value: float, decimals: int = 10) -> str:
    """Número para dentro de uma fórmula: sem zeros à direita, sem separador de milhar."""
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    text = f"{round(value, decimals):.{decimals}f}".rstrip("0").rstrip(".")
    return text or "0"


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    if index < 1:
        raise ValueError("índice de coluna começa em 1")
    letters = ""
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def column_index(letter: str) -> int:
    """A -> 1, AA -> 27."""
    value = 0
    for char in letter.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"coluna inválida: {letter!r}")
        value = value * 26 + (ord(char) - 64)
    return value


# Caracteres que o Excel proíbe em nome de aba, e o limite de 31 caracteres.
FORBIDDEN_SHEET_CHARS = r":\/?*[]"
SHEET_NAME_LIMIT = 31


def sanitize_sheet_name(name: str, taken: set[str] | None = None,
                        limit: int = SHEET_NAME_LIMIT) -> str:
    """Transforma o nome de um tópico do orçamento em nome de aba válido.

    O Excel recusa `: \\ / ? * [ ]`, recusa nome com mais de 31 caracteres e
    recusa nome começando ou terminando com apóstrofo. Os nomes vêm de extração
    de PDF, então também chegam com espaço duplo e acentuação irregular
    (`CAIXA D´ÁGUA`). O corte respeita a fronteira de palavra sempre que sobrar
    nome legível, e a colisão é resolvida com sufixo numérico.
    """
    taken = taken or set()
    cleaned = "".join(" " if c in FORBIDDEN_SHEET_CHARS else c for c in str(name))
    cleaned = _SPACES.sub(" ", cleaned).strip().strip("'").strip()
    if not cleaned:
        cleaned = "ABA"

    if len(cleaned) > limit:
        cut = cleaned[:limit]
        space = cut.rfind(" ")
        # só corta na palavra se ainda sobrar nome reconhecível
        cleaned = cut[:space].rstrip() if space >= limit * 0.6 else cut.rstrip()
        # o corte costuma cair logo depois de um traço ("PAREDE OESTE PISCINA -"),
        # e a pontuação órfã faz o nome parecer defeito de geração
        cleaned = cleaned.rstrip(" -–—,.;:/").strip() or "ABA"

    if cleaned not in taken:
        return cleaned
    for suffix in range(2, 1000):
        tail = f" {suffix}"
        candidate = cleaned[:limit - len(tail)].rstrip() + tail
        if candidate not in taken:
            return candidate
    raise ValueError(f"não foi possível gerar nome de aba único para {name!r}")
