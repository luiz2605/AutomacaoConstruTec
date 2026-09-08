# -*- coding: utf-8 -*-
"""Atribuição de código de composição quando o orçamento não traz um.

A "Planilha Orçamentária" exportada do Excel não tem coluna Código: os itens
chegam com `code=""` e, sem isto, nenhum deles encontraria composição — não
importa o resto do programa.

A atribuição acontece **antes** do planejamento, e o que ela faz é preencher
`item.code`. Assim `planner.py`, `synth.py` e `resolver.py` continuam
trabalhando por código, sem saber que a origem foi uma descrição, e o formato
analítico segue exatamente o mesmo caminho de antes.

Dois limiares, porque as duas situações são diferentes:

* acima do **alto** (0,85) o texto é praticamente o mesmo — no orçamento real
  da piscina, 34 dos 41 itens batem em 1,00, caractere por caractere, porque as
  duas planilhas saíram da mesma tabela SEINFRA. Aceita direto;
* entre o **mínimo** (0,60) e o alto, aceita mas marca para conferência humana
  — vai para a seção 9 do `LOG AUTO` com o escore e as duas descrições;
* abaixo do mínimo não aplica, e o item cai no mesmo caminho já existente de
  "composição não encontrada no arquivo".
"""
from __future__ import annotations

from dataclasses import dataclass

from .compositions import Composition, CompositionIndex
from .config import RulesConfig
from .textutil import normalize, similarity

NUNCA, SEM_CODIGO, SEMPRE = "nunca", "sem_codigo", "sempre"


@dataclass
class DescriptionMatch:
    """O que ligou um item do PDF a uma composição, e com que confiança."""
    topic_number: int
    topic_name: str
    order: str
    description: str                       # como veio no PDF
    composition: Composition | None
    score: float
    accepted: bool
    needs_review: bool

    @property
    def code(self) -> str:
        """Código de fato aplicado — vazio quando o candidato foi recusado.

        A composição continua guardada para o log mostrar de que passou perto,
        mas quem lê a coluna do código não pode achar que ela foi usada.
        """
        return self.composition.code if (self.composition and self.accepted) else ""

    @property
    def situation(self) -> str:
        if not self.accepted:
            return "NAO APLICADO: nenhuma composicao parecida o bastante"
        return "CONFERIR" if self.needs_review else "aceito automaticamente"


def _catalog(index: CompositionIndex) -> list[tuple[str, Composition]]:
    """Descrição normalizada de cada composição, calculada uma vez só.

    Sem isto, `similarity` normalizaria as 4.458 descrições a cada item.
    """
    return [(normalize(c.description), c) for c in index.compositions if c.description]


def best_match(description: str, catalog: list[tuple[str, Composition]]
               ) -> tuple[Composition | None, float]:
    """Composição de descrição mais parecida, e o escore."""
    alvo = normalize(description)
    if not alvo:
        return None, 0.0
    melhor, escore = None, 0.0
    for texto, composition in catalog:
        atual = similarity(alvo, texto)
        if atual > escore:
            melhor, escore = composition, atual
            if escore >= 1.0:              # idêntico: não há como melhorar
                break
    return melhor, escore


def resolve_missing_codes(topics, index: CompositionIndex,
                          rules: RulesConfig | None = None) -> list[DescriptionMatch]:
    """Preenche `item.code` por semelhança de descrição. Devolve o que fez.

    Preferir sempre o código: só entra aqui o item que não tem código nenhum
    (modo `sem_codigo`, o padrão) ou, no modo `sempre`, também aquele cujo
    código não existe no índice. O padrão é deliberadamente conservador — no
    formato analítico, mexer em item com código não encontrado mudaria um
    resultado que hoje já está validado.
    """
    rules = rules or RulesConfig()
    modo = (rules.description_match or SEM_CODIGO).strip().lower()
    if modo == NUNCA:
        return []

    pendentes = []
    for topic in topics:
        for item in topic.items:
            if not (item.code or "").strip():
                pendentes.append((topic, item))
            elif modo == SEMPRE and index.get(item.code) is None:
                pendentes.append((topic, item))
    if not pendentes:
        return []

    catalog = _catalog(index)
    # itens repetidos são comuns (o mesmo concreto em três tópicos): resolver a
    # mesma descrição uma vez só evita varrer o catálogo à toa
    memoria: dict[str, tuple[Composition | None, float]] = {}
    encontrados: list[DescriptionMatch] = []
    for topic, item in pendentes:
        chave = normalize(item.description)
        if chave not in memoria:
            memoria[chave] = best_match(item.description, catalog)
        composition, escore = memoria[chave]

        aceito = composition is not None and escore >= rules.description_match_min
        conferir = aceito and escore < rules.description_match_high
        if aceito:
            item.code = composition.code
        encontrados.append(DescriptionMatch(
            topic_number=topic.number, topic_name=topic.name, order=item.order,
            description=item.description, composition=composition if aceito else composition,
            score=escore, accepted=aceito, needs_review=conferir))
    return encontrados
