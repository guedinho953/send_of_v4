# 🔐 02 — Sessão Projudi (JSESSIONID)

## Data: 2026-07-17

> **Atualização (Windows nativo):** os caminhos `/mnt/...` descritos abaixo
> eram do uso via WSL. No Windows nativo eles foram centralizados em
> `firefox_config.py` e o JSON fica em
> `%LOCALAPPDATA%\send_of_v4\cookies.json`. Veja
> [WINDOWS_FIREFOX.md](WINDOWS_FIREFOX.md). Os caminhos antigos continuam
> sendo aceitos na leitura.

---

## O Problema

O Projudi usa `JSESSIONID` — um cookie de sessão Java **sem data de expiração**.
Esse cookie fica APENAS na memória do navegador. Não é salvo no `cookies.sqlite`
do Firefox.

No WSL/Linux, o `browser_cookie3` lê o `cookies.sqlite`, então **NÃO ENCONTRA**
o JSESSIONID.

No Windows nativo, o `browser_cookie3` consegue descriptografar usando DPAPI
e encontra o JSESSIONID mesmo sendo cookie de sessão.

### Consequência

- `_get_session_from_cookies()` no WSL retorna sessão **sem JSESSIONID**
- O Projudi redireciona pro login → "Sessão expirou"
- A juntada de impossibilidade falha com "Formulario nao encontrado"

---

## A Solução: 4 Camadas de Captura

Implementado em `projudi/services.py:_get_session_from_cookies()`:

```
1. /mnt/d/Projudi/cookies.json         ← ARQUIVO (prioridade máxima)
       ↓ falhou
2. powershell.exe → capture_cookies... ← CHAMA WINDOWS para capturar
       ↓ falhou
3. browser_cookie3.firefox()           ← FALLBACK (só funciona Windows)
       ↓ falhou
4. ProjudiSession (banco)              ← ÚLTIMO recurso (provavelmente expirado)
```

### Camada 1 — Arquivo JSON

```python
caminhos = [
    Path('/mnt/d/Projudi/cookies.json'),
    Path('/mnt/c/Projudi/cookies.json'),
    Path.home() / '.projudi_cookies.json',
    Path('/tmp/projudi_cookies.json'),
]
```

Se encontra JSESSIONID → carrega, aquece sessão (GET no Projudi), retorna.

### Camada 2 — powershell.exe

Se o arquivo não tem JSESSIONID válido, tenta capturar NOVOS cookies:

```python
subprocess.run(
    ['powershell.exe', '-Command',
     'python "D:\\Projudi\\capture_cookies_windows.py" --quiet'],
    capture_output=True, text=True, timeout=30,
)
```

**⚠️ IMPORTANTE:** O script `capture_cookies_windows.py` PRECISA estar em
`D:\Projudi\` (acessível pelo Windows). Se estiver só no WSL
(`/home/ivan/...`), o `powershell.exe` não encontra.

```bash
# Copiar o script para o Windows:
cp scripts/capture_cookies_windows.py /mnt/d/Projudi/
```

### Camada 3 — browser_cookie3 (fallback)

```python
cj = browser_cookie3.firefox(domain_name='projudi.tjba.jus.br')
cookies_ff = {c.name: c.value for c in cj}
```

Só funciona no Windows nativo. No WSL não acha JSESSIONID.

### Camada 4 — ProjudiSession (banco Django)

Último recurso. O cookie JSESSIONID no banco provavelmente já expirou.

---

## Script de Captura (`capture_cookies_windows.py`)

### Funcionamento

O script lê o `cookies.sqlite` do Firefox **junto com os arquivos
`cookies.sqlite-wal` e `cookies.sqlite-shm`**. Isso é essencial quando o
Firefox está aberto: os cookies recém-criados podem estar apenas no WAL e
o `browser_cookie3` sozinho não os enxerga.

Pode rodar no Windows nativo ou no WSL. No WSL, além do perfil Linux, ele
procura os perfis do Firefox do Windows em
`/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite`
e grava em `/mnt/d/Projudi/cookies.json`.

```python
DOMAIN = 'projudi.tjba.jus.br'
OUTPUT_FILE = Path("D:/Projudi/cookies.json")

# Copia cookies.sqlite + -wal + -shm para uma pasta temporária
# e consulta a tabela moz_cookies.
cookies = _extract_firefox_sqlite()

