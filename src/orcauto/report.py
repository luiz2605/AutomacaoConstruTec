# -*- coding: utf-8 -*-
"""Relatório de auditoria: texto para o terminal e aba LOG dentro da pasta."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ooxml import cell_xml
from .planner import NEW, SUBSTITUTED, UPDATED, SheetPlan
from .textutil import column_letter

HEADINGS = ("1)", "2)", "3)", "4)", "5)", "6)", "LEVANTAMENTO")


@dataclass
class Audit:
    plans: list[SheetPlan] = field(default_factory=list)
    suffix: str = " (AUTO)"
    budget_codes: set[str] = field(default_factory=set)
    synth: list = field(default_factory=list)

    def written_rows(self):
        for plan in self.plans:
            for planned in plan.ordered():
                yield plan, planned


def build_rows(audit: Audit) -> list[list]:
    """Linhas da aba de log (listas de valores, já na ordem das colunas)."""
    rows: list[list] = [
        ["LEVANTAMENTO AUTOMATIZADO - CRUZAMENTO ORCAMENTO (PDF) x COMPOSICOES (EXCEL)"],
        ["Busca do coeficiente: o codigo foi procurado APENAS onde forma o TITULO de uma tabela de "
         "composicao. Ocorrencias do mesmo codigo como sub-item de outro servico sao ignoradas."],
        ["Coeficiente aninhado: quando o insumo nao esta direto na composicao, mas dentro de um servico "
         "dela, a formula referencia a linha da sub-composicao multiplicada pelo coeficiente do servico."],
        ["MODO - ATUALIZADA: a linha ja tinha o mesmo codigo; so os coeficientes foram automatizados e a "
         "quantidade da aba foi preservada.  SUBSTITUI: linha legada, com codigo fora do orcamento, "
         "assumida pelo item equivalente do PDF (evita dupla contagem no TOTAL).  NOVA: item gravado em "
         "linha livre."],
        [],
        ["1) MAPEAMENTO APLICADO"],
        ["ABA (AUTO)", "LINHA", "MODO", "ITEM PDF", "CODIGO", "DESCRICAO NO PDF",
         "DESCRICAO DA COMPOSICAO (EXCEL)", "UN", "QUANT. PDF", "QUANT. GRAVADA",
         "ORIGEM DA QUANT.", "COMPOSICAO (ORIGEM)", "COLUNA", "INSUMO",
         "FORMULA GRAVADA", "COEFICIENTE", "CAMINHO"],
    ]
    for plan, planned in audit.written_rows():
        base = [plan.sheet + audit.suffix, planned.row, planned.mode, planned.item.order,
                planned.item.code, planned.item.description, planned.composition.description,
                planned.composition.unit or "", planned.item.quantity, planned.quantity,
                planned.quantity_source, planned.composition.ref]
        for column, coefficient in planned.coefficients.items():
            rows.append(base + [f"{column}{planned.row}", coefficient.input_code,
                                coefficient.formula(), round(coefficient.value, 8),
                                coefficient.trail()])

    rows += [[], ["2) ITENS DO ORCAMENTO NAO APLICADOS"],
             ["ABA (AUTO)", "ITEM PDF", "CODIGO", "DESCRICAO NO PDF",
              "COMPOSICAO ENCONTRADA", "MOTIVO"]]
    for plan in audit.plans:
        for skipped in plan.skipped:
            rows.append([plan.sheet + audit.suffix, skipped.item.order, skipped.item.code,
                         skipped.item.description,
                         skipped.composition.ref if skipped.composition else "-",
                         skipped.reason])

    rows += [[], ["3) RESOLUCAO DE DUPLICIDADE - linhas legadas assumidas por itens do orcamento"],
             ["O codigo legado nao consta em nenhum item do orcamento e descreve o mesmo servico. "
              "A linha original permanece intacta na aba sem sufixo."],
             ["ABA (AUTO)", "LINHA", "CODIGO LEGADO", "DESCRICAO LEGADA", "QUANT. LEGADA",
              "PASSA A SER", "CODIGO", "DESCRICAO", "QUANT. PDF", "DIFERENCA", "SEMELHANCA"]]
    for plan, planned in audit.written_rows():
        if planned.mode != SUBSTITUTED:
            continue
        difference = ("" if planned.replaced_quantity is None or planned.quantity is None
                      else round(planned.quantity - planned.replaced_quantity, 4))
        rows.append([plan.sheet + audit.suffix, planned.row, planned.replaced_code or "",
                     planned.replaced_description or "", planned.replaced_quantity,
                     planned.item.order, planned.item.code, planned.composition.description,
                     planned.item.quantity, difference,
                     round(planned.similarity, 2) if planned.similarity else ""])

    rows += [[], ["4) QUANTIDADES - divergencias entre a aba e o orcamento"],
             ["ABA (AUTO)", "LINHA", "CODIGO", "QUANT. NA ABA", "QUANT. NO PDF",
              "DIFERENCA", "TRATAMENTO"]]
    for plan, planned in audit.written_rows():
        if planned.mode != UPDATED:
            continue
        existing = plan.layout.rows[planned.row].quantity
        if not isinstance(existing, (int, float)) or planned.item.quantity is None:
            continue
        if abs(existing - planned.item.quantity) <= 1e-6:
            continue
        treatment = ("SUBSTITUIDA pela do orcamento" if planned.quantity_source == "orcamento"
                     else "PRESERVADA a quantidade da aba")
        if planned.notes:
            treatment += " - " + "; ".join(planned.notes)
        rows.append([plan.sheet + audit.suffix, planned.row, planned.item.code,
                     round(existing, 4), planned.item.quantity,
                     round(existing - planned.item.quantity, 4), treatment])
    rows += [[], ["6) ABAS GERADAS A PARTIR DO MOLDE"],
             ["Topicos do orcamento que nao tinham aba de destino. A aba foi sintetizada a partir do "
              "molde, com uma coluna por insumo-folha realmente consumido pelos itens do topico."],
             ["ABA GERADA", "TOPICO", "NOME DO TOPICO", "ITENS", "LINHAS", "COLUNAS",
              "ALEM DO MOLDE", "LINHA DO TOTAL", "COLUNA", "INSUMO", "DESCRICAO", "UN",
              "SECAO", "OBSERVACAO"]]
    for plan in audit.synth:
        if not plan.created:
            rows.append([plan.sheet, plan.topic_number, plan.topic_name,
                         len(plan.rows) + len(plan.skipped), 0, 0, 0, "",
                         "", "", "ABA NAO CRIADA: " + plan.reason, "", "", ""])
            continue
        base = [plan.sheet, plan.topic_number, plan.topic_name,
                len(plan.rows) + len(plan.skipped), len(plan.rows), len(plan.columns),
                len(plan.appended), plan.total_row]
        for letter, column in plan.columns:
            nota = ("codigo de servico sem composicao no arquivo: nao foi possivel abrir "
                    "nos insumos dele" if column.unresolved_service else "")
            rows.append(base + [letter, column.code, column.description, column.unit or "",
                                column.section or "", nota])
        for skipped in plan.skipped:
            rows.append([plan.sheet, plan.topic_number, plan.topic_name, "", "", "", "", "",
                         "", skipped.item.code, "NAO APLICADO: " + skipped.reason, ""])

    rows += [[], ["5) LINHAS DA ABA SEM CONTRAPARTIDA NO ORCAMENTO (nao foram tocadas)"],
             ["Estas linhas ja existiam na aba original e continuam somando no TOTAL, mas o codigo delas "
              "nao corresponde a nenhum item do topico. A automacao nao as altera; confira se ainda valem."],
             ["ABA (AUTO)", "LINHA", "CODIGO", "DESCRICAO", "QUANT.", "SITUACAO"]]
    for plan in audit.plans:
        escritas = set(plan.rows)
        for row in plan.layout.rows_inside_total():
            service = plan.layout.rows[row]
            if row in escritas or service.is_blank:
                continue
            if service.code and service.code in audit.budget_codes:
                situacao = "codigo existe no orcamento, mas em outro topico"
            elif service.code:
                situacao = "codigo nao consta em nenhum item do orcamento"
            else:
                situacao = "linha sem codigo de servico (lancamento manual)"
            if service.quantity is None and (service.description or "").strip():
                situacao += "; quantidade vazia ou em erro"
            rows.append([plan.sheet + audit.suffix, row, service.code or "",
                         service.description or "", service.quantity, situacao])

    return rows


def log_sheet_xml(rows: list[list], bold_style: int, wrap_style: int) -> str:
    """Aba de log em XML puro (sem depender do openpyxl para gravar)."""
    widths = [23, 8, 13, 10, 11, 52, 52, 7, 15, 15, 15, 26, 11, 11, 46, 14, 34]
    columns = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1))
    body = []
    for index, values in enumerate(rows, start=1):
        heading = bool(values) and isinstance(values[0], str) and (
            values[0].startswith(HEADINGS) or values[0] == "ABA (AUTO)")
        style = bold_style if heading else wrap_style
        cells = "".join(
            cell_xml(f"{column_letter(position)}{index}", str(style),
                     **({"number": value} if isinstance(value, (int, float))
                        and not isinstance(value, bool) else {"text": str(value)}))
            for position, value in enumerate(values, start=1))
        body.append(f'<row r="{index}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetPr codeName="AUTOLOG"><tabColor rgb="FFFFC000"/></sheetPr>'
            f'<dimension ref="A1:{column_letter(len(widths))}{max(len(rows), 1)}"/>'
            '<sheetViews><sheetView showGridLines="0" workbookViewId="0">'
            '<pane ySplit="7" topLeftCell="A8" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="13.2"/>'
            f'<cols>{columns}</cols><sheetData>{"".join(body)}</sheetData>'
            '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
            'header="0.3" footer="0.3"/></worksheet>')


def text_report(audit: Audit) -> str:
    """Resumo legível para o terminal."""
    lines: list[str] = []
    for plan in audit.synth:
        if not plan.created:
            lines.append(f"[aba nao criada] topico {plan.topic_number} {plan.topic_name}: {plan.reason}")
            lines.append("")
            continue
        title = f"{plan.sheet}  (aba gerada do molde)  <-  topico {plan.topic_number} {plan.topic_name}"
        lines += ["=" * len(title), title, "=" * len(title)]
        lines.append(f"  {len(plan.rows)} linhas, {len(plan.columns)} colunas de insumo "
                     f"({len(plan.appended)} alem do molde), TOTAL na linha {plan.total_row}")
        lines.append("  colunas: " + ", ".join(f"{letra}={col.code}" for letra, col in plan.columns))
        for skipped in plan.skipped:
            lines.append(f"  -- nao aplicado  item {skipped.item.order:>6} "
                         f"{skipped.item.code:<9} {skipped.reason}")
        lines.append("")
    for plan in audit.plans:
        title = f"{plan.sheet}{audit.suffix}  <-  topico {plan.topic_number} {plan.topic_name}"
        lines.append("=" * len(title))
        lines.append(title)
        lines.append("=" * len(title))
        for planned in plan.ordered():
            extra = ""
            if planned.mode == SUBSTITUTED:
                extra = (f"  <- substitui {planned.replaced_code} "
                         f"(semelhanca {planned.similarity:.2f})")
            lines.append(f"  linha {planned.row:>3} [{planned.mode:<10}] item {planned.item.order:>6} "
                         f"{planned.item.code:<9} qtd={planned.quantity} "
                         f"({planned.quantity_source}){extra}")
            for column, coefficient in planned.coefficients.items():
                lines.append(f"          {column}{planned.row:<3} {coefficient.input_code:<8} "
                             f"{coefficient.formula():<46} = {round(coefficient.value, 6)}")
        for skipped in plan.skipped:
            lines.append(f"  -- nao aplicado  item {skipped.item.order:>6} "
                         f"{skipped.item.code:<9} {skipped.reason}")
        if plan.new_last_row:
            lines.append(f"  * intervalo do TOTAL ampliado ate a linha {plan.new_last_row}")
        lines.append("")
    return "\n".join(lines)
