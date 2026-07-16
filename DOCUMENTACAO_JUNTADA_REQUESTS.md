# 📚 Como Funciona a Juntada no Projudi SEM Selenium (só com Requests)

> **Objetivo deste documento:** Ensinar como o sistema consegue fazer juntada de cumprimento no Projudi usando APENAS a biblioteca `requests` do Python, sem abrir navegador (Selenium). Isso é muito mais rápido e estável.

---

## 1. O Segredo: Você NÃO está "logando" no momento da juntada

A grande sacada é que o login já foi feito **antes** (via Selenium/Firefox) e os cookies da sessão foram **salvos no banco de dados Django** (`ProjudiSession`).

Na hora de juntar, o sistema apenas:
1. **Pega os cookies salvos** do banco
2. **Injeta esses cookies** numa session do `requests`
3. **Acessa direto** a URL de movimentação do processo
4. **Envia o formulário** como se fosse um clique no botão "Concluir"

**Fluxo visual:**
```
┌─────────────┐      cookies       ┌─────────────┐
│  Firefox    │ ─────────────────► │   Django    │
│  (login)    │   salvos em JSON   │   (SQLite)  │
└─────────────┘                    └─────────────┘
                                          │
                                          ▼ (na hora de juntar)
                                    ┌─────────────┐
                                    │   requests  │ ◄── pega cookies do banco
                                    │   (Python)  │
                                    └─────────────┘
                                          │
                                          ▼
                                    POST multipart/form-data
                                          │
                                          ▼
                                    ┌─────────────┐
                                    │   Projudi   │
                                    │  (servidor) │
                                    └─────────────┘
```

---

## 2. Por que o Projudi aceita isso?

O Projudi é um sistema web antigo (Java EE / Struts). Ele não usa tokens CSRF modernos nem proteções anti-automação rigorosas. Ele confia na **sessão do cookie** (`JSESSIONID`).

Se você tem o cookie de sessão válido, o servidor trata seu `requests` exatamente como se fosse o navegador Firefox.

---

## 3. A URL de Recebimento (juntada)

Quando o sistema sincroniza ofícios, ele captura 4 URLs para cada ofício:

| URL | Para que serve |
|-----|---------------|
| `url_oficio` | Página que mostra o conteúdo do ofício |
| `url_processo` | Página de dados do processo |
| **`url_recebimento`** | **Página de movimentação/juntada** (a mais importante!) |
| `url_baixa` | Página para dar baixa no ofício |

A `url_recebimento` tem esse formato:
```
https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?
    numeroProcesso=41020261097944
    &juntadaAr=true
    &codDocVinculado=5984298
```

Essa URL abre o **formulário de movimentação** pré-preenchido com os dados do ofício.

---

## 4. O Formulário de Movimentação (o coração da juntada)

Quando o sistema faz `GET` na `url_recebimento`, o Projudi devolve uma página HTML com um `<form>` gigante. Esse form tem campos hidden, checkboxes, selects, textareas, etc.

### Os campos que o sistema extrai automaticamente:

**a) Hidden obrigatórios** (sessão, IDs, etc.):
```html
<input type="hidden" name="numeroProcesso" value="41020261097944">
<input type="hidden" name="acaoCodigoDocumento" value="5984298">
<input type="hidden" name="seqMovimentacao" value="...">
<input type="hidden" name="tipoDocumento" value="...">
```

> ⚠️ **Importante:** Esses campos hidden carregam valores da sessão e IDs internos do sistema. Você NÃO pode inventá-los — tem que extrair do HTML real do form.

**b) Checkboxes marcados** (flags de envio):
```html
<input type="checkbox" name="enviaMP" value="true" checked> Enviar ao MP
<input type="checkbox" name="enviaDelegacia" value="true"> Enviar à Delegacia
```

O sistema copia **apenas os checkboxes que já estão marcados (`checked`)** no HTML, exceto `codParteTransPenal`.

