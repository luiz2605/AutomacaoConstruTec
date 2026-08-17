import pytest

from orcauto.compositions import CompositionIndex, parse_sheet
from orcauto.config import CompositionConfig
from orcauto.resolver import Resolver


@pytest.fixture
def resolver(composition_rows):
    index = CompositionIndex(parse_sheet(composition_rows, "COMPOSICOES"))
    return Resolver(index, CompositionConfig(service_code_re=r"^S"))


def test_coeficiente_direto(resolver):
    coefficient = resolver.resolve("S001")["X001"]
    assert coefficient.value == 2.5
    assert coefficient.formula() == "'COMPOSICOES'!D5"


def test_coeficiente_aninhado_multiplica_pelo_subservico(resolver):
    """S002 não tem cimento direto: vem de S003 (292 kg/m3) x 0,025 m3/m2."""
    coefficient = resolver.resolve("S002")["X001"]
    assert coefficient.value == pytest.approx(7.3)
    assert coefficient.formula() == "'COMPOSICOES'!D16*0.025"
    assert coefficient.trail() == "S002>S003"


def test_soma_parcelas_quando_o_insumo_vem_por_dois_caminhos(resolver):
    """S005 tem cimento direto (350) e via S001 (2,5 x 3)."""
    coefficient = resolver.resolve("S005")["X001"]
    assert coefficient.value == pytest.approx(357.5)
    assert coefficient.formula() == "'COMPOSICOES'!D25+'COMPOSICOES'!D5*3"


def test_mao_de_obra_tambem_e_resolvida(resolver):
    assert resolver.resolve("S002")["M001"].value == 0.6


def test_coefficients_for_filtra_pelas_colunas_rastreadas(resolver):
    found = resolver.coefficients_for("S002", {"F": "X001", "G": "X002", "H": "INEXISTENTE"})
    assert sorted(found) == ["F", "G"]
    assert found["G"].value == pytest.approx(0.0304)


def test_codigo_desconhecido_devolve_vazio(resolver):
    assert resolver.resolve("NAO_EXISTE") == {}


def test_profundidade_maxima_respeitada(composition_rows):
    index = CompositionIndex(parse_sheet(composition_rows, "COMPOSICOES"))
    raso = Resolver(index, CompositionConfig(service_code_re=r"^S", max_depth=0))
    # sem recursão, o sub-serviço S003 permanece como folha
    assert "S003" in raso.resolve("S002")
    assert "X001" not in raso.resolve("S002")


def test_formula_respeita_outra_coluna_de_coeficiente(resolver):
    coefficient = resolver.resolve("S001")["X001"]
    assert coefficient.formula(coefficient_column=5) == "'COMPOSICOES'!E5"
