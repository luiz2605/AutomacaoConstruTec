# -*- coding: utf-8 -*-
"""Cirurgia direta no pacote OOXML (.xlsx).

Motivo de não usar o openpyxl para gravar: reabrir e salvar a pasta inteira
descarta os valores em cache de todas as fórmulas, mexe em vínculos externos e
pode perder detalhes de formatação. Aqui as partes originais são copiadas byte
a byte; só as abas novas são geradas — como cópias exatas das de origem, com
as células alteradas cirurgicamente. Estilos, cores, larguras, mesclagens,
imagens, cabeçalho/rodapé e vínculos externos ficam intactos por construção.
"""
from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

WORKSHEET_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
DRAWING_CT = "application/vnd.openxmlformats-officedocument.drawing+xml"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"


class OoxmlError(RuntimeError):
    pass


@dataclass
class SheetRef:
    name: str
    sheet_id: int
    rel_id: str
    part: str


@dataclass
class NewSheet:
    """Aba nova, ainda em memória, pronta para receber alterações de célula."""
    name: str
    part: str
    xml: str
    source: SheetRef
    styles: dict[str, str] = field(default_factory=dict)


class Workbook:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as archive:
            self.order = list(archive.namelist())
            self.parts = {name: archive.read(name) for name in self.order}
        self._workbook = self.parts["xl/workbook.xml"].decode("utf-8")
        self._rels = self.parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
        self._types = self.parts["[Content_Types].xml"].decode("utf-8")
        self._new: list[NewSheet] = []
        self._counter = 0

    # ------------------------------------------------------------------ leitura
    def sheets(self) -> list[SheetRef]:
        targets: dict[str, str] = {}
        for element in re.findall(r"<Relationship\b[^>]*/>", self._rels):
            rel = re.search(r'Id="([^"]+)"', element)
            target = re.search(r'Target="([^"]+)"', element)
            if rel and target:
                targets[rel.group(1)] = target.group(1)
        found = []
        for element in re.findall(r"<sheet\b[^>]*/>", self._workbook):
            name = re.search(r'name="([^"]*)"', element)
            sheet_id = re.search(r'sheetId="(\d+)"', element)
            rel = re.search(r'r:id="([^"]+)"', element)
            if not (name and sheet_id and rel):
                continue
            target = targets.get(rel.group(1), "")
            part = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            if target.startswith("/"):                      # caminho absoluto no pacote
                part = target.lstrip("/")
            found.append(SheetRef(_unescape(name.group(1)), int(sheet_id.group(1)),
                                  rel.group(1), part))
        return found

    def sheet(self, name: str) -> SheetRef:
        for ref in self.sheets():
            if ref.name == name:
                return ref
        raise OoxmlError(f"aba inexistente: {name!r}")

    # ------------------------------------------------------------------ escrita
    def clone_sheet(self, source_name: str, new_name: str) -> NewSheet:
        """Duplica uma aba (com desenho e configuração de impressão próprios)."""
        if any(ref.name == new_name for ref in self.sheets()) or \
                any(sheet.name == new_name for sheet in self._new):
            raise OoxmlError(f"já existe uma aba chamada {new_name!r}")
        if len(new_name) > 31:
            raise OoxmlError(f"nome de aba com mais de 31 caracteres: {new_name!r}")
        source = self.sheet(source_name)
        self._counter += 1
        index = self._counter
        part = f"xl/worksheets/sheetAUTO{index}.xml"
        xml = self.parts[source.part].decode("utf-8")
        # identidade própria: codeName e uid duplicados confundem o Excel
        xml = re.sub(r'codeName="[^"]*"', f'codeName="AUTO{index}"', xml, count=1)
        xml = re.sub(r'xr:uid="\{[^}]*\}"', f'xr:uid="{{{str(uuid.uuid4()).upper()}}}"',
                     xml, count=1)

        rels_part = source.part.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if rels_part in self.parts:
            rels = self.parts[rels_part].decode("utf-8")
            drawing = re.search(r'Target="\.\./drawings/(drawing\d+)\.xml"', rels)
            if drawing:
                original = drawing.group(1)
                new_drawing = f"drawingAUTO{index}"
                self.parts[f"xl/drawings/{new_drawing}.xml"] = self.parts[f"xl/drawings/{original}.xml"]
                drawing_rels = f"xl/drawings/_rels/{original}.xml.rels"
                if drawing_rels in self.parts:
                    self.parts[f"xl/drawings/_rels/{new_drawing}.xml.rels"] = self.parts[drawing_rels]
                self._types = self._types.replace(
                    "</Types>", f'<Override PartName="/xl/drawings/{new_drawing}.xml" '
                                f'ContentType="{DRAWING_CT}"/></Types>')
                rels = rels.replace(f"../drawings/{original}.xml", f"../drawings/{new_drawing}.xml")
            self.parts[part.replace("worksheets/", "worksheets/_rels/") + ".rels"] = rels.encode("utf-8")

        sheet = NewSheet(new_name, part, xml, source)
        self._new.append(sheet)
        return sheet

    def add_sheet(self, name: str, xml: str) -> NewSheet:
        """Acrescenta uma aba criada do zero (usada pelo relatório)."""
        self._counter += 1
        part = f"xl/worksheets/sheetAUTO{self._counter}.xml"
        sheet = NewSheet(name, part, xml, SheetRef(name, 0, "", part))
        self._new.append(sheet)
        return sheet

    def save(self, destination: str | Path, full_recalc: bool = True) -> Path:
        destination = Path(destination)
        parts = dict(self.parts)
        workbook, rels, types = self._workbook, self._rels, self._types

        max_rel = max(int(n) for n in re.findall(r'Id="rId(\d+)"', rels))
        max_id = max(int(n) for n in re.findall(r'sheetId="(\d+)"', workbook))
        entries, relations, overrides = [], [], []
        for offset, sheet in enumerate(self._new, start=1):
            parts[sheet.part] = sheet.xml.encode("utf-8")
            rel = f"rId{max_rel + offset}"
            entries.append(f'<sheet name="{escape(sheet.name)}" '
                           f'sheetId="{max_id + offset}" r:id="{rel}"/>')
            relations.append(f'<Relationship Id="{rel}" Type="{WORKSHEET_REL}" '
                             f'Target="{sheet.part[len("xl/"):]}"/>')
            overrides.append(f'<Override PartName="/{sheet.part}" ContentType="{WORKSHEET_CT}"/>')

        workbook = workbook.replace("</sheets>", "".join(entries) + "</sheets>")
        if full_recalc and "fullCalcOnLoad" not in workbook:
            if "<calcPr" in workbook:
                workbook = re.sub(r"<calcPr ([^/>]*?)\s*/>", r'<calcPr \1 fullCalcOnLoad="1"/>',
                                  workbook, count=1)
            else:
                workbook = workbook.replace("</workbook>",
                                            '<calcPr fullCalcOnLoad="1"/></workbook>')
        rels = rels.replace("</Relationships>", "".join(relations) + "</Relationships>")
        types = types.replace("</Types>", "".join(overrides) + "</Types>")

        # a cadeia de cálculo fica obsoleta; o Excel a reconstrói sozinho
        parts.pop("xl/calcChain.xml", None)
        types = re.sub(r'<Override[^>]*calcChain[^>]*/>', "", types)
        rels = re.sub(r'<Relationship[^>]*calcChain[^>]*/>', "", rels)

        parts["xl/workbook.xml"] = workbook.encode("utf-8")
        parts["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")
        parts["[Content_Types].xml"] = types.encode("utf-8")

        ordered = [n for n in self.order if n in parts]
        ordered += [n for n in parts if n not in self.order]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
            for name in ordered:
                out.writestr(name, parts[name])
        return destination

    # ------------------------------------------------------- estilos (append-only)
    def append_style(self, bold: bool = False, wrap: bool = False) -> int:
        """Acrescenta um formato ao fim de styles.xml e devolve seu índice.

        Estritamente aditivo: nenhum índice existente muda de significado.
        """
        styles = self.parts["xl/styles.xml"].decode("utf-8")
        font_id = 0
        if bold:
            count = int(re.search(r'<fonts count="(\d+)"', styles).group(1))
            base = re.search(r"<fonts[^>]*>(<font>.*?</font>)", styles, re.S).group(1)
            new_font = base.replace("<font>", "<font><b/>", 1)
            styles = styles.replace(f'<fonts count="{count}"', f'<fonts count="{count + 1}"', 1)
            styles = re.sub(r"</fonts>", new_font + "</fonts>", styles, count=1)
            font_id = count
        count = int(re.search(r'<cellXfs count="(\d+)"', styles).group(1))
        alignment = '<alignment vertical="top" wrapText="1"/>' if wrap else ""
        xf = (f'<xf numFmtId="0" fontId="{font_id}" fillId="0" borderId="0" xfId="0"'
              + (' applyFont="1"' if bold else "")
              + (f' applyAlignment="1">{alignment}</xf>' if wrap else "/>"))
        styles = styles.replace(f'<cellXfs count="{count}"', f'<cellXfs count="{count + 1}"', 1)
        styles = re.sub(r"</cellXfs>", xf + "</cellXfs>", styles, count=1)
        self.parts["xl/styles.xml"] = styles.encode("utf-8")
        return count


