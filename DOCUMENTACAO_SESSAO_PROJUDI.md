# Documentacao: Sessao Projudi - Send of v4

## 1. Visao Geral do Sistema

O Send of v4 eh um sistema Django para cartorio judicial. Ele NAO faz login direto no Projudi. Em vez disso, o usuario faz login MANUAL no Firefox (Windows) e o Django CAPTURA os cookies da sessao ja ativa.

**Fluxo:**
```
[Firefox Windows] --login manual--> [Projudi TJBA]
        |
        | cookies ativos
        v
[WSL Linux/Django] --le cookies.sqlite--> [ProjudiSession]
        |
        | requests com cookies
        v
[Projudi TJBA] --dados---> [Django Dashboard]
```

---

## 2. Arquivos Criados/Modificados

### 2.1 Modelo de Sessao (`projudi/models.py`)

```python
class ProjudiSession(models.Model):
    user = ForeignKey(User)           # Quem sincronizou
    cookies = JSONField()              # Cookies capturados do Firefox
    status = CharField()               # active/expired/invalid
    tenant = ForeignKey(Tenant)        # Obrigatorio (multitenancy)
    session_data = JSONField()         # Metadados extras
    last_activity = DateTimeField()    # Auto-atualizado
```

**O campo `tenant` eh obrigatorio.** Por isso deu erro `NOT NULL constraint` antes de associar o admin a um tenant.

---

### 2.2 Bot de Captura (`projudi_bot.py`)

**Funcao principal:** Le o arquivo `cookies.sqlite` do Firefox Windows via WSL.

```python
import browser_cookie3
import sqlite3, shutil, tempfile

def get_cookies_from_browser(domain='projudi.tjba.jus.br'):
    # 1. Procura automaticamente perfil Firefox no Windows:
    win_profiles = glob.glob('/mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/*.default*')
    
    # 2. Copia cookies.sqlite para temp (evita lock do Firefox)
    shutil.copy2(db_path, tmp.name)
    
    # 3. Le cookies com host contendo 'projudi'
    SELECT name, value FROM moz_cookies WHERE host LIKE '%projudi%'
    
    # 4. Retorna dict {nome: valor}
```

**User-Agent critico:** O bot copia o User-Agent exato do Firefox para o Projudi nao detectar que eh um script:
```python
"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
```

---

### 2.3 Servico Django (`projudi/services.py`)

```python
class ProjudiService:
    def __init__(self, user):
        # Detecta automaticamente o perfil Firefox
        self.profile_path = '/mnt/c/Users/.../Firefox/Profiles/xxx.default-release'
    
    def check_session(self):
        # Cria sessao HTTP e testa se consegue acessar Projudi
        bot.criar_sessao()
        return bot.testar_login()  # True/False
```

---

### 2.4 Views Django (`projudi/views.py`)

**SyncSessionView:**
```python
class SyncSessionView(View):
    def get(self, request):
        1. Instancia ProjudiService(request.user)
        2. Bot captura cookies do Firefox
        3. Testa se consegue acessar Projudi
        4. Salva/atualiza no banco (ProjudiSession)
        5. Inicia thread de keep-alive
        6. Redireciona com mensagem de sucesso
```

---

### 2.5 URLs (`projudi/urls.py`)

| URL | View | Descricao |
|-----|------|-----------|
| `/projudi/sessao/` | SyncSessionTemplateView | Pagina HTML com instrucoes |
| `/projudi/sessao/sincronizar/` | SyncSessionView | Captura cookies (GET) |
| `/projudi/sessao/status/` | SessionStatusView | Retorna JSON com status |
| `/projudi/movimentacoes/` | MovimentacoesListView | Lista movimentacoes |
| `/projudi/oficios/` | OficiosListView | Lista oficios |

---

### 2.6 Templates HTML

- `templates/projudi/sync_session.html` - Pagina de sincronizacao
- `templates/projudi/movimentacoes_list.html` - Lista movimentacoes
- `templates/projudi/oficios_list.html` - Lista oficios

---

## 3. Comandos Linux/WSL Usados

### 3.1 Verificar perfil Firefox
```bash
ls /mnt/c/Users/*/AppData/Roaming/Mozilla/Firefox/Profiles/
# Retorno: akugmqxq.default-release (perfil encontrado)
```

