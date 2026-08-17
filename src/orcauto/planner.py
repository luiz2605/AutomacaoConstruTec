# -*- coding: utf-8 -*-
"""Decide o que gravar em cada linha da aba (AUTO).

Três modos:

* **SUBSTITUI**  — a linha existente traz um código que *não consta em nenhum
  item do orçamento* e descreve o mesmo serviço de um item do PDF. A linha é
  assumida pelo item do orçamento. É o que evita dupla contagem no TOTAL:
  continua havendo uma linha por serviço.
* **ATUALIZADA** — a linha já traz exatamente o mesmo código do item. Só os
  coeficientes são automatizados; a quantidade da aba é preservada por padrão.
* **NOVA**       — item do orçamento sem contrapartida na aba, em linha livre.

A atribuição é feita em três passadas, da maior para a menor confiança
(código idêntico -> melhor semelhança -> ordem do orçamento), e não na ordem
em que os itens aparecem no PDF: senão um item parecido, lido antes, tomaria
a linha do item que de fato corresponde a ela.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .compositions import Composition, CompositionIndex
from .config import RulesConfig
from .layout import SheetLayout
from .pdf_budget import BudgetItem
from .resolver import Coefficient, Resolver
from .textutil import similarity

UPDATED, SUBSTITUTED, NEW = "ATUALIZADA", "SUBSTITUI", "NOVA"


@dataclass
class PlannedRow:
    item: BudgetItem
    composition: Composition
    row: int
    mode: str
    coefficients: dict[str, Coefficient]
    quantity_source: str                    # "orcamento" | "aba"
    quantity: float | None
    similarity: float | None = None
    replaced_code: str | None = None
    replaced_description: str | None = None
    replaced_quantity: float | None = None
    beyond_total: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def writes_identity(self) -> bool:
        """Grava código/descrição/unidade/quantidade, e não apenas coeficientes."""
        return self.mode in (NEW, SUBSTITUTED)


@dataclass
class SkippedItem:
    item: BudgetItem
    composition: Composition | None
    reason: str


@dataclass
class SheetPlan:
    sheet: str
    layout: SheetLayout
    topic_number: int
    topic_name: str
    rows: dict[int, PlannedRow] = field(default_factory=dict)
    skipped: list[SkippedItem] = field(default_factory=list)
    new_last_row: int | None = None         # preenchido se o TOTAL precisar ampliar

    def ordered(self) -> list[PlannedRow]:
        return [self.rows[key] for key in sorted(self.rows)]


class PlanError(RuntimeError):
    pass


@dataclass
class _Candidate:
    item: BudgetItem
    composition: Composition
    coefficients: dict[str, Coefficient]


def plan_sheet(layout: SheetLayout, items: list[BudgetItem], index: CompositionIndex,
               resolver: Resolver, budget_codes: set[str],
               topic_number: int, topic_name: str,
               rules: RulesConfig | None = None) -> SheetPlan:
    rules = rules or RulesConfig()
    plan = SheetPlan(layout.sheet, layout, topic_number, topic_name)

    forced = {int(row): code for row, code in
              (rules.substitution_force.get(layout.sheet) or {}).items()}
    blocked = set(rules.substitution_block.get(layout.sheet) or [])
    overrides = {int(row): source for row, source in
                 (rules.quantity_override.get(layout.sheet) or {}).items()}

    # ---- itens com composição e ao menos um insumo rastreado nesta aba
    candidates: list[_Candidate] = []
    for item in items:
        composition = index.get(item.code)
        if composition is None:
            plan.skipped.append(SkippedItem(item, None, "composição não encontrada no arquivo"))
            continue
        coefficients = resolver.coefficients_for(item.code, layout.tracked)
        if not coefficients:
            plan.skipped.append(SkippedItem(item, composition, "sem insumo rastreado nesta aba"))
            continue
        candidates.append(_Candidate(item, composition, coefficients))

    pending = list(candidates)
    taken: dict[int, tuple[_Candidate, str, float | None]] = {}

    # ---- passada 1: código idêntico
    for candidate in list(pending):
        for row in layout.rows_inside_total():
            service = layout.rows[row]
            if row in taken or row in forced or not service.code:
                continue
            if service.code == candidate.item.code:
                taken[row] = (candidate, UPDATED, None)
                pending.remove(candidate)
                break

    # ---- passada 2: substituição de linha legada (melhor semelhança primeiro)
    pairs: list[tuple[float, int, _Candidate]] = []
    for candidate in pending:
        for row, code in forced.items():
            if code == candidate.item.code:
                pairs.append((2.0, row, candidate))       # forçado vence tudo
        if not rules.substitution_enabled:
            continue
        for row in layout.rows_inside_total():
            service = layout.rows[row]
            if not service.code or service.code in blocked or service.code in budget_codes:
                continue                                   # vazia, bloqueada ou vigente
            if not (set(candidate.coefficients) & service.filled_columns):
                continue                                   # não disputam insumo algum
            legacy = _legacy_description(index, service)
            score = similarity(candidate.composition.description, legacy)
            if score >= rules.substitution_min_similarity:
                pairs.append((score, row, candidate))
    for score, row, candidate in sorted(pairs, key=lambda p: -p[0]):
        if row in taken or candidate not in pending:
            continue
        taken[row] = (candidate, SUBSTITUTED, min(score, 1.0))
        pending.remove(candidate)

    # ---- passada 3: linhas livres, na ordem do orçamento
    free = [row for row in layout.free_rows() if row not in taken]
    for candidate in list(pending):
        if not free:
            plan.skipped.append(SkippedItem(candidate.item, candidate.composition,
                                            "sem linha livre na aba (acrescente linhas ao bloco)"))
            pending.remove(candidate)
            continue
        taken[free.pop(0)] = (candidate, NEW, None)
        pending.remove(candidate)

    # ---- materializa
    for row, (candidate, mode, score) in taken.items():
        existing = layout.rows[row]
        source = "orcamento" if mode in (NEW, SUBSTITUTED) else rules.quantity_policy
        source = overrides.get(row, source)
        quantity = candidate.item.quantity if source == "orcamento" else existing.quantity
        planned = PlannedRow(
            item=candidate.item, composition=candidate.composition, row=row, mode=mode,
            coefficients=candidate.coefficients, quantity_source=source, quantity=quantity,
            similarity=score, beyond_total=row > layout.last_row,
        )
        if mode == SUBSTITUTED:
            planned.replaced_code = existing.code
            planned.replaced_description = _legacy_description(index, existing)
            planned.replaced_quantity = existing.quantity
            planned.notes.append(f"código {existing.code!r} não consta no orçamento; "
                                 f"linha assumida pelo item {candidate.item.order}")
        if mode == UPDATED and source == "orcamento":
            planned.notes.append("quantidade da aba substituída pela do orçamento (override)")
        if planned.beyond_total:
            planned.notes.append("linha fora do intervalo original do TOTAL")
        plan.rows[row] = planned

    beyond = [row for row in plan.rows if row > layout.last_row]
    if beyond:
        if not rules.extend_total_range:
            raise PlanError(f"[{layout.sheet}] linhas {sorted(beyond)} caem fora do intervalo "
                            "do TOTAL e `rules.extend_total_range` está desligado")
        plan.new_last_row = max(beyond)
    return plan


def _legacy_description(index: CompositionIndex, service) -> str | None:
    """Descrição do serviço legado: prefere a da composição, que é limpa."""
    if service.code:
        composition = index.get(service.code)
        if composition is not None:
            return composition.description
    return service.description
