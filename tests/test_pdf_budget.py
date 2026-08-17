"""O parser do orçamento é testado sobre linhas de palavras, sem precisar de PDF."""
from orcauto.pdf_budget import Line, Word, items_by_code, parse_budget


def line(page, top, *pairs):
    return Line(page, top, [Word(text, x) for text, x in pairs])


LINHAS = [
    line(1, 10, ("3", 86.0), ("INFRAESTRUTURA", 140.0), ("439.984,92", 700.0)),
    line(1, 20, ("Ordem", 100.0), ("Código", 200.0), ("Descrição", 300.0)),
    line(1, 30, ("3.1", 90.0), ("C0216", 190.0), ("ARMADURA", 300.0), ("CA-50A", 360.0),
         ("KG", 520.0), ("212,00", 600.0), ("13,34", 660.0), ("2.827,55", 720.0)),
    line(1, 40, ("3.2", 90.0), ("C0843", 190.0), ("CONCRETO", 300.0), ("P/VIBR.,", 360.0),
         ("M3", 520.0), ("8,15", 600.0), ("680,57", 660.0), ("5.546,68", 720.0)),
    line(1, 50, ("AGREGADO", 300.0), ("ADQUIRIDO", 380.0)),
    line(2, 10, ("5", 86.0), ("PAREDES", 140.0), ("E", 200.0), ("PAINÉIS", 220.0),
         ("134.463,03", 700.0)),
    line(2, 20, ("5.1", 90.0), ("C0073", 190.0), ("ALVENARIA", 300.0),
         ("M2", 520.0), ("1.799,61", 600.0), ("73,78", 660.0), ("132.772,57", 720.0)),
]


def test_le_topicos_e_itens():
    topics = parse_budget(LINHAS)
    assert [(t.number, t.name) for t in topics] == [(3, "INFRAESTRUTURA"), (5, "PAREDES E PAINÉIS")]
    assert [i.order for i in topics[0].items] == ["3.1", "3.2"]


def test_le_campos_do_item():
    item = parse_budget(LINHAS)[0].items[1]
    assert (item.code, item.unit) == ("C0843", "M3")
    assert item.quantity == 8.15
    assert item.unit_price == 680.57
    assert item.total == 5546.68


def test_junta_continuacao_da_descricao():
    item = parse_budget(LINHAS)[0].items[1]
    assert item.description == "CONCRETO P/VIBR., AGREGADO ADQUIRIDO"


def test_guarda_o_topico_de_origem():
    item = parse_budget(LINHAS)[1].items[0]
    assert (item.topic_number, item.topic_name) == (5, "PAREDES E PAINÉIS")


def test_linha_de_cabecalho_nao_vira_descricao():
    item = parse_budget(LINHAS)[0].items[0]
    assert "Ordem" not in item.description


def test_items_by_code_indexa_todo_o_orcamento():
    index = items_by_code(parse_budget(LINHAS))
    assert sorted(index) == ["C0073", "C0216", "C0843"]
    assert index["C0843"][0].quantity == 8.15


def test_texto_fora_de_topico_e_ignorado():
    solto = [line(1, 5, ("qualquer", 90.0), ("coisa", 200.0))] + LINHAS
    assert len(parse_budget(solto)) == 2
