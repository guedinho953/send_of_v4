# Prazo DJEN semiautomático

Calcula a cadeia:

```
disponibilização (data bruta)
   ↓ (1º dia útil seguinte)
publicação no DJEN
   ↓ (1º dia útil seguinte; exclui a publicação)
1º dia do prazo
   ↓ (N dias úteis, incluindo o 1º dia)
último dia do prazo
   ↓ (1º dia útil seguinte)
trânsito em julgado
```

Base: Lei 11.419/2006, art. 5º, §3º, e Resolução CNJ 455/2022 —
considera-se publicação o primeiro dia útil seguinte ao da disponibilização,
sem deslocar a disponibilização.

## Tipos iniciais

| `--tipo` | Prazo | Certidão |
|----------|-------|----------|
| `inominado` | **10 dias úteis** | Trânsito em julgado |
| `contrarrazoes_inominado` | **10 dias úteis** | Prazo |
| `cumprimento_sentenca` | **15 dias úteis** | Prazo |
| `pagamento_impugnacao_penhora` | **15 dias úteis** | Prazo |

## Comando

```bat
.venv\Scripts\python.exe manage.py prazo_djen --tipo inominado --disponibilizacao 28/11/2026
```

Opções:

| Opção | Efeito |
|-------|--------|
| `--disponibilizacao` | Data bruta da disponibilização (obrigatória) |
| `--tipo` | Tipo da tabela acima (default `inominado`) |
| `--prazo` | Sobrescreve os dias do tipo |
| `--protocolo` | Data do protocolo do recurso (calcula tempestividade) |
| `--processo` | Número CNJ (para a certidão) |
| `--parte` | Nome da parte (para a certidão) |
| `--servidor` | Nome do servidor que assina |
| `--saida` | Caminho do HTML (default `var/certidao_prazo_<data>.html`) |
| `--sem-html` | Só calcula e mostra a memória de contagem |
| `--origem` | `peticao` ou `movimentacao` (default: petição para recurso/contrarrazões) |
| `--peticao-documento` | Nome do PDF da petição (para a aba Petições) |
| `--peticao-url` | URL do PDF da petição (para a aba Petições) |
| `--nao-registrar` | Teste: não grava no dashboard |

Exemplos:

```bat
REM Recurso inominado protocolado no último dia → TEMPESTIVO
.venv\Scripts\python.exe manage.py prazo_djen ^
  --tipo inominado --disponibilizacao 28/11/2026 ^
  --protocolo 15/12/2026 ^
  --processo 0002803-76.2025.8.05.0191 --parte "JOSE MARCELO BISPO DA SILVA"

REM Protocolo no dia seguinte → INTEMPESTIVO
.venv\Scripts\python.exe manage.py prazo_djen ^
  --tipo inominado --disponibilizacao 28/11/2026 ^
  --protocolo 16/12/2026 --sem-html

REM Cumprimento de sentença (15 dias úteis)
.venv\Scripts\python.exe manage.py prazo_djen ^
  --tipo cumprimento_sentenca --disponibilizacao 28/11/2026
```

O comando gera um **preview HTML** da certidão em `var/`; ele **não expede** nada
no Projudi. O usuário confere a memória de contagem e assina.

## Certidão de recurso inominado (busca automática)

O comando abaixo percorre as movimentações/petições do processo, localiza o
**recurso inominado** e a **disponibilização no DJEN** anterior a ele, calcula
o prazo e gera a certidão. Você informa apenas o processo e o preparo:

```bat
python manage.py certidao_inominado ^
  --processo 0000000-00.0000.8.05.0191 ^
  --preparo gratuidade
```

`--preparo` aceita:

| Valor | Texto da certidão |
|-------|-------------------|
| `gratuidade` | TEMPESTIVO. Não houve o PREPARO, em razão do pedido de assistência judiciária gratuita. |
| `completo` | TEMPESTIVO e regularmente PREPARADO. |
| `incompleto` / `insuficiente` | TEMPESTIVO, porém o PREPARO está INCOMPLETO. |
| `nao_pago` | TEMPESTIVO, porém NÃO HOUVE O PREPARO. |

