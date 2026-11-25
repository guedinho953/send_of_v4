# Planilha de ofícios no Google Docs

O sistema pode ler o último número de ofício da tabela do Google Docs,
somar 1 e inserir uma nova linha com:

- número do ofício;
- data de confecção;
- número do processo;
- órgão de destino.

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
GOOGLE_OFICIOS_DOC_ID=1dY6yODJF0CFdbWZ2tH2f-cfvfyqq6RuKUo92NJE7JrY
GOOGLE_OFICIOS_TABLE_INDEX=0
```

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