# --------------------------------------------------------------------- células
def cell_xml(ref: str, style: str | None, *, number=None, text=None,
             formula=None, value=None) -> str:
    attribute = f' s="{style}"' if style else ""
    if formula is not None:
        cached = "" if value is None else f"<v>{value!r}</v>"
        return f'<c r="{ref}"{attribute}><f>{escape(formula)}</f>{cached}</c>'
    if number is not None:
        return f'<c r="{ref}"{attribute}><v>{number!r}</v></c>'
    if text is not None:
        preserve = ' xml:space="preserve"' if text != text.strip() else ""
        return f'<c r="{ref}"{attribute} t="inlineStr"><is><t{preserve}>{escape(text)}</t></is></c>'
    return f'<c r="{ref}"{attribute}/>'


def has_row(xml: str, row: int) -> bool:
    return re.search(r'<row\b[^>]*\br="%d"[^>]*(?:/>|>)' % row, xml) is not None


def ensure_row(xml: str, row: int, template_row: int | None = None) -> str:
    """Garante que a linha exista no XML, criando-a se preciso.

    Uma pasta gravada por outra ferramenta costuma omitir linhas vazias — elas
    simplesmente não existem no arquivo. Ao criar, o formato é herdado de uma
    linha-modelo (altura, estilo da linha e estilo de cada célula), para que a
    linha nova não destoe visualmente do resto da tabela.
    """
    if has_row(xml, row):
        return xml
    attributes, cells = "", ""
    if template_row is not None and has_row(xml, template_row):
        block = _row_match(xml, template_row).group(0)
        head = block.split(">", 1)[0]
        attributes = "".join(
            f' {name}="{value}"' for name, value in re.findall(r'\b(\w+(?::\w+)?)="([^"]*)"', head)
            if name not in ("r", "hidden"))
        for found in re.finditer(r'<c r="([A-Z]+)\d+"(?:\s[^>]*)?(?:/>|>.*?</c>)', block, re.S):
            style = re.search(r'\bs="(\d+)"', found.group(0))
            cells += cell_xml(f"{found.group(1)}{row}", style.group(1) if style else None)
    element = f'<row r="{row}"{attributes}>{cells}</row>'

    body = re.search(r"<sheetData\b[^>]*>", xml)
    if not body:
        raise OoxmlError("aba sem <sheetData>")
    position = None
    for found in re.finditer(r'<row\b[^>]*\br="(\d+)"', xml):
        if int(found.group(1)) > row:
            position = found.start()
            break
    if position is None:
        closing = xml.index("</sheetData>")
        return xml[:closing] + element + xml[closing:]
    return xml[:position] + element + xml[position:]


