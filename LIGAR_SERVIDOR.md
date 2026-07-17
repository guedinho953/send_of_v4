# 🚀 Ligar o servidor Django

## 1. Subir o PostgreSQL (container original)
```bash
docker start pg_send_of
```

Se precisar recriar:
```bash
docker run -d --name pg_send_of \
  -e POSTGRES_USER=send_of \
  -e POSTGRES_PASSWORD=send_of \
  -e POSTGRES_DB=sccj \
  -v send_of_v4_pgdata:/var/lib/postgresql/data \
  -p 5433:5432 \
  postgres:16
```

## 2. Subir o Django
```bash
cd ~/PythonProjects/send_of_v4
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000
```

Acessar: http://localhost:8000

---

### Login
- Email: `admin@admin.com` (ou o que você criou)
- Senha: a mesma de antes

---

### Comando único:
```bash
docker start pg_send_of && cd ~/PythonProjects/send_of_v4 && source .venv/bin/activate && python manage.py runserver 0.0.0.0:8000
```
