# Windows nativo + Firefox local

Este documento explica como rodar o `send_of_v4` no **Windows** usando o
**Firefox instalado no sistema** para login/cookies, mantendo compatibilidade
com a versão do **Ubuntu/Linux** e com o modo **portátil**.

---

## 1. Como o Firefox é usado

O projeto tem dois papéis distintos para o navegador:

| Papel | Navegador | Para que serve |
|-------|-----------|----------------|
| Login / sessão | **Firefox local** (`C:\Program Files\Mozilla Firefox`) | Você faz login no Projudi e o sistema lê o `cookies.sqlite` (+ `-wal`) do perfil local. |
| Automação | **Firefox do Playwright** | O Playwright abre um Firefox próprio, já com os cookies do Projudi injetados, e executa os fluxos (ofícios, mandados, movimentações). |

> O Playwright **não consegue controlar** o Firefox instalado (ele usa um
> build modificado). Por isso o Firefox local é usado para a sessão e o
> Firefox do Playwright para a automação. O usuário não precisa fazer login
> duas vezes: os cookies são reaproveitados.

Tudo isso é resolvido por `firefox_config.py`, que funciona em:

- Windows nativo (registro do Windows + `%APPDATA%`);
- WSL (perfis do Windows em `/mnt/c/Users/...`);
- Linux/Ubuntu (`~/.mozilla/firefox`).

---

## 2. Instalação no Windows (primeira vez)

Pré-requisitos:

- Windows 64-bit;
- Python 3.12 ou 3.13 (https://www.python.org/downloads/ – marque
  **Add python.exe to PATH**);
- Firefox instalado e com login no Projudi.

Passos:

1. Dê duplo clique em **`INSTALAR_WINDOWS.bat`**.
   Ele cria o `.venv`, instala `requirements-windows.txt`, baixa o Firefox do
   Playwright, cria o `.env`, aplica migrações e cria o usuário local.
2. Dê duplo clique em **`RODAR_WINDOWS.bat`**.
   O servidor sobe em `http://127.0.0.1:8000/` e o **Firefox local** é aberto.
3. Login inicial: **`admin@local` / `admin123`**.
   Troque a senha em `/admin/` depois do primeiro acesso.

### Sincronizar a sessão do Projudi

1. Abra o Firefox local (atalho **`ABRIR_FIREFOX_PROJUDI.bat`**).
2. Faça login no Projudi e **deixe o Firefox aberto**.
3. No sistema, clique em **Sincronizar sessão** (`/projudi/sessao/`), ou dê
   duplo clique em **`CAPTURAR_COOKIES.bat`**.
4. O JSON é gravado em `%LOCALAPPDATA%\send_of_v4\cookies.json` e também no
   banco (`ProjudiSession`).

Se algo falhar, rode **`DIAGNOSTICO_WINDOWS.bat`**. Ele mostra:

- caminho do Firefox local;
- perfil detectado;
- quantidade de cookies e presença de `JSESSIONID`;
- caminho do Firefox do Playwright.

---

## 3. Arquivos e variáveis principais