### 3.2 Verificar cookies.sqlite
```bash
ls /mnt/c/Users/ivan/AppData/Roaming/Mozilla/Firefox/Profiles/akugmqxq.default-release/cookies.sqlite
# Retorno: 524288 bytes (arquivo existe e tem dados)
```

### 3.3 Contar cookies do Projudi
```bash
# Via Python shell:
sqlite3 cookies.sqlite
SELECT COUNT(*) FROM moz_cookies WHERE host LIKE '%projudi%';
# Retorno: 12 cookies do Projudi no Firefox
```

### 3.4 Subir servidor Django
```bash
cd /home/ivan/PythonProjects/send_of_v4
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000 --noreload
```

### 3.5 Verificar servidor rodando
```bash
lsof -ti:8000          # mostra PID ou vazio
ss -tlnp | grep :8000  # mostra processo ou nada
curl -s http://127.0.0.1:8000/ | head  # testa se responde
```

### 3.6 Verificar sessao no banco
```bash
python manage.py shell -c "
from projudi.models import ProjudiSession
s = ProjudiSession.objects.first()
print(s.status, s.cookies)
"
# Retorno: active, {'ADC_CONN_xxx': '...', 'ADC_REQ_xxx': '...'}
```

---

## 4. Depuracao - Erros Encontrados e Solucoes

### Erro 1: `NoReverseMatch` no Dashboard
**Causa:** Faltava URL `list` no app `processes`.
**Solucao:** Criou `processes/urls.py` com `app_name='processes'` e path com `name='list'`.

### Erro 2: `No changes detected` no makemigrations
**Causa:** Pastas `migrations/` sem `__init__.py`.
**Solucao:**
```bash
for app in accounts base projudi processes ...; do
    touch "$app/migrations/__init__.py"
done
```

### Erro 3: `NOT NULL constraint failed: projudi_projudisession.tenant_id`
**Causa:** O usuario admin nao tinha `tenant` associado.
**Solucao:**
```python
from accounts.models import Tenant, User
tenant = Tenant.objects.create(name='Default', cnpj='00.000.000/0000-00', role='cartorio')
user.tenant = tenant
user.save()
```

### Erro 4: `browser_cookie3` nao encontrava Firefox
**Causa:** Procurava em `~/.mozilla/firefox/` (Linux), mas o Firefox estava no Windows.
**Solucao:** Implementou leitura direta do `cookies.sqlite` em `/mnt/c/Users/.../Firefox/Profiles/`.

### Erro 5: Servidor morria ao fechar terminal
**Causa:** WSL encerra processos foreground ao fechar terminal.
**Solucao:** Usar `nohup` ou deixar terminal aberto com `--noreload`.

---

## 5. Fluxo Completo de Uso

### Passo 1: Preparar Firefox
1. Abra Firefox no **Windows**
2. Acesse `https://projudi.tjba.jus.br/projudi/`
3. Faca login com usuario e senha do tribunal
4. **Deixe o Firefox aberto** (cookies precisam estar ativos)

### Passo 2: Sincronizar no Django
1. No navegador, acesse `http://172.24.13.245:8000/projudi/sessao/`
   (ou `http://localhost:8000/projudi/sessao/` se no mesmo PC)
2. Clique em **"Sincronizar Sessao com Firefox"**
3. O Django:
   - Le `cookies.sqlite` do perfil Windows
   - Encontra 2 cookies do Projudi
   - Testa acessar a URL do Projudi
   - Salva no banco como `status='active'`

### Passo 3: Verificar no Admin
1. Va em `http://172.24.13.245:8000/admin/projudi/projudisession/`
2. Deve aparecer a sessao do `igusilva@tjba.jus.br`
3. Status: **Ativa**, Cookies: 2 chaves

### Passo 4: Usar Movimentacoes
1. Va em `http://172.24.13.245:8000/projudi/movimentacoes/`
2. O sistema usa os cookies para fazer requests ao Projudi
3. Retorna lista de movimentacoes pendentes

---

## 6. Arquitetura Tecnica

### Componentes
| Componente | Tecnologia | Funcao |
|------------|-----------|--------|
| Django 6.0.7 | Python | Framework web |
| SQLite | Banco | Armazena sessoes e dados |
| browser_cookie3 | Lib Python | Interface para ler cookies |
| sqlite3 | Nativo Python | Le cookies.sqlite direto |
| requests | Lib Python | HTTP com cookies capturados |
| Selenium (implicito) | Bot legado | Usado pelo ProjudiBot original |
| WSL | Linux no Windows | Onde Django roda |
| Firefox | Navegador | Login manual no Projudi |

