# Correções do relatório v3 — investigação, causa raiz e prova

Cada seção segue o padrão exigido: **o que foi reproduzido**, **a causa raiz**
(não o sintoma), **a correção**, **a prova antes/depois** e o **teste de
regressão** que fixa o comportamento.

Arquivos usados na reprodução:

* `webapp/base/PLANILHA_BASE.xlsx` (arquivo-base, só com `MODELO BASE`)
* `03-_25_06_26_-_LEVANTAMENTO.xlsx` (arquivo com abas de levantamento prontas)
* `OrcamentoAnaliticoProposta1786557748172.pdf`

Suíte: **146 testes passando** (127 originais + 19 novos de regressão).
`orcauto check` continua OK nos dois arquivos gerados.

---

## Resumo executivo

| Bug | Situação | Causa raiz encontrada |
|---|---|---|
| A | **Confirmado** — causa diferente da suposta no relatório | Quebra de linha dentro do título (61 casos) e traço sem espaço em volta (9 casos). **Nenhum en dash** separando código de descrição. |
| B | **Confirmado** — é a causa dos 3 coeficientes errados relatados | O resolvedor abria todo sub-serviço; a mão de obra de dentro dele era somada à da composição-mãe e a coluna do próprio sub-serviço nunca era preenchida. |
| C | **Não reproduzido** — refutado com evidência | Nenhum vazamento entre tópicos. Os dois itens citados estão na aba `DEMOLIÇÕES E REMOÇÕES`, onde pertencem. O que confundiu a leitura foi o bug D. |
| D | **Confirmado** — uma única causa para os dois sintomas | O código `C0711` do PDF aponta, na tabela do arquivo, para outro serviço. A descrição gravada vinha da composição, sem aviso. |

---

## BUG A — título de composição não reconhecido

### O que o relatório supunha

Que o separador seria um en dash (`–`) em vez de hífen.

### O que os arquivos reais mostram

Varredura de todas as linhas candidatas a título nas duas abas de composição:

```
títulos reconhecidos ....... 4.388
títulos NÃO reconhecidos ...    70
variantes de traço nos títulos reconhecidos: {'-': 9.956, '–': 2}
```

Os dois en dashes estão **dentro da descrição** (`REFLETOR LED 50W 3000K – AVANT.`),
nunca separando código de descrição. A causa real são duas, e nenhuma delas é
o tipo do traço:

1. **Quebra de linha dentro da célula — 61 casos.** O título traz `\n` (às
   vezes precedido de tabulações ou de uma corrida de espaços) antes da unidade:

   ```
   'C4933 - HASTE DE ATERRAMENTO COPPERWELD 5/8"X 2.40M          \n - UN'
   'C4952 - PAREDE PRÉ-MOLDADA EM CONCRETO ARMADO, ESP.=13CM,\nINCLUSIVE TRANSPORTE E MONTAGEM - M2'
   ```

   O `(.*)$` do regex não atravessa `\n` (sem `re.MULTILINE`, `$` só casa no
   fim da string), então o título simplesmente não casa.

2. **Traço sem espaço em volta — 9 casos**, todos em `COMPOSIÇÃO PROPRIAS`:

   ```
   'CPC0012- GUARDA CORPO C/ CORRIMÃO EM ALUMÍNIO - ... - M2'
   'CPC0045 -PAINEL DE LED 4000K  24W -  UN'
   ```

   O regex exigia `\s+-\s+`.

O mecanismo de dano descrito no relatório está correto: sem título novo,
`current` continua apontando para a composição anterior, e os insumos da
composição cujo título falhou são anexados a ela.

### Correção

`src/orcauto/compositions.py`

* `flatten()` achata a célula (`\s`, `\xa0` e `\n` viram um espaço) **antes** de
  tentar casar o título;
* o `title_re` padrão passa a aceitar qualquer variante de traço com espaço
  opcional: `^([A-Z0-9][A-Z0-9\.\-/]*?)\s*[-‐‑‒–—―−]\s*(.*)$`;
