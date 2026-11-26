# ============================================================
#  PostgreSQL local do send_of_v4 (Windows, sem Docker)
#
#  Usa os binarios do PostgreSQL ja instalado (15/16/17...) e cria
#  um cluster PROPRIO do projeto em .\pgdata, na porta 5433.
#  Nao mexe no cluster/servico que ja existir.
#
#  Exemplos:
#    .\scripts\postgres_local_windows.ps1                 # inicia e cria sccj
#    .\scripts\postgres_local_windows.ps1 -Status
#    .\scripts\postgres_local_windows.ps1 -Stop
#    .\scripts\postgres_local_windows.ps1 -DumpFile D:\Projudi\sendof_2026.sql.gz
# ============================================================
param(
    [string]$PgBin = "",
    [string]$DataDir = "",
    [int]$Port = 5433,
    [string]$DbName = "sccj",
    [string]$DbUser = "send_of",
    [string]$DbPassword = "send_of",
    [string]$DumpFile = "",
    [switch]$Stop,
    [switch]$Status,
    [switch]$ForceInit
)

$ErrorActionPreference = "Stop"
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $DataDir) { $DataDir = Join-Path $Raiz "pgdata" }

function Info($m) { Write-Host "[pg] $m" -ForegroundColor Cyan }
function Erro($m) { Write-Host "[pg] ERRO: $m" -ForegroundColor Red; exit 1 }

function Achar-PgBin {
    if ($PgBin) {
        if (Test-Path (Join-Path $PgBin "pg_ctl.exe")) { return $PgBin }
        Erro "pg_ctl.exe nao encontrado em $PgBin"
    }
    $base = "C:\Program Files\PostgreSQL"
    if (Test-Path $base) {
        $versoes = Get-ChildItem $base -Directory |
            Sort-Object { [int]($_.Name -replace '\D', '') } -Descending
        foreach ($v in $versoes) {
            $bin = Join-Path $v.FullName "bin"
            if (Test-Path (Join-Path $bin "pg_ctl.exe")) { return $bin }
        }
    }
    $cmd = Get-Command pg_ctl.exe -ErrorAction SilentlyContinue
    if ($cmd) { return (Split-Path $cmd.Source) }
    Erro "PostgreSQL nao encontrado. Instale o PostgreSQL 15+ ou informe -PgBin."
}

$bin = Achar-PgBin
$pgCtl = Join-Path $bin "pg_ctl.exe"
$psql = Join-Path $bin "psql.exe"
$createdb = Join-Path $bin "createdb.exe"
$initdb = Join-Path $bin "initdb.exe"
$pgRestore = Join-Path $bin "pg_restore.exe"

$versao = (& (Join-Path $bin "postgres.exe") --version) 2>&1
Info "Binarios: $bin"
Info "Versao..: $versao"
Info "Cluster.: $DataDir"
Info "Porta...: $Port"

if ($Stop) {
    & $pgCtl -D $DataDir -m fast stop
    exit $LASTEXITCODE
}
if ($Status) {
    & $pgCtl -D $DataDir status
    exit $LASTEXITCODE
}

# ------------------------------------------------------------
# 1. initdb (cluster proprio do projeto)
# ------------------------------------------------------------
$pgVersionFile = Join-Path $DataDir "PG_VERSION"
if (-not (Test-Path $pgVersionFile)) {
    if ((Test-Path $DataDir) -and -not $ForceInit) {
        $itens = Get-ChildItem $DataDir -Force -ErrorAction SilentlyContinue
        if ($itens) { Erro "A pasta $DataDir existe e nao esta vazia (use -ForceInit)." }
    }
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $pwFile = Join-Path $env:TEMP "sendof_pg_pw.txt"
    Set-Content -Path $pwFile -Value $DbPassword -Encoding ASCII -NoNewline
    Info "Criando cluster (initdb)..."
    & $initdb -D $DataDir -U $DbUser --pwfile=$pwFile --auth=scram-sha-256 -E UTF8 --locale=C
    Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { Erro "Falha no initdb." }

    # Escuta somente local e porta definida.
    Add-Content -Path (Join-Path $DataDir "postgresql.conf") -Value @"

# --- send_of_v4 ---
listen_addresses = '127.0.0.1'
port = $Port
"@ -Encoding ASCII
}

