# ============================================================
#  Monta uma pasta PORTATIL do send_of_v4 para Windows 64-bit.
#
#  Uso (PowerShell):
#    .\scripts\montar_portatil_windows.ps1
#    .\scripts\montar_portatil_windows.ps1 -Destino "E:\send_of_v4_portable"
#
#  O Python embarcado e reaproveitado de uma instalacao portatil existente
#  (-PythonBase) ou de _portable_build\python312.
# ============================================================
param(
    [string]$Destino = "D:\send_of_v4_portable_win",
    [string]$PythonBase = "",
    [string]$BancoOrigem = "",
    [switch]$SemNavegador
)

$ErrorActionPreference = "Stop"
$Origem = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Info($msg) { Write-Host "[portatil] $msg" -ForegroundColor Cyan }
function Erro($msg) { Write-Host "[portatil] ERRO: $msg" -ForegroundColor Red; exit 1 }

if (-not $PythonBase) {
    $candidatos = @(
        "D:\send_of_v4_portable\python",
        (Join-Path $Origem "_portable_build\python312"),
        (Join-Path $Origem "_portable_build\python")
    )
    foreach ($c in $candidatos) {
        if (Test-Path (Join-Path $c "python.exe")) { $PythonBase = $c; break }
    }
}
if (-not $PythonBase -or -not (Test-Path (Join-Path $PythonBase "python.exe"))) {
    Erro "Python embarcado nao encontrado. Informe -PythonBase <pasta com python.exe>."
}

$AppDest = Join-Path $Destino "app"
$PythonDest = Join-Path $Destino "python"

Info "Origem ......: $Origem"
Info "Destino .....: $Destino"
Info "Python base .: $PythonBase"

New-Item -ItemType Directory -Force -Path $Destino | Out-Null

if (-not (Test-Path (Join-Path $PythonDest "python.exe"))) {
    Info "Copiando Python embarcado (pode demorar)..."
    robocopy $PythonBase $PythonDest /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Erro "Falha ao copiar o Python embarcado." }
} else {
    Info "Python embarcado ja existe no destino."
}

$Py = Join-Path $PythonDest "python.exe"

Info "Instalando/atualizando dependencias no Python portatil..."
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -r (Join-Path $Origem "requirements-windows.txt") --quiet
if ($LASTEXITCODE -ne 0) { Erro "Falha ao instalar dependencias." }

if (-not $SemNavegador) {
    Info "Baixando o Firefox do Playwright em modo portatil (junto ao pacote)..."
    $env:PLAYWRIGHT_BROWSERS_PATH = "0"
    & $Py -m playwright install firefox
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[portatil] AVISO: falha ao baixar o Firefox do Playwright." -ForegroundColor Yellow
    }
    Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
}

