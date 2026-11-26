# Planilha de ofícios no Google Docs

> **Importante:** o link público sozinho **não** permite que o Django edite o
> documento pela API. É preciso uma das duas opções abaixo:
> **Apps Script** (recomendado; pode ficar “Qualquer pessoa” com token) ou
> **conta de serviço** compartilhada como Editor.
>
> O sistema usa **Google Docs com uma tabela** (`docs.google.com/document/...`).
> Se o seu link for uma **Google Sheets** (`docs.google.com/spreadsheets/...`),
> o Apps Script atual (`DocumentApp`) não serve; será preciso adaptar o script
> para `SpreadsheetApp`.

O sistema pode ler o último número de ofício da tabela do Google Docs,
somar 1 e inserir uma nova linha com:

- número do ofício;
- data de confecção;
- número do processo;
- órgão de destino.

> A senha de app do Gmail usada para enviar e-mails **não** dá acesso à
> API do Google Docs. Para usar o Gmail, use a opção do Apps Script abaixo.

## Opção recomendada: Apps Script com o Gmail que já tem acesso

1. Abra o documento com a conta Google que pode editá-lo.
2. Vá em **Extensões → Apps Script**.
3. Cole o conteúdo de `docs/apps_script_planilha_oficios.gs`.
4. Troque `TOKEN` por uma senha longa.
5. **Implantar → Nova implantação → App da Web**:
   - Executar como: **Eu**
   - Quem tem acesso: **Qualquer pessoa**
6. Copie a URL do App da Web.
7. Configure no `.env`:

```env
GOOGLE_OFICIOS_WEBHOOK_URL=https://script.google.com/macros/s/.../exec
GOOGLE_OFICIOS_WEBHOOK_TOKEN=o-mesmo-token-do-script
```

8. Teste:

```bash
source .venv/bin/activate
python manage.py testar_planilha_oficios
```

Essa opção usa a própria conta Gmail que já tem acesso ao documento e não
precisa de conta de serviço nem chave JSON. “Qualquer pessoa” no App da Web
é seguro o suficiente porque o script exige o `TOKEN`.

> Se você só tem o link do documento, pode colá-lo em
> `GOOGLE_OFICIOS_DOC_URL` no `.env` (o sistema extrai o ID). Mas isso ainda
> exige a conta de serviço ou o Apps Script para autenticar a edição.

## Opção alternativa: conta de serviço

## 1. Criar a conta de serviço

1. Acesse o Google Cloud Console.
2. Crie/abra um projeto.
3. Ative a **Google Docs API**.
4. Crie uma **conta de serviço**.
5. Gere uma chave JSON e salve no servidor, por exemplo:
   `/home/ivan/PythonProjects/send_of_v4/credentials/google-docs.json`

## 2. Compartilhar o documento

No Google Docs, clique em **Compartilhar** e adicione o e-mail da conta
de serviço como **Editor**.

O dono do documento continua sendo o dono; a conta de serviço só recebe
permissão de edição.

## 3. Configurar o `.env`

```env
GOOGLE_SERVICE_ACCOUNT_FILE=/home/ivan/PythonProjects/send_of_v4/credentials/google-docs.json
# ID puro ou link completo:
GOOGLE_OFICIOS_DOC_URL=https://docs.google.com/document/d/SEU_ID/edit
GOOGLE_OFICIOS_DOC_ID=1dY6yODJF0CFdbWZ2tH2f-cfvfyqq6RuKUo92NJE7JrY
GOOGLE_OFICIOS_TABLE_INDEX=0
```

No Windows, use o caminho do JSON, por exemplo
`GOOGLE_SERVICE_ACCOUNT_FILE=C:\send_of_v4\credentials\google-docs.json`.

`GOOGLE_OFICIOS_TABLE_INDEX` é o índice da tabela dentro do documento
(0 = primeira tabela). Se omitido, o sistema tenta escolher a tabela cujo
cabeçalho tenha “número”, “data”, “processo” ou “destinatário”.

## 4. Instalar as dependências

```bash
source .venv/bin/activate
pip install google-api-python-client google-auth google-auth-httplib2
```

## 5. Como funciona

Antes de gerar o ofício, o sistema lê a última linha da tabela, encontra
o último número no formato `001/2026`, soma 1 e usa esse número no ofício.
Depois de registrar o ofício no Projudi, insere a nova linha:

```text
013/2026 | 25/11/2026 | 0002887-43.2026.8.05.0191 | CENTRAL INTEGRADA DE ALTERNATIVAS PENAIS PAULO AFONSO
```

## Fallback

Se a planilha não estiver configurada ou o Google falhar, o ofício continua
sendo expedido no Projudi e o erro é mostrado no log. A planilha não bloqueia
a expedição.
