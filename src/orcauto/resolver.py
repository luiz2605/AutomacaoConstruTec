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
from .textutil import format_number


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
