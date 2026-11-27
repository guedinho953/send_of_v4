import os
from pathlib import Path

import environ

# Playwright síncrono roda dentro de um event loop; permite que o fluxo de
# juntada/assinatura grave os logs e o status no banco sem SynchronousOnlyOperation.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', '1')

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
)

environ.Env.read_env(BASE_DIR / '.env')

# Chave de desenvolvimento usada somente quando .env não existe (ex.: primeiro
# start em uma máquina nova). Em produção, defina SECRET_KEY no .env.
SECRET_KEY = env('SECRET_KEY', default='django-insecure-send-of-local-dev')

DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list(
    'ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_REDIRECT_EXEMPT = [r'^health/$']


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 'django.contrib.postgres' só é necessário se o projeto usar campos
    # específicos do PostgreSQL (ArrayField, HStore, SearchVector...). O uso
    # local no Windows é SQLite; mantê-lo aqui exigiria psycopg2 instalado.
    # Third-party
    'whitenoise.runserver_nostatic',
    # Local apps
    'base',
    'core',
    'accounts',
    'projudi',
    'processes',
    'commands',
    'compliances',
    'documents',
    'emails_app',
    'vector_store',
    'ai',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'base.middleware.TenantMiddleware',
    'base.middleware.FilePermissionMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


DATABASES = {
    'default': env.db('DATABASE_URL', default='postgres://postgres:postgres@db:5432/sccj')
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
]

AUTH_USER_MODEL = 'accounts.User'

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# A pasta 'static' pode não existir em um clone limpo; o Django só aceita
# caminhos existentes em STATICFILES_DIRS.
STATICFILES_DIRS = [
    pasta for pasta in [BASE_DIR / 'static'] if pasta.exists()
]
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'landing'


CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='amqp://guest:guest@rabbitmq:5672//')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE


EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')


OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
QWEN_MODEL_PATH = env('QWEN_MODEL_PATH', default='')
QWEN_SERVER_URL = env('QWEN_SERVER_URL', default='http://localhost:8080')

# ---------------------------------------------------------------------------
# Firefox local / Projudi (Windows nativo, WSL ou Linux)
# ---------------------------------------------------------------------------
# Deixe FIREFOX_PATH/FIREFOX_PROFILE vazios para a detecção automática.
FIREFOX_PATH = env('FIREFOX_PATH', default='')
FIREFOX_PROFILE = env('FIREFOX_PROFILE', default='')
PROJUDI_COOKIES_FILE = env('PROJUDI_COOKIES_FILE', default='')
PROJUDI_DOMAIN = env('PROJUDI_DOMAIN', default='projudi.tjba.jus.br')

# Automação (Playwright). Por padrão abre o Firefox visível.
PLAYWRIGHT_HEADLESS = env.bool('PLAYWRIGHT_HEADLESS', default=False)
PLAYWRIGHT_FIREFOX_EXECUTABLE = env(
    'PLAYWRIGHT_FIREFOX_EXECUTABLE', default='')

# Garante que firefox_config.py (importado por scripts soltos) enxergue as
# mesmas variáveis definidas no .env.
for _nome, _valor in (
    ('FIREFOX_PATH', FIREFOX_PATH),
    ('FIREFOX_PROFILE', FIREFOX_PROFILE),
    ('PROJUDI_COOKIES_FILE', PROJUDI_COOKIES_FILE),
    ('PROJUDI_DOMAIN', PROJUDI_DOMAIN),
    ('PLAYWRIGHT_HEADLESS', '1' if PLAYWRIGHT_HEADLESS else '0'),
    ('PLAYWRIGHT_FIREFOX_EXECUTABLE', PLAYWRIGHT_FIREFOX_EXECUTABLE),
):
    if _valor:
        os.environ.setdefault(_nome, str(_valor))

# Planilha/tabela de ofícios no Google Docs (conta de serviço)
GOOGLE_SERVICE_ACCOUNT_FILE = env('GOOGLE_SERVICE_ACCOUNT_FILE', default='')
GOOGLE_OFICIOS_DOC_ID = env(
    'GOOGLE_OFICIOS_DOC_ID',
    default='1dY6yODJF0CFdbWZ2tH2f-cfvfyqq6RuKUo92NJE7JrY',
)
# Aceita também o link completo do Google Docs; o serviço extrai o ID.
GOOGLE_OFICIOS_DOC_URL = env('GOOGLE_OFICIOS_DOC_URL', default='')
GOOGLE_OFICIOS_TABLE_INDEX = env.int('GOOGLE_OFICIOS_TABLE_INDEX', default=0)

# Alternativa sem conta de serviço: Web App do Apps Script (roda com o Gmail
# que tem acesso ao documento). Se a URL estiver preenchida, ela tem
# prioridade sobre a conta de serviço.
GOOGLE_OFICIOS_WEBHOOK_URL = env('GOOGLE_OFICIOS_WEBHOOK_URL', default='')
GOOGLE_OFICIOS_WEBHOOK_TOKEN = env('GOOGLE_OFICIOS_WEBHOOK_TOKEN', default='')


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
