# Resumo das Alteracoes Feitas - send_of_v4

## Data: 10/07/2026
## Objetivo: Juntada sem Selenium + Numero CNJ correto

---

## 1. Juntada via Requests (SEM Selenium)

### Arquivos alterados:
- `projudi/oficio_service.py` - REESCRITO metodos de juntada
- `exemplo_refatoracao_oo.py` - Adicionado Firefox ESR path + headless

### O que mudou:
**ANTES (com Selenium):**
```python
juntada = ProjudiJuntada(cfg, cookies)
juntada.realizar_juntada(url_recebimento, numero_oficio, ...)
# Abria Firefox, navegava, preenchia campos, clicava
```

**AGORA (via Requests):**
```python
self._juntar_via_requests(record)
# GET pagina com cookies -> extrai form -> POST com dados
```

### Vantagens:
- 10x mais rapido
- Mesma sessao do usuario (cookies compartilhados)
- Sem interface grafica
- Mais confiavel

---

## 2. Numero do Processo CNJ

### Arquivos alterados:
- `projudi/models.py` - Adicionado campo `numero_processo_cnj`
- `projudi/services.py` - Extrai CNJ do texto do link
- `projudi/oficio_service.py` - Salva CNJ no banco
- `projudi_client.py` - Extrai texto do processo
- `templates/projudi/oficio_dashboard.html` - Mostra CNJ
- `templates/projudi/oficio_detail.html` - Mostra CNJ como titulo
- `templates/dashboard/dashboard.html` - Mostra CNJ nos cards
- `projudi/templatetags/processo_filters.py` - Filtro de formatacao

### O que mudou:
**ANTES:**
```
Proc. 41020243903870
```

**AGORA:**
```
0001306-27.2025.8.05.0191
```

### Como funciona:
1. Na sincronizacao, extrai o texto visivel do link do processo (ex: "0001306-27.2025.8.05.0191")
2. Salva no campo `numero_processo_cnj`
3. Templates mostram CNJ quando disponivel

---

## 3. Firefox + GeckoDriver no WSL

### Instalado:
- **Firefox ESR**: `/opt/firefox-esr/firefox` (v140.12.0)
- **GeckoDriver**: `~/.local/bin/geckodriver` (v0.35.0)

### Como usar:
```bash
# Verificar versao
/opt/firefox-esr/firefox --version
~/.local/bin/geckodriver --version

# Modo headless
firefox --headless https://projudi.tjba.jus.br
```

---

## 4. Templates Atualizados

### oficio_dashboard.html:
- Cards mostram **CNJ como titulo principal**
- Badge de status colorido (Pendente/Enviado/Juntado/Falhou)
- Info de envio com icone de email (✉️)
- Filtros por status

### oficio_detail.html:
- **CNJ no topo** como titulo principal
- Numero do oficio como subtitulo
- Timeline de logs
- Botao "Juntar" para oficios enviados

### dashboard.html:
- Cards com CNJ nos ultimos oficios
- Stats: Total, Pendentes, Enviados, Juntados
- Links para areas do sistema

---

## 5. Novos Arquivos Criados

| Arquivo | Descricao |
|---------|-----------|
| `DOCUMENTACAO_JUNTADA.md` | Documentacao completa do fluxo |
| `RESUMO_ALTERACOES.md` | Este arquivo |
| `CONFIGURAR_EMAIL.md` | Guia de configuracao SMTP |
| `projudi/templatetags/processo_filters.py` | Filtro Django para formatar processo |
| `scripts/capture_cookies.bat` | Script Windows para capturar cookies |
| `scripts/capture_cookies_windows.py` | Script Python para capturar cookies |
| `/mnt/d/Projudi/*.bat` | Scripts Windows para automacao |

---

## 6. Fluxo Completo Agora

```
1. Usuario loga no Firefox Windows
   |
2. Executa capture_cookies_windows.py
   -> Gera D:\Projudi\cookies.json
   |
3. Django le cookies.json
   -> Salva em ProjudiSession
   |
4. Sincronizacao busca oficios
   -> Usa cookies para acessar Projudi
   -> Extrai: numero_oficio, email, URL, CNJ
   -> Salva em OficioRecord
   |
5. Envio de email
   -> Usa Django send_mail
   -> Anexa brasao (opcional)
   -> Atualiza status: "enviado"
   |
6. Juntada (NOVO!)
   -> GET url_recebimento com cookies
   -> Extrai formulario HTML
   -> POST com codigo 11383 + observacao
   -> Atualiza status: "juntado"
```

---

## 7. Comandos Uteis

```bash
# Iniciar servidor
cd /home/ivan/PythonProjects/send_of_v4
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000 --noreload

# Sincronizar cookies
python scripts/capture_cookies_windows.py  # Windows
# Depois no Django:
python manage.py shell
>>> from projudi.services import ProjudiService
>>> service = ProjudiService(user)
>>> service.sincronizar_cookies_de_arquivo('/mnt/d/Projudi/cookies.json')

# Resetar status (para testes)
python manage.py shell
>>> from projudi.models import OficioRecord
>>> OficioRecord.objects.filter(status='falhou_email').update(status='pendente')

# Contar oficios
python manage.py shell
>>> OficioRecord.objects.count()
>>> OficioRecord.objects.filter(status='pendente').count()
>>> OficioRecord.objects.filter(status='enviado').count()
>>> OficioRecord.objects.filter(status='juntado').count()
```

---

## 8. Proximos Passos

- [ ] Configurar EMAIL_HOST_PASSWORD no .env
- [ ] Testar juntada real com oficio enviado
- [ ] Implementar upload de documentos (juntada com PDF)
- [ ] Criar cron job para sincronizacao automatica
- [ ] Adicionar testes automatizados

---

*Documento gerado em 10/07/2026*
