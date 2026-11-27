# RAG — despacho de certificação dos embargos à execução

> Referência de texto para cadastro/matching. O foco são os **dois primeiros
> parágrafos** do despacho; os parágrafos seguintes (contadoria, vista e
> sentença) não integram a RAG desta certidão.

## Texto de referência

> **DESPACHO**
>
> Certifique-se o cartório acerca da tempestividade dos embargos (art. 525,
> caput, do CPC) e a integral segurança do Juízo, devendo ser observado o
> valor executado e o valor depositado/penhorado (Enunciado n. 117 do
> FONAJE).
>
> Se for o caso, intime-se o(a) embargado(a) na pessoa de seu advogado(a)
> ou, não o tendo, pessoalmente, para, querendo, no prazo de 15 (quinze)
> dias, apresentar manifestação acerca dos embargos à execução.

## Como a RAG deve ser cadastrada

Sugestão de campos:

- **despacho_ato**:
  `CERTIFIQUE-SE TEMPESTIVIDADE DOS EMBARGOS E SEGURANÇA DO JUÍZO - ART. 525 CPC - FONAJE 117 - INTIME-SE EMBARGADO - 15 DIAS`
- **despacho_observacao**: apenas os dois primeiros parágrafos acima.
- **sequencia_cumprimento**: depende da decisão operacional. Para evitar
  intimação automática indevida (o despacho só intima “se for o caso”),
  **não** cadastre um passo `intimacao_eletronica` cego. O fluxo recomendado
  é:

1. a RAG identifica o despacho e cria a tarefa de certificação;
2. o cartório gera a certidão pela tela
   `/projudi/certidoes/movimentacoes/impugnacao-embargos/`;
3. se a certidão concluir **TEMPESTIVA**, usa-se **Juntar + intimar** no
   detalhe da certidão. O sistema intima o embargado/exequente para
   manifestação em 15 dias;
4. se **INTEMPESTIVA**, usa-se apenas **Juntar certidão**, sem intimação.

Exemplo de passo de tarefa (não executa a certidão automaticamente):

```json
[
  {
    "tipo": "movimentacao",
    "codigo_mov": "581",
    "descricao_mov": "Certidão de Tempestividade e Segurança do Juízo",
    "observacao": "Certifique-se a tempestividade dos embargos (art. 525, caput, do CPC) e a integral segurança do Juízo, observados o valor executado e o valor depositado/penhorado (Enunciado n. 117 do FONAJE). Se tempestivos, intime-se o(a) embargado(a) para manifestação em 15 dias.",
    "observacao_prazo": false,
    "expede_certidao_prazo": false
  }
]
```

> Não usar `sequencia_cumprimento` vazia com RAG ativa: pelo desenho atual,
> isso libera o fluxo dinâmico e pode expedir atos não desejados.

## O que a certidão aproveita do despacho

O texto público da certidão já incorpora:

- prazo de **15 (quinze) dias úteis** para pagamento;
- referência ao **art. 525, caput, do CPC**;
- conclusão **TEMPESTIVA/INTEMPESTIVA**;
- segurança do juízo (integral, depósito parcial ou não houve);
- observação do **valor executado** e do **valor depositado/penhorado**
  (Enunciado n. 117 do FONAJE);
- intimação do embargado em 15 dias, somente quando tempestivos, no fluxo
  **Juntar + intimar**.
