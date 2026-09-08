"""O parser do orçamento é testado sobre linhas de palavras, sem precisar de PDF."""
from pathlib import Path
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


# ===========================================================================
# Perfil "planilha exportada" — PLANILHA ORÇAMENTÁRIA vinda do Excel.
# Cada teste isola um dos achados na análise do PDF real da piscina.
# ===========================================================================
import pytest

from orcauto.pdf_budget import (detect_profile, normalize_lines,
                                parse_budget_planilha_excel)

# Layout real: Item@44 | Descrição@78 | Un.@363 | Quant.@398 | Preço@456 | Subtotal@512
PLANILHA = [
    line(1, 156, ("Item", 43.0), ("Descrição", 198.0), ("Un.", 362.0),
         ("Quant.", 395.0), ("Preço", 442.0), ("Subtotal", 492.0), ("Perc.", 547.0)),
    # tópico com PONTO e sem valor nenhum no fim da linha
    line(1, 234, ("2.00", 44.0), ("SERVIÇOS", 78.0), ("PRELIMINARES", 111.0)),
    line(1, 253, ("2.01", 44.0), ("DEMOLIÇÃO", 80.0), ("DE", 117.0), ("PISO", 127.0),
         ("M3", 363.0), ("67,83", 398.0), ("R$", 432.0), ("88,26", 456.0),
         ("R$", 477.0), ("5", 512.0), (".986,61", 515.0)),
    line(1, 387, ("SUBTOTAL", 440.0), ("R$", 477.0), ("2", 508.0), ("5.106,83", 511.3)),
    # tópico com VÍRGULA, no mesmo arquivo
    line(1, 406, ("3,00", 44.0), ("MOVIMENTAÇÃO", 78.0), ("DE", 130.0), ("TERRA", 140.0)),
    # descrição órfã ACIMA da linha numérica
    line(1, 558, ("ALVENARIA", 78.0), ("DE", 115.0), ("BLOCO", 125.0), ("CERÂMICO", 148.0)),
    line(1, 562, ("3,02", 44.0), ("M2", 363.0), ("118,55", 397.0), ("R$", 432.0),
         ("95,01", 456.0), ("R$", 477.0), ("1", 508.0), ("1.262,96", 511.3)),
    # e outra ABAIXO
    line(1, 566, ("HIDRATADA", 78.0), ("ESP=19", 114.0), ("cm", 138.0)),
]


def test_detecta_o_perfil_pela_coluna_codigo():
    """O funcionário arrasta o PDF; quem escolhe o formato é o programa."""
    assert detect_profile(LINHAS) == "analitico"        # tem cabeçalho "Código"
    assert detect_profile(PLANILHA) == "planilha"       # não tem


def test_numero_partido_em_dois_tokens_e_remontado():
    """Três formas do mesmo defeito de exportação, todas vistas no PDF real."""
    partido = [
        line(1, 10, ("R$", 477.0), ("5", 511.7), (".986,61", 515.0)),      # 5.986,61
        line(1, 20, ("R$", 477.0), ("1", 508.4), ("5.400,82", 511.7)),     # 15.400,82
        line(1, 30, ("R$", 477.0), ("1", 508.4), ("0.180,59", 511.7)),     # 10.180,59
    ]
    assert [l.texts for l in normalize_lines(partido)] == [
        ["5.986,61"], ["15.400,82"], ["10.180,59"]]


def test_nao_junta_numeros_de_colunas_diferentes():
    """A trava é a folga em x: no PDF real o par partido fica a 3,3 pt."""
    separados = [line(1, 10, ("1", 398.0), ("5.400,82", 456.0))]
    assert normalize_lines(separados)[0].texts == ["1", "5.400,82"]


def test_remove_o_rs_intercalado_entre_os_numeros():
    """'R$' aparece no meio, não só como prefixo, e parava a leitura cedo."""
    com_moeda = [line(1, 10, ("67,83", 398.0), ("R$", 432.0), ("88,26", 456.0))]
    assert normalize_lines(com_moeda)[0].texts == ["67,83", "88,26"]


def test_normalizacao_nao_altera_o_formato_analitico():
    """Roda nos dois perfis; no que já está em uso não pode mudar nada."""
    assert [l.texts for l in normalize_lines(LINHAS)] == [l.texts for l in LINHAS]