| Arquivo / variável | Função |
|--------------------|--------|
| `env.windows.example` | Modelo de `.env` para Windows. |
| `env.linux.example` | Modelo de `.env` para Ubuntu/Linux. |
| `.env` | Configuração real (não versionada). |
| `INSTALAR_WINDOWS.bat` | Instalação completa no Windows. |
| `RODAR_WINDOWS.bat` | Sobe o Django e abre o Firefox local. |
| `CAPTURAR_COOKIES.bat` | Captura cookies do Firefox local. |
| `DIAGNOSTICO_WINDOWS.bat` | Diagnóstico de Firefox/cookies/Playwright. |
| `ABRIR_FIREFOX_PROJUDI.bat` | Abre o Projudi no Firefox local. |
| `PARAR_POSTGRES.bat` | Para o PostgreSQL local do projeto. |
| `RESTAURAR_BANCO_POSTGRES.bat` | Restaura um dump `.sql/.sql.gz/.dump`. |
| `scripts/postgres_local_windows.ps1` | Cria/sobe/para o PostgreSQL local (porta 5433). |
| `scripts/exportar_dump_postgres_ubuntu.sh` | Exporta o `pg_send_of` no Ubuntu para `D:\Projudi`. |
| `FIREFOX_PATH` | Caminho do `firefox.exe` (vazio = detecção automática). |
| `FIREFOX_PROFILE` | Pasta do perfil (vazio = perfil mais recente). |
| `PROJUDI_COOKIES_FILE` | Caminho do JSON de cookies (vazio = padrão do SO). |
| `PLAYWRIGHT_HEADLESS` | `0` = Firefox visível; `1` = sem janela. |
| `PLAYWRIGHT_FIREFOX_EXECUTABLE` | Build compatível do Firefox (normalmente vazio). |

O `env.windows.example` vem com `DATABASE_URL=sqlite:///db.sqlite3`, então
**não é necessário Docker/PostgreSQL** para uso local. A instalação atual em
`D:\send_of_v4_win` está configurada para o **PostgreSQL local** (veja abaixo).

---

## 4. Banco de dados no Windows

### 4.1 PostgreSQL local do projeto (recomendado para espelhar o Docker)

O PostgreSQL 15 já instalado no Windows **não** é o `pg_send_of` (o banco dele
é outro, de 2023). Para não depender de admin nem do serviço do Windows, o
projeto cria um **cluster próprio** em `.\pgdata`, na porta **5433**:

```powershell
.\scripts\postgres_local_windows.ps1
# cria o cluster (se preciso), sobe, cria o banco sccj e mostra a URL
.\scripts\postgres_local_windows.ps1 -Status
.\scripts\postgres_local_windows.ps1 -Stop
```

Depois, no `.env`:

```env
DATABASE_URL=postgres://send_of:send_of@127.0.0.1:5433/sccj
```

E rode:

```bat
.venv\Scripts\python.exe manage.py migrate
```

O `RODAR_WINDOWS.bat` detecta `postgres://` no `.env` e sobe o cluster
automaticamente. `PARAR_POSTGRES.bat` encerra.

### 4.2 Copiar o espelho SQLite para o PostgreSQL

```bat
.venv\Scripts\python.exe manage.py copiar_dados_sqlite ^
    --origem D:\send_of_v4\db.sqlite3 --limpar
```

Isso preserva IDs e copia todas as tabelas de aplicação que existem nos dois
lados. Tabelas novas (que o espelho antigo não tinha) ficam vazias.

### 4.3 Restaurar o banco real do Docker (`pg_send_of`)

1. **No Ubuntu**, com o container ligado:

   ```bash
   docker start pg_send_of
   bash scripts/exportar_dump_postgres_ubuntu.sh
   ```

   O dump sai em `D:\Projudi\sendof_AAAAmmdd_HHMMSS.sql.gz` (via `/mnt/d`).

2. **No Windows**, dê duplo clique em **`RESTAURAR_BANCO_POSTGRES.bat`** e
   arraste o arquivo `.sql.gz`. Ele restaura no cluster local (porta 5433) e
   roda as migrações.

3. Inicie com `RODAR_WINDOWS.bat`.

> Se o dump for de PostgreSQL 16 e a restauração reclamar de alguma opção
> nova, instale o PostgreSQL 16 ou use `pg_dump --no-owner --no-privileges`
> em uma versão compatível. O script de exportação já usa essas opções.

### 4.4 Voltar para SQLite

No `.env`:

```env
DATABASE_URL=sqlite:///db.sqlite3
```

O banco `db.sqlite3` continua na raiz do projeto (com o espelho aplicado).

---

## 5. Ubuntu / Linux (mesmo repositório)

