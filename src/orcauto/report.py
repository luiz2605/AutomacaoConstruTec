# -*- coding: utf-8 -*-
"""Relatório de auditoria: texto para o terminal e aba LOG dentro da pasta."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ooxml import cell_xml
from .planner import NEW, SUBSTITUTED, UPDATED, SheetPlan
from .textutil import column_letter, similarity

HEADINGS = ("1)", "2)", "3)", "4)", "5)", "6)", "7)", "8)", "9)", "LEVANTAMENTO")


@dataclass
class Audit:
    plans: list[SheetPlan] = field(default_factory=list)
    suffix: str = " (AUTO)"
    budget_codes: set[str] = field(default_factory=set)
    synth: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matches: list = field(default_factory=list)
    # abaixo disto a descricao do PDF e a da composicao sao consideradas
    # servicos diferentes, e o par codigo/descricao vira divergencia (secao 7)
    description_min_similarity: float = 0.60
    description_match_high: float = 0.85
    description_match_min: float = 0.60

    def written_rows(self):
        for plan in self.plans:
            for planned in plan.ordered():
                yield plan, planned

    def identified_rows(self):
        """Toda linha gravada, dos dois modos: (aba, item do PDF, composicao)."""
        for plan in self.plans:
            for planned in plan.ordered():
                yield plan.sheet + self.suffix, planned.item, planned.composition
        for plan in self.synth:
            if not plan.created:
                continue
            for entry in plan.rows:
                yield plan.sheet, entry.item, entry.composition

    def divergences(self):
        """Itens cuja descricao no PDF nao bate com a da composicao do codigo.

        O cruzamento e feito por CODIGO; a descricao gravada vem da composicao.
        Quando as duas discordam, o codigo do orcamento aponta para outro
        servico na Tabela SEINFRA do arquivo — o item pedido no PDF nao entra na
        planilha e no lugar dele aparece um servico que o PDF nao pediu. Era o
        caso do item 2.4 (C0711): o PDF diz "CARGA MECANIZADA DE ENTULHO",
        a tabela diz "CARGA, DESCARGA E TRANSP. DE TUBOS ... DN 150mm".
        """
        for sheet, item, composition in self.identified_rows():
            pdf_text = (item.description or "").strip()
            excel_text = (composition.description or "").strip()
            if not pdf_text or not excel_text:
                continue
            score = similarity(pdf_text, excel_text)
            if score >= self.description_min_similarity:
                continue
            yield sheet, item, composition, score


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
    # abas sintetizadas do molde tambem descartam itens; sem isto a secao 2
    # saia vazia num arquivo-base, onde TODA aba e sintetizada
    for plan in audit.synth:
        for skipped in plan.skipped:
            rows.append([plan.sheet, skipped.item.order, skipped.item.code,
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

    rows += [[], ["7) DIVERGENCIA ENTRE A DESCRICAO DO PDF E A DA COMPOSICAO"],
             ["O cruzamento e por CODIGO e a descricao gravada vem da composicao. Quando as duas "
              "discordam, o codigo do orcamento aponta para outro servico na tabela do arquivo: "
              "o servico pedido no PDF nao entra na planilha e no lugar dele aparece um que o PDF "
              "nao pediu. Confira o codigo no orcamento ou a versao da tabela."],
             ["ABA", "ITEM PDF", "CODIGO", "DESCRICAO NO PDF", "DESCRICAO GRAVADA (EXCEL)",
              "COMPOSICAO (ORIGEM)", "SEMELHANCA"]]
    for sheet, item, composition, score in audit.divergences():
        rows.append([sheet, item.order, item.code, item.description or "",
                     composition.description, composition.ref, round(score, 2)])

    if audit.matches:
        rows += [[], ["9) CASAMENTO POR DESCRICAO (orcamento sem coluna de codigo)"],
                 ["Este orcamento nao traz codigo de servico, entao cada item foi ligado a uma "
                  "composicao pela semelhanca das descricoes. Acima de "
                  f"{audit.description_match_high:.2f} o texto e praticamente o mesmo e o "
                  f"casamento foi aceito direto; entre {audit.description_match_min:.2f} e esse "
                  "valor esta marcado CONFERIR e precisa de olho humano."],
                 ["TOPICO", "ITEM", "DESCRICAO NO PDF", "MELHOR CANDIDATO",
                  "CODIGO APLICADO", "DESCRICAO DO CANDIDATO (EXCEL)",
                  "SEMELHANCA", "SITUACAO"]]
        for match in sorted(audit.matches, key=lambda m: m.score):
            rows.append([f"{match.topic_number} {match.topic_name}", match.order,
                         match.description,
                         match.composition.ref if match.composition else "-",
                         match.code,
                         match.composition.description if match.composition else "",
                         round(match.score, 3), match.situation])

    rows += [[], ["8) AVISOS DE LEITURA DAS COMPOSICOES"],
             ["Linhas da aba de composicoes que parecem titulo de tabela e nao foram reconhecidas "
              "como tal. Enquanto um titulo nao e reconhecido, a composicao anterior continua "
              "aberta e absorve os insumos que seriam da seguinte."],
             ["AVISO"]]
    for warning in audit.warnings:
        rows.append([warning])

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
    conferir = [m for m in audit.matches if m.needs_review]
    sem_par = [m for m in audit.matches if not m.accepted]
    if audit.matches:
        aceitos = sum(1 for m in audit.matches if m.accepted)
        lines.append(f"[descricao] orcamento sem coluna de codigo: {aceitos}/{len(audit.matches)} "
                     f"itens casados por semelhanca de descricao "
                     f"({len(conferir)} para conferir, {len(sem_par)} sem par)")
        for match in sorted(conferir + sem_par, key=lambda m: m.score):
            alvo = match.composition.description if match.composition else "-"
            lines.append(f"   {match.situation:<52} {match.score:.2f}  item {match.order:>6} "
                         f"{match.description[:44]!r} -> {alvo[:44]!r}")
        lines.append("")
    divergentes = list(audit.divergences())
    if divergentes:
        lines.append(f"[atencao] {len(divergentes)} item(ns) com descricao divergente entre o PDF "
                     f"e a composicao do mesmo codigo (secao 7 do log):")
        for sheet, item, composition, score in divergentes:
            lines.append(f"   {sheet} item {item.order} {item.code}: "
                         f"PDF={item.description!r} != EXCEL={composition.description!r} "
                         f"(semelhanca {score:.2f})")
        lines.append("")
    if audit.warnings:
        lines.append(f"[atencao] {len(audit.warnings)} linha(s) parecem titulo de composicao e nao "
                     f"foram reconhecidas (secao 8 do log):")
        for warning in audit.warnings[:10]:
            lines.append("   " + warning)
        if len(audit.warnings) > 10:
            lines.append(f"   ... mais {len(audit.warnings) - 10}")
        lines.append("")
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