* a separação de unidade também aceita as variantes de traço;
* **checagem defensiva**: uma linha que *parece* título (código curto em
  maiúsculas seguido de traço, vizinhos vazios) e mesmo assim não casa passa a
  gerar `possível título de composição não reconhecido em ABA!An: '...'`. O aviso
  vai para o terminal e para a **seção 8 do `LOG AUTO`**. Corrupção silenciosa
  vira alerta visível.

O regex foi validado contra o arquivo real antes de ser adotado:
**70 títulos recuperados, 0 regressões, 0 falsos positivos novos.**

### Prova antes/depois (arquivo real)

```
composições indexadas ............ 4.388  ->  4.458   (+70 títulos)
composições descontaminadas ......    48
insumos alheios removidos ........   224

C4935  DISJUNTOR TÉRMICO ...       43 -> 3 insumos   (engolia C4936, C4933, C4934)
C4758  SUBESTAÇÃO AÉREA 300 KVA    57 -> 43 insumos
C4750  TAMPA EM FIBRA DE VIDRO     12 -> 3 insumos
CPC0378 CONCRETO GROUT             14 -> 4 insumos
```

Invariante estrutural verificada em toda a planilha depois da correção:
**nenhuma composição tem insumo em linha posterior ao título da composição
seguinte** (0 violações). Avisos remanescentes: **1**, e é legítimo — o banner
`RELATÓRIO ANALÍTICO - COMPOSIÇÕES DE CUSTOS` na linha 1 da aba, que de fato
não é uma composição.

### Alcance no orçamento em questão

Dos 164 códigos do orçamento, **nenhum** mudava de composição por causa do bug A
— ou seja, o bug A **não é** a causa dos coeficientes errados relatados (isso é
o bug B). Ele é uma corrupção latente que atingiria outro orçamento que usasse
qualquer um dos 70 códigos afetados.

### Testes

`tests/test_compositions.py`

* `test_titulo_irregular_nao_vaza_insumo_para_a_composicao_anterior`
  (6 variantes: `\n` no fim, `\n` no meio, tabulações, sem espaço antes,
  sem espaço depois, en dash)
* `test_titulo_com_quebra_de_linha_preserva_descricao_e_unidade`
* `test_linha_parecida_com_titulo_e_nao_reconhecida_vira_aviso`
* `test_titulo_reconhecido_nao_gera_aviso`

---

## BUG B — sub-serviço aberto quando ele mesmo devia ser a coluna

### Reprodução

Confirmado exatamente como descrito, e é a causa dos **três** coeficientes
errados do relatório:

```
C3347  ALVENARIA DE PEDRA ARGAMASSADA
   1º nível: I2391=5,0  I2543=7,0  I1600=1,15  C0171=0,3
   resolve() antigo: I2543 = 10,0000   (7,0 + 0,3 x 10,0 da argamassa)   esperado 7,0
                     I0109 = 0,3648 e I0805 = 109,5 -> as "colunas soltas"
                     C0171 nunca aparece -> a coluna de ARGAMASSA fica vazia

C4592  ALVENARIA DE EMBASAMENTO
   resolve() antigo: I2543 = 12,2000   esperado 9,2

C4301  FORMA PARA CONCRETO "IN LOCO"
   resolve() antigo: I0498 = 1,1000    esperado 0,25
                     (0,25 próprio + 0,5 x 0,2 de C4281 + 0,75 x 1,0 de C4282)
```

