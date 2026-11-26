# send_of_v4 — Windows + Firefox local

Guia completo: **[docs/WINDOWS_FIREFOX.md](docs/WINDOWS_FIREFOX.md)**

## Início rápido (Windows nativo)

1. Instale Python 3.12/3.13 (marque *Add python.exe to PATH*).
2. Duplo clique em **`INSTALAR_WINDOWS.bat`**.
3. Duplo clique em **`RODAR_WINDOWS.bat`**.
4. Abra o Firefox local, faça login em <https://projudi.tjba.jus.br> e deixe-o aberto.
5. No sistema, clique em **Sincronizar sessão** ou rode **`CAPTURAR_COOKIES.bat`**.

Login inicial: **`admin@local` / `admin123`**.

### Banco

Por padrão usa **SQLite** (`db.sqlite3`), com os dados do espelho (70 ofícios).
O PostgreSQL local do projeto (`.\pgdata`, porta 5433) fica como opção para
espelhamento/uso futuro.

- Ativar PostgreSQL: troque no `.env` para
  `DATABASE_URL=postgres://send_of:send_of@127.0.0.1:5433/sccj`
  e rode `RODAR_WINDOWS.bat` (ele sobe o cluster).
- Espelhar SQLite -> PostgreSQL:
  `python manage.py copiar_dados_sqlite --origem db.sqlite3 --limpar`
- Parar o PostgreSQL: `PARAR_POSTGRES.bat`
- Restaurar o banco real do Docker: `RESTAURAR_BANCO_POSTGRES.bat`
  (gere o dump no Ubuntu com `scripts/exportar_dump_postgres_ubuntu.sh`)

## Arquivos

| Arquivo | Função |
|---------|--------|
| `INSTALAR_WINDOWS.bat` | Cria o `.venv`, instala dependências e o Firefox do Playwright |
| `RODAR_WINDOWS.bat` | Sobe o Django e abre o Firefox local |
| `CAPTURAR_COOKIES.bat` | Lê os cookies do Firefox local |
| `DIAGNOSTICO_WINDOWS.bat` | Mostra Firefox, perfil, cookies e Playwright |
| `ABRIR_FIREFOX_PROJUDI.bat` | Abre o Projudi no Firefox local |
| `env.windows.example` | Modelo de `.env` para Windows |
| `requirements-windows.txt` | Dependências do Windows |

## Ubuntu/Linux

Use `env.linux.example`, `requirements.txt` e:

```bash
python -m playwright install firefox
python manage.py migrate
python manage.py runserver
```

O mesmo código detecta o Firefox do Windows, do WSL ou do Linux.

## Portátil

Já existe uma pasta pronta em `D:\send_of_v4_portable_win` (Python embarcado +
Firefox do Playwright + banco copiado). Para regerar:

```powershell
.\scripts\montar_portatil_windows.ps1 -Destino "D:\send_of_v4_portable_win"
```
