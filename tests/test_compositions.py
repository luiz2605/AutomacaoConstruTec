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


# ---------------------------------------------------------------------------
# Bug A do relatório v3 — título não reconhecido derruba a fronteira entre
# composições. Na Tabela SEINFRA real são 70 títulos: 61 com quebra de linha
# antes da unidade e 9 sem espaço em volta do traço.
# ---------------------------------------------------------------------------

def _linhas_com_titulo(titulo: str) -> list[list]:
    """Duas composições em sequência; a segunda com o título problemático."""
    return [
        ["S001 - CHAPISCO DE CIMENTO E AREIA - M2"],
        ["MATERIAIS", None, "Unidade", "Coeficiente"],
        ["X001", "CIMENTO", "KG", 2.5],
        [titulo],
        ["MATERIAIS", None, "Unidade", "Coeficiente"],
        ["X009", "PEDRA DE MAO", "M3", 1.15],
    ]


@pytest.mark.parametrize("titulo, motivo", [
    ("S002 - HASTE DE ATERRAMENTO 5/8\"X 2.40M    \n - UN", "quebra de linha antes da unidade"),
    ("S002 - PAREDE PRE-MOLDADA, ESP.=13CM,\nINCLUSIVE MONTAGEM - UN", "quebra de linha no meio"),
    ("S002 - PORTAO NYLOFOR - FORNECIMENTO\t\t\t\t\n - UN", "tabulações antes da unidade"),
    ("S002- TORNEIRA CROMADA P/ BANCADA - UN", "sem espaço antes do traço"),
    ("S002 -PAINEL DE LED 4000K 24W - UN", "sem espaço depois do traço"),
    ("S002 – REFLETOR LED 50W 3000K - UN", "travessão em vez de hífen"),
])
def test_titulo_irregular_nao_vaza_insumo_para_a_composicao_anterior(titulo, motivo):
    """O insumo da segunda composição não pode acabar dentro da primeira."""
    encontradas = parse_sheet(_linhas_com_titulo(titulo), "COMPOSICOES")
    codigos = [c.code for c in encontradas]
    assert codigos == ["S001", "S002"], f"título não reconhecido ({motivo}): {titulo!r}"
    primeira, segunda = encontradas
    assert list(primeira.inputs) == ["X001"]         # não engoliu o insumo seguinte
    assert list(segunda.inputs) == ["X009"]
    assert segunda.unit == "UN"


def test_titulo_com_quebra_de_linha_preserva_descricao_e_unidade():
    linhas = _linhas_com_titulo(
        "S002 - PISO INTERTRAVADO (20X10X6)CM - COMPACTACAO MECANIZADA\n - M2")
    segunda = parse_sheet(linhas, "COMPOSICOES")[1]
    assert segunda.description == "PISO INTERTRAVADO (20X10X6)CM - COMPACTACAO MECANIZADA"
    assert segunda.unit == "M2"


def test_linha_parecida_com_titulo_e_nao_reconhecida_vira_aviso():
    """Corrupção silenciosa vira alerta visível — o que o bug A não tinha."""
    avisos: list[str] = []
    linhas = [["S001 - CHAPISCO - M2"], ["MATERIAIS", None, "Unidade", "Coeficiente"],
              ["RELATORIO ANALITICO – COMPOSICOES DE CUSTOS COM PALAVRAS DEMAIS NO CODIGO"]]
    parse_sheet(linhas, "COMPOSICOES", warnings=avisos)
    assert len(avisos) == 1
    assert "COMPOSICOES!A3" in avisos[0]


def test_titulo_reconhecido_nao_gera_aviso(composition_rows):
    avisos: list[str] = []
    parse_sheet(composition_rows, "COMPOSICOES", warnings=avisos)
    assert avisos == []