# ------------------------------------------------------------
# 2. start
# ------------------------------------------------------------
$iniciado = $false
$pgIsReady = Join-Path $bin "pg_isready.exe"
& $pgIsReady -h 127.0.0.1 -p $Port *> $null
if ($LASTEXITCODE -eq 0) {
    Info "Servidor ja esta rodando."
    $iniciado = $true
} else {
    Info "Iniciando servidor..."
    & $pgCtl -D $DataDir -l (Join-Path $DataDir "server.log") `
        -o "-p $Port -c listen_addresses=127.0.0.1" -w start
    if ($LASTEXITCODE -ne 0) { Erro "Falha ao iniciar. Veja $(Join-Path $DataDir 'server.log')." }
    $iniciado = $true
}

$env:PGPASSWORD = $DbPassword
$env:PGCONNECT_TIMEOUT = "5"
$hostArg = "127.0.0.1"

# ------------------------------------------------------------
# 3. banco sccj
# ------------------------------------------------------------
$existe = (@(& $psql -w -h $hostArg -p $Port -U $DbUser -d postgres -tAc `
    "select 1 from pg_database where datname='$DbName'") -join '').Trim()
if ($existe -ne "1") {
    Info "Criando banco $DbName..."
    & $createdb -w -h $hostArg -p $Port -U $DbUser $DbName
    if ($LASTEXITCODE -ne 0) { Erro "Falha ao criar o banco $DbName." }
} else {
    Info "Banco $DbName ja existe."
}

# ------------------------------------------------------------
# 4. dump opcional
# ------------------------------------------------------------
if ($DumpFile) {
    if (-not (Test-Path $DumpFile)) { Erro "Dump nao encontrado: $DumpFile" }
    $ext = [IO.Path]::GetExtension($DumpFile).ToLower()
    if ($DumpFile.ToLower().EndsWith(".sql.gz")) {
        Info "Descompactando e restaurando $DumpFile ..."
        $tmpSql = Join-Path $env:TEMP "sendof_restore.sql"
        $entrada = [IO.File]::OpenRead($DumpFile)
        $saida = [IO.File]::Create($tmpSql)
        $gz = New-Object IO.Compression.GZipStream($entrada, [IO.Compression.CompressionMode]::Decompress)
        $gz.CopyTo($saida)
        $gz.Dispose(); $saida.Dispose(); $entrada.Dispose()
        & $psql -w -h $hostArg -p $Port -U $DbUser -d $DbName -v ON_ERROR_STOP=0 -f $tmpSql
        Remove-Item $tmpSql -Force -ErrorAction SilentlyContinue
    } elseif ($ext -in @('.dump', '.backup', '.tar')) {
        Info "Restaurando dump customizado $DumpFile ..."
        & $pgRestore -w -h $hostArg -p $Port -U $DbUser -d $DbName `
            --no-owner --no-privileges --clean --if-exists $DumpFile
    } else {
        Info "Restaurando SQL $DumpFile ..."
        & $psql -w -h $hostArg -p $Port -U $DbUser -d $DbName -v ON_ERROR_STOP=0 -f $DumpFile
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[pg] AVISO: o restore retornou erros; confira as tabelas." -ForegroundColor Yellow
    }
}

Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue

$url = "postgres://{0}:{1}@127.0.0.1:{2}/{3}" -f $DbUser, $DbPassword, $Port, $DbName
Write-Host ""
Info "Pronto."
Write-Host "Coloque no .env:" -ForegroundColor Yellow
Write-Host "  DATABASE_URL=$url" -ForegroundColor White
Write-Host ""
Write-Host "Depois rode:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\python.exe manage.py migrate" -ForegroundColor White
Write-Host ""
Write-Host "Para parar: .\scripts\postgres_local_windows.ps1 -Stop" -ForegroundColor Gray
