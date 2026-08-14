#!/usr/bin/env python3
"""kv-agent-vision MCP server —— 零依赖 stdio 实现(Model Context Protocol)。

把 vision.py 的图片理解能力包装成 MCP 工具,任何支持 MCP 的客户端
(Cursor / Claude Code / Claude Desktop / Codex / Cline 等)都可直接调用:

    tools:
      describe_image(image, question?, ocr?, simple?)
        深度结构化描述图片 / 针对性图片问答 / OCR 文字提取 / 简短概览

用法:
  python mcp_server.py                     # 以 MCP stdio 模式运行
  python mcp_server.py --env-file <路径>   # 指定 env 配置文件(默认脚本同目录 .env)

协议说明(实现子集,足够主流客户端使用):
  - 传输: stdio,newline-delimited JSON-RPC 2.0(每行一条消息)
  - 方法: initialize / notifications/initialized / tools/list / tools/call / ping
  - 配置加载与视觉 API 调用完全复用 vision.py(同目录 .env,零第三方依赖)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import vision  # 复用 vision.py 的全部核心逻辑

SERVER_NAME = "kv-agent-vision"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

DESCRIBE_TOOL = {
    "name": "describe_image",
    "description": (
        "分析图片并返回结构化中文描述(深度模式 7 层次:整体概览/九宫格空间布局/"
        "对象细节带位置占比颜色/文字与UI逐条带位置/数据数字/隐含信息区分事实与推测/易漏细节)。"
        "支持本地图片路径或 http(s) 图片 URL。可针对图片提问(-q 语义),或只提取文字(OCR),"
        "或只要简短概览。纯文本模型没有多模态能力,理解任何图片内容都必须调用本工具。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "图片路径(本地绝对/相对路径)或 http(s) 图片 URL",
            },
            "question": {
                "type": "string",
                "description": "可选:针对图片的提问,如'这个界面的主色调和操作按钮是什么?'",
            },
            "ocr": {
                "type": "boolean",
                "description": "可选:true 时只提取图片中的全部文字(带位置标注)",
            },
            "simple": {
                "type": "boolean",
                "description": "可选:true 时只返回简短概览,不做深度结构化分析",
            },
            "coords": {
                "type": "boolean",
                "description": "可选:true 时对象/文字/UI 附加百分比坐标 (x%,y%,w%,h%),供定位/点击/裁切(会增加输出长度)",
            },
            "colors": {
                "type": "boolean",
                "description": "可选:true 时对象颜色附加精确 HEX 色值,供设计复刻/取色(会增加输出长度)",
            },
            "auto": {
                "type": "boolean",
                "description": "可选:true 时由视觉模型按图片内容自动判断是否附加坐标/色值(显式 coords/colors 优先;探索性看图推荐)",
            },
        },
        "required": ["image"],
    },
}


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _call_describe_image(args):
    image = (args or {}).get("image")
    if not image or not isinstance(image, str):
        raise ValueError("缺少必填参数 image(图片路径或 URL)")
    # 构造与 vision.py CLI 一致的参数对象
    ns = argparse.Namespace(
        ocr=bool(args.get("ocr", False)),
        question=(args.get("question") or "").strip(),
        simple=bool(args.get("simple", False)),
        coords=bool(args.get("coords", False)),
        colors=bool(args.get("colors", False)),
        auto=bool(args.get("auto", False)),
    )
    prompt = vision.build_prompt(ns)
    if image.startswith(("data:", "http://", "https://")):
        url = image
    else:
        url = vision.image_path_to_data_url(image)
    return vision.describe_image(url, prompt, max_tokens=16384)


def _handle_message(msg):
    """处理一条 JSON-RPC 消息,返回待发送的响应(notification 返回 None)。"""
    if not isinstance(msg, dict) or "method" not in msg:
        return None
    method = msg.get("method")
    req_id = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        client_info = (msg.get("params") or {}).get("clientInfo") or {}
        return _rpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "使用 describe_image 工具分析图片:传 image(路径或 URL),"
                "需要针对具体问题或只提取文字时使用 question/ocr 参数。"
            ),
        })
    if method == "notifications/initialized":
        return None  # 通知,无需响应
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": [DESCRIBE_TOOL]})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != DESCRIBE_TOOL["name"]:
            return _rpc_error(req_id, -32602, f"未知工具: {name}")
        try:
            text = _call_describe_image(args)
            return _rpc_result(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as exc:  # noqa: BLE001 —— 转为 MCP 错误响应
            return _rpc_error(req_id, -32603, f"{type(exc).__name__}: {exc}")
    return _rpc_error(req_id, -32601, f"方法未实现: {method}")


def main():
    parser = argparse.ArgumentParser(description="kv-agent-vision MCP server (stdio, 零依赖)")
    parser.add_argument("--env-file", default="", help="指定 env 配置文件路径(默认脚本同目录 .env)")
    args, _ = parser.parse_known_args()

    # Windows 下保证 UTF-8 读写,避免中文乱码
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    vision.load_default_env(args.env_file)
    vision._required("VISION_API_KEY")
    vision._required("VISION_BASE_URL")
    vision._required("VISION_MODEL")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