Info "Copiando o codigo do projeto..."
New-Item -ItemType Directory -Force -Path $AppDest | Out-Null
$excluirDirs = @(
    ".git", ".venv", "venv", "__pycache__", "staticfiles",
    "media", "backups", ".pytest_cache", ".mypy_cache"
) | ForEach-Object { Join-Path $Origem $_ }
$excluirArqs = @(".env", "db.sqlite3", "*.pyc", "*.pyo", "*.log", "nul")
$roboArgs = @($Origem, $AppDest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
$roboArgs += "/XD"
$roboArgs += $excluirDirs
$roboArgs += "/XF"
$roboArgs += $excluirArqs
robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { Erro "Falha ao copiar o codigo do projeto." }

if (-not (Test-Path (Join-Path $AppDest ".env"))) {
    Copy-Item (Join-Path $Origem "env.windows.example") (Join-Path $AppDest ".env")
    Info ".env criado a partir de env.windows.example"
}

if ($BancoOrigem -and (Test-Path $BancoOrigem)) {
    Info "Copiando banco existente: $BancoOrigem"
    Copy-Item $BancoOrigem (Join-Path $AppDest "db.sqlite3") -Force
}

# ------------------------------------------------------------------
# run.bat / atalhos
# ------------------------------------------------------------------
$runBat = @'
@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PYTHON=%ROOT%python\python.exe"
set "APP=%ROOT%app"
set "PLAYWRIGHT_BROWSERS_PATH=0"

if not exist "%PYTHON%" (
    echo [ERRO] Python embarcado nao encontrado em %PYTHON%
    pause
    exit /b 1
)
cd /d "%APP%"

echo ============================================================
echo  send_of_v4 - modo portatil
echo  Servidor: http://127.0.0.1:8000/
echo ============================================================
"%PYTHON%" manage.py migrate --noinput
"%PYTHON%" manage.py collectstatic --noinput >nul 2>&1
"%PYTHON%" manage.py criar_usuario_local >nul 2>&1

start "" /b "%PYTHON%" scripts\abrir_navegador.py http://127.0.0.1:8000/ --delay 3
"%PYTHON%" manage.py runserver 127.0.0.1:8000
endlocal
'@

$capturarBat = @'
@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PYTHON=%ROOT%python\python.exe"
set "APP=%ROOT%app"
set "PLAYWRIGHT_BROWSERS_PATH=0"
cd /d "%APP%"
echo Deixe o Firefox aberto e logado no Projudi.
"%PYTHON%" scripts\capture_cookies_windows.py
pause
endlocal
'@

$diagBat = @'
@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PYTHON=%ROOT%python\python.exe"
set "APP=%ROOT%app"
set "PLAYWRIGHT_BROWSERS_PATH=0"
cd /d "%APP%"
"%PYTHON%" manage.py diagnostico_firefox
pause
endlocal
'@

$leiaMe = @'
send_of_v4 - VERSAO PORTATIL (Windows 64-bit)
=============================================

Roda sem instalar Python. Basta dar duplo clique em run.bat.

Pastas:
  python\  -> Python 3.12 embarcado + dependencias + Firefox do Playwright
  app\     -> codigo Django, .env, db.sqlite3

Primeiro uso:
  1. run.bat
  2. Abra o Firefox local e faca login no Projudi (https://projudi.tjba.jus.br)
  3. No sistema, clique em Sincronizar sessao ou rode CAPTURAR_COOKIES.bat
  4. Login inicial: admin@local / admin123

Observacoes:
  - O Firefox LOCAL e usado para login/cookies.
  - A automacao usa o Firefox proprio do Playwright, ja incluido em python\.
  - Para diagnostico, rode DIAGNOSTICO.bat.
'@

Set-Content -Path (Join-Path $Destino "run.bat") -Value $runBat -Encoding Default
Set-Content -Path (Join-Path $Destino "CAPTURAR_COOKIES.bat") -Value $capturarBat -Encoding Default
Set-Content -Path (Join-Path $Destino "DIAGNOSTICO.bat") -Value $diagBat -Encoding Default
Set-Content -Path (Join-Path $Destino "LEIA-ME.txt") -Value $leiaMe -Encoding UTF8

# .bat precisa de CRLF para o cmd.exe do Windows.
foreach ($bat in @("run.bat", "CAPTURAR_COOKIES.bat", "DIAGNOSTICO.bat")) {
    $caminhoBat = Join-Path $Destino $bat
    $conteudo = Get-Content $caminhoBat -Raw
    $conteudo = $conteudo -replace "`r`n", "`n" -replace "`n", "`r`n"
    [System.IO.File]::WriteAllText($caminhoBat, $conteudo, [System.Text.Encoding]::Default)
}

Info "Aplicando migracoes no banco portatil..."
Push-Location $AppDest
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = "0"
    & $Py manage.py migrate --noinput
    & $Py manage.py collectstatic --noinput | Out-Null
    & $Py manage.py criar_usuario_local | Out-Null
} finally {
    Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
    Pop-Location
}

Info "Pronto: $Destino"
Info "Inicie com: $(Join-Path $Destino 'run.bat')"