def _row_match(xml: str, row: int):
    match = re.search(r'<row\b[^>]*\br="%d"[^>]*(?:/>|>.*?</row>)' % row, xml, re.S)
    if not match:
        raise OoxmlError(f"linha {row} não existe na aba")
    return match


def _cell_pattern(ref: str) -> re.Pattern:
    return re.compile(r'<c r="%s"(?:\s[^>]*)?(?:/>|>.*?</c>)' % ref, re.S)


def cell_style(xml: str, row: int, column: str) -> str | None:
    """Índice de formato da célula, para que a gravação não altere a aparência."""
    block = _row_match(xml, row).group(0)
    found = _cell_pattern(f"{column}{row}").search(block)
    if not found:
        return None
    style = re.search(r'\bs="(\d+)"', found.group(0))
    return style.group(1) if style else None


def set_cell(xml: str, row: int, column: str, create: bool = True, **kwargs) -> str:
    """Grava uma célula preservando o formato que ela já tinha."""
    if create:
        xml = ensure_row(xml, row)
    match = _row_match(xml, row)
    block = match.group(0)
    ref = f"{column}{row}"
    replacement = cell_xml(ref, cell_style(xml, row, column), **kwargs)
    pattern = _cell_pattern(ref)
    if pattern.search(block):
        block = pattern.sub(lambda _: replacement, block, count=1)
    else:
        block = _insert_cell(block, column, replacement)
    return xml[:match.start()] + block + xml[match.end():]


