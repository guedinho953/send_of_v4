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

### Recurso Inominado
A contagem é feita a partir da **intimação da sentença ao recorrente**:

1. localiza a sentença e a respectiva intimação (DJEN/advogado/e-mail/AR);
2. para DJEN, usa a data de **disponibilização**;
3. calcula 10 dias úteis;
4. compara a **data de protocolo do recurso** com o último dia do prazo;
5. marca **TEMPESTIVO** ou **INTEMPESTIVO**.

O evento do protocolo do recurso é identificado no processo e pode ser
ajustado na tela.

### Demais tipos
1. Procura a primeira intimação **após a data de envio** da petição.
2. Se não localizar, usa a data de envio como fallback.

## Geração

O botão **Gerar certidão** monta o HTML e salva em `GeneratedDocument`.

Para **recurso inominado**, a tela permite escolher:

- **Tempestivo — pedido de gratuidade**;
- **Tempestivo — preparo integral**;
- **Intempestivo**.

O corpo público segue o modelo do Ofício Circular nº 034/2015/COJE, com
`TEMPESTIVO`, `PREPARADO` ou `INTEMPESTIVO` em negrito.

Os dados privados (evento da intimação da sentença, data da intimação,
último dia do prazo, decurso e recorrente) ficam:

- no log `projudi.certidoes`;
- na observação para juntada exibida na prévia;
- fora do corpo público da certidão.

A certidão é exibida em tela para impressão. Na própria prévia é possível
juntá-la ao Projudi e/ou realizar a intimação (veja abaixo).

## Juntar a certidão e intimar

Na prévia da certidão de **Recurso Inominado** existem as ações:

- **Apenas juntar certidão** — insere a certidão no Projudi via Mov581 e
  assina o documento;
- **Juntar certidão + intimar** — junta a certidão e, na sequência, faz a
  intimação conforme a situação;
- **Apenas intimar** — aparece quando a certidão já foi juntada.

### Tempestivo — preparo integral ou gratuidade

Nos dois casos, intima-se o **recorrido** para contrarrazões:

```text
Intime(m)-se o(s) recorrido(s) para que, querendo, apresente(m)
contrarrazões ao Recurso Inominado (evento XX), no prazo de
10 dias úteis.
```

- `prazo_intimacao='3'` (10 dias), `motivo_intimacao='3'`;
- `polo_intimacao='autores' | 'res'`;
- o número do evento é extraído do corpo da certidão
  (“recurso inominado interposto no evento XX”).

O sistema sugere o polo oposto ao recorrente quando ele está cadastrado
como parte no processo; sem cadastro, sugere **Autoras/Autores**.

### Intempestivo

- Intima-se o **recorrente** para ciência da **INTEMPESTIVIDADE** do
  recurso interposto/apresentado, conforme certidão em anexo;
- prazo padrão de **5 dias úteis** (código 2), ajustável para 10 ou
  15 dias na prévia;
- o polo deve ser o do **recorrente** (autoras/autores ou réus/rés).

Conversão de prazo usada no Projudi:

```text
5 dias úteis  → prazo_intimacao='2'
10 dias úteis → prazo_intimacao='3'
15 dias úteis → prazo_intimacao='4'
```

São duas movimentações no Projudi: a juntada da certidão e a intimação.
Se a certidão for juntada mas a intimação falhar, a certidão permanece
marcada como juntada e a prévia salva é reaberta automaticamente
(`/projudi/certidoes/peticoes/<id>/preview/`) para usar o botão
**Apenas intimar** e repetir somente a intimação.

A fila envia a URL do processo no Projudi (`DadosProcesso?numeroProcesso=...`),
que é salva em `Process.projudi_url`. É dessa URL que a juntada extrai o
número interno do processo; sem ela, o Projudi retorna
**“Número Projudi não encontrado”**.

## Assinatura

A fila de petições tem um seletor de assinatura no topo:

- **Ivan Guedes da Silva — Secretário em Substituição** (padrão);
- **Ivan Guedes da Silva — Servidor de Secretaria 2**;
- **Mauro Emílio Viana da Silva Moreira — Secretário**;
- **Outro** (nome e cargo digitados).

A escolha vale para todas as certidões geradas naquela página. O template
usa `{{ servidor }}` e `{{ servidor_cargo }}`; portanto não fica mais fixo
como “Servidor Secretaria 2”.

## Desempenho

A primeira leitura consulta a fila e os processos no Projudi e pode levar
até ~30 segundos. O resultado fica em cache por 5 minutos. O botão
**Atualizar fila** força nova leitura.
