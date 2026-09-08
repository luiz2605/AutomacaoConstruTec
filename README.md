# orcauto

Cruza um **orçamento analítico em PDF** com as **composições de custo** de uma
planilha Excel e gera versões automatizadas das abas de levantamento, mantendo
o arquivo original intacto.

Para cada item do orçamento, a ferramenta localiza a composição correspondente,
extrai o coeficiente de cada insumo rastreado pela aba de destino e grava uma
**fórmula que aponta para a linha de origem** — e não um número solto. Se a
composição mudar, o levantamento acompanha.

```
='COMPOSIÇÃO TAB 28'!D11462          coeficiente direto
='COMPOSIÇÃO TAB 28'!D55622*0.3      coeficiente vindo de uma sub-composição
```

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Requer Python 3.11+ (a leitura da configuração usa `tomllib`, da biblioteca padrão).

## Uso

```bash
# o que a ferramenta enxerga no arquivo, sem gravar nada
orcauto inspect --xlsx LEVANTAMENTO.xlsx --pdf ORCAMENTO.pdf

# gera o arquivo com as abas (AUTO)
orcauto run --xlsx LEVANTAMENTO.xlsx --pdf ORCAMENTO.pdf \
            --out "LEVANTAMENTO (AUTO).xlsx" \
            --config config/hospital-veterinario.toml

# confere que o gerado não tocou nas abas originais
orcauto check --original LEVANTAMENTO.xlsx --generated "LEVANTAMENTO (AUTO).xlsx"
```

Como biblioteca:

```python
from orcauto import Config, run

resultado = run("LEVANTAMENTO.xlsx", "ORCAMENTO.pdf", "saida.xlsx",
                Config.load("config/hospital-veterinario.toml"))
print(resultado.report)
```

## As duas regras que sustentam o resultado

**1. O código só vale como título de tabela.** Um código como `C0776` aparece
19 vezes na planilha de composições — 18 delas como sub-item de outro serviço,
com o coeficiente daquele contexto. Só uma é o **título** da tabela dele.
A ferramenta aceita exclusivamente essa, o que elimina o falso positivo mais
comum desse cruzamento.

**2. Coeficiente aninhado é multiplicado, não copiado.** Quando o insumo não
está direto na composição, mas dentro de um serviço que ela consome, o valor é
o do sub-item vezes o coeficiente do serviço. A fórmula gravada preserva os
dois números separados, então dá para auditar a conta na própria célula.

## Como as linhas são decididas

| Modo | Quando | O que grava |
|---|---|---|
| `ATUALIZADA` | a linha já tem o mesmo código do item | só os coeficientes; a quantidade da aba é preservada |
| `SUBSTITUI` | a linha tem um código que **não consta em nenhum item do orçamento** e descreve o mesmo serviço | assume o item do orçamento por inteiro |
| `NOVA` | o item não tem contrapartida na aba | grava em linha livre |

`SUBSTITUI` é o que evita dupla contagem: sem ela, a linha legada e a linha do
orçamento somariam juntas no TOTAL. A atribuição é feita **globalmente**, da
maior para a menor semelhança — não na ordem do PDF —, senão um item parecido,
lido antes, tomaria a linha do item que de fato corresponde a ela.

Tudo isso é ajustável em `[rules]`: `substitution_enabled`, `substitution_force`,
`substitution_block`, `quantity_policy` e `quantity_override`.

## Por que não usar o openpyxl para gravar

Reabrir e salvar a pasta inteira com openpyxl descarta os **valores em cache**
de todas as fórmulas, mexe em vínculos externos (`[2]TAB.28!…`) e pode perder
detalhes de formatação.

`orcauto` faz cirurgia direta no pacote OOXML: as partes originais são copiadas
byte a byte e só as abas novas são geradas, como cópias exatas das de origem
com as células alteradas cirurgicamente. Estilos, cores, larguras de coluna,
mesclagens, imagens, cabeçalho/rodapé e vínculos externos ficam preservados por
construção — não por cuidado.

No arquivo real, as únicas partes originais que mudam são as quatro do registro
das abas novas: `[Content_Types].xml`, `xl/workbook.xml`,
`xl/_rels/workbook.xml.rels` e `xl/styles.xml` (este só recebe acréscimos ao
final, sem alterar nenhum índice existente). É o que o `orcauto check` verifica.

## Nada é fixado em código

