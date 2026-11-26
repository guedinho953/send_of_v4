# Dashboard de Certidões

Rota: `/projudi/certidoes/dashboard/`

Separa as certidões em duas origens:

| Origem | Fonte | Regra |
|---|---|---|
| Análises de petições | `MovimentacaoRecord` | `categoria='certidao'` e `rag_example` preenchido |
| Movimentações | `MovimentacaoRecord` | `categoria='certidao'` e `rag_example` vazio |

## Por que `rag_example`?

- Quando a certidão nasce da análise de uma decisão/petição pela RAG, o
  `MovimentacaoRecord` é criado com `rag_example` apontando para o exemplo.
- Quando nasce da varredura direta de movimentações do Projudi, o registro
  fica sem `rag_example`.

## Filtros

- `?origem=peticao`
- `?origem=movimentacao`
- `?status=pendente|cumprido|falha|dispensado`

## Observação

Se o dashboard de certidões existente no seu ambiente usar outro critério
para separar as origens (por exemplo, `CumprimentoRecord` em vez de
`MovimentacaoRecord`), ajuste `projudi/certidao_views.py` para o campo
correspondente. A estrutura visual já está pronta com as duas seções.
