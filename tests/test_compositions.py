import pytest

from orcauto.compositions import CompositionIndex, parse_sheet


@pytest.fixture
def index(composition_rows):
    return CompositionIndex(parse_sheet(composition_rows, "COMPOSICOES"))


def test_reconhece_apenas_titulos_de_tabela(index):
    assert sorted(index.codes()) == ["S001", "S002", "S003", "S004", "S005"]


def test_ignora_codigo_que_aparece_como_subitem(index):
    """S001 também aparece dentro de S005 com coeficiente 3 (linha 28).

    O índice tem de apontar para a TABELA de S001 (linha 3), não para a
    ocorrência como sub-item — é o falso positivo que a regra evita.
    """
    assert index.get("S001").title_row == 3
    assert index.get("S001").inputs["X001"].coefficient == 2.5
    assert index.get("S005").inputs["S001"].coefficient == 3


def test_le_descricao_e_unidade_do_titulo(index):
    composition = index.get("S003")
    assert composition.description == "ARGAMASSA DE CIMENTO E AREIA"
    assert composition.unit == "M3"
    assert composition.ref == "COMPOSICOES!A14"


def test_secoes_nao_viram_composicao(index):
    assert "MATERIAIS" not in index.codes()
    assert "SERVICOS" not in index.codes()


def test_guarda_linha_de_cada_insumo(index):
    assert index.get("S003").inputs["X001"].row == 16
    assert index.get("S003").inputs["X002"].row == 17


def test_owner_of_row_identifica_a_tabela_dona(index):
    assert index.owner_of_row("COMPOSICOES", 16).code == "S003"
    assert index.owner_of_row("COMPOSICOES", 5).code == "S001"


def test_precedencia_entre_abas_duplicadas(composition_rows):
    primary = parse_sheet(composition_rows, "PRINCIPAL")
    secondary = parse_sheet(composition_rows, "ANTIGA")
    index = CompositionIndex(primary + secondary, preferred_sheets=["PRINCIPAL", "ANTIGA"])
    assert index.get("S001").sheet == "PRINCIPAL"
    assert len(index.all("S001")) == 2