**c) Selects com valor selecionado** (localizadores, prazos):
```html
<select name="codTipoLocalizador">
    <option value="-1">Selecione...</option>
    <option value="5" selected>Secretaria</option>
</select>
```

O sistema copia o valor do `<option selected>`.

**d) Textareas** (observação):
```html
<textarea name="observacao">Texto da observação...</textarea>
```

---

## 5. O SEGREDO MAIS IMPORTANTE: `multipart/form-data`

O Projudi exige que o POST seja enviado com `Content-Type: multipart/form-data`. Isso é obrigatório porque o form original do HTML tem `enctype="multipart/form-data"`.

### ❌ ERRADO (o que NÃO funciona):
```python
# ISSO NÃO FUNCIONA COM O PROJUDI!
response = session.post(url, data=payload)
```
Isso envia como `application/x-www-form-urlencoded`. O Projudi recebe, devolve HTTP 200, mas **não processa a juntada**.

### ✅ CERTO (o que funciona):
```python
# Cria estrutura multipart
multipart_data = {k: (None, str(v)) for k, v in payload.items()}

# Envia como files= (isso força multipart/form-data)
response = session.post(url, files=multipart_data)
```

A tupla `(None, str(v))` diz pro `requests`: "esse campo é um campo de texto no multipart" (não é arquivo).

### Por que o Projudi exige multipart?

Porque o formulário original pode aceitar uploads de arquivo (anexos). Mesmo quando você não está enviando arquivo, o form continua sendo `multipart/form-data`. Se você manda `application/x-www-form-urlencoded`, o servidor Java do Projudi **rejeita silenciosamente**.

---

## 6. O Botão "Concluir" é um `input type="image"`

No HTML do Projudi, o botão de concluir é assim:
```html
<input type="image" name="Concluir" src="..." value="Concluir">
```

Quando você clica num `input type="image"`, o navegador envia as coordenadas do clique:
```
Concluir.x=10
Concluir.y=10
```

O sistema adiciona isso manualmente no payload:
```python
payload['Concluir.x'] = '10'
payload['Concluir.y'] = '10'
```

Sem isso, o servidor pode ignorar o submit.

---

## 7. Código da Movimentação: 11383 vs 581

O Projudi tem um campo `seqCategoriaMovimentacao` que define qual tipo de movimentação será criada.

| Código | Significado | Quando usar |
|--------|------------|-------------|
| **11383** | **Cumprimento de Ofício** | O correto para ofícios enviados por e-mail |
| **581** | **TD - Tipo Documental** | Fallback genérico quando 11383 não funciona |

O sistema tenta **11383 primeiro**. Se falhar (o form ainda aparece na resposta), tenta **581 como fallback**.

```python
payload['seqCategoriaMovimentacao'] = '11383'
payload['descCategoriaMovimentacao'] = 'Cumprimento de Oficio'
```

---

## 8. Como saber se a juntada DEU CERTO?

Este é o ponto mais crítico. O Projudi **sempre** devolve HTTP 200, mesmo quando deu erro. Você não pode confiar no `status_code`.

### Critérios que indicam FALHA:
1. **Formulário MovimentarProcesso ainda presente** na resposta → o Projudi devolveu a mesma página (validação falhou)
2. **Texto "ocorreu um erro"** ou **"erro não definido"** no HTML
3. **Redirect pra página de login** → sessão expirou
4. **"doesn't contain a multipart/form-data"** → você mandou `data=` em vez de `files=`

### Critérios que indicam SUCESSO:
1. **Redirect pra `DadosProcesso`** ou **`Historico`** → a juntada foi processada e o sistema te mandou pra página do processo
2. **Texto "movimentação incluída"** ou **"operação realizada"** no HTML
3. **Não achou o form** e **não achou mensagem de erro** → assume sucesso (pode ser redirect ou página de confirmação)

