#!/usr/bin/env bash
# agent-vision 一键安装脚本 (bash / macOS / Linux / Git Bash on Windows)
# 用法: bash install.sh <目标Agent的skills目录>
set -euo pipefail

TARGET="${1:?用法: bash install.sh <目标Agent的skills目录>}"
DEST="$TARGET/agent-vision"
mkdir -p "$DEST"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -f "$SCRIPT_DIR/SKILL.md" \
      "$SCRIPT_DIR/PROMPT.md" \
      "$SCRIPT_DIR/vision.py" \
      "$SCRIPT_DIR/.env.example" \
      "$SCRIPT_DIR/README.md" \
      "$SCRIPT_DIR/vision-test.png" \
      "$DEST/"
# 本地已配置 .env 时一并带上(仓库版无 .env,安装后需 cp .env.example .env 填 key)
if [ -f "$SCRIPT_DIR/.env" ]; then
  cp -f "$SCRIPT_DIR/.env" "$DEST/"
fi

echo "✔ agent-vision 已安装到: $DEST"
echo ""
echo "验证是否可用:"
echo "  PYTHONIOENCODING=utf-8 python \"$DEST/vision.py\" \"$DEST/vision-test.png\" --simple"
