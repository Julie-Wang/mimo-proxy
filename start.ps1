# MiMo Local Proxy 启动脚本 (PowerShell)
# 用法: 右键 → 使用 PowerShell 运行，或在终端执行 .\start.ps1

$ErrorActionPreference = "Stop"

# 检查 Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "❌ 未找到 python，请先安装 Python 3.9+ 并添加到 PATH" -ForegroundColor Red
    exit 1
}

# 安装/更新依赖
Write-Host "📦 检查依赖..." -ForegroundColor Cyan
& python -m pip install -q -r requirements.txt

# 检查 .env 是否已配置
if (-not (Test-Path ".env")) {
    Write-Host "❌ 未找到 .env 文件，请复制 .env.example 为 .env 并填写 MIMO_API_KEY" -ForegroundColor Red
    exit 1
}

$envContent = Get-Content ".env" -Raw
if ($envContent -match "sk-你的真实小米API-Key" -or $envContent -match "MIMO_API_KEY=\s*$") {
    Write-Host "⚠️  请先在 .env 文件中填写你的真实 MIMO_API_KEY" -ForegroundColor Yellow
    exit 1
}

# 启动服务
Write-Host "🚀 启动 MiMo Local Proxy..." -ForegroundColor Green
& python main.py
