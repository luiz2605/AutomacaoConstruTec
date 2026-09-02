# -*- coding: utf-8 -*-
"""Índice das tabelas de composição de custo do arquivo Excel.

Uma composição é reconhecida apenas quando o código forma o **título** da
tabela (célula isolada no formato `CÓDIGO - DESCRIÇÃO - UNIDADE`). Ocorrências
do mesmo código como sub-item de outro serviço são deliberadamente ignoradas —
é o que evita o falso positivo de pegar o coeficiente da tabela errada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .config import CompositionConfig
from .textutil import normalize


@dataclass
class Input:
    """Um insumo (ou sub-serviço) dentro de uma composição."""
    code: str
    description: str
    unit: str | None
    coefficient: float
    row: int
    section: str | None


@dataclass
class Composition:
    code: str
    description: str
    unit: str | None
    sheet: str
    title_row: int
    inputs: dict[str, Input] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.sheet}!A{self.title_row}"


class CompositionIndex:
    """Coleção de composições, consultável por código."""

    def __init__(self, compositions: Iterable[Composition],
                 preferred_sheets: list[str] | None = None,
                 warnings: list[str] | None = None):
        self.compositions = list(compositions)
        self.preferred_sheets = preferred_sheets or []
        self.warnings = list(warnings or [])
        self._by_code: dict[str, list[Composition]] = {}
        for composition in self.compositions:
            self._by_code.setdefault(composition.code, []).append(composition)

    def __len__(self) -> int:
        return len(self.compositions)

    def codes(self) -> list[str]:
        return sorted(self._by_code)

    def all(self, code: str) -> list[Composition]:
        return list(self._by_code.get(code, []))

    def get(self, code: str) -> Composition | None:
        """Composição de um código. Havendo duplicidade, vence a aba de maior precedência."""
        found = self._by_code.get(code)
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        def rank(item: Composition) -> int:
            try:
                return self.preferred_sheets.index(item.sheet)
            except ValueError:
                return len(self.preferred_sheets)
        return sorted(found, key=lambda c: (rank(c), c.title_row))[0]

    def owner_of_row(self, sheet: str, row: int) -> Composition | None:
        """Qual composição contém determinada linha (usado nas conferências)."""
        best = None
        for composition in self.compositions:
            if composition.sheet != sheet or composition.title_row > row:
                continue
            if best is None or composition.title_row > best.title_row:
                best = composition
        return best


def _is_section(value, keywords) -> str | None:
    if not isinstance(value, str):
        return None
    text = normalize(value)
    return text if any(text.startswith(k) for k in keywords) else None


DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_WHITESPACE = re.compile(r"[\s\u00a0]+")
_UNIT_SPLIT = re.compile(rf"\s[{DASHES}]\s")


def flatten(text: str) -> str:
    """Achata o título numa linha só.

    Na Tabela SEINFRA real 61 títulos trazem uma quebra de linha antes da
    unidade (`'C4933 - HASTE ...\\n - UN'`) e outros trazem tabulações ou uma
    corrida de espaços. Como `.` do regex não atravessa `\\n`, o título não era
    reconhecido — e sem título novo os insumos seguintes iam parar na
    composição anterior.
    """
    return _WHITESPACE.sub(" ", text).strip()


def _looks_like_title(text: str) -> bool:
    """Heurística usada só para avisar: código curto seguido de um traço."""
    head = text.split(" ", 1)[0]
    return (bool(head) and head[0].isalnum() and head.upper() == head
            and any(d in text for d in DASHES) and len(head) <= 20)


def parse_sheet(rows: Iterable[list], sheet_name: str,
                config: CompositionConfig | None = None,
                warnings: list[str] | None = None) -> list[Composition]:
    """Lê composições de uma sequência de linhas (lista de valores por célula).

    `rows` é qualquer iterável de listas — o que permite testar sem Excel.

    `warnings`, quando informado, recebe um aviso por linha que *parece* título
    de composição e mesmo assim não foi reconhecida. Antes essa linha era
    silenciosamente tratada como dado solto e a composição anterior continuava
    ativa, engolindo os insumos da seguinte: corrupção invisível de dado. O
    aviso segue o mesmo espírito do log de inserções de `audit.py`.
    """
    config = config or CompositionConfig()
    title_re = re.compile(config.title_re)
    keywords = tuple(normalize(k) for k in config.section_keywords)
    code_i = config.code_column - 1
    desc_i = config.description_column - 1
    unit_i = config.unit_column - 1
    coef_i = config.coefficient_column - 1

    found: list[Composition] = []
    current: Composition | None = None
    section: str | None = None

    for row_number, values in enumerate(rows, start=1):
        def cell(index):
            return values[index] if index < len(values) else None

        first = cell(code_i)
        if isinstance(first, str) and first.strip():
            text = first.strip()
            keyword = _is_section(text, keywords)
            if keyword:
                section = keyword
                continue
            flat = flatten(text)
            match = title_re.match(flat)
            empty_neighbours = not str(cell(desc_i) or "").strip() and not str(cell(unit_i) or "").strip()
            if match and empty_neighbours:
                code = match.group(1).strip()
                rest = match.group(2).strip()
                description, unit = rest, None
                split = _UNIT_SPLIT.split(rest)
                if len(split) > 1:
                    description = _UNIT_SPLIT.sub(" - ", " - ".join(split[:-1])).strip()
                    unit = split[-1].strip()
                current = Composition(code, description, unit, sheet_name, row_number)
                found.append(current)
                section = None
                continue
            if warnings is not None and empty_neighbours and not match and _looks_like_title(flat):
                warnings.append(
                    f"possível título de composição não reconhecido em "
                    f"{sheet_name}!A{row_number}: {flat[:120]!r}")

        coefficient = cell(coef_i)
        if (current is not None and isinstance(first, str) and first.strip()
                and cell(desc_i) is not None and isinstance(coefficient, (int, float))
                and not isinstance(coefficient, bool)):
            code = first.strip()
            if code not in current.inputs:
                current.inputs[code] = Input(code, str(cell(desc_i)).strip(),
                                             str(cell(unit_i)).strip() if cell(unit_i) else None,
                                             float(coefficient), row_number, section)
    return found


def _sheet_rows(worksheet, max_column: int):
    row_number = 0
    for row in worksheet.iter_rows(min_row=1, max_col=max_column):
        row_number += 1
        yield row_number, [cell.value for cell in row]


def build_index(workbook, config: CompositionConfig | None = None,
                sheet_names: list[str] | None = None) -> CompositionIndex:
    """Constrói o índice a partir de um workbook openpyxl aberto com `data_only=True`."""
    config = config or CompositionConfig()
    names = sheet_names or list(config.sheets) or autodetect_sheets(workbook, config)
    if not names:
        raise ValueError("nenhuma aba de composição encontrada; declare `compositions.sheets`")
    max_column = max(config.code_column, config.description_column,
                     config.unit_column, config.coefficient_column)
    compositions: list[Composition] = []
    warnings: list[str] = []
    for name in names:
        if name not in workbook.sheetnames:
            raise ValueError(f"aba de composição inexistente: {name!r}")
        worksheet = workbook[name]
        rows = (values for _, values in _sheet_rows(worksheet, max_column))
        compositions.extend(parse_sheet(rows, name, config, warnings))
    return CompositionIndex(compositions, preferred_sheets=names, warnings=warnings)


def autodetect_sheets(workbook, config: CompositionConfig | None = None) -> list[str]:
    """Aponta as abas que se parecem com relatórios de composição."""
    config = config or CompositionConfig()
    title_re = re.compile(config.title_re)
    max_column = max(config.code_column, config.coefficient_column)
    detected: list[tuple[int, str]] = []
    for name in workbook.sheetnames:
        worksheet = workbook[name]
        hits = 0
        for index, (_, values) in enumerate(_sheet_rows(worksheet, max_column)):
            if index > 4000:
                break
            value = values[config.code_column - 1] if values else None
            if isinstance(value, str) and title_re.match(flatten(value)):
                hits += 1
        if hits >= config.min_tables_to_autodetect:
            detected.append((hits, name))
    return [name for _, name in sorted(detected, reverse=True)]
