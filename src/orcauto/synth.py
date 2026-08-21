# -*- coding: utf-8 -*-
"""Síntese de uma aba de levantamento a partir da aba-molde.

Caminho usado quando o tópico do orçamento **não tem** aba de destino. A aba
nasce vazia, então não existe linha pré-existente para atualizar ou substituir:
todo item vira uma linha nova, na ordem do orçamento. Por isso este módulo não
reaproveita `planner.py` — os três modos de lá resolvem um problema que aqui
não existe.

O que ele precisa decidir, e que o caminho de preenchimento recebe pronto, é o
**conjunto de colunas**: uma por insumo-folha realmente consumido pelos itens
do tópico, na ordem de primeira aparição.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .compositions import Composition, CompositionIndex
from .config import Config
from .layout import TemplateLayout
from .ooxml import (cell_style, clear_row, ensure_row, hide_row, row_styles, set_cell,
                    set_column_width, set_dimension, show_row, total_formula,
                    unit_lookup_formula)
from .pdf_budget import BudgetItem, Topic
from .planner import SkippedItem
from .resolver import Coefficient, InputColumn, Resolver, topic_inputs
from .textutil import column_index, column_letter


@dataclass
class SynthRow:
    item: BudgetItem
    composition: Composition
    row: int
    quantity: float | None
    coefficients: dict[str, Coefficient] = field(default_factory=dict)


@dataclass
class SynthPlan:
    sheet: str                                   # nome da aba a criar
    template: str
    topic_number: int
    topic_name: str
    columns: list[tuple[str, InputColumn]] = field(default_factory=list)
    rows: list[SynthRow] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    first_row: int = 0
    total_row: int = 0
    appended: list[str] = field(default_factory=list)   # colunas além do molde
    created: bool = True                                # False = aba não valia a pena
    reason: str = ""

    def ordered(self) -> list[SynthRow]:
        return list(self.rows)


def plan_synthesis(layout: TemplateLayout, topic: Topic, sheet_name: str,
                   index: CompositionIndex, resolver: Resolver,
                   config: Config | None = None) -> SynthPlan:
    config = config or Config()
    plan = SynthPlan(sheet=sheet_name, template=layout.sheet,
                     topic_number=topic.number, topic_name=topic.name,
                     first_row=layout.first_row)

    usable: list[tuple[BudgetItem, Composition]] = []
    for item in topic.items:
        composition = index.get(item.code)
        if composition is None:
            plan.skipped.append(SkippedItem(item, None, "composição não encontrada no arquivo"))
            continue
        if not resolver.resolve(item.code):
            plan.skipped.append(SkippedItem(item, composition, "composição sem insumos"))
            continue
        usable.append((item, composition))

    inputs = topic_inputs([item for item, _ in usable], index, resolver,
                          config.compositions.column_sections)
    for position, column_input in enumerate(inputs):
        if position < len(layout.slots):
            letter = layout.slots[position]
        else:
            letter = column_letter(column_index(layout.slots[-1]) + 1 + position - len(layout.slots))
            plan.appended.append(letter)
        plan.columns.append((letter, column_input))

    wanted = {letter: column_input.code for letter, column_input in plan.columns}
    for offset, (item, composition) in enumerate(usable):
        row = layout.first_row + offset
        plan.rows.append(SynthRow(item=item, composition=composition, row=row,
                                  quantity=item.quantity,
                                  coefficients=resolver.coefficients_for(item.code, wanted)))
    plan.total_row = layout.first_row + len(usable)
    return plan


def write_synthesis(xml: str, plan: SynthPlan, layout: TemplateLayout,
                    config: Config | None = None) -> str:
    """Escreve a aba sintetizada sobre a cópia do molde.

    A ordem importa. O formato das linhas de item e o da linha de TOTAL são
    capturados **antes** de qualquer escrita, e depois aplicados explicitamente.
    Sem isso, uma linha de item que caísse sobre a linha de TOTAL do molde
    herdaria o cinza de total, e o TOTAL de verdade, empurrado para baixo,
    nasceria sem formato nenhum — que era exatamente o defeito.
    """
    config = config or Config()
    unit_row = layout.header_row + 1
    model = layout.slots[-1]
    letters = [letter for letter, _ in plan.columns]
    body = [layout.order_column, layout.code_column, layout.description_column,
            layout.unit_column, layout.quantity_column] + letters

    # ---- formatos de referência, lidos do molde intacto
    item_style = row_styles(xml, layout.first_row, body)
    total_style = row_styles(xml, layout.total_row, body)

    # ---- barra colorida: cada aba diz a que tópico pertence
    xml = set_cell(xml, layout.banner_row, layout.order_column,
                   text=f"{config.targets.banner_prefix}{plan.topic_name}")

    # ---- colunas: cabeçalho de três linhas, escrito do zero
    # O molde traz a fórmula de unidade mas não a de nome; herdar cegamente
    # reproduziria esse buraco em toda aba gerada.
    for letter, column_input in plan.columns:
        forced = letter in plan.appended
        if forced:
            xml = set_column_width(xml, letter, template=model)
        xml = set_cell(xml, layout.input_row, letter, style_from=model,
                       force_style=forced, text=column_input.code)
        xml = set_cell(xml, layout.header_row, letter, style_from=model,
                       force_style=forced, text=column_input.label)
        xml = set_cell(xml, unit_row, letter, style_from=model, force_style=forced,
                       formula=unit_lookup_formula(letter, layout.input_row,
                                                   config.targets.insumos_lookup_range),
                       value=column_input.unit)

    # ---- uma linha por item, TODAS com o mesmo formato de linha de item
    for entry in plan.rows:
        xml = ensure_row(xml, entry.row, layout.first_row)
        xml = show_row(xml, entry.row)
        xml = set_cell(xml, entry.row, layout.order_column,
                       style=item_style[layout.order_column], text=entry.item.order)
        xml = set_cell(xml, entry.row, layout.code_column,
                       style=item_style[layout.code_column], text=entry.item.code)
        xml = set_cell(xml, entry.row, layout.description_column,
                       style=item_style[layout.description_column],
                       text=entry.composition.description)
        xml = set_cell(xml, entry.row, layout.unit_column,
                       style=item_style[layout.unit_column],
                       text=entry.composition.unit or entry.item.unit or "")
        xml = set_cell(xml, entry.row, layout.quantity_column,
                       style=item_style[layout.quantity_column],
                       **({"number": entry.quantity} if entry.quantity is not None else {}))
        for letter in letters:
            coefficient = entry.coefficients.get(letter)
            estilo = item_style.get(letter) or cell_style(xml, entry.row, model)
            if coefficient is None:
                xml = set_cell(xml, entry.row, letter, style=estilo)
            else:
                xml = set_cell(xml, entry.row, letter, style=estilo,
                               formula=coefficient.formula(config.compositions.coefficient_column),
                               value=coefficient.value)

    # ---- linha de TOTAL, sempre logo depois do último item
    xml = ensure_row(xml, plan.total_row, layout.total_row)
    xml = show_row(xml, plan.total_row)
    for column in body:
        xml = set_cell(xml, plan.total_row, column, style=total_style.get(column))
    xml = set_cell(xml, plan.total_row, layout.order_column,
                   style=total_style.get(layout.order_column),
                   text=config.targets.total_label)
    for letter, column_input in plan.columns:
        bag = (config.compositions.bag_size
               if column_input.code in config.compositions.bag_rounding_inputs else None)
        xml = set_cell(xml, plan.total_row, letter,
                       style=total_style.get(letter) or cell_style(xml, plan.total_row, model),
                       formula=total_formula(letter, layout.quantity_column,
                                             plan.first_row, plan.total_row - 1,
                                             bag_size=bag))

    # ---- sobras do molde depois do TOTAL: esvaziadas e ocultas
    for row in range(plan.total_row + 1, layout.total_row + 1):
        xml = clear_row(xml, row, body)
        xml = hide_row(xml, row)

    return set_dimension(xml, letters[-1] if letters else layout.quantity_column,
                         plan.total_row)