Se o recurso for **INTEMPESTIVO**, o preparo não é verificado/mencionado.

A tempestividade é apurada pela intimação **do recorrente**. O comando tenta
identificar quem recorreu no PDF da petição (ou use `--recorrente`), filtra o
DJEN pelo nome e usa a comunicação dirigida a essa parte. A linha `PARA` da
certidão mostra `Promovente: ... / Promovido: ...`; se as partes não forem
localizadas, a linha é omitida.

| Opção | Efeito |
|-------|--------|
| `--recorrente` | Nome do recorrente, quando não for possível ler no PDF |
| `--peticao-url` | URL do PDF da petição (para identificar o recorrente) |
| `--parte` | Sobrescreve o texto da linha `PARA` |

Se a busca automática não achar o evento/data, use os sobreposições:

```bat
python manage.py certidao_inominado --processo ... --preparo completo ^
  --evento-recurso 50 --data-disponibilizacao 28/11/2026 ^
  --data-protocolo 15/12/2026
```

Também é possível informar `--url` com a URL `DadosProcesso` do Projudi.

## Fila de petições (`JuntadaPeticao`)

A página `https://projudi.tjba.jus.br/projudi/listagens/JuntadaPeticao` lista
as petições aguardando juntada. O comando abaixo varre essa fila, identifica
os **recursos inominados** (pelo tipo da juntada, pelo nome do PDF e,
opcionalmente, pelo conteúdo do PDF) e mostra os comprovantes/guias para
conferência manual:

```bat
python manage.py peticoes_inominado --listar
```

Para gerar a certidão de uma petição da fila, informe o CNJ e o preparo:

```bat
python manage.py peticoes_inominado ^
  --processo 0002888-28.2026.8.05.0191 ^
  --preparo gratuidade
```

O comando usa a **data de envio** da petição como data de protocolo, abre o
processo e busca o DJEN anterior a essa data. Ele **não executa**
“Movimentar/Juntar” no Projudi: apenas lê a fila, gera o preview e registra o
controle no dashboard.

| Opção | Efeito |
|-------|--------|
| `--listar` | Só lista as petições de recurso inominado |
| `--processo` | CNJ da petição a certificar |
| `--preparo` | `gratuidade`, `completo`, `incompleto`/`insuficiente` ou `nao_pago` |
| `--verificar-pdf` | Baixa a petição e confirma “RECURSO INOMINADO” no texto quando o tipo/nome não bastam |
| `--data-protocolo` | Sobrescreve a data de envio |
| `--recorrente` | Nome do recorrente, se não for possível ler no PDF |
| `--peticao-url` | URL do PDF da petição (default: a da fila) |
| `--nao-registrar` | Teste: gera o preview sem gravar no dashboard |
| `--saida` | Caminho do HTML do preview |

O comando identifica o recorrente no PDF da petição e usa a intimação/DJEN
dirigida a ele. Se não conseguir, informe `--recorrente`.

Os **comprovantes/guias não definem o preparo**: o comando apenas os lista.
Quem confere os valores é o usuário, que informa o `--preparo`.

## Separação por origem: petições × movimentações

As certidões são separadas em duas abas/dashboards:

| Rota | Conteúdo |
|------|----------|
| `/projudi/certidoes/` | Todas as certidões (visão geral) |
| `/projudi/certidoes/peticoes/` | Certidões vinculadas à fila de petições (`JuntadaPeticao`) |
| `/projudi/certidoes/movimentacoes/` | Certidões vinculadas a movimentações/prazos do processo |

O campo `PrazoDjenRecord.origem` guarda `peticao` ou `movimentacao`.

- `peticoes_inominado` e `certidao_inominado` registram automaticamente
  `origem='peticao'`, com o nome e a URL do PDF da petição.
