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

**Embargos de declaração:** se houver embargos antes do recurso, o marco
inicial passa a ser a **intimação a respeito da decisão dos embargos**
(acolhidos, não acolhidos, rejeitados ou julgados), e não a intimação da
sentença original. O sistema:

1. procura uma intimação que referencie os embargos de declaração;
2. se não encontrar rotulada, usa somente quando existe **uma única**
   intimação posterior à decisão dos embargos; havendo mais de uma, não
   escolhe arbitrariamente e sinaliza a intimação como não localizada;
3. só usa a intimação da sentença quando **não há embargos**.

O evento do protocolo do recurso e o evento da intimação considerada
(sentença ou embargos) são identificados no processo e podem ser ajustados
na tela.

O **recorrente** é extraído do cabeçalho da petição, priorizando o nome que
antecede a expressão **“nos autos da Ação”**. Exemplo:

```text
BANCO BRADESCO S/A., nos autos da Ação de Indenização que lhe move
JOSEFA TEIXEIRA LIMA, por intermédio dos seus procuradores...
```

Nesse caso, o recorrente é **BANCO BRADESCO S/A**; Josefa é a recorrida.
Isso evita confundir o recorrido com o recorrente e faz a intimação
considerada ser a do polo correto (evento 31, de Bradesco, e não o evento
30, de Josefa).

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

Os dados privados (evento da intimação considerada — sentença ou embargos —,
data da intimação, último dia do prazo, decurso e recorrente) ficam:

- no log `projudi.certidoes`;
- na observação para juntada exibida na prévia;
- fora do corpo público da certidão.

A certidão é exibida em tela para impressão. Na própria prévia é possível
juntá-la ao Projudi e/ou realizar a intimação (veja abaixo).

## Layout

A certidão de **Recurso Inominado** usa o brasão do TJBA acima do cabeçalho,
no mesmo padrão dos ofícios e da Certidão de Prazo:

```text
https://projudi.tjba.jus.br/projudi/imagens/brasaoPetroBranco.jpg
```

O corpo da certidão foi ampliado para **12pt** (título 15pt, cabeçalho
13pt/11pt, rodapé 8pt) para melhor leitura na prévia e no Projudi.

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
- usa o mesmo fluxo de intimação das partes autoras/réus, passando o
  número interno do Projudi (`proc_projudi`, extraído da URL
  `DadosProcesso?numeroProcesso=...`);
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

A observação da movimentação é normalizada para **ISO-8859-1 (latin-1)**.
Travessão (`—`), aspas curvas e reticências são convertidos para
equivalentes ASCII antes do envio, e caracteres fora do latin-1 são
removidos. Isso evita os `?` no texto da observação no Projudi.

## Separação por origem

O campo `MovimentacaoRecord.origem` separa os registros:

```text
peticao      → certidões/procedimentos gerados pela fila/análise de petições
movimentacao → certidões/procedimentos gerados pela análise de movimentações
```

O dashboard de **Certidões** usa esse campo para montar os dois grupos.
O dashboard e a lista de **Movimentações** excluem `categoria='certidao'`,
de modo que todas as certidões ficam dentro do módulo de Certidões.

## Rastrear movimentações por RAG do despacho

No grupo **Certidões de despacho (RAG)**, dentro de Certidões > Movimentações,
existem duas ações:

- **Rastrear RAG do despacho (certidões)** — varre as últimas movimentações
  do Projudi, faz o match RAG e importa somente os cumprimentos cujo template
  é do tipo `certidao`;
- **Executar certidões pendentes** — executa apenas as certidões de RAG
  pendentes/falhas, sem executar os demais cumprimentos/movimentações.

Também é possível executar uma certidão individual pelo botão
**Executar certidão** no cartão correspondente.

A geração da certidão em si continua usando `CumprimentoService` e o
`Certidão de Prazo`/template indicado pela RAG; depois da execução, o
`MovimentacaoRecord` gerado entra em **Certidões vindas das movimentações**
com `origem='movimentacao'`.

