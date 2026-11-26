# Certidões da fila de petições

Fonte: `https://projudi.tjba.jus.br/projudi/listagens/JuntadaPeticao`

Rota no sistema:

```text
/projudi/certidoes/peticoes/
```

## Tipos e prazos

| Tipo na fila | Certidão | Prazo |
|---|---|---|
| Recurso Inominado | Recurso Inominado | 10 dias úteis |
| Contrarrazões ao Recurso Inominado | Contrarrazões | 10 dias úteis |
| Impugnação / Cumprimento de Sentença | Impugnação/Cumprimento | 15 dias úteis |
| Impugnação / Decurso do Prazo da Penhora | Impugnação/Penhora | 15 dias úteis |

## Contagem — Lei 11.419/2006

A contagem usa o meio de intimação localizado no processo:

| Meio | Regra |
|---|---|
| DJEN / domicílio eletrônico | `eletronico` — 1º dia da intimação e 1º dia útil seguinte não contam |
| Advogado | `advogado` — dia do recebimento não conta |
| E-mail | `email` — regra padrão |
| AR / Correios | `ar` — regra padrão |
| Mandado | `mandado` — regra padrão |

Função: `CumprimentoService.contar_prazo_por_fluxo`.

## Data de início

1. Procura a primeira intimação **após a data de envio** da petição.
2. Para DJEN, usa a data de **disponibilização**, se estiver no texto.
3. Se não localizar nenhuma intimação, usa a **data de envio** como fallback
   e avisa na tela: “Data de envio (intimação não localizada no processo)”.

## Geração

O botão **Gerar certidão** monta o HTML usando o template
**Certidão de Prazo** (com `recorrente`, quando encontrado no nome do
documento) e salva em `GeneratedDocument`.

A certidão é exibida em tela para impressão. A inserção automática no
Projudi/Mov581 é uma etapa separada, que pode ser adicionada depois.
