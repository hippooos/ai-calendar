$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$backendDirectory = Join-Path $projectRoot 'backend'
$frontendDirectory = Join-Path $projectRoot 'frontend'
$python = Join-Path $backendDirectory '.venv\Scripts\python.exe'
$frontendServer = Join-Path $frontendDirectory 'serve.mjs'
$logDirectory = Join-Path $projectRoot 'runtime\logs'

function Test-Endpoint([string]$url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-Endpoint([string]$url, [string]$serviceName) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Endpoint $url) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "$serviceName 未能在 20 秒内启动。请查看 $logDirectory"
}

if (-not (Test-Path $python)) { throw "找不到后端 Python：$python" }
if (-not (Test-Path $frontendServer)) { throw "找不到前端服务：$frontendServer" }

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

if (-not (Test-Endpoint 'http://127.0.0.1:8000/readyz')) {
    Start-Process -FilePath $python -WorkingDirectory $backendDirectory `
        -ArgumentList @('-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $logDirectory 'backend.stderr.log')
    Wait-Endpoint 'http://127.0.0.1:8000/readyz' '后端服务'
}

if (-not (Test-Endpoint 'http://127.0.0.1:4173/')) {
    Start-Process -FilePath 'node.exe' -WorkingDirectory $frontendDirectory `
        -ArgumentList @('serve.mjs') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $logDirectory 'frontend.stderr.log')
    Wait-Endpoint 'http://127.0.0.1:4173/' '前端服务'
}

Start-Process 'http://127.0.0.1:4173/'