def _insert_cell(block: str, column: str, replacement: str) -> str:
    from .textutil import column_index
    position = None
    for found in re.finditer(r'<c r="([A-Z]+)\d+"(?:\s[^>]*)?(?:/>|>.*?</c>)', block, re.S):
        if column_index(found.group(1)) > column_index(column):
            position = found.start()
            break
    if position is None:
        position = block.rindex("</row>")
    return block[:position] + replacement + block[position:]


def show_row(xml: str, row: int) -> str:
    """Remove `hidden` de uma linha (as linhas-modelo costumam vir ocultas)."""
    if not has_row(xml, row):
        return xml
    match = _row_match(xml, row)
    block = match.group(0)
    head, rest = block.split(">", 1)
    return xml[:match.start()] + head.replace(' hidden="1"', "") + ">" + rest + xml[match.end():]


_REFERENCE = re.compile(r"(?<![A-Za-z0-9_.])(\$?)([A-Z]{1,3})(\$?)(\d+)")


def shift_formula(formula: str, column_delta: int, row_delta: int) -> str:
    """Traduz as referências relativas de uma fórmula (o que o Excel faz ao copiar)."""
    from .textutil import column_index, column_letter

    def replace(match: re.Match) -> str:
        col_anchor, letters, row_anchor, digits = match.groups()
        column = letters if col_anchor else column_letter(
            max(1, column_index(letters) + column_delta))
        number = digits if row_anchor else str(max(1, int(digits) + row_delta))
        return f"{col_anchor}{column}{row_anchor}{number}"

    return _REFERENCE.sub(replace, formula)


def _shared_formulas(block: str, row: int) -> dict[str, tuple[str, str]]:
    """Mapa si -> (fórmula da mestre, coluna da mestre) dentro de uma linha."""
    masters: dict[str, tuple[str, str]] = {}
    for cell in re.finditer(r'<c r="([A-Z]+)%d"(?:\s[^>]*)?>(.*?)</c>' % row, block, re.S):
        found = re.search(r'<f\b(?=[^>]*t="shared")(?=[^>]*\bref=")[^>]*si="(\d+)"[^>]*>(.+?)</f>',
                          cell.group(2), re.S)
        if found:
            masters[found.group(1)] = (_unescape(found.group(2)), cell.group(1))
    return masters


def retarget_sumproduct(xml: str, row: int, old_last: int, new_last: int,
                        columns: list[str]) -> str:
    """Amplia o intervalo somado pela linha de TOTAL.

    Reescrever só a célula-mestre de um grupo `t="shared"` deixaria as
    dependentes órfãs, então a fórmula de cada dependente é materializada a
    partir da mestre (com as referências relativas deslocadas) antes de ampliar.
    """
    from .textutil import column_index

    match = _row_match(xml, row)
    block = match.group(0)
    masters = _shared_formulas(block, row)
    for column in columns:
        found = _cell_pattern(f"{column}{row}").search(block)
        if not found:
            continue
        element = found.group(0)
        # a dependente de um grupo compartilhado vem como <f .../> auto-fechada
        formula = re.search(r"<f\b[^>]*?(?:/>|>(.*?)</f>)", element, re.S)
        if not formula:
            continue
        text = _unescape(formula.group(1) or "")
        if not text:                                     # dependente de um grupo compartilhado
            si = re.search(r'si="(\d+)"', element)
            if not si or si.group(1) not in masters:
                continue
            source, origin = masters[si.group(1)]
            text = shift_formula(source, column_index(column) - column_index(origin), 0)
        updated = re.sub(r"(\$?[A-Z]{1,3}\$?)%d\b" % old_last, r"\g<1>%d" % new_last, text)
        style = re.search(r'\bs="(\d+)"', element)
        block = block.replace(element,
                              cell_xml(f"{column}{row}", style.group(1) if style else None,
                                       formula=updated), 1)
    return xml[:match.start()] + block + xml[match.end():]


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