def test_topico_sem_valor_no_fim_da_linha_e_reconhecido():
    """O valor vem num SUBTOTAL depois dos itens, não na linha do tópico."""
    topics = parse_budget_planilha_excel(PLANILHA)
    assert [(t.number, t.name) for t in topics] == [
        (2, "SERVIÇOS PRELIMINARES"), (3, "MOVIMENTAÇÃO DE TERRA")]


def test_numeracao_com_ponto_e_com_virgula_no_mesmo_arquivo():
    topics = parse_budget_planilha_excel(PLANILHA)
    assert [i.order for i in topics[0].items] == ["2.01"]     # ponto
    assert [i.order for i in topics[1].items] == ["3,02"]     # vírgula


def test_le_os_campos_sem_coluna_de_codigo():
    item = parse_budget_planilha_excel(PLANILHA)[0].items[0]
    assert item.code == ""                     # este formato não tem código
    assert item.description == "DEMOLIÇÃO DE PISO"
    assert (item.unit, item.quantity) == ("M3", 67.83)
    assert item.unit_price == 88.26
    assert item.total == 5986.61               # remontado dos dois tokens


def test_descricao_orfa_antes_e_depois_da_linha_numerica():
    """O perfil analítico só olha para a frente; aqui vem dos dois lados."""
    item = parse_budget_planilha_excel(PLANILHA)[1].items[0]
    assert item.description == "ALVENARIA DE BLOCO CERÂMICO HIDRATADA ESP=19 cm"
    assert item.unit == "M2" and item.quantity == 118.55


def test_linha_de_subtotal_nao_vira_item():
    topics = parse_budget_planilha_excel(PLANILHA)
    assert sum(len(t.items) for t in topics) == 2


def test_sem_topico_reconhecido_nao_devolve_item_solto():
    """Sem tópico ativo o item não tem onde morar — melhor devolver vazio."""
    orfaos = [line(1, 10, ("2.01", 44.0), ("ALGO", 80.0), ("M3", 363.0),
                   ("1,00", 398.0), ("2,00", 456.0), ("3,00", 512.0))]
    assert parse_budget_planilha_excel(orfaos) == []


# --------------------------------------------------------------- PDFs reais
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("arquivo, perfil, topicos, itens", [
    ("pdf_planilha_exportada.pdf", "planilha", 13, 54),
    ("pdf_orcamento_analitico.pdf", "analitico", 20, 189),
])
def test_pdfs_reais_de_ponta_a_ponta(arquivo, perfil, topicos, itens):
    """O perfil é escolhido sozinho e todo item sai com descrição."""
    pytest.importorskip("pdfplumber")
    caminho = FIXTURES / arquivo
    if not caminho.exists():
        pytest.skip(f"fixture ausente: {arquivo}")
    from orcauto.pdf_budget import extract_lines, read_budget

    assert detect_profile(extract_lines(caminho)) == perfil
    lidos = read_budget(caminho)
    assert len(lidos) == topicos
    assert sum(len(t.items) for t in lidos) == itens
    for topic in lidos:
        for item in topic.items:
            assert item.description.strip(), f"{arquivo} item {item.order} sem descrição"
            assert item.quantity is not None, f"{arquivo} item {item.order} sem quantidade"


def test_orcamento_analitico_nao_regride():
    """O formato em uso tem de sair exatamente como saía antes dos dois perfis."""
    pytest.importorskip("pdfplumber")
    caminho = FIXTURES / "pdf_orcamento_analitico.pdf"
    if not caminho.exists():
        pytest.skip("fixture ausente")
    from orcauto.pdf_budget import read_budget

    topics = read_budget(caminho)
    # âncoras conferidas à mão contra o PDF, antes de existir o segundo perfil
    assert [(t.number, t.name) for t in topics][:3] == [
        (1, "SERVIÇOS PRELIMINARES"), (2, "DEMOLIÇÕES E REMOÇÕES"), (3, "INFRAESTRUTURA")]
    demolicoes = topics[1].items
    assert [i.code for i in demolicoes] == ["97622", "97625", "C2992", "C0711", "C0702", "C2530"]
    item = demolicoes[2]
    assert (item.order, item.unit, item.quantity) == ("2.3", "M3", 65.0)
    assert item.description == "DEMOLIÇÃO DE ALVENARIA DE PEDRA COM REMOÇÃO LATERAL"
    assert all(i.code for t in topics for i in t.items)     # todo item tem código
