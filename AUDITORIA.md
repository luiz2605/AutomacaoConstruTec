# Auditoria da automação `orcauto` — 17/08/2026

Auditoria do relatório de correções sobre a saída real (Hospital Veterinário
Unicatólica Quixadá), conferida contra o PDF do orçamento, a aba
`COMPOSIÇÃO TAB 28` e as abas de levantamento **originais**.

**Resultado**: de 22 pontos levantados, **2 são erros confirmados da automação**
(ambos corrigidos), **1 é uma decisão de projeto revertida por escolha do
Luiz**, **16 são comportamento correto** e **3 são leitura manual a revisar**.
A varredura ampla encontrou **2 defeitos que o relatório não pegou**.

---

## 1. Erros confirmados e corrigidos

### 1.1 Perda de formatação (a queixa "erro de formatação em Paredes")

**Causa raiz**: `ooxml.py::_cell_pattern`. O padrão `<c r="REF"(?:\s[^>]*)?(?:/>|>.*?</c>)`
usa `[^>]*` **guloso**, que consome também a barra de uma célula auto-fechada:

```
<c r="D12" s="169"/><c r="E12" s="541"><v>38.96</v></c>
           └──── [^>]* engole ` s="169"/` ────┘
```

Sem a barra, a alternância cai em `>.*?</c>` e o casamento **atravessa a célula
seguinte** até o próximo `</c>`. Ao regravar D12, a E12 era apagada junto;
reinserida depois por `_insert_cell`, nascia sem `s=` — sem borda, sem
preenchimento, sem fonte da tabela.

**Correção**: atributos passam a ser casados de forma **não-gulosa** (`[^>]*?`),
de modo que `/>` fecha a célula auto-fechada antes de a alternância avançar.
O mesmo padrão foi unificado em `_insert_cell`, `ensure_row` e `_shared_formulas`,
que tinham a falha idêntica.

**Alcance real (o relatório só viu Paredes):**

| Aba | Linha | Células afetadas |
|---|---|---|
| PAREDES | 12 | E, G |
| REVESTIMENTOS | 14 | C |
| REVESTIMENTOS | 15 | C |

Nenhuma célula foi perdida em definitivo — todas foram regravadas depois, só
que sem formato. Depois da correção: **0 células sem formatação**.

Teste de regressão: `test_gravar_celula_autofechada_nao_engole_a_seguinte`.

### 1.2 Unidade de medida vazia (a queixa sobre C0776)

**Confirmado.** `pipeline.py::_write_sheet` só escrevia identidade
(código/descrição/unidade/quantidade) em linhas `NOVA` e `SUBSTITUI`. Numa linha
`ATUALIZADA` a unidade ficava como estava — e em REVESTIMENTOS ela é um
`IFERROR(VLOOKUP(...#REF!...))` que resolve para vazio.

**Correção**: nova regra `rules.fill_empty_identity` (ligada por padrão).
Em linha `ATUALIZADA`, unidade e descrição são preenchidas a partir da
composição **apenas quando a célula está vazia ou exibindo erro** (`#REF!`,
`#N/A`, …). Conteúdo aproveitável nunca é sobrescrito.

Depois: `REVESTIMENTOS!D10 = M2`, `PAREDES!D10 = M2`, `INFRAESTRUTURA!D12 = M3`.

---

## 2. Comportamento correto — com a evidência

### 2.1 Os 12 itens "ausentes" (C0216, C4301, C0384, C3001, C2789, C1256, C0328, C0702, C0710, 103670, CPC597, CPE07)

A paridade fecha nas três abas — **nenhum item se perde silenciosamente**:

| Aba | Itens no PDF | Gravadas | Puladas | Soma |
|---|---|---|---|---|
| INFRAESTRUTURA | 16 | 6 | 10 | **16** |
| PAREDES | 2 | 2 | 0 | **2** |
| REVESTIMENTOS | 6 | 4 | 2 | **6** |

Os 9 itens marcados como "sem insumo rastreado" foram conferidos insumo a
insumo: **a interseção com as colunas da aba é vazia em todos**. Exemplos:
C0216 consome aço, arame e mão de obra; C2789, escavadeira e servente;
C3001, cerâmica e argamassa pré-fabricada. A aba não tem coluna para nada
disso. O motivo registrado no log está correto.

Os 3 restantes (`103670`, `CPC597`, `CPE07`) **não existem** em nenhuma das
abas de composição, sob nenhuma grafia próxima. São códigos SINAPI/próprios
ausentes do arquivo.

### 2.2 C1905, C2461 (Revestimento) e C1630, C0329 (Infraestrutura) — "não estão no PDF"