O código continua funcionando no Ubuntu. Use o modelo de ambiente Linux:

```bash
cp env.linux.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install firefox     # baixa o Firefox do Playwright
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py criar_usuario_local
python manage.py runserver 0.0.0.0:8000
```

O Firefox local do Ubuntu é detectado automaticamente (`/usr/bin/firefox`,
snap, `/opt/firefox` etc.). Se o login/cookies estiverem em outro perfil,
defina `FIREFOX_PROFILE` no `.env`.

> Para PostgreSQL, troque `DATABASE_URL` no `.env`. O app
> `django.contrib.postgres` foi removido de `INSTALLED_APPS` porque o
> projeto não usa campos específicos do PostgreSQL; isso permite rodar com
> SQLite sem instalar `psycopg2`.

---

## 6. Versão portátil

A pasta portátil é gerada por:

```powershell
.\scripts\montar_portatil_windows.ps1
# opcional:
.\scripts\montar_portatil_windows.ps1 -Destino "E:\send_of_v4_portable" `
    -BancoOrigem "D:\send_of_v4_portable\app\db.sqlite3"
```

Ela contém:

```
send_of_v4_portable_win\
  python\   -> Python 3.12 embarcado + dependências + Firefox do Playwright
  app\      -> código, .env, db.sqlite3
  run.bat
  CAPTURAR_COOKIES.bat
  DIAGNOSTICO.bat
```

O `run.bat` define `PLAYWRIGHT_BROWSERS_PATH=0`, então o Firefox do Playwright
fica **dentro da pasta portátil** e não depende do cache do usuário.

Já existe uma cópia pronta em `D:\send_of_v4_portable_win` (gerada a partir
deste repositório, com o banco antigo copiado).

---

## 7. O que mudou no código

- `firefox_config.py` (novo): detecção de Firefox/perfis e captura de cookies
  multiplataforma (Windows, WSL e Linux).
- `projudi_bot.py`: usa `firefox_config`; removidos caminhos `/mnt/...`.
- `projudi/services.py`: sessão do Projudi capturada direto do Firefox local;
  removidos PowerShell/WSL do caminho principal.
- `projudi/playwright_firefox.py` (novo): centraliza o `launch` do Firefox do
  Playwright (ajustes de GPU só em Linux/WSL, `PLAYWRIGHT_HEADLESS` etc.).
- `app_paths.py` (novo): substitui `/tmp` por uma pasta temporária portátil.
- `core/settings.py`: `STATICFILES_DIRS` tolerante, variáveis de Firefox e
  remoção do `django.contrib.postgres`.
- Scripts legados (`expedir_*.py`, `rastrear_expedir.py`) passaram a usar
  caminhos portáteis e o Firefox local.
- Novos comandos:
  - `python manage.py criar_usuario_local`
  - `python manage.py diagnostico_firefox`

---

## 8. Problemas comuns

### “JSESSIONID não encontrado”

- O Firefox local precisa estar **aberto e logado** no Projudi.
- Rode `CAPTURAR_COOKIES.bat` e confira com `DIAGNOSTICO_WINDOWS.bat`.
- O `JSESSIONID` expira; sincronize novamente quando a sessão cair.

### “Executable doesn't exist … firefox”

Rode:

```bat
.venv\Scripts\python.exe -m playwright install firefox
```

No portátil, rode `DIAGNOSTICO.bat` para conferir o caminho interno.

### Firefox não abre pelo atalho

Defina `FIREFOX_PATH` no `.env` com o caminho correto do `firefox.exe`.

### `gunicorn` no Windows

Não use `gunicorn` no Windows (ele é Unix-only). Para uso local, o
`manage.py runserver` é suficiente. O `requirements-windows.txt` não o inclui.

### Sessão do Django/estáticos

Se aparecer erro de estáticos após atualizar o código:

```bat
.venv\Scripts\python.exe manage.py collectstatic --noinput
```
