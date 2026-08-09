# agent-vision 一键安装脚本 (Windows PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File .\install.ps1 <目标Agent的skills目录>
param([Parameter(Mandatory=$true)][string]$Target)

$Dest = Join-Path $Target "agent-vision"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$Src = $PSScriptRoot
Copy-Item -Force "$Src\SKILL.md", "$Src\PROMPT.md", "$Src\vision.py", "$Src\.env.example", "$Src\README.md", "$Src\vision-test.png" $Dest
# 本地已配置 .env 时一并带上(仓库版无 .env,安装后需 cp .env.example .env 填 key)
if (Test-Path "$Src\.env") { Copy-Item -Force "$Src\.env" $Dest }

Write-Host "✔ agent-vision 已安装到: $Dest"
Write-Host ""
Write-Host "验证是否可用:"
Write-Host "  `$env:PYTHONIOENCODING='utf-8'; python `"$Dest\vision.py`" `"$Dest\vision-test.png`" --simple"