**Correto, e não foram introduzidos pela automação.** Estão nessas mesmas
linhas, com os mesmos valores, na aba **original**. A automação nunca as tocou:
`clone_sheet` copia a aba byte a byte e só as linhas de `plan.ordered()` são
editadas.

São linhas legadas sem contrapartida no orçamento — e o relatório tem razão em
estranhá-las. **Melhoria implementada**: nova **seção 5 do `LOG AUTO`**,
"LINHAS DA ABA SEM CONTRAPARTIDA NO ORÇAMENTO", que agora as lista:

| Aba | Linha | Código | Situação |
|---|---|---|---|
| INFRAESTRUTURA | 10 | C1630 | código existe no orçamento, mas em outro tópico (1.1) |
| INFRAESTRUTURA | 11 | C0329 | código não consta em nenhum item |
| PAREDES | 11 | — | linha sem código de serviço (lançamento manual) |
| PAREDES | 13 | CPC0002 | código não consta em nenhum item |
| REVESTIMENTOS | 12 | C1905 | código não consta em nenhum item |
| REVESTIMENTOS | 13 | C2461 | código não consta em nenhum item |

Sobre C1630 especificamente: a hipótese de fronteira de tópico perdida no PDF
foi **descartada** — `read_budget` atribui C1630 ao tópico 1 (SERVIÇOS
PRELIMINARES), corretamente. Ele chegou à aba pelas mãos do orçamentista, não
pela automação.

### 2.3 C3087, C3035, C4592 — "coeficientes com elementos que não deveriam estar"

**Duas hipóteses testadas e refutadas:**

*Contaminação de fronteira de tabela* — conferi linha a linha o intervalo entre
o título de cada composição e o da seguinte. Todos os insumos indexados
pertencem à sua própria tabela; as linhas de rodapé (`Total Simples`,
`Encargos Sociais`, `Valor BDI`, `Valor Geral`) são corretamente ignoradas por
não terem código na coluna A.

*Coeficiente sem valor em cache* — varri a coluna D inteira da `COMPOSIÇÃO TAB 28`:
**0 fórmulas sem cache**. Nenhum insumo foi omitido por esse motivo.

O que o relatório interpretou como "elementos a mais" é o **aninhamento**: em
C3087 o único material é o serviço `C4429 - ARGAMASSA ... TRAÇO 1:5` (coef.
0,025); como a aba tem colunas de areia e cimento, a automação abre a
sub-composição e grava `D26292*0,025` e `D26293*0,025`. É o mesmo procedimento
que o autor da planilha fazia à mão — a linha 11 original trazia `=1.216*0.025`
e `=243*0.025`.

Sobre a unidade de C4592: `D12 = M3`, que é a unidade da composição
(`COMPOSIÇÃO TAB 28!A36599`) e a do item 3.5 do PDF. Confere.

### 2.4 C3347 — "faltante" e "sem coluna rastreada"

**Leitura manual a revisar.** C3347 **está** na aba, linha 13, com os três
materiais gravados: `F13 = D27143` (pedra de mão), `G13 = D55622*0,3` (cimento,
via C0171) e `H13 = D55621*0,3` (areia). Assumiu a linha que era do código
legado C0054, que não consta no orçamento. Está registrado na seção 3 do LOG.

---

## 3. Decisão revertida: C3614 × C3615 (Paredes)

Não é erro de nenhum dos dois lados — é uma escolha, e ela mudou.

| | Código | Descrição | Quantidade |
|---|---|---|---|
| Linha legada | C3614 | tijolo maciço aparente, esp=11 cm (86,96 un/m²) | 38,96 m² |
| Item 5.2 do PDF | C3615 | tijolo maciço aparente, esp=22 cm (173,92 un/m²) | 4,32 m² |

C3614 não consta em nenhum item do orçamento, e a semelhança de descrição é
0,98 — por isso a regra de substituição assumiu a linha. Isso descartava os
38,96 m² medidos.

**Aplicado**: `rules.substitution_block = { PAREDES = ["C3614"] }`. C3614
permanece na linha 12 com 38,96 m²; C3615 entra na linha 14 com 4,32 m²; o
intervalo do TOTAL é ampliado sozinho para `$E$10:$E$14`.

**Consequência a decidir**: as duas linhas agora somam no mesmo TOTAL. Se as
duas descrevem a mesma parede, o tijolo maciço aparente está contado em
dobro. A seção 5 do LOG sinaliza a linha 12. Para voltar atrás, basta remover
o bloco do `.toml`.

---

## 4. Hipóteses de erro de formatação descartadas

