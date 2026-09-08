# -*- coding: utf-8 -*-
"""Configuração do projeto (TOML ou JSON).

Tudo tem padrão utilizável; o arquivo de configuração só precisa declarar o que
foge do padrão. Veja `config/` para exemplos comentados.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:                                     # Python >= 3.11
    import tomllib
except ModuleNotFoundError:              # pragma: no cover
    tomllib = None


@dataclass
class PdfConfig:
    """Como ler o orçamento analítico em PDF.

    O leitor padrão espera o layout `Ordem | Código | Descrição | Unidade |
    Quantidade | Preço | Total`, com títulos de tópico no formato
    `<número> <NOME EM MAIÚSCULAS> <valor>`.
    """
    topic_number_re: str = r"^\d+$"
    item_order_re: str = r"^\d+(?:\.\d+)+$"
    number_re: str = r"^[\d\.]+,\d+$"
    topic_max_x: float = 120.0
    continuation_min_x: float = 200.0
    trailing_numbers: int = 3
    header_words: tuple[str, ...] = ("Ordem", "Código", "Descrição", "Unidade")
    line_tolerance: float = 2.5
    # ---- perfil "planilha exportada" -------------------------------------
    # Segundo formato: PLANILHA ORÇAMENTÁRIA exportada do Excel. Não tem coluna
    # Código, o tópico não traz valor na própria linha (vem num SUBTOTAL, depois
    # de todos os itens) e a numeração mistura ponto e vírgula no mesmo arquivo.
    # Campos separados de propósito: o perfil analítico não muda em nada.
    planilha_topic_re: str = r"^\d+[.,]0+$"      # "1.00", "3,00"
    planilha_order_re: str = r"^\d+[.,]\d+$"     # "2.01", "4,01"
    planilha_order_max_x: float = 60.0           # coluna Item, encostada à esquerda
    planilha_value_min_x: float = 355.0          # daqui p/ a direita: Un. e números
    planilha_orphan_max_gap: float = 14.0        # distância vertical p/ adotar órfã
    planilha_noise_words: tuple[str, ...] = ("SUBTOTAL", "TOTAL", "BDI", "Item")
    # token que denuncia o formato analítico: ele tem coluna Código, o outro não
    code_header_words: tuple[str, ...] = ("CODIGO", "CODE")


@dataclass
class CompositionConfig:
    """Onde e como ler as tabelas de composição de custo."""
    sheets: list[str] = field(default_factory=list)   # vazio = detecta sozinho
    # O separador aceita qualquer variante de traço e dispensa o espaço em volta:
    # na Tabela SEINFRA real há 70 títulos escritos como "CPC0012- DESCRIÇÃO" ou
    # com quebra de linha antes da unidade. Sem isso o título não é reconhecido e
    # os insumos dele vazam para a composição anterior (bug A do relatório v3).
    title_re: str = r"^([A-Z0-9][A-Z0-9\.\-/]*?)\s*[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]\s*(.*)$"
    section_keywords: tuple[str, ...] = (
        "EQUIPAMENTO", "MAO DE OBRA", "MATERIAIS", "SERVICOS", "TRANSPORTE",
    )
    code_column: int = 1
    description_column: int = 2
    unit_column: int = 3
    coefficient_column: int = 4
    service_code_re: str = r"^C"          # insumo que casa vira sub-composição
    max_depth: int = 3
    # True  = uma coluna por insumo-FOLHA; o sub-serviço é aberto e some.
    # False = o sub-serviço com composição própria vira ele mesmo uma coluna,
    #         com o coeficiente de primeiro nível — que é como a planilha feita
    #         à mão faz (a aba INFRAESTRUTURA real tem uma coluna C3129).
    #         Evita a dupla contagem: a mão de obra de dentro da argamassa
    #         deixa de ser somada à mão de obra da alvenaria.
    expand_subservices: bool = True
    # insumos cotados em KG mas comprados em saco: o TOTAL da coluna recebe
    # ROUNDUP(.../tamanho do saco). Não dá para inferir só pela unidade — a
    # Tabela SEINFRA não diz o que é ensacado —, então é lista explícita.
    bag_rounding_inputs: tuple[str, ...] = ("I0805",)   # I0805 = CIMENTO PORTLAND
    bag_size: float = 50.0
    # seções de composição que viram coluna numa aba gerada. Vazio = todas.
    # Numa "RELAÇÃO DE MATERIAIS", ("MATERIAIS",) deixa de fora mão de obra e
    # equipamento — no orçamento real isso é 34% das colunas.
    column_sections: tuple[str, ...] = ()
    min_tables_to_autodetect: int = 5


@dataclass
class TargetConfig:
    """Abas de destino (as planilhas de levantamento)."""
    suffix: str = " (AUTO)"
    sheets: list[str] = field(default_factory=list)   # vazio = todas as mapeadas
    topic_map: dict[str, str] = field(default_factory=dict)   # "3" -> "INFRAESTRUTURA"
    min_topic_similarity: float = 0.60
    header_keywords: tuple[str, ...] = ("ITEM", "CODIGO", "QUANT")
    total_label: str = "TOTAL"
    # aba-molde usada para sintetizar uma aba que ainda não existe
    template_sheet: str = "MODELO BASE"
    generate_missing: bool = True
    # faixa consultada pelo VLOOKUP de unidade no cabeçalho das colunas novas
    insumos_lookup_range: str = "insumos!$A$6:$D$8635"
    # texto da barra colorida acima do cabeçalho, reescrito por aba gerada
    banner_prefix: str = "LEVANTAMENTO - "
    # a coluna nunca encolhe; só alarga quando o valor não caberia e viraria
    # `#######`. A folga cobre o negrito da linha de TOTAL, que é mais largo
    # que a unidade de largura do Excel, medida na fonte normal.
    folga_largura: float = 3.0


@dataclass
class RulesConfig:
    """Regras de decisão da automação."""
    # quantidade de linha cujo código já batia: "preservar" (padrão) ou "orcamento"
    quantity_policy: str = "preservar"
    # substituição de linha legada por item do orçamento
    substitution_enabled: bool = True
    substitution_min_similarity: float = 0.55
    # {"ABA": {"12": "C3615"}} força; {"ABA": ["C0054"]} em `substitution_block` proíbe
    substitution_force: dict[str, dict[str, str]] = field(default_factory=dict)
    substitution_block: dict[str, list[str]] = field(default_factory=dict)
    # {"ABA": {"10": "orcamento"}} força a origem da quantidade de uma linha
    quantity_override: dict[str, dict[str, str]] = field(default_factory=dict)
    # amplia o intervalo do TOTAL quando faltarem linhas livres dentro dele
    extend_total_range: bool = True
    # em linha ATUALIZADA, preenche unidade/descrição que estejam vazias ou em
    # erro (#REF!), sem jamais sobrescrever conteúdo aproveitável
    fill_empty_identity: bool = True
    # ---- casamento por descrição (orçamento sem coluna Código) -----------
    # "sem_codigo" (padrão): só o item que chega sem código nenhum. É o que
    #   torna a Planilha Orçamentária utilizável sem tocar no formato analítico,
    #   onde todo item tem código e o resultado já está validado.
    # "sempre": também tenta quando o código existe mas não está no índice.
    # "nunca": desliga.
    description_match: str = "sem_codigo"
    description_match_high: float = 0.85     # daqui para cima, aceita direto
    description_match_min: float = 0.60      # entre os dois, aceita e sinaliza
    write_log_sheet: bool = True
    log_sheet_name: str = "LOG AUTO"


@dataclass
class Config:
    pdf: PdfConfig = field(default_factory=PdfConfig)
    compositions: CompositionConfig = field(default_factory=CompositionConfig)
    targets: TargetConfig = field(default_factory=TargetConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path is None:
            return cls()
        path = Path(path)
        raw = path.read_bytes()
        if path.suffix.lower() == ".json":
            data = json.loads(raw.decode("utf-8"))
        else:
            if tomllib is None:                                  # pragma: no cover
                raise RuntimeError("TOML exige Python 3.11+; use um arquivo .json")
            data = tomllib.loads(raw.decode("utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        def build(kind, key):
            payload = dict(data.get(key) or {})
            known = {f.name for f in kind.__dataclass_fields__.values()}
            unknown = set(payload) - known
            if unknown:
                raise ValueError(f"[{key}] opção desconhecida: {', '.join(sorted(unknown))}")
            for name, value in list(payload.items()):
                current = kind.__dataclass_fields__[name]
                if isinstance(current.default, tuple) and isinstance(value, list):
                    payload[name] = tuple(value)
            return kind(**payload)

        unknown = set(data) - {"pdf", "compositions", "targets", "rules"}
        if unknown:
            raise ValueError(f"seção desconhecida na configuração: {', '.join(sorted(unknown))}")
        return cls(build(PdfConfig, "pdf"), build(CompositionConfig, "compositions"),
                   build(TargetConfig, "targets"), build(RulesConfig, "rules"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