Ou seja: os três sintomas ("coeficiente errado", "colunas soltas sem relação
com a composição" e "falta a coluna da argamassa") são **um só defeito**.

### Verificação sistêmica (todas as abas)

```
[PLANILHA_BASE] nenhuma coluna pré-formatada rastreia código de serviço
[LEVANTAMENTO]  INFRAESTRUTURA!J rastreia C3129 (AREIA DE CAMPO - EXTRAÇÃO)
```

`INFRAESTRUTURA!J` é uma coluna **feita à mão** rotulada com um código de
serviço. Ela nunca recebia valor. É a prova de que a planilha do escritório
espera o sub-serviço como coluna — e o docstring antigo de `topic_inputs` citava
justamente esse par (`C0329` -> `C3129`) para justificar o contrário.

### Correção

`src/orcauto/resolver.py`

* `resolve(code, stop_at=())` — códigos em `stop_at` não são abertos: viram
  parcela direta, com o coeficiente de primeiro nível. O cache passa a ser
  indexado por `(código, stop_at)`.
* `coefficients_for(code, wanted)` passa `stop_at=wanted.values()`
  automaticamente: **um código que já tem coluna própria nunca é aberto**.
  Isso conserta o modo de preenchimento sozinho, sem configuração nenhuma.
* `topic_inputs(..., expand_subservices=)` decide o mesmo para a aba
  sintetizada, onde as colunas ainda não existem e precisam ser escolhidas.

`src/orcauto/config.py` — nova opção `compositions.expand_subservices`:

* `true` (**padrão de fábrica, comportamento histórico preservado**): só
  insumo-folha vira coluna;
* `false`: o sub-serviço com composição própria vira uma coluna com o
  coeficiente de primeiro nível.

**Decisão adotada:** `expand_subservices = false` nas duas configurações reais
(`config/planilha-base.toml` e `config/hospital-veterinario.toml`), porque é o
que o relatório pede em três casos independentes e é como a planilha feita à mão
trabalha. O padrão do código continua `true` para não mudar o comportamento de
quem já usa a ferramenta sem configuração. **Reverter é uma linha de `.toml`.**

### Prova antes/depois (aba `INFRAESTRUTURA` gerada do molde)

| Item | Insumo | Antes | Depois | Esperado (relatório) |
|---|---|---|---|---|
| C4301 | I0498 CARPINTEIRO | 1,1000 | **0,2500** | 0,2500 |
| C4301 | C4281 / C4282 | sem coluna | **0,2 / 1,0** | só C4281/C4282 |
| C3347 | I2543 SERVENTE | 10,0000 | **7,0000** | 7,0000 |
| C3347 | C0171 ARGAMASSA | sem coluna | **0,3** | coluna presente |
| C4592 | I2391 PEDREIRO | 8,5000 | 8,5000 | 8,5000 |
| C4592 | I2543 SERVENTE | 12,2000 | **9,2000** | 9,2000 |
| C4592 | C0171 ARGAMASSA | sem coluna | **0,3** | coluna presente |

E no modo de preenchimento, sobre o arquivo real: `INFRAESTRUTURA (AUTO)!J11`
deixa de sair vazia e passa a trazer `='COMPOSIÇÃO TAB 28'!D48228`.

### Testes

`tests/test_resolver.py`

* `test_coluna_de_subservico_recebe_coeficiente_de_primeiro_nivel`
* `test_subservico_com_coluna_propria_nao_e_aberto_nos_insumos`
* `test_stop_at_nao_contamina_o_cache`
* `test_mao_de_obra_da_mae_nao_soma_a_do_subservico` (o caso C3347: 10,0 -> 7,0)

`tests/test_synth.py`

* `test_subservico_vira_coluna_quando_a_expansao_esta_desligada`
* `test_aba_gerada_sem_expansao_traz_o_coeficiente_de_primeiro_nivel`

---

## BUG C — itens de Demolições no topo de Infraestrutura/Superestrutura

### Não reproduzido. As duas hipóteses do relatório foram testadas e caem.

**Hipótese 1 (conteúdo pré-existente): impossível neste arquivo.**
`PLANILHA_BASE.xlsx` não tem aba `Infraestrutura` nem `Superestrutura` —
suas abas são `MATERIAL, RES, TELHAS, TRELIÇA, FERRAGENS, insumos,
COMPOSIÇÃO PROPRIAS, TAB.28, COMPOSIÇÃO TAB 28, MODELO BASE, RESUMO, COMP.027`.
As duas abas citadas são **sintetizadas do molde**, nascem vazias e não têm
conteúdo legado para herdar. A seção 5 do `LOG AUTO` (linhas sem contrapartida)
sai vazia, coerentemente.

**Hipótese 2 (fronteira de tópico no PDF): a leitura está correta.**
`orcauto inspect` encontra os 20 tópicos e o pareamento tópico -> aba é 1:1.
A leitura dos itens confirma a fronteira:

```
TÓPICO 2 DEMOLIÇÕES E REMOÇÕES     2.3 C2992 ... | 2.4 C0711 ...
TÓPICO 3 INFRAESTRUTURA            3.1 C0216 ARMADURA CA-50A MÉDIA D= 6,3 A 10,0mm
                                   3.2 C0843 CONCRETO P/VIBR., FCK 25 MPa
TÓPICO 4 SUPERESTRUTURA            4.1 C0843 CONCRETO P/VIBR., FCK 25 MPa
```

E a planilha gerada bate com isso:

```
INFRAESTRUTURA  linha 10: 3.1 C0216 ARMADURA CA-50A MÉDIA   <- exatamente o esperado pelo relatório
INFRAESTRUTURA  linha 11: 3.2 C0843 CONCRETO P/VIBR. 25 MPa <- exatamente o esperado pelo relatório
SUPERESTRUTURA  linha 10: 4.1 C0843 CONCRETO P/VIBR. 25 MPa
DEMOLIÇÕES      linha 10: 2.3 C2992 | linha 11: 2.4 C0711   <- os dois itens estão aqui
```

**Verificação sistêmica em todos os 20 tópicos:** para cada aba, o primeiro item
gravado é o primeiro item do tópico que tem composição no arquivo.
**0 abas divergentes.**

### Explicação provável do relato

O item 2.4 aparece na aba de Demolições com o texto
`CARGA, DESCARGA E TRANSP. DE TUBOS E CONEXÕES EM MBV DN 150mm ATÉ 15km`, que
não é o que o PDF pediu — isso é o **bug D**. Ver duas linhas "de outro assunto"
no topo de uma aba de estrutura é o sintoma do bug D lido como se fosse
cruzamento de tópicos. Nenhuma alteração de código foi feita para o bug C,
porque não há defeito a corrigir; o que havia era falta de aviso, e isso o
bug D resolve.

---

## BUG D — item do PDF ausente / item presente que não está no PDF

### Reprodução: os dois sintomas têm a mesma causa

```
PDF, item 2.4:   C0711  CARGA MECANIZADA DE ENTULHO EM CAMINHÃO BASCULANTE  120,64 M3
COMPOSIÇÃO TAB 28!A14795:
                 C0711  CARGA, DESCARGA E TRANSP. DE TUBOS E CONEXÕES EM MBV DN 150mm ATÉ 15km
COMPOSIÇÃO TAB 28!A14909:
                 C0708  CARGA MECANIZADA DE ENTULHO EM CAMINHÃO BASCULANTE
```

O cruzamento é **por código**. O programa acha `C0711`, resolve os coeficientes
dele e grava a descrição **da composição** (`_write_sheet` e `write_synthesis`
gravam `composition.description`, e a unidade virou `M` em vez de `M3`).
Resultado:

* "CARGA MECANIZADA DE ENTULHO" não aparece — o programa nunca usou `C0708`;
* "CARGA, DESCARGA E TRANSP. DE TUBOS" aparece — porque é o que `C0711` é
  na tabela deste arquivo.

Não é o motivo "composição não encontrada": `C0708` **existe** no índice, com
3 insumos. É divergência entre a versão da tabela usada no orçamento e a versão
da tabela que está na planilha (ou um código digitado errado no orçamento).

### Correção

O par código/descrição não pode ser corrigido pelo programa — só o autor do
orçamento sabe qual dos dois está certo. O que **é** defeito é fazer isso em
silêncio. Passa a existir:

* `Audit.divergences()` — compara a descrição do PDF com a da composição
  (limiar de semelhança 0,60) em **todas** as linhas gravadas, nos dois modos;
* **seção 7 do `LOG AUTO`**: `DIVERGENCIA ENTRE A DESCRICAO DO PDF E A DA
  COMPOSICAO`, com item, código, as duas descrições, a origem e a semelhança;
* um bloco `[atencao]` no relatório do terminal.

### Prova (execução real)

```
[atencao] 6 item(ns) com descricao divergente entre o PDF e a composicao do mesmo codigo:
   DEMOLIÇÕES E REMOÇÕES  2.4  C0711   'CARGA MECANIZADA DE ENTULHO...' != 'CARGA, DESCARGA E TRANSP. DE TUBOS...'  (0.41)
   INSTALAÇÕES HIDROSSAN.  9.15 CPC0041 'RALO LINEAR' != 'CERÂMICA ESMALTADA CONCRETE CINZA 60X60...'              (0.22)
   INSTALAÇÕES ELÉTRICAS  10.16 C4802   'Luminária Plafon LED 45W 30x120...' != 'LUMINÁRIA DE SOBREPOR/EMBUTIR...'  (0.39)
   FORROS                 13.2  C1877   'TABICA DE GESSO' != 'PERFIL DE ALUMÍNIO TIPO ( L- T- U )'                 (0.27)
   REVESTIMENTO           14.5  C0384   'BATE-MACAS' != 'BATE-MACAS EM MADEIRA BOLEADA'                            (0.51)
   ACABAMENTOS            17.3  CPC0336 'RODAPÉ CURVO LETE AUTOCOLANTE...' != 'RODAPÉ BOLEADO - HOMENEY'            (0.33)
```

O relatório apontou **1** caso; a verificação sistêmica achou **6**. Cinco deles
ninguém tinha notado, e todos precisam de conferência humana no orçamento.

### Defeito adicional encontrado no `LOG AUTO`

A **seção 2 (ITENS DO ORÇAMENTO NÃO APLICADOS)** saía **sempre vazia** num
arquivo-base, apesar de a execução relatar 58 itens não aplicados: ela só lia
`audit.plans` (abas preenchidas) e ignorava `audit.synth` (abas sintetizadas) —
e num arquivo-base *toda* aba é sintetizada. Corrigido: a seção agora lista os
itens descartados dos dois modos.

### Testes

`tests/test_pipeline.py`

* `test_descricao_divergente_entre_pdf_e_composicao_vira_aviso`
* `test_descricao_equivalente_nao_vira_aviso`
* `test_aviso_de_titulo_nao_reconhecido_chega_ao_log`

`tests/test_synth.py`

* `test_item_nao_aplicado_em_aba_sintetizada_aparece_na_secao_2_do_log`

---

## Nota do relatório sobre C2992 — confirmada

O relatório desconfiava, e estava certo. Na planilha real:

```
C2992  DEMOLIÇÃO DE ALVENARIA DE PEDRA COM REMOÇÃO LATERAL   (A59351)
       I2391 PEDREIRO = 1,0000   I2543 SERVENTE = 8,7600
C1043  DEMOLIÇÃO DE ALVENARIA DE TIJOLOS S/ REAPROVEITAMENTO (A46442)
       I2391 PEDREIRO = 0,3000   I2543 SERVENTE = 3,0000
```

Os valores 0,3000/3,0000 usados como "esperado" no relatório são de **C1043**,
não de C2992. O item 2.3 do orçamento é C2992, e para C2992 o programa grava
1,0000 e 8,7600 — que é o que a tabela do arquivo diz. **Não há erro aqui**, e
nada foi alterado por causa desse item. Se o serviço correto for o de tijolos,
o que precisa mudar é o código no orçamento (C1043), não a automação.

---

## O que não mudou (regra 4 do prompt)

Nenhuma correção migrou para "gerar aba do zero". A edição continua sendo
in-place sobre o XML original: `SUMPRODUCT`, `ROUNDUP(.../50)`, `VLOOKUP` de
unidade, estilos, larguras e bordas seguem exatamente como estavam.
`orcauto check` confirma nos dois arquivos gerados:

```
OK: abas originais preservadas e pacote íntegro.
```
