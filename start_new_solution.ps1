$projectPath = $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$dataPath = Join-Path $projectPath 'data'
$env:PYTHONDONTWRITEBYTECODE = '1'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host '未找到项目虚拟环境，请先按照 README 安装依赖。' -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null

function Test-ListeningPort([int]$port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-ListeningPort 8001)) {
    Start-Process -FilePath $pythonPath -WindowStyle Hidden -WorkingDirectory $projectPath -ArgumentList @(
        '-m', 'uvicorn', '10_api:app', '--host', '127.0.0.1', '--port', '8001'
    ) -RedirectStandardOutput (Join-Path $dataPath 'api.out.log') -RedirectStandardError (Join-Path $dataPath 'api.err.log')
    Write-Host '已启动后端，运行日志保存在 data 目录。'
} else {
    Write-Host '8001 端口已有服务，请确认它属于当前项目。'
}

if (-not (Test-ListeningPort 8503)) {
    Start-Process -FilePath $pythonPath -WindowStyle Hidden -WorkingDirectory $projectPath -ArgumentList @(
        '-m', 'streamlit', 'run', '09_app.py', '--server.address', '127.0.0.1', '--server.port', '8503'
    ) -RedirectStandardOutput (Join-Path $dataPath 'web.out.log') -RedirectStandardError (Join-Path $dataPath 'web.err.log')
    Write-Host '已启动网页端，运行日志保存在 data 目录。'
} else {
    Write-Host '8503 端口已有服务，请确认它属于当前项目。'
}
Write-Host '网页地址：http://127.0.0.1:8503'
Write-Host '接口文档：http://127.0.0.1:8001/docs'