| Hipótese | Veredito |
|---|---|
| `<mergeCells>` não replicado em linha nova | **Descartada** — nenhuma das três abas tem mesclagem no bloco de serviços; a lista é idêntica na original e na (AUTO) |
| Estilo ausente porque a linha-modelo não tinha a coluna | **Descartada** — a causa era o regex guloso (§1.1), não a herança |
| `<dimension>` desatualizado | **Sem efeito observado** — o Excel recalcula a dimensão ao abrir; `orcauto check` não acusa |
| `<row>`/`<c>` fora de ordem no XML | **Descartada** — varri as 15 abas: 0 linhas e 0 células fora de ordem crescente |
| `spans` insuficiente | **Sem efeito** — herdado da linha-modelo, cobre as colunas usadas |

---

## 5. Diagnóstico da planilha original

Não está corrompida no sentido estrutural. O que existe:

| Achado | Quantidade | Efeito na automação |
|---|---|---|
| `definedNames` apontando para `#REF!` | 46 de 56 | Nenhum — a automação não os usa. É o que faz o Excel reclamar ao abrir. |
| Fórmulas sem valor em cache | 16, todas em REVESTIMENTOS | Era a causa da unidade vazia; tratado em §1.2 |
| Fórmulas resolvendo em erro | 5 em COMPOSIÇÃO PROPRIAS, 1 em PAREDES (`E16 = #REF!`) | Linha 16 de PAREDES está fora do intervalo do TOTAL; não contamina |
| Vínculos externos (`[2]TAB.28!`) | 4 | Preservados byte a byte |
| Linhas/células fora de ordem no XML | 0 | — |
| `COMPOSIÇÃO TAB 28` | 0 defeitos | Os coeficientes são confiáveis |

**Correção mínima recomendada** (fora do escopo da automação, a ser feita por
você no Excel, uma vez): apagar os 46 nomes definidos quebrados em
*Fórmulas → Gerenciador de Nomes*, e corrigir ou remover a linha 16 de PAREDES.
Não recomendo mexer em mais nada — o resto está íntegro.

---

## 6. Recomendação: coluna nova para insumo sem coluna (para sua decisão)

Levantei quantos itens cada coluna nova recuperaria:

**INFRAESTRUTURA — 7 itens fora por falta de coluna** (C0216, C4301, C2789,
C1256, C0328, C0702, C0710). A coluna que mais recuperaria é `I2543` (SERVENTE),
com 5 itens — mas é **mão de obra**, e a aba se chama "RELAÇÃO DE MATERIAIS".
As colunas de material recuperariam 1 item cada: `I0163` (aço CA-50),
`I0111` (areia vermelha), `I0103` (arame recozido).

**REVESTIMENTOS — 2 itens fora** (C0384, C3001), cada um exigindo 4 a 6
colunas novas distintas (carpintaria, cerâmica, perfis).

**PAREDES — 0 itens fora.**

Sobre CPC001 (itens 3.6 e 3.8), os insumos sem coluna são:

| Insumo | Descrição | Coeficiente |
|---|---|---|
| I0280 | BRITA | 0,627 |
| I1605 | PEDRISCO | 0,209 |
| I7952 | AÇO CA-50/60 | 111,3 |
| I1916 | TÁBUA DE 1" DE 3ª | 28,4 |
| I0682 | BETONEIRA (equipamento) | 0,714 |
| … | mais 10, quase todos mão de obra | |

**Minha recomendação**: não implementar criação automática de coluna. Recuperar
todos os 7 itens de Infraestrutura exigiria mais de 10 colunas novas, a maioria
de mão de obra e equipamento, que não pertencem a uma relação de materiais.
O caminho barato e reversível é você acrescentar **à mão** as 2 ou 3 colunas que
realmente quer comprar — Brita e Pedrisco são as mais defensáveis — seguindo o
padrão das existentes: código do insumo na linha 7, e o `VLOOKUP` de descrição
e unidade nas linhas 8 e 9. A automação passa a rastreá-las **sozinha** na
próxima execução, porque `layout.py::detect` lê as colunas da linha 7 em tempo
de execução. Nenhuma mudança de código é necessária.

Se depois disso ainda fizer sentido automatizar a criação, ela deve nascer como
`rules.allow_new_tracked_column` (opt-in), nunca por padrão — inserir coluna é
mudança estrutural, não correção.

---

## 7. Verificação final

```
orcauto check --original levantamento.xlsx --generated "... (AUTO) v2.xlsx"
  partes novas ......... 13
  partes removidas ..... ['xl/calcChain.xml']
  originais alteradas .. [Content_Types].xml, workbook.xml, workbook.xml.rels, styles.xml
  XML mal formado ...... nenhum
  OK: abas originais preservadas e pacote íntegro.

células que perderam formatação: 0   (antes: 4)
paridade PDF ↔ aba: OK nas três abas
suíte de testes: 75 passed
```
