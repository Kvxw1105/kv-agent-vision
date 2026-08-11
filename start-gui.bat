@echo off
rem kv-agent-vision 配置中心 —— 启动 GUI(管理共享配置,所有 Agent 共用)
rem 可选参数: --port 19123  --no-browser  --env-file <路径>
py -3 "%~dp0gui.py" %*
