# APRENDIZADOS — Certidão de Prazo no processo real 0002235-26.2026.8.05.0191 (41020263379522)

Data: 14/08/2026 (2ª sessão de certidão de prazo, após `a6284a8`)
Autor: Ivan (send_of_v4) — assistido por Hermes Agent

---

## 0. RESUMO DO QUE FOI FEITO NESTA SESSÃO

Fluxo completo testado de ponta a ponta num processo REAL do Projudi:

1. **Buscar os atos (movimentações)** do Projudi e salvar no banco (Process + Movement),
   inclusive o **texto dos despachos anexados (HTML)** e o **texto dos PDFs (petições)**.
2. **Corrigir um bug** no `_data_intimacao_do_tracker` que impedia a certidão de prazo
   de achar a data de início.
3. **Criar RAG** de intimação eletrônica + observação de prazo.
4. **Executar a Mov581 real** no Projudi (com e sem a observação), confirmando o ato novo.

---

## 1. ARQUIVOS CRIADOS / ALTERADOS (estado do working tree)

| Arquivo | Mudança |
|---|---|
| `projudi/cumprimento_service.py` | Fix do `_data_intimacao_do_tracker` (+`_processo_resolvido`): resolve o Process e usa a data DJEN para `data_inicio`. **+92 linhas**. |
| `scripts/pegar_atos_processo.py` | **NOVO** — busca atos do Projudi + baixa docs (HTML despacho + PDF) e grava nas `Movement`. Reutilizável. |
| `criar_rag_certidao_prazo_2235.py` | **NOVO** — cria RAG de certidão de prazo + liga CumprimentoRecord. |

> `projudi/notas.txt` está modificado MAS é scratch não relacionado (aliases de modelo do Hermes) — NÃO entrou no commit desta sessão.

---

## 2. COMO PEGAR OS ATOS (movimentações) + DOCUMENTOS DO PROJUDI

### 2.1 Números do processo (IMPORTANTE — não confundir)

- **Número interno do Projudi**: `41020263379522` — usado na URL `DadosProcesso?numeroProcesso=` e no `CumprimentoRecord.processo`.
- **CNJ**: `0002235-26.2026.8.05.0191` — usado no `Process.number` / `CumprimentoRecord.numero_processo_cnj`.
- **» O CNJ e o interno NÃO se convertem por algoritmo.** O parser do DadosProcesso dá as partes; o CNJ vem da tela.

### 2.2 Script `scripts/pegar_atos_processo.py`

```bash
cd /home/ivan/PythonProjects/send_of_v4 && source .venv/bin/activate
# busca/salva atos do processo pelo nº interno (usa cookies do Projudi)
python manage.py shell -c "import sys; sys.path.insert(0,'scripts'); import pegar_atos_processo as m; m.run('41020263379522', salvar=True)"
```

O que ele faz:
1. Obtém a sessão via `ProjudiService(user)._get_session_from_cookies()` (4 camadas: JSON → PowerShell → browser_cookie3 → banco).
2. Baixa `listagens/DadosProcesso?numeroProcesso=<interno>`.
3. `ProcessoParser(html).extrair_movimentacoes()` → lista enriquecida (evento, ato, data, categoria, situacao_comunicacao, meio_comunicacao, destinatario, **data_djen**, **documentos** etc.).
4. Salva `Process` (get_or_create por CNJ) + `Movement` (update_or_create por event_number).
5. Para cada movimento com `documentos`, **baixa o (primeiro) documento** e grava o texto na `Movement.observation` com prefixo `[DOC: <nome>]` e guarda a URL em `Movement.document_url`.

### 2.3 Mapeamento de campos parser → Movement (não errar)

| parser (`extrair_movimentacoes`) | Movement |
|---|---|
| `evento` | `event_number` |
| `ato` / `ato_normalizado` | `act_description` / `act_normalized` |
| `data_obj` / `data_texto` | `act_date` |
| `data_leitura` | `reading_date` |
| **`data_djen`** | **`reference_date`** ← data de disponibilização no DJEN |
| `autor` | `author` |
| `categoria` | `category` |
| `situacao_comunicacao` | `communication_status` |
| `meio_comunicacao` | `communication_means` |
| `destinatario` (dict/str) | `recipient` |
| `observacao` (+ documento) | `observation` |
| `evento_referenciado` | `referenced_event` |
| `prazo_dias_ev_ref` | `deadline_days` |
| primeiro documento | `document_url` |

> **`data_djen` (disponibilização) é DIFERENTE de `act_date`.** O ato "Disponibilização no DJEN ... em (10/08/26)" tem `act_date=06/08` (data da movimentação) mas a disponibilização real é **10/08**. Para a certidão de prazo eletrônica, `data_inicio` = `reference_date` (10/08), NÃO `act_date`.

---

## 3. PITFALLS DESCOBERTOS NESTA SESSÃO (CRÍTICOS)

