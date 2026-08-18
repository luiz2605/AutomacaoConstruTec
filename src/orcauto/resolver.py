# -*- coding: utf-8 -*-
"""Resolução do coeficiente de um insumo dentro de uma composição.

Quando o insumo não está direto na composição, mas dentro de um serviço que ela
consome, o coeficiente é o do sub-item multiplicado pelo coeficiente do serviço.
A fórmula gravada preserva essa rastreabilidade: em vez de um número solto,
referencia a linha de origem (`'COMPOSIÇÃO TAB 28'!D55622*0,3`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .compositions import CompositionIndex
from .config import CompositionConfig
from .textutil import format_number, normalize


@dataclass
class Term:
    """Uma parcela do coeficiente: linha de origem x fator acumulado."""
    sheet: str
    row: int
    factor: float
    coefficient: float
    path: tuple[str, ...]

    @property
    def value(self) -> float:
        return self.coefficient * self.factor

    def formula(self) -> str:
        ref = f"'{self.sheet}'!D{self.row}"
        return ref if abs(self.factor - 1.0) < 1e-12 else f"{ref}*{format_number(self.factor)}"

    def trail(self) -> str:
        return ">".join(self.path)


@dataclass
class Coefficient:
    """Coeficiente completo de um insumo: uma ou mais parcelas somadas."""
    input_code: str
    terms: list[Term]

    @property
    def value(self) -> float:
        return sum(term.value for term in self.terms)

    def formula(self, coefficient_column: int = 4) -> str:
        letter = chr(64 + coefficient_column) if coefficient_column <= 26 else "D"
        parts = []
        for term in self.terms:
            text = term.formula()
            if letter != "D":
                text = text.replace(f"!D{term.row}", f"!{letter}{term.row}", 1)
            parts.append(text)
        return "+".join(parts)

    def trail(self) -> str:
        return " ; ".join(term.trail() for term in self.terms)


class Resolver:
    def __init__(self, index: CompositionIndex, config: CompositionConfig | None = None):
        self.index = index
        self.config = config or CompositionConfig()
        self._service_re = re.compile(self.config.service_code_re)
        self._cache: dict[str, dict[str, Coefficient]] = {}

    def resolve(self, code: str) -> dict[str, Coefficient]:
        """Todos os insumos-folha de um serviço, com origem e fator."""
        if code in self._cache:
            return self._cache[code]
        found: dict[str, list[Term]] = {}
        self._walk(self.index.get(code), 1.0, 0, (), found, {code})
        result = {key: Coefficient(key, terms) for key, terms in found.items()}
        self._cache[code] = result
        return result

    def _walk(self, composition, factor, depth, path, found, seen):
        if composition is None or depth > self.config.max_depth:
            return
        trail = path + (composition.code,)
        for code, item in composition.inputs.items():
            child = self.index.get(code) if self._service_re.match(code) else None
            recurse = (child is not None and child.code not in seen
                       and depth < self.config.max_depth)
            if recurse:
                self._walk(child, factor * item.coefficient, depth + 1, trail,
                           found, seen | {child.code})
            else:
                found.setdefault(code, []).append(
                    Term(composition.sheet, item.row, factor, item.coefficient, trail))

    def coefficients_for(self, code: str, wanted: dict[str, str]) -> dict[str, Coefficient]:
        """Filtra a resolução pelas colunas rastreadas: {coluna: código do insumo}."""
        resolved = self.resolve(code)
        return {column: resolved[input_code]
                for column, input_code in wanted.items() if input_code in resolved}


@dataclass
class InputColumn:
    """Um insumo-folha que merece uma coluna na aba gerada."""
    code: str
    description: str
    unit: str | None
    used_by: list[str]                      # códigos de serviço que o consomem
    section: str | None = None              # MATERIAIS, MAO DE OBRA, EQUIPAMENTOS...
    unresolved_service: bool = False        # parece serviço, mas não tem composição

    @property
    def label(self) -> str:
        return self.description or self.code


def topic_inputs(items, index, resolver: Resolver,
                 sections: tuple[str, ...] = ()) -> list[InputColumn]:
    """Insumos-folha usados por um tópico inteiro, em ordem determinística.

    A lista sai da resolução **recursiva** — nunca de `Composition.inputs` de
    primeiro nível. A diferença é decisiva: a composição C0329 tem, no bloco
    SERVIÇOS, o código C3129, que é ele mesmo uma sub-composição. Lendo o
    primeiro nível, C3129 viraria uma coluna; o que precisa virar coluna são os
    insumos reais de dentro dele.

    A ordem é a de primeira aparição, percorrendo os itens na ordem do
    orçamento, para que duas execuções sobre o mesmo PDF gerem a mesma aba.
    """
    columns: dict[str, InputColumn] = {}
    descriptions = _input_catalog(index)
    for item in items:
        if index.get(item.code) is None:
            continue
        for code, coefficient in resolver.resolve(item.code).items():
            existing = columns.get(code)
            if existing is None:
                description, unit, section = descriptions.get(code, (code, None, None))
                columns[code] = InputColumn(
                    code, description, unit, [item.code], section,
                    unresolved_service=bool(resolver._service_re.match(code)
                                            and index.get(code) is None))
            elif item.code not in existing.used_by:
                existing.used_by.append(item.code)
    if not sections:
        return list(columns.values())
    wanted = [normalize(s) for s in sections]
    return [c for c in columns.values()
            if c.section and any(normalize(c.section).startswith(w) for w in wanted)]


def _input_catalog(index) -> dict[str, tuple[str, str | None, str | None]]:
    """Descrição, unidade e seção de cada insumo, como aparecem nas composições."""
    catalog: dict[str, tuple[str, str | None, str | None]] = {}
    for composition in index.compositions:
        for code, item in composition.inputs.items():
            if code not in catalog and item.description:
                catalog[code] = (item.description, item.unit, item.section)
    return catalog
