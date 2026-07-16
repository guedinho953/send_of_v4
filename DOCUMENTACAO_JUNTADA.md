# Documentacao Completa: Juntada sem Selenium no Projudi

## Sumario
1. [O que mudou e por que](#1-o-que-mudou-e-por-que)
2. [Arquitetura da Juntada via Requests](#2-arquitetura-da-juntada-via-requests)
3. [Fluxo Passo a Passo](#3-fluxo-passo-a-passo)
4. [Codigo Implementado](#4-codigo-implementado)
5. [Instalacao do Firefox + GeckoDriver](#5-instalacao-do-firefox--geckodriver)
6. [Possibilidade Futura: Juntar Documentos](#6-possibilidade-futura-juntar-documentos)
7. [O que voce precisa saber para ser um profissional melhor](#7-o-que-voce-precisa-saber-para-ser-um-profissional-melhor)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. O que mudou e por que

### Antes (com Selenium)
```
Selenium -> abre Firefox -> navega ate pagina -> preenche campos -> clica botoes -> aceita alerta
```
**Problemas:**
- Firefox precisa estar com interface grafica (ou headless complicado)
- geckodriver + Firefox + WSL = problemas de compatibilidade
- Sessao do Selenium != sessao do requests (cookies nao compartilham automaticamente)
- Lento (abre navegador, renderiza pagina, espera elementos)

### Agora (via Requests)
```
Requests -> GET pagina (com cookies salvos) -> extrai formulario -> POST com dados
```
**Vantagens:**
- Usa MESMA sessao do usuario (mesmos cookies JSESSIONID)
- Nao precisa de interface grafica
- 10x mais rapido
- Mais confiavel (sem race conditions do navegador)

---

## 2. Arquitetura da Juntada via Requests

### Componentes

```
Usuario logado no Firefox (Windows)
    |
    v
scripts/capture_cookies_windows.py  ->  cookies.json (D:/Projudi/)
    |
    v
Django (WSL) le cookies.json  ->  ProjudiSession (banco)
    |
    v
OficioService.juntar_cumprimento()  ->  requests.Session (com cookies)
    |
    v
POST para Projudi  ->  Juntada realizada!
```

### Arquivos envolvidos

| Arquivo | Papel |
|---------|-------|
| `projudi/oficio_service.py` | Logica principal da juntada |
| `projudi/services.py` | Sessao HTTP com cookies salvos |
| `projudi/models.py` | OficioRecord (guarda URL recebimento) |
| `exemplo_refatoracao_oo.py` | Configuracao (codigo 581) |
| `pipeline_orchestrator.py` | Configuracao (codigo 581) |

---

## 3. Fluxo Passo a Passo

### Etapa 1: Capturar Cookies (Windows)
```bash
# No Windows, com Firefox aberto e logado no Projudi:
python D:\Projudi\capture_cookies_windows.py
```
Gera: `D:\Projudi\cookies.json`

### Etapa 2: Sincronizar com Django
```bash
# No WSL:
python manage.py sync_cookies  # ou via dashboard
```
Salva cookies no banco: `ProjudiSession`

### Etapa 3: Juntada Automatica
```python
# oficio_service.py

1. Pega sessao requests com cookies do banco
   session = requests.Session()
   for name, value in cookies.items():
       session.cookies.set(name, value)

2. Acessa URL de recebimento
   resp = session.get(url_recebimento)

3. Extrai formulario HTML
   soup = BeautifulSoup(resp.text, 'html.parser')
   form = soup.find('form')

4. Monta payload com inputs hidden + campos
   payload = {}
   for inp in form.find_all('input'):
       payload[inp['name']] = inp.get('value', '')
   
   payload['seqCategoriaMovimentacao'] = '11383'  # Codigo do oficio
   payload['observacao'] = 'Enviado por email...'

5. Envia POST
   resp = session.post(post_url, data=payload)

6. Verifica sucesso (HTTP 200 + sem redirecionamento)
```

---

## 4. Codigo Implementado

### 4.1. `projudi/oficio_service.py` - Metodo principal

```python
def juntar_cumprimento(self, record: OficioRecord) -> bool:
    """Realiza juntada via requests (mesma sessao do usuario)."""
    
    try:
        sucesso = self._juntar_via_requests(record)
        if sucesso:
            record.status = 'juntado'
            record.save()
            self._log(record, 'juntada', 
                f"Juntada realizada no Projudi. Oficio {record.numero_oficio} cumprido.")
            return True
    except Exception as e:
        self._log(record, 'erro_juntada', f"Erro: {e}")
    
    record.status = 'falhou_juntada'
    record.save()
    return False
```

### 4.2. `projudi/oficio_service.py` - Metodo privado `_juntar_via_requests`

```python
def _juntar_via_requests(self, record: OficioRecord) -> bool:
    """
    Juntada via requests seguindo fluxo do enviar.ipynb:
    1. GET url_recebimento (com cookies)
    2. Extrai form + inputs hidden
    3. Preenche codigo 11383 + observacao
    4. POST para concluir
    """
    from bs4 import BeautifulSoup
    import time

    # 1. Pega sessao com cookies do banco
    result = self.projudi_service._get_session_from_cookies()
    if result is None:
        raise Exception("Sessao nao disponivel")
    session, _ = result

    # 2. Acessa pagina de recebimento
    resp = session.get(record.url_recebimento, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")

    # Verifica se nao foi redirecionado para login
    if 'login' in resp.url.lower():
        raise Exception("Sessao expirada")

    # 3. Parse do formulario HTML
    soup = BeautifulSoup(resp.text, 'html.parser')
    form = soup.find('form')
    if not form:
        raise Exception("Formulario nao encontrado")

    # Extrai action do form
    action = form.get('action', '')
    if action.startswith('/'):
        post_url = f"https://projudi.tjba.jus.br{action}"
    else:
        post_url = record.url_recebimento

    # 4. Monta payload com todos os inputs hidden
    payload = {}
    for inp in form.find_all('input'):
        name = inp.get('name')
        value = inp.get('value', '')
        if name:
            payload[name] = value

    # 5. Adiciona codigo da movimentacao (11383 = Cumprimento de Oficio)
    payload['seqCategoriaMovimentacao'] = '11383'

    # 6. Adiciona observacao
    data_envio = record.data_envio.strftime('%d/%m/%Y') if record.data_envio else ''
    hora_envio = record.hora_envio.strftime('%H:%M:%S') if record.hora_envio else ''
    payload['observacao'] = (
        f"Enviado por email o Oficio- {record.numero_oficio} "
        f"em {data_envio} as {hora_envio}, "
        f"para: {record.email_destino}, link: {record.url_oficio}"
    )

    # 7. Faz POST
    time.sleep(1)  # delay humano
    resp_post = session.post(post_url, data=payload, timeout=15)

    # 8. Verifica sucesso
    return resp_post.status_code == 200
```

### 4.3. `exemplo_refatoracao_oo.py` - Configuracao

```python
class ProjudiConfig:
    link_base: str = 'https://projudi.tjba.jus.br/projudi/'
    codigo_juntada: str = '11383'  # Cumprimento de Oficio
```

---

## 5. Instalacao do Firefox + GeckoDriver

### Ja instalado no WSL:

```bash
# Firefox ESR (versao para servidores)
/opt/firefox-esr/firefox --version
# Mozilla Firefox 140.12.0esr

# GeckoDriver (driver para Selenium)
~/.local/bin/geckodriver --version
# geckodriver 0.35.0
```

### Como foi instalado:

```bash
# 1. Baixou geckodriver
cd /tmp
curl -L "https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-linux64.tar.gz" -o geckodriver.tar.gz
tar -xzf geckodriver.tar.gz

# 2. Moveu para PATH
mkdir -p ~/.local/bin
mv geckodriver ~/.local/bin/
chmod +x ~/.local/bin/geckodriver
```

---

## 6. Possibilidade Futura: Juntar Documentos

### O que ja temos:
- Sessao HTTP autenticada com cookies
- Parser de formularios HTML
- Sistema de POST com payload

### Para juntar documentos no futuro:

```python
# Exemplo de como seria:

def juntar_documento(self, record, arquivo_pdf_path, descricao):
    """
    Juntar PDF no processo (futuro)
    
    Passos:
    1. GET pagina de juntada (igual ao recebimento)
    2. Extrai formulario
    3. Adiciona arquivo com multipart/form-data
    4. POST com files + dados
    """
    
    session = self.get_session()
    
    # GET formulario
    resp = session.get(record.url_recebimento)
    soup = BeautifulSoup(resp.text, 'html.parser')
    form = soup.find('form')
    
    # Monta dados
    data = {}
    for inp in form.find_all('input'):
        if inp.get('name'):
            data[inp['name']] = inp.get('value', '')
    
    # Adiciona arquivo
    with open(arquivo_pdf_path, 'rb') as f:
        files = {'arquivo': ('documento.pdf', f, 'application/pdf')}
        resp = session.post(post_url, data=data, files=files)
    
    return resp.status_code == 200
```

### O que precisaria adicionar:

1. **Campo no modelo**:
```python
class OficioRecord(models.Model):
    # ... campos existentes ...
    documento_pdf = models.FileField(upload_to='documentos/', blank=True, null=True)
```

2. **View para upload**:
```python
# views.py
class OficioUploadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        oficio = OficioRecord.objects.get(pk=pk)
        arquivo = request.FILES['arquivo']
        oficio.documento_pdf = arquivo
        oficio.save()
        
        # Chama juntada com arquivo
        service = OficioService(request.user)
        service.juntar_documento(oficio, arquivo.path)
```

3. **Template com upload**:
```html
<form method="post" enctype="multipart/form-data">
    <input type="file" name="arquivo" accept=".pdf">
    <button type="submit">Juntar Documento</button>
</form>
```

---

## 7. O que voce precisa saber para ser um profissional melhor

### 7.1. Conceitos Fundamentais

#### HTTP Request vs Browser Automation

| | Requests | Selenium |
|--|----------|----------|
| **O que faz** | Envia HTTP direto | Controla navegador |
| **Velocidade** | Rapido | Lento |
| **Confiabilidade** | Alta | Media (race conditions) |
| **Sessao** | Mesma sessao do usuario | Sessao separada |
| **Quando usar** | APIs, formularios simples | Paginas complexas, JS heavy |

#### Cookies e Sessao

```
Cookie = identidade do usuario no servidor
JSESSIONID = sessao Java do Projudi

Quando voce faz login no Firefox:
  Servidor -> Set-Cookie: JSESSIONID=abc123
  Firefox -> Guarda cookie
  Proxima requisicao -> Cookie: JSESSIONID=abc123
  Servidor -> "Ah, e o Ivan logado"

Requests com cookie:
  session.cookies.set('JSESSIONID', 'abc123')
  session.get(url)  ->  Servidor reconhece como Ivan logado
```

#### Formularios HTML

```html
<form action="/projudi/movimentacao/MovimentarProcesso" method="POST">
    <input type="hidden" name="codDocVinculado" value="5984298">
    <input type="hidden" name="codGrupo" value="46">
    <input type="text" name="seqCategoriaMovimentacao" value="">
    <textarea name="observacao"></textarea>
    <input type="submit" value="Concluir">
</form>
```

```python
# Extrair automaticamente:
soup = BeautifulSoup(html, 'html.parser')
form = soup.find('form')

payload = {}
for inp in form.find_all(['input', 'textarea']):
    name = inp.get('name')
    if name:
        payload[name] = inp.get('value', '')

# Resultado:
# payload = {
#     'codDocVinculado': '5984298',
#     'codGrupo': '46',
#     'seqCategoriaMovimentacao': '',
#     'observacao': ''
# }
```

### 7.2. Padroes Profissionais

#### Nunca hardcode URLs
```python
# RUIM:
resp = requests.get('https://projudi.tjba.jus.br/projudi/movimentacao/MovimentarProcesso?numeroProcesso=123')

# BOM:
BASE_URL = 'https://projudi.tjba.jus.br/projudi'
resp = requests.get(f'{BASE_URL}/movimentacao/MovimentarProcesso', params={'numeroProcesso': '123'})
```

#### Sempre tratar erros
```python
try:
    resp = session.get(url, timeout=15)
    resp.raise_for_status()  # Levanta excecao se HTTP >= 400
except requests.exceptions.Timeout:
    print("Servidor demorou muito")
except requests.exceptions.ConnectionError:
    print("Sem internet")
except requests.exceptions.HTTPError as e:
    print(f"Erro HTTP: {e}")
```

#### Logging em vez de print
```python
import logging
logger = logging.getLogger(__name__)

# Em vez de:
print("Enviado com sucesso")

# Use:
logger.info("Email enviado", extra={'oficio': numero_oficio, 'destino': email})
```

#### Separation of Concerns
```python
# Cada classe faz UMA coisa:

class ProjudiSessionManager:
    """Gerencia cookies e sessao HTTP"""
    
class OficioExtractor:
    """Extrai dados de HTML"""
    
class OficioService:
    """Orquestra o fluxo completo"""
    
class OficioRecord:
    """Modelo de dados (banco)"""
```

### 7.3. Ferramentas que voce deve conhecer

| Ferramenta | Para que serve | Quando usar |
|------------|---------------|-------------|
| `requests` | HTTP cliente | APIs, formularios |
| `BeautifulSoup` | Parser HTML | Extrair dados de paginas |
| `lxml` | Parser XML/HTML rapido | Grandes volumes |
| `httpie` | Testar APIs no terminal | Debug rapido |
| `curl` | Transferencia de dados | Scripts shell |
| `Postman` | Testar APIs visualmente | Desenvolvimento |
| `Charles/Fiddler` | Interceptar HTTP | Debug de cookies/sessao |

### 7.4. Como debugar problemas de sessao

```python
# 1. Verificar cookies
print(session.cookies.get_dict())

# 2. Verificar redirecionamentos
resp = session.get(url, allow_redirects=False)
print(resp.status_code)  # 302 = redirect
print(resp.headers['Location'])  # Para onde redirecionou

# 3. Verificar se esta logado
if 'login' in resp.url:
    print("DESLOGADO!")
elif 'sessao' in resp.text.lower():
    print("SESSAO EXPIRADA!")

# 4. Salvar HTML para inspecionar
with open('debug.html', 'w') as f:
    f.write(resp.text)
```

### 7.5. Seguranca

#### Nunca commite credenciais
```python
# settings.py
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')  # BOM
EMAIL_HOST_PASSWORD = 'senha123'  # RUIM - NUNCA FAÇA ISSO
```

#### Use .env
```bash
# .env
EMAIL_HOST_USER=pafonso.2vsj@gmail.com
EMAIL_HOST_PASSWORD=sua_senha_de_app
```

```python
# settings.py
from dotenv import load_dotenv
load_dotenv()

EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
```

---

## 8. Troubleshooting

### Problema: "Sessao expirada"
**Causa:** Cookies do Projudi expiram apos ~30 minutos de inatividade
**Solucao:**
```bash
# Windows - recapturar cookies:
python D:\Projudi\capture_cookies_windows.py

# WSL - sincronizar:
python manage.py sync_cookies
```

### Problema: "Formulario nao encontrado"
**Causa:** Pagina de recebimento mudou ou oficio ja foi juntado
**Solucao:**
```python
# Verificar se pagina tem form
soup = BeautifulSoup(resp.text, 'html.parser')
if not soup.find('form'):
    print("Oficio ja processado ou pagina invalida")
```

### Problema: "HTTP 500"
**Causa:** Erro no servidor do Projudi
**Solucao:** Aguardar 5 minutos e tentar novamente

### Problema: Firefox nao abre no WSL
**Causa:** WSL nao tem interface grafica por padrao
**Solucao:**
```bash
# Usar modo headless (sem interface)
firefox --headless

# Ou instalar WSLg (Windows 11)
# https://github.com/microsoft/wslg
```

---

## Checklist de Manutencao

- [ ] Recapturar cookies toda manha (expiram)
- [ ] Verificar logs de erro no Django
- [ ] Monitorar oficios com status "falhou_juntada"
- [ ] Atualizar geckodriver quando atualizar Firefox
- [ ] Fazer backup do banco SQLite regularmente

---

## Proximos Passos Recomendados

1. **Testar juntada real** com oficio 096/2026- SEC
2. **Configurar email** no .env (EMAIL_HOST_PASSWORD)
3. **Agendar cron job** para sincronizar cookies automaticamente
4. **Implementar upload de documentos** (secao 6)
5. **Criar testes automatizados** para o fluxo

---

*Documentacao gerada em 10/07/2026*
*Para o projeto send_of_v4 - Cartorio Digital*