```python
def _verificar_sucesso_juntada(self, resp_post):
    # 1. HTTP não é 200?
    if resp_post.status_code != 200:
        return False, "HTTP 500/403/etc"

    # 2. Foi pro login?
    if 'login' in resp_post.url.lower():
        return False, "Sessão expirou"

    # 3. Tem mensagem de erro no HTML?
    if 'ocorreu um erro' in resp_post.text.lower():
        return False, "Erro do servidor"

    # 4. Ainda tem o formulário?
    soup = BeautifulSoup(resp_post.text, 'html.parser')
    form = soup.find('form')
    if form and 'MovimentarProcesso' in str(form.get('action', '')):
        return False, "Formulário ainda presente (não processou)"

    # 5. Redirect pra página do processo?
    if 'DadosProcesso' in resp_post.url:
        return True, "Redirect para página do processo"

    # 6. Mensagem de confirmação?
    if 'movimentação incluída' in resp_post.text.lower():
        return True, "Confirmação encontrada"

    # Se não achou erro nem form → assume sucesso
    return True, "Sem erro detectado"
```

---

## 9. Campos que DEVEM ser REMOVIDOS do payload

O form do Projudi vem com vários campos que, se enviados, criam movimentações indesejadas ou dão erro:

```python
campos_indesejados = [
    'codDelegacia',          # Cria movimentação pra delegacia
    'codPrazoEnviaDelegacia',
    'enviaDelegacia',        # Flag de envio à delegacia
    'enviaMP',               # Enviar ao Ministério Público
    'enviaTurmaRecursal',    # Turma recursal
    'enviaCartorioExtrajudicial',  # Cartório extrajudicial
    'arquivar',              # Arquivar o processo (!!!)
    'psicossocial',          # Psicossocial
    'contador',              # Contador de prazo
]
for campo in campos_indesejados:
    payload.pop(campo, None)
```

> ⚠️ Se você enviar `arquivar=true`, o Projudi vai **arquivar o processo**! Sempre remova campos que você não quer ativar.

---

## 10. Fluxo Completo da Juntada (passo a passo)

```
1. Usuário clica "Juntar" no dashboard
        │
        ▼
2. OficioService.juntar_cumprimento(record)
        │
        ▼
3. Pega cookies do banco (ProjudiSession)
        │
        ▼
4. session.get(url_recebimento) ← acessa formulário
        │
        ▼
5. BeautifulSoup parseia o HTML, extrai todos os campos
        │
        ▼
6. Monta payload (hidden + checked + selected + textarea)
        │
        ▼
7. Adiciona Concluir.x / Concluir.y
        │
        ▼
8. Define seqCategoriaMovimentacao = 11383
        │
        ▼
9. Remove campos indesejados (delegacia, MP, arquivar...)
        │
        ▼
10. Cria multipart_data = {k: (None, str(v)) for ...}
        │
        ▼
11. session.post(post_url, files=multipart_data)
        │
        ▼
12. Verifica resposta (form ainda presente? redirect? erro?)
        │
        ├─► Falhou? → tenta código 581 (fallback)
        │
        ▼
13. Loga resultado no banco (OficioLog)
        │
        ▼
14. Atualiza status do OficioRecord (juntado / falhou_juntada)
```

---

## 11. É possível juntar DOCUMENTOS (PDFs) assim também?

**SIM!** O `requests` suporta upload de arquivo nativamente no multipart.

### Como juntar um PDF via requests:

```python
# Ler o arquivo PDF em binário
with open('/caminho/documento.pdf', 'rb') as f:
    pdf_bytes = f.read()

# Montar o multipart com arquivo
multipart_data = {}

# Campos de texto (igual antes)
for k, v in payload.items():
    multipart_data[k] = (None, str(v))

# Campo de ARQUIVO (o nome do campo depende do form do Projudi)
# Normalmente é algo como 'arquivo', 'documento', 'fileUpload'
multipart_data['arquivo'] = ('documento.pdf', pdf_bytes, 'application/pdf')

# Envia
response = session.post(post_url, files=multipart_data)
```