### 3.1 `downloadarquivo` (minúsculo) → 404; use `DownloadArquivo` (D maiúsculo)

O `ProcessoParser.extrair_movimentacoes()` minúsculiza a href dos documentos e monta
`.../listagens/downloadarquivo?arquivo=N` → **404**. A URL correta é
`.../listagens/DownloadArquivo?arquivo=N` → **200** (retorna o `online.html` do despacho).
Ao baixar, normalize:

```python
url = url.replace('/downloadarquivo?', '/DownloadArquivo?')
```

### 3.2 `projudiDocReader` NÃO importa (`projudi_command_analyzer` inexistente)

`projudiDocReader.py` faz `import projudi_command_analyzer` no topo → **ModuleNotFoundError**.
Portanto `from projudiDocReader import DocumentAnalyzer` quebra. Se precisar da limpeza de
documento, **replique inline** (BeautifulSoup → corta script/style/head → corta
`DESPACHO/SENTENÇA/DECISÃO/FORÇA DE MANDADO` → corta rodapé `Documento Assinado
Eletronicamente`). Foi o que o `pegar_atos_processo.py` fez.

### 3.3 Bytes NUL quebram o INSERT no Postgres

Extrair texto de PDF com `get_text()` pode deixar `\x00` (e outros binários), e o
psycopg2 lança `ValueError: A string literal cannot contain NUL`. **Remover `\x00`** antes
de salvar e **descartar binários PDF** (`texto.lstrip().startswith('%PDF')` + checagem de
chars imprimíveis) para não poluir a `observation`.

### 3.4 Extrair texto de PDF com PyMuPDF (`fitz`)

Disponível no venv (`import fitz`, v1.28). O `DownloadArquivo` retorna os bytes crus do PDF:

```python
import fitz
doc = fitz.open(stream=rr.content, filetype='pdf')
texto = '\n'.join(pg.get_text() for pg in doc if pg.get_text())
```

### 3.5 `SynchronousOnlyOperation` ao rodar execução pelo shell

Rodando `executar_cumprimento` via `manage.py shell`, o Playwright roda em contexto async e
os saves de auditoria (`CumprimentoLog.objects.create`) disparam
`SynchronousOnlyOperation`. **Sintoma:** o(s) log(s) não salvam, MAS a Mov581 real ainda
submete e o `record.status='cumprido'` persiste. **Solução:** rodar com
`DJANGO_ALLOW_ASYNC_UNSAFE=true python manage.py shell -c "..."` p/ os logs também salvarem,
OU executar pelo dashboard (fluxo preferido do Ivan, sem esse erro).

---

## 4. BUG CORRIGIDO: `_data_intimacao_do_tracker`

**Antes (quebrado):**
```python
proc = record.processo          # string interno ('41020263379522')
mvs = Movement.objects.filter(process__processo=proc)  # FieldError: campo 'processo' não existe
```
→ `FieldError` sempre (o campo do Process é `number`/`number_normalized`) → pego pelo
`except` → **retornava None sempre**. A data NUNCA vinha do tracker.

**Depois (corrigido):**
1. `_processo_resolvido(record)` — acha o `Process` pelo CNJ (`numero_processo_cnj`) ou
   interno (`processo`).
2. Lê `Movement.objects.filter(process=proc)` (filtra `recipient__icontains` se parte preenchida).
3. **Fluxo `eletronico`/`advogado` (DJEN):** `data_inicio` = `reference_date` mais recente
   (data de disponibilização DJEN). Fallbacks: `reading_date` (leitura) → `act_date` →
   último `reference_date`.

Teste no processo real: `data_inicio=2026-08-10` (DJEN), prazo 10 dias úteis → término
25/08/2026, decurso 26/08/2026. **Fonte: tracker.**

---

## 5. RAG DE CERTIDÃO DE PRAZO + EXECUÇÃO REAL

### 5.1 A RAG (arquivo `criar_rag_certidao_prazo_2235.py`)

```json
[
  {
    "tipo": "intimacao_eletronica",
    "fluxo": "analisar",
    "fluxo_fallback": true,
    "fallback": "solicitar_expecidao",
    "assinar_ar": false,
    "codigo_mov": "581",
    "polo_prazo": "reu",
    "observacao_prazo": true,
    "expede_certidao_prazo": false
  }
]
```

### 5.2 ⚠️ `tipo` INTIMACAO_ELETRONICA × MOVIMENTACAO — SEMÂNTICA CRÍTICA (testado)

O `_config_prazo_do_rag` do CumprimentoService casa o item da `sequencia_cumprimento` pelo
`tipo` **mapeado do fluxo** do CumprimentoRecord:
`eletronico → 'movimentacao'`, `advogado → 'movimentacao'`, etc.

- **`"tipo": "movimentacao"`** → casa no fluxo `eletronico` → **as flags
  `observacao_prazo`/`expede_certidao_prazo`/`polo_prazo` DISPARAM** → a observação de
  prazo entra no Mov581.