# Fallback para cookies de sessão no sessionstore e outros navegadores.
if 'JSESSIONID' not in cookies:
    cookies.update(browser_cookie3.firefox(domain_name=DOMAIN))
```

### Modos de execução

| Modo | Comando | Comportamento |
|------|---------|---------------|
| Interativo | `python capture_cookies_windows.py` | Mostra output + keep-alive a cada 60s |
| Silencioso | `python capture_cookies_windows.py --quiet` | Captura e sai (usado pelo Django e pelo `.bat`) |

O `.bat` usa `%~dp0` e chama o `.py` com `--quiet`, então funciona mesmo
quando o cmd abre em outro diretório.

### BUG CORRIGIDO — cookies no WAL do Firefox

**Sintoma:** Firefox aberto e logado no Projudi, mas o script capturava
`0 cookies`; o `D:\Projudi\cookies.json` não era atualizado.

**Causa:** o `browser_cookie3` copia apenas o `cookies.sqlite` principal.
Com o Firefox aberto, o `JSESSIONID` recém-criado pode estar somente em
`cookies.sqlite-wal`. O banco principal fica sem nenhum cookie do Projudi.

**Correção:** o script agora copia `cookies.sqlite`, `-wal` e `-shm` antes
de consultar. Também exige `JSESSIONID` para gravar o JSON e retorna erro
se a sessão não estiver disponível.

### BUG CORRIGIDO — modo `--quiet`

**Problema:** Versão anterior entrava em `while True` mesmo com `--quiet`,
fazendo o subprocess.run timeout após 30s.

**Correção:** Modo `--quiet` agora retorna imediatamente após capturar.

```python
def main():
    quiet = '--quiet' in sys.argv
    cookies = capture_cookies(quiet=quiet)
    if not cookies:
        if quiet:
            return 1  # sai silenciosamente
    ...
    if not quiet:
        # Só entra em keep-alive no modo interativo
        while True:
            ...
```

---

## Keep-alive (Cron Job)

Para manter os cookies sempre frescos:

```bash
# Cron job Hermes (a cada 5 minutos)
~/.hermes/scripts/capturar_cookies_projudi.sh
```

O script chama:
```bash
powershell.exe -Command "python D:\\Projudi\\capture_cookies_windows.py --quiet"
```

**Pré-requisito:** Firefox DEVE estar aberto e logado no Projudi. Sem o Firefox
logado, o `browser_cookie3` não consegue capturar o JSESSIONID.

---

## Como usar (passo a passo)

1. Abra o Firefox
2. Faça login no Projudi
3. **Deixe o Firefox aberto**
4. Clique em **📨 Processar Pendentes** no dashboard

O sistema automaticamente:
- Tenta ler `D:\Projudi\cookies.json`
- Se expirado, chama `powershell.exe` → captura cookies novos
- Se conseguir JSESSIONID → junta impossibilidade no Projudi
- Se não conseguir → registra localmente com o motivo

---

## Pitfalls

1. **check_session() retorna True mesmo sem JSESSIONID válido**: Porque testa
   via bot (Firefox aberto), não via requests. Não confiar só no status.

2. **ADC_REQ e ADC_CONN não bastam**: São cookies de balanceamento F5. Sem
   JSESSIONID, o Projudi redireciona pro login.

3. **JSESSIONID expira rápido**: Se ficar muito tempo sem acessar o Projudi,
   expira no servidor. Precisa re-capturar com Firefox aberto.

4. **Rodar com o Firefox errado**: o Firefox logado no Projudi é o do
   Windows. O script procura esse perfil em `/mnt/c` quando roda no WSL.
   O `.bat` do projeto usa `%~dp0`, então funciona mesmo quando o cmd abre
   em outro diretório.

5. **Cópia em `D:\Projudi`**: o `powershell.exe` automático do
   `projudi/services.py` chama `D:\Projudi\capture_cookies_windows.py`.
   Mantenha essa cópia igual à de `scripts/` após alterar o script.

---

## Arquivos

| Arquivo | Função |
|---------|--------|
| `projudi/services.py` → `_get_session_from_cookies()` | 4 camadas de captura |
| `scripts/capture_cookies_windows.py` | Script de captura (Windows) |
| `scripts/capture_cookies.bat` | Atalho .bat manual |
| `/mnt/d/Projudi/cookies.json` | Arquivo de cookies (sincronia WSL↔Windows) |
| `~/.hermes/scripts/capturar_cookies_projudi.sh` | Cron job (a cada 5 min) |