### Modelo de Dados
```
accounts.Tenant (1)
    |
    +-- accounts.User (N)
            |
            +-- projudi.ProjudiSession (1:1)
                    - cookies: JSON
                    - status: active/expired/invalid
                    - tenant: FK obrigatoria
```

---

## 7. Scripts Python Completos

### 7.1 Bot (projudi_bot.py) - Resumido
```python
class ProjudiBot:
    BASE_URL = "https://projudi.tjba.jus.br/projudi/cadastros/AnalisarMovimentacao"
    
    def __init__(self, browser='auto', profile_path=None):
        self.session = requests.Session()
        self.browser = browser
        self.profile_path = profile_path
    
    def get_cookies(self):
        # Le cookies.sqlite do Firefox Windows via WSL
        return get_cookies_from_browser(
            domain='projudi.tjba.jus.br',
            profile_path=self.profile_path
        )
    
    def criar_sessao(self):
        # Headers idênticos ao Firefox
        self.session.headers.update({...})
        cookies = self.get_cookies()
        self.session.cookies.update(cookies)
        return self.session
    
    def testar_login(self):
        # Acessa URL protegida e verifica se nao redirecionou para login
        r = self.session.get(self.BASE_URL)
        return "login" not in r.url.lower()
    
    def iniciar_keep_alive(self):
        # Thread que pinga a cada 60s para manter sessao
        threading.Thread(target=self._loop_keep_alive, daemon=True).start()
```

### 7.2 View de Sincronizacao (projudi/views.py)
```python
class SyncSessionView(View):
    def get(self, request):
        service = ProjudiService(request.user)
        bot = service.get_bot()
        bot.criar_sessao()
        
        if bot.testar_login():
            # Sucesso: salva no banco
            ProjudiSession.objects.update_or_create(
                user=request.user,
                defaults={
                    'cookies': bot.exportar_cookies(),
                    'status': 'active',
                    'tenant': request.user.tenant,  # OBRIGATORIO
                }
            )
            bot.iniciar_keep_alive()
```

---

## 8. Restricoes e Limitacoes

1. **Firefox deve estar aberto:** Se fechar o Firefox, os cookies podem expirar
2. **Login manual obrigatorio:** O sistema NAO automatiza login/senha
3. **WSL = Linux:** O Django roda em WSL, mas le arquivos do Windows via `/mnt/c/`
4. **IP diferente:** O navegador pode precisar usar o IP WSL (`172.24.13.245`) em vez de `localhost`
5. **Keep-alive limitado:** A thread pinga a cada 60s, mas o Projudi pode expirar por inatividade real

---

## 9. Comandos Rápidos (Cheatsheet)

```bash
# Ativar venv
cd /home/ivan/PythonProjects/send_of_v4
source .venv/bin/activate

# Subir servidor
python manage.py runserver 0.0.0.0:8000 --noreload

# Shell Django
python manage.py shell

# Verificar sessoes
from projudi.models import ProjudiSession
ProjudiSession.objects.all()

# Verificar usuarios
from accounts.models import User
User.objects.all()

# Criar tenant
from accounts.models import Tenant
Tenant.objects.create(name='Meu Cartorio', cnpj='12.345.678/0001-90')

# Associar tenant
u = User.objects.get(email='igusilva@tjba.jus.br')
u.tenant = Tenant.objects.first()
u.save()
```

---

## 10. URLs Importantes

| URL | Descricao |
|-----|-----------|
| `http://172.24.13.245:8000/` | Landing page |
| `http://172.24.13.245:8000/admin/` | Admin Django |
| `http://172.24.13.245:8000/dashboard/` | Dashboard principal |
| `http://172.24.13.245:8000/projudi/sessao/` | Sincronizar sessao |
| `http://172.24.13.245:8000/projudi/movimentacoes/` | Movimentacoes |
| `http://172.24.13.245:8000/projudi/oficios/` | Oficios |
| `http://172.24.13.245:8000/accounts/login/` | Login do sistema |
| `http://172.24.13.245:8000/accounts/profile/` | Perfil do usuario |

---

**Documento gerado em:** 2026-07-09
**Projeto:** Send of v4
**Autor:** Hermes Agent
**Versao:** 1.0
