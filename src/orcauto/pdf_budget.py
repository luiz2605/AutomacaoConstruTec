# -*- coding: utf-8 -*-
"""Leitura do orçamento analítico em PDF.

Duas camadas propositalmente separadas:

* `extract_lines`  — adaptador do pdfplumber; devolve linhas de palavras.
* `parse_budget`   — função pura sobre essas linhas.

Isso deixa o parser testável sem precisar de um PDF em disco.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import PdfConfig
from .textutil import parse_number


@dataclass
class Word:
    text: str
    x0: float


@dataclass
class Line:
    page: int
    top: float
    words: list[Word]

    @property
    def texts(self) -> list[str]:
        return [w.text for w in self.words]

    def joined(self) -> str:
        return " ".join(self.texts)


@dataclass
class BudgetItem:
    order: str                 # "3.2"
    code: str                  # "C0843"
    description: str
    unit: str | None
    quantity: float | None
    unit_price: float | None
    total: float | None
    page: int
    topic_number: int
    topic_name: str


@dataclass
class Topic:
    number: int
    name: str
    items: list[BudgetItem] = field(default_factory=list)


def extract_lines(pdf_path: str | Path, config: PdfConfig | None = None) -> list[Line]:
    """Extrai as linhas de palavras do PDF (requer pdfplumber)."""
    import pdfplumber

    config = config or PdfConfig()
    lines: list[Line] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            buckets: dict[float, list] = {}
            for word in page.extract_words(use_text_flow=False, keep_blank_chars=False):
                top = round(word["top"], 0)
                key = next((k for k in buckets if abs(k - top) <= config.line_tolerance), top)
                buckets.setdefault(key, []).append(word)
            for key in sorted(buckets):
                ordered = sorted(buckets[key], key=lambda w: w["x0"])
                lines.append(Line(page_number, key,
                                  [Word(w["text"], round(w["x0"], 1)) for w in ordered]))
    return lines


def parse_budget(lines: list[Line], config: PdfConfig | None = None) -> list[Topic]:
    """Reconstrói tópicos e itens a partir das linhas do PDF."""
    config = config or PdfConfig()
    topic_re = re.compile(config.topic_number_re)
    order_re = re.compile(config.item_order_re)
    number_re = re.compile(config.number_re)

    topics: list[Topic] = []
    topic: Topic | None = None
    item: BudgetItem | None = None

    for line in lines:
        if not line.words:
            continue
        first, x0 = line.words[0].text, line.words[0].x0
        texts = line.texts

        # cabeçalho de tópico: "3  INFRAESTRUTURA  439.984,92"
        if topic_re.match(first) and x0 < config.topic_max_x and len(texts) >= 2:
            rest = texts[1:]
            name = " ".join(rest[:-1]).strip()
            if rest and number_re.match(rest[-1]) and name and not any(c.islower() for c in name):
                topic = Topic(int(first), name)
                topics.append(topic)
                item = None
                continue

        if topic is None:
            continue

        # linha de item: "3.2  C0843  DESCRIÇÃO ...  M3  8,15  680,57  5.546,68"
        if order_re.match(first) and len(texts) >= 3:
            tail = list(texts)
            numbers: list[str] = []
            cursor = len(tail) - 1
            while cursor > 0 and number_re.match(tail[cursor]) and len(numbers) < config.trailing_numbers:
                numbers.insert(0, tail[cursor])
                cursor -= 1
            unit = tail[cursor] if cursor > 1 else None
            complete = len(numbers) == config.trailing_numbers
            item = BudgetItem(
                order=first,
                code=tail[1],
                description=" ".join(tail[2:cursor]).strip(),
                unit=unit if complete else None,
                quantity=parse_number(numbers[0]) if complete else None,
                unit_price=parse_number(numbers[1]) if complete else None,
                total=parse_number(numbers[2]) if complete else None,
                page=line.page,
                topic_number=topic.number,
                topic_name=topic.name,
            )
            topic.items.append(item)
            continue

        # continuação da descrição (linha indentada, sem "Ordem")
        if item is not None and x0 > config.continuation_min_x and first not in config.header_words:
            item.description = (item.description + " " + line.joined()).strip()

    return topics


def read_budget(pdf_path: str | Path, config: PdfConfig | None = None) -> list[Topic]:
    return parse_budget(extract_lines(pdf_path, config), config)


def items_by_code(topics: list[Topic]) -> dict[str, list[BudgetItem]]:
    """Índice código -> itens, em todo o orçamento (usado para detectar código legado)."""
    index: dict[str, list[BudgetItem]] = {}
    for topic in topics:
        for item in topic.items:
            index.setdefault(item.code, []).append(item)
    return index