- `prazo_djen` usa `movimentacao` por padrão; para recurso/contrarrazões,
  usa `peticao` automaticamente. Também é possível forçar com `--origem`.
- A aba Petições mostra o documento da petição e o link para o PDF.
- A aba Movimentações mostra os prazos/decursos calculados a partir de
  eventos e intimações.

A migração `projudi/0018` adiciona `origem`, `peticao_documento` e
`peticao_url` e marca os registros antigos de recurso/contrarrazões como
`peticao`.

## Certidão de decurso de pagamento voluntário (15 dias)

A certidão de decurso apura o prazo de **15 dias úteis** para o pagamento
voluntário no cumprimento de sentença/execução:

1. localiza o despacho que determinou o pagamento em 15 dias
   (automático ou `--evento`);
2. identifica o executado/promovido (ou `--executado`);
3. localiza a intimação desse despacho para o executado;
4. calcula os 15 dias úteis conforme o meio de intimação;
5. só gera a certidão depois do **decurso**; antes disso, informa a data.

Pela tela:

```
/projudi/certidoes/movimentacoes/decurso-pagamento/
```

Ou pelo comando:

```bat
python manage.py certidao_decurso_pagamento ^
  --processo 0000000-00.0000.8.05.0191
```

Opções úteis:

| Opção | Efeito |
|-------|--------|
| `--evento` | Número do despacho, se a busca automática não achar |
| `--executado` | Nome do executado, se houver dúvida |
| `--url` | URL `DadosProcesso` do Projudi |
| `--nao-registrar` | Teste: gera o preview sem gravar no dashboard |
| `--saida` | Caminho do HTML do preview |

A certidão é registrada na aba **Movimentações**, com status **DECURSO** e
o evento do despacho em `evento_origem`. O template é
`Certidão de Decurso de Prazo para Pagamento Voluntário`, criado pela
migração `processes/0024` e revisado pela `processes/0025`.

O texto público segue o modelo:

> Certifico, para os devidos fins, o **DECURSO DO PRAZO** de 15 (quinze)
> dias úteis para cumprimento voluntário da sentença/impugnação pelo(a)(s)
> executado(a)(s), referente à **intimação eletrônica (DJEN)**. Publicação
> em DD/MM/AAAA; início do prazo em DD/MM/AAAA; decurso em DD/MM/AAAA.

A assinatura padrão é **IVAN GUEDES DA SILVA / Servidor Secretaria 2**,
com a opção de trocar o subscritor na tela.

## Fila de petições com escolha manual

A fila `JuntadaPeticao` também pode ser aberta pela tela:

```
/projudi/certidoes/peticoes/fila/
```

Cada linha mostra processo, data de envio, PDF da petição, comprovantes e a
**sugestão** de certidão. A sugestão vem do tipo/nome do PDF, mas **não é
automática**: você escolhe a certidão no seletor.

Opções da tela:

- **Certidão**: Recurso Inominado (10), Contrarrazões (10),
  Impugnação/Cumprimento (15), Impugnação/Penhora (15) ou Decurso de
  Pagamento (15);
- **Preparo**: para recurso inominado (gratuidade, completo,
  incompleto/insuficiente ou não pagou);
- **Intimação**: para contrarrazões/impugnação, informe o **evento da
  decisão/recurso**; o sistema localiza automaticamente a intimação
  posterior (ou usa o próprio evento, se ele já for a intimação). A data
  manual fica como **fallback**, para quando a localização automática não
  encontrar. Para decurso, a data também é automática, com fallback manual;
- **Parte a intimar**: opcional, ajuda a desambiguar quando há mais de uma
  intimação após o evento;
- **Ação**: por ora **Gerar certidão**. As ações **Juntar** e
  **Juntar + intimar** aparecem como “em breve” e serão habilitadas na
  próxima etapa.

