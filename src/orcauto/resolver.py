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
from typing import Iterable

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
        self._cache: dict[tuple[str, frozenset], dict[str, Coefficient]] = {}

    def resolve(self, code: str, stop_at: Iterable[str] = ()) -> dict[str, Coefficient]:
        """Todos os insumos-folha de um serviço, com origem e fator.

        `stop_at` lista códigos que **não** devem ser abertos: mesmo tendo
        composição própria, eles saem como parcela direta, com o coeficiente
        de primeiro nível. É o que faz uma coluna rotulada com um código de
        serviço receber valor — antes ela ficava eternamente vazia, porque o
        resolvedor devolvia só os insumos de dentro dele.
        """
        stop = frozenset(stop_at)
        key = (code, stop)
        if key in self._cache:
            return self._cache[key]
        found: dict[str, list[Term]] = {}
        self._walk(self.index.get(code), 1.0, 0, (), found, {code}, stop)
        result = {key_: Coefficient(key_, terms) for key_, terms in found.items()}
        self._cache[key] = result
        return result

    def _walk(self, composition, factor, depth, path, found, seen, stop=frozenset()):
        if composition is None or depth > self.config.max_depth:
            return
        trail = path + (composition.code,)
        for code, item in composition.inputs.items():
            child = self.index.get(code) if self._service_re.match(code) else None
            recurse = (child is not None and child.code not in seen
                       and code not in stop
                       and depth < self.config.max_depth)
            if recurse:
                self._walk(child, factor * item.coefficient, depth + 1, trail,
                           found, seen | {child.code}, stop)
            else:
                found.setdefault(code, []).append(
                    Term(composition.sheet, item.row, factor, item.coefficient, trail))

    def coefficients_for(self, code: str, wanted: dict[str, str]) -> dict[str, Coefficient]:
        """Filtra a resolução pelas colunas rastreadas: {coluna: código do insumo}.

        Um código que já tem coluna própria nunca é aberto — senão ele sumiria
        do resultado e a coluna dele ficaria vazia, enquanto os insumos de
        dentro dele seriam somados às colunas dos insumos da composição-mãe
        (a mão de obra da argamassa entrando na mão de obra da alvenaria).
        """
        resolved = self.resolve(code, stop_at=wanted.values())
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
                 sections: tuple[str, ...] = (),
                 expand_subservices: bool = True,
                 priority_units: tuple[str, ...] = ()) -> list[InputColumn]:
    """Insumos usados por um tópico inteiro, em ordem determinística.

    `expand_subservices=True` (padrão histórico) resolve recursivamente e só
    insumos-folha viram coluna: a composição C0329 consome o serviço C3129, e o
    que aparece na aba são os insumos de dentro dele.

    `expand_subservices=False` faz o sub-serviço com composição própria virar
    ele mesmo uma coluna, com o coeficiente de primeiro nível. É como a planilha
    feita à mão trabalha — a aba INFRAESTRUTURA real tem uma coluna rotulada
    `C3129` — e é o que o relatório de erros v3 pede em três casos independentes
    (a coluna de ARGAMASSA de C3347 e C4592, as colunas C4281/C4282 de C4301).
    Também é o que elimina a dupla contagem: com o sub-serviço aberto, a mão de
    obra da argamassa era somada à mão de obra da alvenaria (SERVENTE 10,0 em
    vez de 7,0 em C3347).

    A ordem é a de primeira aparição, percorrendo os itens na ordem do
    orçamento, para que duas execuções sobre o mesmo PDF gerem a mesma aba.
    """
    columns: dict[str, InputColumn] = {}
    descriptions = _input_catalog(index)
    for item in items:
        composition = index.get(item.code)
        if composition is None:
            continue
        resolved = (resolver.resolve(item.code) if expand_subservices
                    else resolver.resolve(item.code, stop_at=composition.inputs))
        for code, coefficient in resolved.items():
            existing = columns.get(code)
            if existing is None:
                description, unit, section = descriptions.get(code, (code, None, None))
                columns[code] = InputColumn(
                    code, description, unit, [item.code], section,
                    unresolved_service=bool(resolver._service_re.match(code)
                                            and index.get(code) is None))
            elif item.code not in existing.used_by:
                existing.used_by.append(item.code)
    escolhidas = list(columns.values())
    if sections:
        wanted = [normalize(s) for s in sections]
        escolhidas = [c for c in escolhidas
                      if c.section and any(normalize(c.section).startswith(w) for w in wanted)]
    return order_by_unit(escolhidas, priority_units)


def order_by_unit(columns: list[InputColumn],
                  priority: tuple[str, ...] = ()) -> list[InputColumn]:
    """Agrupa as colunas por unidade, com as unidades prioritárias na frente.

    A equipe usa as colunas em **H** (hora) para outras contas — mão de obra e
    equipamento — e precisa delas à mão, não espalhadas entre trinta colunas de
    material. Então elas vêm primeiro, e o resto fica agrupado por unidade, o
    que também deixa junto o que se soma junto (M2 com M2, KG com KG).

    A ordenação é estável: dentro de cada grupo continua valendo a ordem de
    primeira aparição no orçamento, que é o que faz duas execuções sobre o
    mesmo PDF gerarem a mesma aba.
    """
    prioritarias = [normalize(u) for u in priority]
    primeira_vez: dict[str, int] = {}
    for posicao, coluna in enumerate(columns):
        primeira_vez.setdefault(normalize(coluna.unit), posicao)

    def chave(coluna: InputColumn) -> tuple:
        unidade = normalize(coluna.unit)
        if unidade in prioritarias:
            return (0, prioritarias.index(unidade))
        if not unidade:                      # sem unidade declarada: por último
            return (2, 0)
        return (1, primeira_vez[unidade])

    return sorted(columns, key=chave)


def _input_catalog(index) -> dict[str, tuple[str, str | None, str | None]]:
    """Descrição, unidade e seção de cada insumo, como aparecem nas composições."""
    catalog: dict[str, tuple[str, str | None, str | None]] = {}
    for composition in index.compositions:
        for code, item in composition.inputs.items():
            if code not in catalog and item.description:
                catalog[code] = (item.description, item.unit, item.section)
    return catalog
