# Prazo DJEN semiautomático

Calcula a cadeia:

```
disponibilização
   ↓ (se sábado/domingo/feriado/sem expediente → 1º dia útil seguinte)
disponibilização considerada
   ↓ (1º dia útil seguinte)
publicação no DJEN
   ↓ (1º dia útil seguinte; exclui a publicação)
1º dia do prazo
   ↓ (N dias úteis, incluindo o 1º dia)
último dia do prazo
   ↓ (1º dia útil seguinte)
trânsito em julgado
```

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

## Dashboard de certidões

Acesse **Certidões** no menu ou:

```
http://127.0.0.1:8000/projudi/certidoes/
```

O dashboard mostra:

- abas **Todas / Petições / Movimentações**, com contadores por origem;
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

## Template

`Certidão de Tempestividade / Trânsito (DJEN)`, criado pela migração
`processes/0021_certidao_tempestividade_djen.py`.

## Testes

```bat
python -m unittest test_prazo_djen test_verificacao_inominado test_peticoes_inominado test_partes_inominado
python manage.py test test_certidao_origem
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
  e nos comandos.

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