- **`"tipo": "intimacao_eletronica"`** (fluxo `analisar`) → NÃO casa no fluxo `eletronico`
  (e o item não tem chave `observacao` p/ casar por snippet) → **as flags ficam False** →
  **a observação NÃO entra** no Mov581.

**Resultado real do teste com `intimacao_eletronica`:** a Mov581 foi submetida (atu #47
"Juntada de Cumprimento Genérico") mas **sem a observação de prazo** (`observacao: False`
no retorno; `obs=''` no Projudi). Ficaram 2 movimentações genéricas sem observação (#46 e #47).

> **Conclusão:** `tipo: "intimacao_eletronica"` pertence ao fluxo FluxoDecisor de intimação
> (analisar), NÃO ao CumprimentoService. Para a observação de prazo sair no Mov581 de um
> cumprimento `eletronico`, usar `"tipo": "movimentacao"`.

### 5.3 Executar

```bash
# (opcional) resetar p/ pendente se quiser re-executar
python manage.py shell -c "from projudi.models import CumprimentoRecord as C; c=C.objects.get(id=115); c.status='pendente'; c.save(update_fields=['status'])"

DJANGO_ALLOW_ASYNC_UNSAFE=true python manage.py shell -c "
from projudi.models import CumprimentoRecord
from accounts.models import User
from projudi.cumprimento_service import CumprimentoService
c=CumprimentoRecord.objects.get(id=115)
out=CumprimentoService(user=User.objects.get(is_active=True)).executar_cumprimento(c)
print(out)
"
```

Observação gerada (quando a flag dispara): *"Intimação eletrônica (DJEN) — Prazo de 10 dias
úteis ao réu BANCO BRADESCO S.A. e SERASA S A. Leitura em 10/08/2026; não contam a leitura
nem o 1º dia útil subsequente à leitura; início da contagem em 12/08/2026; término em
25/08/2026 (decorrido o prazo em 26/08/2026)."*

---

## 6. PARTES DO PROCESSO (destinatários da intimação)

Do parser do DadosProcesso (3 partes):
- **DIOGLEIRY CRISTIANE FARIAS GONZAGA** — PROMOVENTE (autora)
- **BANCO BRADESCO S.A.** — PROMOVIDO (réu), domicílio DJEN
- **SERASA S A** — PROMOVIDO (réu), domicílio DJEN

Destinatário da intimação do despacho do evento 13 = **ambos os réus**.
No CR115, `parte_nome = 'BANCO BRADESCO S.A. e SERASA S A'`, `parte_papel = 'reu'`.

---

## 7. CADEIA DE DESPACHOS REFERENCIADOS (contexto p/ certidão)

Textos salvos nas `Movement.observation` do Process 176:
- **evento 13** (30/07): *"...intime-se a parte demandada para se manifestar sobre o pedido
  liminar no prazo de 10 dias. Após, com ou sem resposta, venham conclusos..."* ← **despacho
  original do CR115**.
- **evento 31** (04/08): *"...o despacho proferido no evento 13 ... ficando ratificado o
  prazo consignado no despacho retro..."* → referencia o 13.
- **evento 45** (13/08): *"...Certifique-se sobre o decurso do prazo sinalizado no evento 13
  para ambas as rés..."* → referencia o 13.

Isso é o "despacho anterior com contexto": o ato atual faz remissão ao evento anterior, e o
conteúdo dele agora está no banco (observação + `document_url`).

---

## 8. PENDÊNCIAS / PRÓXIMOS PASSOS

- [ ] **Decidir o `tipo` da RAG #2525**: se quiser a observação no Mov581 de um cumprimento
      `eletronico`, trocar para `"tipo": "movimentacao"`. O teste provou que
      `intimacao_eletronica` NÃO dispara as flags no CumprimentoService.
- [ ] Remover/tratar as movimentações genéricas sem observação (#46 e #47) se não desejadas.
- [ ] Confirmar se o fluxo que o Ivan quer é o **FluxoDecisor de intimação** (aí a RAG com
      `intimacao_eletronica`/`fluxo: analisar` é o caminho certo, outro fluxo).
- [ ] Reiniciar o `runserver --noreload` p/ carregar o fix do `_data_intimacao_do_tracker`.

---

## 9. VERIFICAÇÃO

- [x] 45 atos extraídos e salvos no banco (Process 176).
- [x] Despachos (13/31/45) com texto salvo; PDFs (1/23/42) com texto extraído via PyMuPDF.
- [x] Certidão de prazo calculou data DJEN 10/08 + 10 dias úteis → 25/08 (decurso 26/08).
- [x] Mov581 real executado (atos #46 e #47 no Projudi); CR115 status `cumprido`.
- [x] Config/teste documentado (observação vs. sem observação conforme `tipo` da RAG).
