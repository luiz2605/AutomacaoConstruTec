# Relatório: erros visuais e coeficientes — auditoria de 25/08/2026

Resposta ao relatório de erros, com a causa de cada item, a correção aplicada e
a evidência. Três dos quatro pontos tinham **a mesma causa raiz**.

---

## Resumo

| Item do relatório | Veredito | Causa |
|---|---|---|
| Divisões sumidas em INFRAESTRUTURA e SUPERESTRUTURA | **ERRO CONFIRMADO** | herança de estilo de fora da tabela |
| Divisão faltando na coluna VÉU DE POLIÉSTER (Impermeabilização) | **ERRO CONFIRMADO** | a mesma |
| Coeficientes fora do padrão (`0,8669`, `15`) | **VALOR CORRETO, FORMATO ERRADO** | a mesma |
| `#######` no TOTAL de PAREDES E PAINÉIS | **ERRO CONFIRMADO** | largura de coluna |

---

## 1. A causa raiz das divisões e do formato dos números

A aba gerada nasce como cópia do `MODELO BASE`, e o formato de cada célula é
copiado da linha de item do molde. O problema está no molde: **a linha 10 tem
células até a coluna S**, enquanto a tabela de insumos vai só até L.

```
A=134  B=132  C=367  D=159  E=133          <- identificação do serviço
F=158  G=158  H=158  I=158  J=158  K=158  L=158   <- colunas de insumo
M=305  N=305  O=305  P=155  Q=154  R=156  S=157   <- fora da tabela
```

Quando um tópico precisa de mais de 7 insumos, as colunas seguem para M, N, O…
e o código copiava o formato da célula que já estava naquela posição — os
estilos `305`, `155`, `154`, `156`, `157`, que são de **fora** da tabela: sem
borda e com outro formato numérico.

Daí os dois sintomas, que pareciam separados:

- **A divisória vertical some** de M a S, porque esses estilos não têm borda à
  direita. Da coluna T em diante voltava ao normal — ali o molde não tem célula
  nenhuma, e o código caía no caminho correto. É exatamente o trecho que o
  relatório aponta.
- **O coeficiente aparece como `15` em vez de `15,0000`**, porque o estilo `155`
  usa `General` e o `157` usa `0.00`, enquanto a tabela usa `#,##0.0000`.

INFRAESTRUTURA (36 colunas) e SUPERESTRUTURA (26) sofrem mais porque passam
bem da sétima coluna. IMPERMEABILIZAÇÃO tem 8 colunas — só uma além do molde,
e é por isso que ali o relatório notou apenas "um detalhe pequeno de divisão".

### Correção

`synth.py` passa a escolher o formato assim: **coluna acrescentada segue sempre
a coluna-modelo da tabela**, e nunca o que houver naquela posição no molde.

```python
def estilo_de(mapa, letra):
    padrao = mapa.get(model)          # última coluna de insumo do molde
    if letra in plan.appended:
        return padrao                 # acrescentada: ignora o que havia ali
    return mapa.get(letra) or padrao
```

Vale para as linhas de item e para a linha de TOTAL.

**Verificação**: 5.030 células de coeficiente e total, em 19 abas, conferidas
contra o padrão do molde — item `('-S--', '#,##0.0000', não-negrito)` e total
`('SSSS', '#,##0.00', negrito)`. **Zero fora do padrão.** Antes eram 7 colunas
irregulares em INFRAESTRUTURA, 7 em SUPERESTRUTURA e 1 em IMPERMEABILIZAÇÃO.

---

## 2. O `#######` em PAREDES E PAINÉIS

É a coluna **K, tijolo cerâmico furado**: 1.799,61 m² × 25 un/m² = **44.990,25**.
São 9 caracteres numa coluna de largura 10,42.

Pareceria caber, e é por isso que passou despercebido: a linha de TOTAL é
**negrito**, e a unidade de largura do Excel é medida na fonte normal. Nove
caracteres em negrito ocupam mais que 10,42 unidades.

O estouro só acontece no TOTAL porque ele é quantidade × coeficiente — ordens
de grandeza acima do coeficiente para o qual a coluna foi dimensionada
("25,0000" cabe folgado em 10,42).

### Correção

Depois de escrever a aba, cada coluna de insumo é medida: o maior coeficiente
(4 casas) e o total (2 casas), mais uma folga de 3 unidades para o negrito.
Se a largura atual não bastar, a coluna cresce — **nunca encolhe**, para
preservar o desenho onde ele já servia.

No caso relatado, K passou de 10,4 para 12,0. Nas 19 abas, **nenhuma coluna
ficou com risco de estouro**, e as que já eram largas o bastante não foram
tocadas.

A folga é configurável em `targets.folga_largura`.

---

## 3. Os coeficientes `0,8669` e `15`

**Os dois valores estão corretos.** O estranhamento veio do formato, não do
número — é o mesmo defeito do item 1.

**AREIA MEDIA = 0,8669** — vem direto de `COMPOSIÇÃO TAB 28!D11460`, na tabela
do C0843 (CONCRETO P/VIBR., FCK 25 MPa). São 0,8669 m³ de areia por m³ de
concreto, o que é o esperado para um traço com agregado adquirido.

**AJUDANTE = 15** — o relatório diz "AJUDANTE DE PEDREIRO", mas o insumo é o
**I0041, AJUDANTE DE CARPINTEIRO**. O valor é aninhado:

```
CPC001 (concreto armado, inclusive forma)
  └── C1401 (forma de tábuas)  coeficiente 10 m²/m³
        └── I0041 ajudante de carpinteiro  1,5 h/m²   [TAB 28!D59310]

10 × 1,5 = 15 h de ajudante de carpinteiro por m³
```

Faz sentido: o CPC001 embute a forma, e 10 m² de forma por m³ de concreto a
1,5 h/m² dá 15 h. A fórmula gravada na célula mostra a conta —
`='COMPOSIÇÃO TAB 28'!D59310*10` — então dá para auditar sem sair da planilha.

Com o formato corrigido, ele passa a aparecer como `15,0000`, no mesmo padrão
dos demais.

---

## 4. Sobre a busca do coeficiente

O relatório levanta a hipótese de desalinhamento de matriz (*off-by-one*). Não
é o caso, e a razão é estrutural: a busca não navega por índices de linha e
coluna. A `COMPOSIÇÃO TAB 28` é lida uma vez para um índice
`código → {insumo: (coeficiente, linha)}`, e uma composição só é reconhecida
quando o código forma o **título** da tabela — no arquivo real, `C0776` aparece
19 vezes, 18 delas como sub-item de outro serviço.

A gravação usa `resolver.coefficients_for(código, colunas)`, que só devolve
chave para insumo presente na resolução daquele serviço. Uma coluna cujo insumo
o serviço não consome não recebe nada — não por uma verificação, mas porque a
chave não existe. Há teste que amarra isso ao arquivo gravado, nos dois
sentidos.

Auditoria anterior: 199 coeficientes conferidos célula a célula contra a
`COMPOSIÇÃO TAB 28` em três abas, incluindo os aninhados, com zero divergência.

---

## 5. Sobre `pandas` e o modo de escrita

O `orcauto` nunca usou `pandas`, e não reescreve a pasta. A gravação é cirurgia
direta no pacote OOXML: as partes originais são copiadas byte a byte e só as
abas novas são geradas. Das 96 partes do arquivo, apenas quatro mudam — as do
registro das abas novas. `orcauto check` verifica isso a cada execução.

É uma abordagem mais conservadora que o modo de edição do `openpyxl`, que
reserializa a pasta inteira e descarta os valores em cache das fórmulas.