## Modelos de Certidões

Rota:

```text
/projudi/certidoes/modelos/
```

Permite cadastrar, editar, pré-visualizar, duplicar e ativar/desativar
modelos de certidão sem usar o Django Admin.

Todo modelo criado aqui recebe:

```text
template_type = certidao
```

Para aparecer em **Gerar certidão via RAG**, ele precisa ser vinculado a uma
`RAGExample` em `suggested_templates`. O vínculo ainda é feito no Django
Admin (ou por script), mas o modelo em si é cadastrado na área de Certidões.

## Gerar certidão via RAG (documento no Projudi)

Na seção **Certidões de despacho (RAG)** existe o formulário:

```text
📄 Gerar certidão via RAG diretamente no Projudi
```

Ele recebe:

- processo;
- RAG (somente RAGs ativas com template de certidão vinculado);
- URL do Projudi (opcional; usa a URL já salva no processo);
- opção “Gerar novamente”.

O sistema cria um `CumprimentoRecord`, usa o template de certidão da RAG e
executa `CumprimentoService.executar_cumprimento`: o documento é montado,
inserido no Projudi e assinado.

Diferença importante:

- **Fila de Movimentações → Executar pendentes** registra apenas o Mov581;
- **Gerar certidão via RAG** gera o documento da certidão.

Novos modelos cadastrados como `DocumentTemplate` do tipo `certidao` e
vinculados a uma `RAGExample` aparecem automaticamente no seletor de RAG.

## Fila de Movimentações

Rota:

```text
/projudi/movimentacoes/fila/
```

A fila operacional mostra todos os `MovimentacaoRecord` pendentes/falhas,
inclusive os classificados como `certidao`. Cada item pode ser executado,
dispensado ou aberto nos detalhes.

Ações disponíveis:

- **Sincronizar Movimentações**;
- **Sincronizar somente hoje**;
- **Executar pendentes** (ou somente os de hoje quando o filtro está ativo);
- filtro **📅 Somente hoje**.

A separação por origem continua nos dashboards: as certidões aparecem em
**Certidões**, e os demais atos em **Movimentações**. A fila é a visão
operacional unificada para execução.

## Movimentações de hoje

A listagem do Projudi traz a data da movimentação. Os fluxos de
sincronização aceitam o parâmetro `hoje=1` para processar somente as
movimentações do dia:

- **Movimentações → Sincronizar somente hoje**;
- **Cumprimentos → Sincronizar somente hoje**;
- **Certidões → Certidões de despacho (RAG) → Rastrear RAG de hoje**.

Depois da sincronização, o filtro **📅 Hoje** mostra somente as
movimentações do dia, e o botão **Executar pendentes de hoje** executa
apenas essas movimentações.

Itens sem data na listagem são preservados para não perder movimento por
falha de leitura.

## Certidão de inexistência de custas da execução

Essa certidão fica na área de **Certidões**, dentro do grupo
**“Certidões vindas das movimentações”**, como tarefa específica:

```text
/projudi/certidoes/movimentacoes/custas/inexistencia/
```

Ela não é gerada pela varredura automática das movimentações; o usuário
a produz sob demanda para o processo informado.

Campos:

- processo;
- parte (opcional);
- movimentação (opcional);
- URL do processo no Projudi (opcional, usada para juntar);
- assinante.

Template:

```text
Certidão de Inexistência de Custas da Execução
```

O corpo público certifica que não existem custas processuais relativas à
execução pendentes de recolhimento. Depois da prévia, o botão
**Apenas juntar certidão** insere o documento no Projudi pelo mesmo fluxo
de juntada das demais certidões.

Outros comandos de custas (cálculo/cobrança, custas recolhidas ou
inexistência por decisão específica) podem ser adicionados como novas
tarefas nesse mesmo grupo.

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