A âncora de cada aba de destino é a linha de **TOTAL**: a fórmula
`SUMPRODUCT($E$10:$E$17;F10:F17)` informa, de uma vez, qual é a coluna de
quantidade e quais linhas formam o bloco de serviços. O resto é deduzido para
cima — cabeçalho, linha dos códigos de insumo e colunas rastreadas.

O casamento tópico → aba é por token, aceitando prefixo: liga
`14 REVESTIMENTO` a `REVESTIMENTOS` e `5 PAREDES E PAINÉIS` a `PAREDES`, sem
aceitar coincidências curtas (a aba `RES` não casa com `SERVIÇOS PRELIMINARES`).
Havendo dúvida, `targets.topic_map` fixa o destino.

## Estrutura

```
src/orcauto/
  textutil.py       normalização de texto e números no padrão brasileiro
  config.py         configuração (TOML/JSON) com padrões utilizáveis
  pdf_budget.py     leitura do orçamento — parser puro + adaptador pdfplumber
  compositions.py   índice das tabelas de composição (regra do título)
  resolver.py       coeficiente de um insumo, inclusive aninhado
  layout.py         detecção automática do layout da aba de destino
  planner.py        decisão de ATUALIZADA / SUBSTITUI / NOVA
  synth.py          síntese de aba nova a partir do molde
  ooxml.py          cirurgia no pacote .xlsx
  report.py         relatório de terminal e aba LOG
  pipeline.py       orquestração
  cli.py            run / inspect / check

webapp/
  service.py        processar_orcamento() — sem HTTP, sem CLI
  jobs.py           fila em memória, execução em thread, expiração
  app.py            rotas FastAPI
  templates/        página única
```

## Testes

```bash
pytest              # 146 testes, ~5s
```

A suíte é autossuficiente: monta uma pasta Excel e um orçamento sintéticos do
zero, com layout **diferente** do arquivo real (outras linhas, outras colunas),
justamente para provar que nada depende de posições fixas. Nenhum teste precisa
do PDF ou da planilha do projeto.

O fixture inclui as armadilhas que a ferramenta precisa evitar: um código que
aparece como sub-item com coeficiente diferente do da sua própria tabela, um
insumo que chega por dois caminhos ao mesmo tempo, e uma linha legada parecida
com um item do orçamento.

## Limitação conhecida

O `fullCalcOnLoad` faz o Excel recalcular tudo ao abrir. Validar isso por linha
de comando com o LibreOffice não é viável em pastas muito grandes: na planilha
real (65 mil linhas, ~4.300 composições) o recálculo headless não termina nem
em 25 minutos. A conferência estrutural — `orcauto check` mais a suíte de
testes — cobre integridade do pacote e preservação das abas originais, mas não
substitui abrir o arquivo no Excel uma vez.

## Documentos de apoio

| Arquivo | O que traz |
|---|---|
| `AUDITORIA.md` | auditoria de 17/08: erros apontados pelo Luiz, com evidência |
| `RELATORIO-ERROS-VISUAIS.md` | bordas perdidas, `#######` e conferência de coeficientes |
| `CORRECOES-V3.md` | bugs A/B/C/D do relatório v3: causa raiz, prova antes/depois e testes |

### Opções que mudam o resultado do levantamento

`compositions.expand_subservices` decide o que acontece quando uma composição
consome outro serviço que tem composição própria (a alvenaria que consome
argamassa, a forma que consome fabricação + aplicação):

* `true` (padrão) — o sub-serviço é aberto e só o insumo-folha vira coluna;
* `false` — o sub-serviço vira uma coluna com o coeficiente de primeiro nível.

As configurações reais do escritório usam `false`: é como a planilha feita à
mão trabalha (a aba `INFRAESTRUTURA` original tem uma coluna rotulada `C3129`)
e é o que evita a dupla contagem da mão de obra. Ver `CORRECOES-V3.md`, bug B.

## Autenticação da aplicação web

O endereço é público, então as rotas que mostram ou entregam dado de orçamento
(`/`, `/processar`, `/estado/{id}`, `/baixar/{id}`) exigem **HTTP Basic**.
`GET /saude` fica aberta de propósito: é o health check do Render e não devolve
nada além do estado do serviço.

| Variável | Obrigatória | Padrão |
|---|---|---|
| `ORCAUTO_USUARIO` | não | `orcamentos` |
| `ORCAUTO_SENHA` | **sim** | — |