Ao escolher **Decurso de Pagamento** no seletor, aparecem no próprio card os
campos **Evento do despacho (opcional)**, **Executado(a) (opcional)** e
**Assinatura da certidão**. O sistema usa o evento informado ou localiza o
despacho automaticamente, confere a intimação do executado e só gera a
certidão se o prazo já tiver decorrido. Se ainda não decorreu, mostra a data
do decurso e não gera. Tudo na mesma página da fila.

A tela gera a certidão, registra na aba **Petições** e abre o detalhe com o
preview. Nada é juntado/movimentado no Projudi nesta etapa.

## Dashboard de certidões

Acesse **Certidões** no menu ou:

```
http://127.0.0.1:8000/projudi/certidoes/
```

O dashboard mostra:

- abas **Todas / Petições / Movimentações**, com contadores por origem;
- atalho **Fila de petições** na aba Petições e **Nova certidão de decurso**
  na aba Movimentações;
- cards de **Total / Tempestivas / Intempestivas / Sem protocolo**;
- filtros por status, tipo e busca (processo, parte ou motivo);
- tabela com processo, parte, tipo, último dia, protocolo, preparo,
  status e as **razões** (resumidas);
- botão **Detalhe** com a memória completa e os dias contados/excluídos;
- botão **Preview** para abrir o HTML da certidão.

A certidão leva apenas a conclusão e as datas essenciais. As razões completas
ficam registradas em:

- `PrazoDjenRecord` (banco) — visível no dashboard e no admin;
- `var/prazo_djen.jsonl` (uma linha JSON por cálculo).

O detalhe da certidão agora **embute o preview** no próprio painel e preenche
o texto público também nos tipos que não são recurso inominado.

## Template

`Certidão de Tempestividade / Trânsito (DJEN)`, criado pela migração
`processes/0021_certidao_tempestividade_djen.py`.

## Testes

```bat
python -m unittest test_prazo_djen test_verificacao_inominado test_peticoes_inominado test_partes_inominado test_intimacao_evento
python manage.py test test_certidao_origem test_decurso_pagamento test_peticoes_fila_views
```

Casos cobertos:

- disponibilização no sábado → considerada segunda; publicação terça; início
  quarta;
- disponibilização na sexta → publicação segunda; início terça;
- disponibilização no domingo/feriado → considerada segunda; publicação terça;
  início quarta;
- prazo de 1 dia inclui o próprio dia de início;
- detecção de recurso inominado e exclusão de contrarrazões;
- DJEN posterior à data do protocolo é ignorado;
- leitura da fila `JuntadaPeticao`, detecção por tipo/nome do PDF e separação
  dos comprovantes;
- identificação do recorrente e escolha do DJEN nominal do recorrente
  (ex.: evento da Maria x evento do Banco);
- linha `PARA` com promovente/promovido ou omissão quando não localizados;
- separação das certidões por origem (petição × movimentação) no dashboard
  e nos comandos;
- localização do despacho de pagamento, intimação do executado e cálculo do
  decurso de 15 dias;
- geração do HTML e registro da certidão de decurso em Movimentações;
- fila de petições com sugestão de certidão e escolha manual do tipo,
  preparo e ação;
- localização da intimação por evento (contrarrazões/impugnação), com data
  manual apenas como fallback.

## Limitações / próximos passos

- O comando é **semiautomático**: lê a fila e o processo, mas o preparo é
  informado pelo usuário (os comprovantes são apenas listados).
- Se a petição ainda não virou evento no processo, o evento da certidão fica
  `infra` e a data de protocolo vem da fila (`Data Envio`).
- Se a petição for digitalizada (sem texto), a identificação automática do
  recorrente pode falhar; nesse caso use `--recorrente "NOME"`.
- Se a intimação escolhida não citar o recorrente, o comando avisa; confira ou
  use `--data-disponibilizacao`/`--evento-intimacao`.
- O trânsito é projetado como o **primeiro dia útil após o vencimento**.
  Confirme nos autos que não houve recurso antes de assinar.
- Prazos especiais (fazenda pública, litisconsórcio, etc.) devem ser ajustados
  no `--prazo`.
