# -*- coding: utf-8 -*-
"""Leitura do orçamento analítico em PDF.

Duas camadas propositalmente separadas:

* `extract_lines`  — adaptador do pdfplumber; devolve linhas de palavras.
* `parse_budget`   — função pura sobre essas linhas.

Isso deixa o parser testável sem precisar de um PDF em disco.

Há **dois perfis de leitura**, escolhidos sozinhos por `detect_profile`:

* `parse_budget` — "Orçamento Analítico", com coluna Código;
* `parse_budget_planilha_excel` — "Planilha Orçamentária" exportada do Excel,
  sem coluna Código, com o valor do tópico numa linha de SUBTOTAL à parte e
  numeração misturando ponto e vírgula.

Os dois são funções separadas de propósito: o formato analítico já está em uso
e não pode regredir por causa do outro. O que os dois compartilham é o passo de
normalização (`normalize_lines`), que conserta artefatos da exportação e é
comprovadamente inócuo no formato analítico.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import PdfConfig
from .textutil import normalize, parse_number


@dataclass
class Word:
    text: str
    x0: float


@dataclass
class Line:
    page: int
    top: float
    words: list[Word]

    @property
    def texts(self) -> list[str]:
        return [w.text for w in self.words]

    def joined(self) -> str:
        return " ".join(self.texts)


@dataclass
class BudgetItem:
    order: str                 # "3.2"
    code: str                  # "C0843"
    description: str
    unit: str | None
    quantity: float | None
    unit_price: float | None
    total: float | None
    page: int
    topic_number: int
    topic_name: str


@dataclass
class Topic:
    number: int
    name: str
    items: list[BudgetItem] = field(default_factory=list)


def extract_lines(pdf_path: str | Path, config: PdfConfig | None = None) -> list[Line]:
    """Extrai as linhas de palavras do PDF (requer pdfplumber)."""
    import pdfplumber

    config = config or PdfConfig()
    lines: list[Line] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            buckets: dict[float, list] = {}
            for word in page.extract_words(use_text_flow=False, keep_blank_chars=False):
                top = round(word["top"], 0)
                key = next((k for k in buckets if abs(k - top) <= config.line_tolerance), top)
                buckets.setdefault(key, []).append(word)
            for key in sorted(buckets):
                ordered = sorted(buckets[key], key=lambda w: w["x0"])
                lines.append(Line(page_number, key,
                                  [Word(w["text"], round(w["x0"], 1)) for w in ordered]))
    return lines


_DIGITO_SOLTO = re.compile(r"^\d$")
# O segundo pedaço vem de três jeitos, todos vistos no arquivo real:
#   '5' + '.986,61'   -> 5.986,61     (começa no ponto de milhar)
#   '1' + '5.400,82'  -> 15.400,82    (começa num dígito)
#   '1' + '0.180,59'  -> 10.180,59    (idem, com zero)
# Em todos, concatenar os dois tokens dá o número certo.
_RESTO_DO_MILHAR = re.compile(r"^\d?\.\d{3}(?:\.\d{3})*,\d+$")
# Folga máxima em x entre os dois pedaços. No PDF real ela é 3,3 pt em todos os
# 54 pares — a largura de um dígito. A trava impede juntar uma quantidade "1"
# com o preço da coluna seguinte, que estaria dezenas de pontos à direita.
_FOLGA_FRAGMENTO = 6.0
_MOEDA = "R$"


def normalize_lines(lines: list[Line]) -> list[Line]:
    """Conserta dois artefatos da exportação em PDF, para os dois perfis.

    1. **Número partido em dois tokens.** Na planilha exportada o primeiro
       dígito do valor se desgruda do resto: `1` + `5.400,82` para 15.400,82,
       `5` + `.986,61` para 5.986,61. É consistente o bastante para remontar
       sem ambiguidade — um token de um dígito só, seguido de um token que
       começa com ponto de milhar.
    2. **`R$` intercalado entre os números**, não apenas como prefixo. A busca
       dos números finais da linha para no primeiro token que não é número, e
       `R$` no meio a interrompia cedo demais.

    No "Orçamento Analítico" real isto não altera uma linha sequer (zero
    números partidos, zero `R$` soltos), então roda nos dois sem risco.
    """
    saida: list[Line] = []
    for line in lines:
        palavras: list[Word] = []
        for palavra in line.words:
            if palavra.text == _MOEDA:
                continue
            anterior = palavras[-1] if palavras else None
            if (anterior is not None and _DIGITO_SOLTO.match(anterior.text)
                    and _RESTO_DO_MILHAR.match(palavra.text)
                    and palavra.x0 - anterior.x0 <= _FOLGA_FRAGMENTO):
                palavras[-1] = Word(anterior.text + palavra.text, anterior.x0)
                continue
            palavras.append(palavra)
        saida.append(Line(line.page, line.top, palavras))
    return saida


def detect_profile(lines: list[Line], config: PdfConfig | None = None) -> str:
    """Qual perfil de leitura serve para este PDF: 'analitico' ou 'planilha'.

    O sinal é o cabeçalho da tabela: o Orçamento Analítico tem uma coluna
    `Código`, a Planilha Orçamentária não tem. É o funcionário que arrasta o
    PDF na tela — ele não deve precisar escolher formato nenhum.
    """
    config = config or PdfConfig()
    procurados = tuple(normalize(p) for p in config.code_header_words)
    for line in lines:
        if line.page > 2:                      # o cabeçalho está no começo
            break
        if any(normalize(palavra) in procurados for palavra in line.texts):
            return "analitico"
    return "planilha"


def parse_budget(lines: list[Line], config: PdfConfig | None = None) -> list[Topic]:
    """Reconstrói tópicos e itens a partir das linhas do PDF."""
    config = config or PdfConfig()
    topic_re = re.compile(config.topic_number_re)
    order_re = re.compile(config.item_order_re)
    number_re = re.compile(config.number_re)
    lines = normalize_lines(lines)

    topics: list[Topic] = []
    topic: Topic | None = None
    item: BudgetItem | None = None

    for line in lines:
        if not line.words:
            continue
        first, x0 = line.words[0].text, line.words[0].x0
        texts = line.texts

        # cabeçalho de tópico: "3  INFRAESTRUTURA  439.984,92"
        if topic_re.match(first) and x0 < config.topic_max_x and len(texts) >= 2:
            rest = texts[1:]
            name = " ".join(rest[:-1]).strip()
            if rest and number_re.match(rest[-1]) and name and not any(c.islower() for c in name):
                topic = Topic(int(first), name)
                topics.append(topic)
                item = None
                continue

        if topic is None:
            continue

        # linha de item: "3.2  C0843  DESCRIÇÃO ...  M3  8,15  680,57  5.546,68"
        if order_re.match(first) and len(texts) >= 3:
            tail = list(texts)
            numbers: list[str] = []
            cursor = len(tail) - 1
            while cursor > 0 and number_re.match(tail[cursor]) and len(numbers) < config.trailing_numbers:
                numbers.insert(0, tail[cursor])
                cursor -= 1
            unit = tail[cursor] if cursor > 1 else None
            complete = len(numbers) == config.trailing_numbers
            item = BudgetItem(
                order=first,
                code=tail[1],
                description=" ".join(tail[2:cursor]).strip(),
                unit=unit if complete else None,
                quantity=parse_number(numbers[0]) if complete else None,
                unit_price=parse_number(numbers[1]) if complete else None,
                total=parse_number(numbers[2]) if complete else None,
                page=line.page,
                topic_number=topic.number,
                topic_name=topic.name,
            )
            topic.items.append(item)
            continue

        # continuação da descrição (linha indentada, sem "Ordem")
        if item is not None and x0 > config.continuation_min_x and first not in config.header_words:
            item.description = (item.description + " " + line.joined()).strip()

    return topics


def _numeros_finais(texts: list[str], number_re, quantos: int) -> tuple[list[str], int]:
    """Números do fim da linha e o índice do token imediatamente anterior."""
    numeros: list[str] = []
    cursor = len(texts) - 1
    while cursor > 0 and number_re.match(texts[cursor]) and len(numeros) < quantos:
        numeros.insert(0, texts[cursor])
        cursor -= 1
    return numeros, cursor


def parse_budget_planilha_excel(lines: list[Line],
                                config: PdfConfig | None = None) -> list[Topic]:
    """Perfil de leitura da "Planilha Orçamentária" exportada do Excel.

    Três diferenças que impedem o perfil analítico de ler este formato:

    * **Não há coluna Código.** O cabeçalho é `Item | Descrição | Un. | Quant. |
      Preço | Subtotal | Perc.`. Os itens saem daqui com `code=""`, e quem
      atribui o código é o casamento por descrição (`matching.py`).
    * **O tópico não traz valor na própria linha.** É `4,00 INFRAESTRUTURA` e
      ponto; o dinheiro vem numa linha `SUBTOTAL ...` depois de todos os itens.
      O perfil analítico exige o valor no fim e por isso não reconhecia nenhum
      tópico — e sem tópico ativo todo item era descartado em silêncio.
    * **A numeração mistura ponto e vírgula no mesmo arquivo**: tópicos 1 e 2
      usam `1.00`/`2.01`, do 3 em diante é `3,00`/`4,01`. É assim na origem.

    A descrição pode estar quebrada em linhas **antes e depois** da linha
    numérica; `_adotar_orfas` cuida disso.
    """
    config = config or PdfConfig()
    topic_re = re.compile(config.planilha_topic_re)
    order_re = re.compile(config.planilha_order_re)
    number_re = re.compile(config.number_re)
    ruido = tuple(normalize(p) for p in config.planilha_noise_words)
    lines = normalize_lines(lines)

    fragmentos = _adotar_orfas(lines, config)

    topics: list[Topic] = []
    topic: Topic | None = None
    for line in lines:
        if not line.words:
            continue
        first, x0 = line.words[0].text, line.words[0].x0
        texts = line.texts
        if normalize(first) in ruido:
            continue
        if x0 > config.planilha_order_max_x:
            continue

        # tópico primeiro: "4,00" também casaria com a regex de item
        if topic_re.match(first) and len(texts) >= 2:
            nome = " ".join(texts[1:]).strip()
            if nome and not any(c.islower() for c in nome):
                topic = Topic(int(re.split(r"[.,]", first)[0]), nome)
                topics.append(topic)
            continue

        if topic is None or not order_re.match(first):
            continue

        numeros, cursor = _numeros_finais(texts, number_re, config.trailing_numbers)
        completo = len(numeros) == config.trailing_numbers
        unidade = texts[cursor] if completo and cursor >= 1 else None
        proprio = " ".join(texts[1:cursor]).strip() if completo else " ".join(texts[1:]).strip()

        # a descrição pode vir de três lugares: linha de cima, a própria linha e
        # linha de baixo. Ordenar por altura reconstrói a frase na ordem certa.
        pedacos = list(fragmentos.get((line.page, line.top), []))
        if proprio:
            pedacos.append((line.top, proprio))
        descricao = " ".join(texto for _, texto in sorted(pedacos, key=lambda x: x[0]))

        topic.items.append(BudgetItem(
            order=first,
            code="",                            # este formato não tem código
            description=" ".join(descricao.split()),
            unit=unidade if completo else None,
            quantity=parse_number(numeros[0]) if completo else None,
            unit_price=parse_number(numeros[1]) if completo else None,
            total=parse_number(numeros[2]) if completo else None,
            page=line.page,
            topic_number=topic.number,
            topic_name=topic.name,
        ))
    return topics


def _adotar_orfas(lines: list[Line], config: PdfConfig) -> dict:
    """Liga cada linha de texto solta à linha numérica mais próxima.

    O perfil analítico só olha para a frente (continuação depois do item) e
    exige `x0 > continuation_min_x`. Aqui a continuação aparece **antes e
    depois** da linha numérica e encostada na margem, no mesmo x da descrição —
    ou seja, nenhum dos dois critérios serve. O que identifica a órfã é ela ser
    puro texto: nenhuma palavra alcança a faixa das colunas Un./Quant./Preço.
    """
    topic_re = re.compile(config.planilha_topic_re)
    order_re = re.compile(config.planilha_order_re)
    ruido = tuple(normalize(p) for p in config.planilha_noise_words)

    ancoras: list[Line] = []
    orfas: list[Line] = []
    for line in lines:
        if not line.words:
            continue
        first, x0 = line.words[0].text, line.words[0].x0
        e_ordem = x0 <= config.planilha_order_max_x and order_re.match(first)
        if e_ordem and not topic_re.match(first):
            ancoras.append(line)
        elif (not e_ordem and not topic_re.match(first)
              and normalize(first) not in ruido
              and all(w.x0 < config.planilha_value_min_x for w in line.words)):
            orfas.append(line)

    adotadas: dict = {}
    for orfa in orfas:
        candidatas = [a for a in ancoras if a.page == orfa.page]
        if not candidatas:
            continue
        perto = min(candidatas, key=lambda a: abs(a.top - orfa.top))
        if abs(perto.top - orfa.top) > config.planilha_orphan_max_gap:
            continue
        adotadas.setdefault((perto.page, perto.top), []).append(
            (orfa.top, orfa.joined().strip()))
    return adotadas


def read_budget(pdf_path: str | Path, config: PdfConfig | None = None) -> list[Topic]:
    """Lê o orçamento escolhendo sozinho o perfil que serve para este PDF."""
    lines = extract_lines(pdf_path, config)
    if detect_profile(lines, config) == "analitico":
        return parse_budget(lines, config)
    return parse_budget_planilha_excel(lines, config)


def items_by_code(topics: list[Topic]) -> dict[str, list[BudgetItem]]:
    """Índice código -> itens, em todo o orçamento (usado para detectar código legado)."""
    index: dict[str, list[BudgetItem]] = {}
    for topic in topics:
        for item in topic.items:
            index.setdefault(item.code, []).append(item)
    return index