Sem `ORCAUTO_SENHA` o servidor responde **503** ("Autenticação não configurada
no servidor") em vez de 401 — um deploy mal configurado diz o que está errado,
e em nenhuma hipótese fica aberto. Credencial errada responde 401 com
`WWW-Authenticate: Basic`, que é o que faz o navegador abrir a caixa de login.

Use senha **só com caracteres ASCII**: o cabeçalho Basic é decodificado como
ASCII, então uma senha acentuada nunca chega inteira ao servidor.

Local:

```bash
export ORCAUTO_USUARIO=orcamentos
export ORCAUTO_SENHA='uma-senha-boa'
uvicorn webapp.app:app --reload
```

No Render, `ORCAUTO_SENHA` está declarada em `render.yaml` com `sync: false`:
o valor é digitado no painel e nunca entra no repositório. Ver `.env.example`.

## Relato de problema pela tela

Nas telas de resultado e de erro aparece um link **"Relatar um problema"**: o
funcionário descreve o que viu e o texto vai por e-mail para o suporte, sem
precisar saber endereço de ninguém. Junto vai o contexto que ele não teria como
digitar — usuário, `job_id`, nome do arquivo enviado, estado do processamento e
a mensagem de erro exata, quando houve.

O PDF **não** é anexado: ele é apagado do servidor assim que o processamento
termina (`jobs.py::executar`), então não há o que anexar. Se o suporte precisar
do arquivo, pede ao funcionário.

| Variável | Obrigatória | Padrão |
|---|---|---|
| `ORCAUTO_SMTP_HOST` | sim | — |
| `ORCAUTO_SMTP_PORTA` | não | `465` (SSL) |
| `ORCAUTO_SMTP_USUARIO` | sim | — (também é o remetente) |
| `ORCAUTO_SMTP_SENHA` | sim | — |
| `ORCAUTO_EMAIL_SUPORTE` | sim | — (destinatário) |

Faltando qualquer uma delas o recurso simplesmente não é oferecido: o link não
aparece na tela e a rota `/relatar` responde **503**. O resto da aplicação segue
funcionando normalmente. Quando o envio é tentado e o servidor de e-mail recusa
ou não responde, a resposta é **502** — falha temporária, não erro de quem
escreveu.

Na maioria dos provedores use uma **senha de aplicativo**, não a senha da conta.

## Dois formatos de PDF

O programa reconhece sozinho qual dos dois formatos chegou, olhando o cabeçalho
da tabela na primeira página. O funcionário arrasta o PDF e pronto — não existe
seleção de formato na tela.

| | **Orçamento Analítico** | **Planilha Orçamentária** |
|---|---|---|
| Colunas | `Ordem \| Código \| Descrição \| Unidade \| Quantidade \| Preço \| Total` | `Item \| Descrição \| Un. \| Quant. \| Preço \| Subtotal \| Perc.` |
| Coluna Código | sim | **não** |
| Valor do tópico | na própria linha do tópico | numa linha `SUBTOTAL`, depois dos itens |
| Numeração | `3.2` | `2.01` e `4,01` — ponto e vírgula no mesmo arquivo |
| Casamento | por código | por descrição |
| Função | `parse_budget` | `parse_budget_planilha_excel` |

São dois leitores separados de propósito. O analítico está em uso e validado; a
suíte tem um teste dedicado provando que ele sai **idêntico** ao que saía antes
de o segundo existir.

O que os dois compartilham é `normalize_lines`, que conserta dois artefatos da
exportação: o número partido em dois tokens (`1` + `5.400,82` = 15.400,82, com
trava de proximidade em x para não juntar colunas distintas) e o `R$`
intercalado entre os números. No Orçamento Analítico real isso não altera uma
linha sequer, então roda nos dois sem risco.

### Casamento por descrição

Sem coluna Código, o item é ligado à composição pela semelhança das descrições
(`matching.py`), antes do planejamento — assim `planner`, `synth` e `resolver`
seguem trabalhando só por código.

| Faixa | O que acontece |
|---|---|
| ≥ `description_match_high` (0,85) | aceita direto |
| entre o mínimo e o alto | aceita e marca **CONFERIR** na seção 9 do `LOG AUTO` |
| < `description_match_min` (0,60) | não aplica; cai em "composição não encontrada" |

`rules.description_match` controla quando isso vale: `"sem_codigo"` (padrão) só
para item que chega sem código nenhum — é o que torna a Planilha Orçamentária
utilizável **sem** tocar no formato analítico, onde todo item tem código e o
resultado já está validado. `"sempre"` também tenta quando o código existe mas
não está no índice; `"nunca"` desliga.