### Desafios pra juntar documentos:

1. **Nome do campo de arquivo varia** — pode ser `arquivo`, `documento`, `fileUpload`, `arquivos[0]`. Você precisa inspecionar o HTML do form pra saber o `name` correto.

2. **O Projudi pode exigir descrição do documento** — tem que preencher `descricaoDocumento` ou similar.

3. **Tipo de documento** — pode ter um select `codTipoDocumento` que precisa ser selecionado.

4. **Limite de tamanho** — o servidor pode rejeitar arquivos muito grandes.

### Quando você já faz juntada de documento hoje?

Na verdade, quando você juntar um **ofício de cumprimento**, o Projudi já está juntando o **documento do ofício** (que está vinculado via `codDocVinculado` na URL). A juntada que o sistema faz é uma **movimentação de cumprimento** que aponta pro documento que já existe no sistema.

Se você quiser juntar um **PDF novo** (que não está no Projudi ainda), aí teria que:
1. Fazer upload do PDF numa URL de upload do Projudi
2. Pegar o `codDocumento` gerado
3. Usar esse código na movimentação

Isso é mais complexo e exigiria engenharia reversa da tela de upload do Projudi.

---

## 12. Dicas de Debugging

### a) Como ver o que o Projudi está devolvendo?

Adicione isso no código antes de verificar sucesso:
```python
# Salvar a resposta em arquivo pra inspecionar
with open('/tmp/resposta_juntada.html', 'w', encoding='utf-8') as f:
    f.write(resp_post.text)
print(f"Resposta salva em /tmp/resposta_juntada.html")
print(f"URL final: {resp_post.url}")
print(f"Status: {resp_post.status_code}")
```

### b) Como comparar com o navegador?

1. Abra o Firefox, vá na página de movimentação do processo
2. Aperte F12 → Network
3. Clique em "Concluir"
4. Veja a requisição POST no painel Network
5. Compare os campos enviados pelo navegador com os campos enviados pelo Python

### c) Log sempre o snippet

O sistema agora salva os primeiros 800 caracteres do HTML de resposta no log:
```python
snippet = resp_post.text[:800]
self._log(record, 'erro_juntada', "Falhou", {'snippet': snippet})
```

Isso permite ver se o Projudi devolveu um alerta de JavaScript, mensagem de validação, ou redirect.

---

## 13. Resumo das Regras de Ouro

| Regra | Por quê |
|-------|---------|
| **Sempre use `files=`** no POST | O Projudi exige `multipart/form-data` |
| **Sempre extraia o form do HTML real** | Campos hidden têm valores de sessão que mudam |
| **Sempre remova campos indesejados** | Evita criar movimentações erradas (delegacia, arquivar) |
| **NUNCA confie só em `status_code == 200`** | O Projudi devolve 200 mesmo quando dá erro |
| **Verifique se o form ainda está na resposta** | Se estiver, a juntada NÃO foi processada |
| **Adicione `Concluir.x` e `Concluir.y`** | O botão é `input type="image"`, precisa dessas coordenadas |
| **Use código 11383 primeiro** | É o código correto para "Cumprimento de Ofício" |
| **Faça fallback pro 581** | Se 11383 falhar, 581 é mais genérico e costuma passar |

---

## 14. Arquivos que implementam isso

| Arquivo | Função |
|---------|--------|
| `projudi/oficio_service.py` | `juntar_cumprimento()`, `_juntar_via_requests()`, `_verificar_sucesso_juntada()` |
| `projudi/services.py` | `ProjudiService._get_session_from_cookies()` — pega cookies do banco |
| `projudi/models.py` | `ProjudiSession` — onde os cookies são salvos |
| `projudi_client.py` | `ProjudiClient` — classe que usa Selenium pra obter cookies |

---

*Documento gerado para fins educativos. Se o Projudi mudar o HTML dos formulários, a extração de campos pode precisar de ajustes.*
