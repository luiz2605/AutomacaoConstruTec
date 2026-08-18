# -*- coding: utf-8 -*-
"""Detecção automática do layout de uma aba de levantamento.

Nenhuma posição é fixada em código. A âncora é a linha de TOTAL: a fórmula
`SUMPRODUCT($E$10:$E$17;F10:F17)` informa, de uma vez, qual é a coluna de
quantidade e quais linhas compõem o bloco de serviços. A partir dela o resto
é deduzido para cima.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import TargetConfig
from .textutil import column_index, column_letter, normalize

_SUMPRODUCT = re.compile(
    r"SUMPRODUCT\(\s*\$?(?P<qcol>[A-Z]{1,3})\$?(?P<r0>\d+)\s*:\s*\$?(?P=qcol)\$?(?P<r1>\d+)\s*[,;]",
    re.IGNORECASE)


ERROR_VALUES = ("#REF!", "#N/A", "#VALUE!", "#NAME?", "#DIV/0!", "#NULL!", "#NUM!")


def is_empty(value) -> bool:
    """Célula sem conteúdo aproveitável: vazia, ou exibindo um erro do Excel.

    A planilha original tem VLOOKUPs apontando para `#REF!`, que o Excel
    resolve como texto vazio ou erro. Uma célula assim não carrega informação
    e pode ser preenchida sem destruir nada do trabalho do orçamentista.
    """
    if value is None:
        return True
    text = str(value).strip()
    return not text or text in ERROR_VALUES


@dataclass
class ServiceRow:
    row: int
    code: str | None
    description: str | None
    unit: str | None
    quantity: float | None
    filled_columns: set[str] = field(default_factory=set)

    @property
    def is_blank(self) -> bool:
        """Linha realmente disponível: sem código, sem quantidade, sem descrição
        e sem nenhum coeficiente rastreado. Uma linha com escopo manual (por
        exemplo um insumo avulso, sem código de serviço) NÃO é livre."""
        return not (self.filled_columns or self.code or self.quantity
                    or (self.description or "").strip())


@dataclass
class SheetLayout:
    sheet: str
    header_row: int
    input_row: int              # linha com os códigos dos insumos rastreados
    quantity_column: str
    order_column: str
    code_column: str
    description_column: str
    unit_column: str
    first_row: int
    last_row: int               # última linha dentro do intervalo do TOTAL
    total_row: int
    max_row: int                # última linha utilizável antes do TOTAL
    tracked: dict[str, str]     # coluna -> código do insumo
    rows: dict[int, ServiceRow] = field(default_factory=dict)

    def free_rows(self) -> list[int]:
        """Linhas realmente vazias, primeiro as que já somam no TOTAL."""
        return [r for r in self.rows_inside_total() if self.rows[r].is_blank] + \
               [r for r in self.rows_beyond_total() if self.rows[r].is_blank]

    def rows_beyond_total(self) -> list[int]:
        """Linhas depois do intervalo do TOTAL: usá-las exige ampliar o intervalo."""
        return list(range(self.last_row + 1, self.max_row + 1))

    def rows_inside_total(self) -> list[int]:
        return list(range(self.first_row, self.last_row + 1))


@dataclass
class TemplateLayout:
    """Âncoras de uma aba-molde, que ainda não tem nenhum insumo declarado."""
    sheet: str
    header_row: int
    input_row: int
    quantity_column: str
    order_column: str
    code_column: str
    description_column: str
    unit_column: str
    first_row: int
    last_row: int
    total_row: int
    slots: list[str]        # colunas de insumo já formatadas no molde


class LayoutError(RuntimeError):
    pass


def detect_template(formula_ws, value_ws, config: TargetConfig | None = None) -> TemplateLayout:
    """Lê as âncoras de uma aba-molde.

    `detect` exige ao menos um insumo declarado na linha de códigos, e o molde
    por definição não tem nenhum. Aqui as colunas de insumo disponíveis são
    deduzidas da própria linha de TOTAL: cada coluna que já traz um SUMPRODUCT
    é um lugar formatado esperando um insumo. É a leitura mais fiel à intenção
    de quem desenhou o molde, e não depende de adivinhar estilo.
    """
    config = config or TargetConfig()
    total_row = _find_total_row(value_ws, config)
    quantity_column, first_row, last_row = _read_total_range(formula_ws, total_row)
    header_row = _find_header_row(value_ws, total_row, config)
    quantity_index = column_index(quantity_column)

    slots = []
    for index in range(quantity_index + 1, formula_ws.max_column + 1):
        value = formula_ws.cell(total_row, index).value
        if isinstance(value, str) and "SUMPRODUCT" in value.upper():
            slots.append(column_letter(index))
    if not slots:
        raise LayoutError(f"[{formula_ws.title}] o molde não tem nenhuma coluna de insumo "
                          f"com SUMPRODUCT na linha {total_row}")
    return TemplateLayout(
        sheet=formula_ws.title, header_row=header_row, input_row=header_row - 1,
        quantity_column=quantity_column,
        order_column=column_letter(max(1, quantity_index - 4)),
        code_column=column_letter(max(1, quantity_index - 3)),
        description_column=column_letter(max(1, quantity_index - 2)),
        unit_column=column_letter(max(1, quantity_index - 1)),
        first_row=first_row, last_row=last_row, total_row=total_row, slots=slots)


def detect(formula_ws, value_ws, config: TargetConfig | None = None) -> SheetLayout:
    """Descobre o layout de uma aba a partir das duas leituras (fórmula e valor)."""
    config = config or TargetConfig()
    total_row = _find_total_row(value_ws, config)
    quantity_column, first_row, last_row = _read_total_range(formula_ws, total_row)
    header_row = _find_header_row(value_ws, total_row, config)
    input_row = header_row - 1
    if input_row < 1:
        raise LayoutError(f"[{formula_ws.title}] linha de insumos não localizada")

    quantity_index = column_index(quantity_column)
    tracked: dict[str, str] = {}
    for index in range(quantity_index + 1, formula_ws.max_column + 1):
        value = value_ws.cell(input_row, index).value
        if isinstance(value, str) and value.strip():
            tracked[column_letter(index)] = value.strip()
    if not tracked:
        raise LayoutError(f"[{formula_ws.title}] nenhum insumo rastreado na linha {input_row}")

    layout = SheetLayout(
        sheet=formula_ws.title, header_row=header_row, input_row=input_row,
        quantity_column=quantity_column,
        order_column=column_letter(max(1, quantity_index - 4)),
        code_column=column_letter(max(1, quantity_index - 3)),
        description_column=column_letter(max(1, quantity_index - 2)),
        unit_column=column_letter(max(1, quantity_index - 1)),
        first_row=first_row, last_row=last_row, total_row=total_row,
        max_row=total_row - 1, tracked=tracked,
    )
    for row in range(first_row, layout.max_row + 1):
        layout.rows[row] = _read_row(formula_ws, value_ws, layout, row)
    return layout


def _find_total_row(value_ws, config: TargetConfig) -> int:
    wanted = normalize(config.total_label)
    for row in range(1, value_ws.max_row + 1):
        for column in range(1, 4):
            if normalize(value_ws.cell(row, column).value) == wanted:
                return row
    raise LayoutError(f"[{value_ws.title}] linha de {config.total_label!r} não encontrada")


def _read_total_range(formula_ws, total_row: int) -> tuple[str, int, int]:
    for column in range(1, formula_ws.max_column + 1):
        value = formula_ws.cell(total_row, column).value
        if isinstance(value, str) and "SUMPRODUCT" in value.upper():
            match = _SUMPRODUCT.search(value.replace(" ", ""))
            if match:
                return (match.group("qcol").upper(),
                        int(match.group("r0")), int(match.group("r1")))
    raise LayoutError(f"[{formula_ws.title}] a linha {total_row} não tem SUMPRODUCT legível; "
                      "o intervalo do bloco de serviços não pôde ser deduzido")


def _find_header_row(value_ws, total_row: int, config: TargetConfig) -> int:
    keywords = [normalize(k) for k in config.header_keywords]
    for row in range(total_row - 1, 0, -1):
        texts = [normalize(value_ws.cell(row, c).value) for c in range(1, 8)]
        if sum(any(t.startswith(k) for t in texts) for k in keywords) >= len(keywords):
            return row
    raise LayoutError(f"[{value_ws.title}] linha de cabeçalho não encontrada")


def _read_row(formula_ws, value_ws, layout: SheetLayout, row: int) -> ServiceRow:
    filled = {column for column in layout.tracked
              if formula_ws[f"{column}{row}"].value not in (None, "")}
    code = value_ws[f"{layout.code_column}{row}"].value
    quantity = value_ws[f"{layout.quantity_column}{row}"].value
    description = value_ws[f"{layout.description_column}{row}"].value
    unit = value_ws[f"{layout.unit_column}{row}"].value
    return ServiceRow(
        row=row,
        code=str(code).strip() if isinstance(code, str) and str(code).strip() else None,
        description=str(description).strip() if isinstance(description, str) else None,
        unit=None if is_empty(unit) else str(unit).strip(),
        quantity=quantity if isinstance(quantity, (int, float)) and not isinstance(quantity, bool) else None,
        filled_columns=filled,
    )
