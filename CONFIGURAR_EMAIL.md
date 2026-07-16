# CONFIGURAR E-MAIL - Send of v4

## PROBLEMA
O envio de oficios por e-mail esta funcionando, mas precisa da senha de app do Gmail.

## COMO CONFIGURAR

### 1. Criar Senha de App no Gmail
1. Acesse: https://myaccount.google.com/apppasswords
2. Faca login com a conta: pafonso.2vsj@gmail.com
3. Selecione "Outro (nome personalizado)"
4. Digite: "Send of v4"
5. Clique em "GERAR"
6. Copie a senha de 16 caracteres (exemplo: abcd efgh ijkl mnop)

### 2. Configurar no Sistema
Edite o arquivo `/home/ivan/PythonProjects/send_of_v4/.env`:

```
EMAIL_HOST_USER=pafonso.2vsj@gmail.com
EMAIL_HOST_PASSWORD=sua_senha_de_app_aqui
```

Ou configure via Django Admin (quando implementado).

### 3. Testar
Acesse: http://localhost:8000/projudi/oficios/dashboard/
- Clique em "Enviar" em um oficio pendente
- O sistema deve enviar o e-mail com sucesso

## O QUE JA ESTA FUNCIONANDO
✅ Sincronizacao com Projudi (70 oficios)
✅ Lista de oficios no dashboard
✅ Envio por e-mail (aguardando senha)
✅ Juntada no Projudi
✅ Logs humanizados
✅ Dashboard integrado
