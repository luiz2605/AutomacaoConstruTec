import openpyxl
import pytest

from orcauto.compositions import CompositionIndex, parse_sheet
from orcauto.config import CompositionConfig, RulesConfig
from orcauto.layout import detect
from orcauto.planner import NEW, SUBSTITUTED, UPDATED, plan_sheet
from orcauto.resolver import Resolver


@pytest.fixture
def context(workbook_path, composition_rows, topics):
    index = CompositionIndex(parse_sheet(composition_rows, "COMPOSICOES"))
    resolver = Resolver(index, CompositionConfig(service_code_re=r"^S"))
    formulas = openpyxl.load_workbook(workbook_path)
    values = openpyxl.load_workbook(workbook_path, data_only=True)
    layout = detect(formulas["REVESTIMENTO"], values["REVESTIMENTO"])
    budget_codes = {item.code for topic in topics for item in topic.items}
    return layout, topics[0].items, index, resolver, budget_codes


def build(context, rules=None):
    layout, items, index, resolver, codes = context
    return plan_sheet(layout, items, index, resolver, codes, 5, "REVESTIMENTO",
                      rules or RulesConfig())


def test_codigo_identico_atualiza_e_preserva_a_quantidade(context):
    plan = build(context)
    row = plan.rows[10]
    assert (row.mode, row.item.code) == (UPDATED, "S001")
    assert row.quantity == 100          # da aba, não os 120 do orçamento
    assert row.quantity_source == "preservar"


def test_linha_legada_fora_do_orcamento_e_substituida(context):
    plan = build(context)
    row = plan.rows[11]
    assert (row.mode, row.item.code) == (SUBSTITUTED, "S002")
    assert row.replaced_code == "S004"
    assert row.quantity == 210          # passa a valer a do orçamento
    assert row.similarity > 0.9


def test_item_sem_contrapartida_vai_para_linha_livre(context):
    plan = build(context)
    assert (plan.rows[12].mode, plan.rows[12].item.code) == (NEW, "S005")


def test_item_sem_composicao_e_reportado(context):
    plan = build(context)
    assert [(s.item.code, s.reason) for s in plan.skipped] == \
           [("S999", "composição não encontrada no arquivo")]


def test_substituicao_pode_ser_desligada(context):
    plan = build(context, RulesConfig(substitution_enabled=False))
    assert plan.rows[12].item.code == "S002"       # foi para linha livre
    assert plan.rows[12].mode == NEW
    assert 11 not in plan.rows                     # linha legada intacta


def test_substituicao_pode_ser_bloqueada_por_codigo(context):
    plan = build(context, RulesConfig(substitution_block={"REVESTIMENTO": ["S004"]}))
    assert all(row.mode != SUBSTITUTED for row in plan.ordered())


def test_politica_de_quantidade_pode_seguir_o_orcamento(context):
    plan = build(context, RulesConfig(quantity_policy="orcamento"))
    assert plan.rows[10].quantity == 120


def test_override_de_quantidade_por_linha(context):
    plan = build(context, RulesConfig(quantity_override={"REVESTIMENTO": {"10": "orcamento"}}))
    assert plan.rows[10].quantity == 120
    assert plan.rows[10].notes


def test_atribuicao_e_global_e_nao_pela_ordem_do_pdf(context):
    """S005 é lido antes de nada disputar a linha 11; a linha legada tem de ficar
    com S002, que é quem de fato corresponde a ela."""
    layout, items, index, resolver, codes = context
    invertidos = list(reversed(items))
    plan = plan_sheet(layout, invertidos, index, resolver, codes, 5, "REVESTIMENTO")
    assert plan.rows[11].item.code == "S002"


def test_sem_linha_livre_o_item_e_reportado(context):
    layout, items, index, resolver, codes = context
    for row in layout.free_rows():             # ocupa todas as livres
        layout.rows[row].quantity = 1
    plan = plan_sheet(layout, items, index, resolver, codes, 5, "REVESTIMENTO")
    assert any("sem linha livre" in s.reason for s in plan.skipped)
