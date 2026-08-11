#!/usr/bin/env python3
"""kv-agent-vision 配置中心 —— 零依赖本地 Web GUI。

管理视觉 API 多站点配置(主站点 VISION_* + 备用站点 VISION2_* / VISION3_* ...,
主站点故障自动切换备用站点)。所有装配了本能力的本地 Agent 共用同一份 env 配置
(默认 Windows: %LOCALAPPDATA%\\codex-deepseek-vision\\env;其它系统:
~/.config/codex-deepseek-vision/env),本 GUI 直接编辑这份共享配置。

用法:
  python gui.py                 # 启动并自动打开浏览器
  python gui.py --no-browser    # 只启动,不自动打开浏览器
  python gui.py --port 19123    # 指定端口(默认 19123,被占用时自动后延)
  python gui.py --host 0.0.0.0  # 默认仅本机 127.0.0.1(配置含密钥,不建议开放)
  python gui.py --env-file <路径>   # 管理指定的 env 文件(默认共享配置)

安全:API 密钥仅掩码显示,不写入日志;保存前自动备份 env 文件。
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import vision  # 同目录 vision.py:保险丝白名单、describe_image 等

MANAGED_PREFIX = "VISION"
_FIELD_KEYS = ("BASE_URL", "API_KEY", "MODEL")
_KEY_RE = re.compile(r"^VISION(\d*)_(BASE_URL|API_KEY|MODEL)$")
_PROXY_PORT = 19100
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# 测试锁:describe_image 按站点临时改写 os.environ,串行化避免线程间互相污染
_TEST_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kv-agent-vision 配置中心 · 眼科检查单</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23211f1b'%3E%3Cpath d='M8 5h13v4H8zM8 10h10v4H8zM8 15h13v4H8zM4 5h2v14H4z'/%3E%3C/svg%3E">
<style>
  :root {
    --paper: #f6f3ec;
    --paper-deep: #efeae0;
    --ink: #211f1b;
    --ink-soft: #6b6659;
    --ink-faint: #a49d8d;
    --line: #d8d2c2;
    --line-strong: #211f1b;
    --seal: #a63c2b;
    --verdigris: #3f6b4f;
    --ochre: #8a6a1f;
    --ink-blue: #2f4a6e;
    --font-serif: "Songti SC", "SimSun", "Noto Serif SC", "Source Han Serif SC", serif;
    --font-kai: "KaiTi", "STKaiti", "楷体", cursive;
    --font-mono: "Cascadia Mono", "JetBrains Mono", Consolas, "Courier New", monospace;
    --font-sans: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    --shadow: none;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --paper: #1a1713; --paper-deep: #221e18;
      --ink: #e6dfd0; --ink-soft: #a29a88; --ink-faint: #6f695a; --line: #3b372d;
      --line-strong: #e6dfd0; --seal: #c2553f; --verdigris: #7fa884;
      --ochre: #c9a24f; --ink-blue: #8aa5c9; }
  }
  :root[data-theme="dark"] { --paper: #1a1713; --paper-deep: #221e18;
    --ink: #e6dfd0; --ink-soft: #a29a88; --ink-faint: #6f695a; --line: #3b372d;
    --line-strong: #e6dfd0; --seal: #c2553f; --verdigris: #7fa884;
    --ochre: #c9a24f; --ink-blue: #8aa5c9; }
  * { box-sizing: border-box; }
  html { scrollbar-color: var(--ink-faint) transparent; }
  body { margin: 0; min-height: 100vh; background: var(--paper); color: var(--ink);
         font: 14px/1.7 var(--font-sans); -webkit-font-smoothing: antialiased; }
  /* 纸张纹理:极淡的纤维感 */
  body::before { content: ""; position: fixed; inset: 0; pointer-events: none; opacity: .5;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 .025 0'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)'/%3E%3C/svg%3E"); }
  .wrap { max-width: 900px; margin: 0 auto; padding: 26px 20px 80px; position: relative; }
  /* 顶栏:检查单头 */
  header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
           border-bottom: 2px solid var(--line-strong); padding-bottom: 14px; }
  .no { font-family: var(--font-mono); font-size: 12px; color: var(--ink-soft); letter-spacing: 1px; }
  h1 { font-family: var(--font-serif); font-size: 22px; font-weight: 700; margin: 0;
       letter-spacing: 2px; }
  h1 .sub-tag { font-family: var(--font-kai); font-size: 13px; color: var(--ink-faint);
                font-weight: 400; margin-left: 8px; letter-spacing: 1px; }
  .sub { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-faint);
         margin: 10px 0 0; word-break: break-all; }
  /* 视力表头 */
  .snellen { display: flex; align-items: flex-end; gap: 0; margin: 20px 0 18px;
             user-select: none; overflow: hidden; }
  .snellen .e-row { display: flex; align-items: flex-end; gap: 10px; flex: 1; }
  .snellen .e { display: inline-flex; color: var(--ink); animation: focusIn 1.2s ease both; }
  .snellen .e:nth-child(2) { animation-delay: .08s; }
  .snellen .e:nth-child(3) { animation-delay: .16s; }
  .snellen .e:nth-child(4) { animation-delay: .24s; }
  .snellen .e:nth-child(5) { animation-delay: .32s; }
  .snellen .e:nth-child(6) { animation-delay: .4s; }
  .snellen .e:nth-child(7) { animation-delay: .48s; }
  .snellen .e:nth-child(8) { animation-delay: .56s; }
  .snellen .scale { font-family: var(--font-mono); color: var(--ink-faint);
                    font-size: 11px; padding-left: 14px; border-left: 1px solid var(--line);
                    white-space: nowrap; letter-spacing: 2px; }
  @keyframes focusIn { from { opacity: 0; filter: blur(3px); transform: translateY(4px); }
                       to { opacity: 1; filter: blur(0); transform: none; } }
  /* 工具栏 */
  .bar { display: flex; gap: 8px; align-items: center; margin: 0 0 14px; flex-wrap: wrap;
         padding: 10px 0; border-bottom: 1px solid var(--line); }
  button { background: transparent; border: 1px solid var(--ink-soft); color: var(--ink);
           padding: 6px 14px; border-radius: 2px; cursor: pointer; font-size: 13px;
           font-family: var(--font-sans); display: inline-flex; align-items: center; gap: 6px;
           transition: background .12s ease, color .12s ease, border-color .12s ease,
                       transform .1s ease; letter-spacing: .5px; }
  button:hover { border-color: var(--line-strong); background: var(--paper-deep);
                 transform: translateY(-1px); }
  button:active { transform: translateY(0) scale(.99); }
  button.primary { background: var(--ink); border-color: var(--ink); color: var(--paper); }
  button.primary:hover { background: var(--seal); border-color: var(--seal); color: var(--paper); }
  button.danger:hover { border-color: var(--seal); color: var(--seal); background: transparent; }
  button:disabled { opacity: .4; cursor: not-allowed; transform: none !important; }
  button svg { flex: none; }
  /* 检查记录卡 */
  .card { background: var(--paper); border: 1px solid var(--line); border-radius: 0;
          padding: 14px 18px 14px; margin-bottom: 14px; position: relative;
          animation: cardIn .3s ease both; }
  .card::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
                 background: transparent; }
  .card.dragging { opacity: .45; border-style: dashed; }
  .card.drag-over-top { box-shadow: inset 0 2px 0 var(--line-strong); }
  .card.drag-over-bottom { box-shadow: inset 0 -2px 0 var(--line-strong); }
  @keyframes cardIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .card-head { display: flex; align-items: center; gap: 10px; padding-bottom: 10px;
               border-bottom: 1px solid var(--line); margin-bottom: 4px; flex-wrap: wrap; }
  .card-head .drag-handle { cursor: grab; color: var(--ink-faint); display: inline-flex;
                            padding: 2px; border-radius: 2px; }
  .card-head .drag-handle:hover { color: var(--ink); }
  .card-head .drag-handle:active { cursor: grabbing; }
  /* E 字(视力符号,方向随站点变化;健康度差 → 更大) */
  .e-mark { display: inline-flex; color: var(--ink); flex: none; line-height: 0;
            transform: rotate(var(--rot, 0deg)); transition: transform .3s ease; }
  .card:hover .e-mark { transform: rotate(calc(var(--rot, 0deg) + 90deg)); }
  .tag { display: inline-flex; align-items: center; font-size: 12px; font-family: var(--font-serif);
         letter-spacing: 1px; padding: 1px 8px; border: 1px solid var(--ink-soft);
         color: var(--ink-soft); white-space: nowrap; }
  .tag.main { border-color: var(--line-strong); color: var(--ink); font-weight: 700; }
  .tag.incomplete { border-style: dashed; }
  /* 视力等级 */
  .vision { font-family: var(--font-kai); font-size: 13px; letter-spacing: 1px; }
  .vision.ok { color: var(--verdigris); }
  .vision.err { color: var(--seal); }
  .vision.na { color: var(--ink-faint); }
  .vision.warn { color: var(--ochre); }
  .check { font-family: var(--font-kai); font-size: 13px; color: var(--seal);
           letter-spacing: 1px; }
  /* 检查单表格 */
  .table { width: 100%; border-collapse: collapse; }
  .tr { display: flex; gap: 14px; padding: 7px 0; border-bottom: 1px dotted var(--line);
        align-items: baseline; }
  .tr:last-child { border-bottom: none; }
  .tr .k { flex: 0 0 92px; font-size: 11.5px; color: var(--ink-faint); letter-spacing: 1px;
           font-family: var(--font-sans); }
  .tr .v { flex: 1; min-width: 0; word-break: break-all; font-family: var(--font-mono);
           font-size: 13px; display: flex; align-items: center; gap: 8px; }
  .tr .v.key-val { font-size: 13px; }
  .key-toggle { cursor: pointer; color: var(--ink-faint); display: inline-flex; padding: 2px; }
  .key-toggle:hover { color: var(--ink); }
  .ops { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .ops button { padding: 4px 12px; font-size: 12.5px; }
  .hint { font-size: 12px; color: var(--ink-faint); }
  .dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex: none; }
  .dot.on { background: var(--verdigris); animation: blink 2s ease infinite; }
  .dot.off { background: var(--ink-faint); }
  @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
  /* 状态条(诊室设备) */
  .status-card { border: 1px solid var(--line); padding: 10px 16px; margin-bottom: 14px;
                 display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
                 background: var(--paper-deep); }
  .status-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px;
                 color: var(--ink-soft); }
  .status-item b { color: var(--ink); font-weight: 600; font-family: var(--font-mono); }
  .status-title { font-family: var(--font-serif); font-size: 12px; letter-spacing: 2px;
                  color: var(--ink-soft); border-right: 1px solid var(--line); padding-right: 12px; }
  .log-box { background: var(--paper-deep); border: 1px solid var(--line); padding: 10px 12px;
             font: 11.5px/1.6 var(--font-mono); color: var(--ink-soft);
             max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-all;
             margin-top: 10px; display: none; }
  /* 印章 */
  .stamp { position: fixed; top: 30%; left: 50%; transform: translate(-50%,-50%) scale(1.6) rotate(-8deg);
           border: 3px solid var(--seal); color: var(--seal); font-family: var(--font-serif);
           font-size: 22px; letter-spacing: 6px; padding: 8px 18px 8px 24px; opacity: 0;
           pointer-events: none; z-index: 100; }
  .stamp.show { animation: stampIn .45s cubic-bezier(.2,1.4,.4,1) forwards, stampOut .4s ease 1.4s forwards; }
  @keyframes stampIn { 0% { opacity: 0; transform: translate(-50%,-50%) scale(1.8) rotate(-12deg); }
                       100% { opacity: 1; transform: translate(-50%,-50%) scale(1) rotate(-6deg); } }
  @keyframes stampOut { to { opacity: 0; transform: translate(-50%,-50%) scale(1.05) rotate(-4deg); } }
  /* 错误与提示 */
  .msg { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(8px);
         padding: 9px 18px; font-size: 13px; font-family: var(--font-kai); letter-spacing: 1px;
         opacity: 0; pointer-events: none; transition: opacity .25s ease, transform .25s ease;
         z-index: 99; background: var(--ink); color: var(--paper); max-width: min(92vw, 560px); }
  .msg.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .msg.ok { background: var(--verdigris); }
  .msg.err { background: var(--seal); }
  .msg.warn { background: var(--ochre); }
  .spin { display: inline-block; width: 11px; height: 11px; border: 1.5px solid var(--ink-faint);
          border-top-color: var(--ink); border-radius: 50%;
          animation: spin .7s linear infinite; vertical-align: -1px; flex: none; }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* 添加表单 */
  .add-form { border: 1px solid var(--line-strong); padding: 16px 18px; margin-bottom: 14px;
              background: var(--paper); }
  .add-form .title { font-family: var(--font-serif); font-size: 14px; letter-spacing: 2px;
                     margin-bottom: 12px; font-weight: 700; }
  .field label { display: block; font-size: 11.5px; color: var(--ink-faint);
                 letter-spacing: 1px; margin-bottom: 3px; }
  .field input { width: 100%; padding: 6px 10px; border: 1px solid var(--line);
                 border-radius: 0; background: var(--paper); color: var(--ink);
                 font: 13px var(--font-mono); }
  .field input:focus { outline: none; border-color: var(--line-strong); }
  /* 空状态:Ishihara 色盲检测圆点 */
  .empty { text-align: center; padding: 40px 20px 48px; }
  .empty .ishihara { margin: 0 auto 22px; display: block; }
  .empty h2 { font-family: var(--font-serif); font-size: 18px; margin: 0 0 8px; letter-spacing: 3px; }
  .empty p { color: var(--ink-soft); margin: 0 auto 20px; max-width: 460px; font-size: 13px; }
  .empty .steps { display: inline-flex; gap: 10px; flex-wrap: wrap; justify-content: center;
                  margin-bottom: 24px; }
  .step-chip { border: 1px solid var(--line); padding: 4px 12px; font-size: 12.5px;
               color: var(--ink-soft); letter-spacing: 1px; font-family: var(--font-serif); }
  .step-chip b { color: var(--ink); font-weight: 700; }
  details { margin-top: 14px; }
  summary { cursor: pointer; color: var(--ink-faint); font-size: 12.5px; user-select: none;
            font-family: var(--font-serif); letter-spacing: 2px; }
  summary:hover { color: var(--ink); }
  details .hint { margin-top: 8px; }
  .hidden-file { display: none; }
  @media (max-width: 720px) {
    .wrap { padding: 18px 12px 60px; }
    .snellen { display: none; }
    .tr { flex-direction: column; gap: 2px; }
    .tr .k { flex: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="no">NO.&nbsp;KV-AGENT-VISION</span>
    <h1>配置中心<span class="sub-tag">视觉能力 · 验光记录</span></h1>
    <span style="flex:1"></span>
    <span id="envBadge" class="tag" style="display:none"></span>
    <span id="dirtyBadge" class="tag" style="display:none;border-color:var(--ochre);color:var(--ochre)">未存档</span>
    <button id="btnTheme" title="切换明暗" style="padding:5px 9px"></button>
  </header>
  <div class="sub" id="envPath"></div>

  <div class="snellen" aria-hidden="true">
    <div class="e-row" id="eRow"></div>
    <div class="scale">5.0&nbsp;4.9&nbsp;4.8&nbsp;4.7&nbsp;4.6&nbsp;4.5&nbsp;4.4&nbsp;4.3</div>
  </div>

  <div class="bar">
    <button class="primary" id="btnAdd">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
      添加站点
    </button>
    <button id="btnSave">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
      存档
    </button>
    <button id="btnTestAll">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
      全部验光
    </button>
    <button id="btnReload">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6"/></svg>
      重读档案
    </button>
    <button id="btnExport">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3m0 0L8 7m4-4l4 4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
      导出
    </button>
    <button id="btnImport">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l4-4m-4 4l-4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
      导入
    </button>
    <input type="file" id="importFile" class="hidden-file" accept=".json,application/json">
    <button id="btnRestartProxy">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 014-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 01-4 4H3"/></svg>
      重启代理
    </button>
    <span style="flex:1"></span>
    <span id="testProgress" class="hint" style="display:none"></span>
  </div>

  <div class="status-card">
    <span class="status-title">诊室设备</span>
    <span class="status-item"><span id="proxyDot" class="dot off"></span>视觉代理
      <b id="proxyPort">—</b></span>
    <span class="status-item">PID <b id="proxyPid">—</b></span>
    <span class="status-item">在册站点 <b id="siteCount">0</b></span>
    <span class="status-item" id="lastSave" style="font-family:var(--font-kai)"></span>
    <span style="flex:1"></span>
    <button id="btnProxyLog" style="padding:4px 9px">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/></svg>
      设备日志
    </button>
    <div id="proxyLogBox" class="log-box"></div>
  </div>

  <div id="msg" class="msg"></div>
  <div id="stamp" class="stamp">已存档</div>

  <div id="sites"></div>

  <div class="add-form" id="addForm" style="display:none">
    <div class="title">添加站点 · 新档案</div>
    <div class="row" style="display:flex;gap:12px;flex-wrap:wrap">
      <div class="field" style="flex:2 1 260px;min-width:0"><label>BASE URL(端点)</label>
        <input id="addBase" placeholder="https://api.example.com/v1" spellcheck="false"></div>
      <div class="field" style="flex:1 1 160px;min-width:0"><label>模型名</label>
        <input id="addModel" placeholder="model-name" spellcheck="false"></div>
      <div class="field" style="flex:2 1 220px;min-width:0"><label>API 密钥</label>
        <input id="addKey" type="password" placeholder="sk-..." autocomplete="off" spellcheck="false"></div>
      <div class="ops" style="align-self:flex-end;margin-top:0">
        <button class="primary" id="btnAddOk">建档</button>
        <button id="btnAddCancel">取消</button>
      </div>
    </div>
  </div>

  <details>
    <summary>说明 · 医嘱</summary>
    <div class="hint">
      所有装配了本能力的本地 Agent 共用同一份配置,存档后新调用立即生效;
      视觉代理(19100)需「重启代理」加载新配置。站点可拖拽排序,第 1 个是主站点,
      其余为备用(主站故障自动切换)。站点测试结果即"视力等级":5.0 健康、3.0 失明,
      看不清的站点在页面上会更大。测试结果保存在本地浏览器。
    </div>
  </details>
</div>

<script>
"use strict";
let sites = [];
let dirty = false;
const RESULTS_KEY = "kv-gui-test-results";
const THEME_KEY = "kv-gui-theme";
const ROTATIONS = [0, 90, 180, 270];
const E_SIZES = [20, 24, 30];  // ok / 未测 / 失败 → E 字大小(视力越差越大)

const $ = (id) => document.getElementById(id);
const ICONS = {
  eye: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-10-8-10-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 10 8 10 8a18.5 18.5 0 01-2.16 3.19M1 1l22 22"/></svg>',
  drag: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.7"/><circle cx="15" cy="6" r="1.7"/><circle cx="9" cy="12" r="1.7"/><circle cx="15" cy="12" r="1.7"/><circle cx="9" cy="18" r="1.7"/><circle cx="15" cy="18" r="1.7"/></svg>',
  edit: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5z"/></svg>',
  trash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/></svg>',
  sun: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>'
};

function toast(text, kind, ms) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg show " + (kind || "ok");
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = "msg"; }, ms || 3500);
}

function stamp() {
  const el = $("stamp");
  el.classList.remove("show");
  void el.offsetWidth;
  el.classList.add("show");
}

async function api(method, path, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opt.body = JSON.stringify(body);
  const resp = await fetch(path, opt);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- 主题 ---------- */
function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
  const dark = mode === "dark" ||
    (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  $("btnTheme").innerHTML = dark ? ICONS.sun : ICONS.moon;
  $("btnTheme").title = dark ? "切到明室" : "切到暗室";
}
function cycleTheme() {
  const cur = localStorage.getItem(THEME_KEY) || "auto";
  const next = cur === "auto" ? "dark" : (cur === "dark" ? "light" : "auto");
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

/* ---------- 视力等级 ---------- */
function loadResults() {
  try { return JSON.parse(localStorage.getItem(RESULTS_KEY) || "{}"); }
  catch (e) { return {}; }
}
function saveResult(baseUrl, ok, latency) {
  const r = loadResults();
  r[baseUrl] = { ok: !!ok, latency: latency || 0, ts: Date.now() };
  try { localStorage.setItem(RESULTS_KEY, JSON.stringify(r)); } catch (e) {}
}
function visionOf(baseUrl, complete) {
  if (!complete) return { label: "未填全", cls: "na", eSize: E_SIZES[2] };
  const r = loadResults()[baseUrl];
  if (!r) return { label: "未验光", cls: "na", eSize: E_SIZES[1] };
  if (r.ok) return { label: "视力 5.0 · " + r.latency + "ms", cls: "ok", eSize: E_SIZES[0] };
  return { label: "视力 3.0 · 上次失败", cls: "err", eSize: E_SIZES[2] };
}

/* ---------- E 字 ---------- */
function eMark(size, rot) {
  return `<span class="e-mark" style="width:${size}px;height:${size}px;--rot:${rot}deg">
    <svg width="${size}" height="${size}" viewBox="0 0 40 40" fill="currentColor">
      <path d="M8 8h26v5H13v5h21v5H13v5h21v5H8z"/></svg></span>`;
}

/* ---------- 渲染 ---------- */
function render() {
  const box = $("sites");
  if (!sites.length) {
    box.innerHTML = `
      <div class="card empty">
        <svg class="ishihara" width="220" height="220" viewBox="0 0 220 220" aria-hidden="true" id="ishihara"></svg>
        <h2>本册暂无档案</h2>
        <p>添加视觉 API 站点后,装配了该能力的 Agent 就能看图。
           主站故障时自动切换备用站点,健康程度按"视力等级"记录在案。</p>
        <div class="steps">
          <span class="step-chip"><b>壹</b> 建档</span>
          <span class="step-chip"><b>贰</b> 验光</span>
          <span class="step-chip"><b>叁</b> 存档</span>
          <span class="step-chip"><b>肆</b> 重启设备</span>
        </div>
        <button class="primary" onclick="openAdd()">建档</button>
      </div>`;
    drawIshihara();
  } else {
    box.innerHTML = sites.map((s, i) => {
      const v = visionOf(s.base_url, s.complete);
      const tag = i === 0 ? '<span class="tag main">主站点</span>'
                          : `<span class="tag">备用站点</span>`;
      const inc = s.complete ? "" : '<span class="tag incomplete">未填全</span>';
      const issues = (s.issues || []).map((x) =>
        `<div class="hint" style="margin-top:6px;color:var(--seal)">⚠ ${escapeHtml(x)}</div>`).join("");
      return `<div class="card" data-i="${i}" draggable="true">
        <div class="card-head">
          <span class="drag-handle" title="拖拽排序">${ICONS.drag}</span>
          ${eMark(v.eSize, ROTATIONS[i % ROTATIONS.length])}
          ${tag}${inc}
          <span class="vision ${v.cls}">${v.label}</span>
          <span style="flex:1"></span>
          <span class="hint" id="lat-${i}"></span>
        </div>
        <div class="table">
          <div class="tr"><div class="k">BASE URL</div>
            <div class="v">${escapeHtml(s.base_url || "(空)")}</div></div>
          <div class="tr"><div class="k">模型</div>
            <div class="v">${escapeHtml(s.model || "(空)")}</div></div>
          <div class="tr"><div class="k">API 密钥</div>
            <div class="v key-val"><span id="keyval-${i}">${escapeHtml(s.api_key_masked || "未设置")}</span>
              ${s.api_key ? `<span class="key-toggle" id="keytoggle-${i}" title="显示/隐藏">${ICONS.eye}</span>` : ""}
            </div></div>
        </div>
        <div class="ops">
          <button onclick="testSite(${i})">验光</button>
          <button onclick="editSite(${i})">${ICONS.edit} 修改</button>
          <button class="danger" id="delbtn-${i}" onclick="delSite(${i})">${ICONS.trash} 注销</button>
        </div>
        <div id="edit-${i}"></div>
        ${issues}
      </div>`;
    }).join("");
    bindDrag();
  }
  $("siteCount").textContent = sites.length;
  $("dirtyBadge").style.display = dirty ? "" : "none";
}

/* Ishihara 色盲检测:圆点阵列,中心藏一个 E */
function drawIshihara() {
  const svg = $("ishihara");
  if (!svg) return;
  const N = 15, cell = 14.5, off = 8;
  const colors = ["#3f6b4f", "#a63c2b", "#8a6a1f", "#6b6659", "#2f4a6e"];
  const centerR = 3, centerC = 6;  // 中心 E 区域:行 6-8,列 4-10
  const inE = (r, c) =>
    (c === 4 && r >= 6 && r <= 8) ||          // 左竖
    ((r === 6 || r === 7 || r === 8) && c >= 5 && c <= 10);  // 三横(缺口朝右)
  let dots = "";
  for (let r = 0; r < N; r++) {
    for (let c = 0; c < N; c++) {
      if ((r + c) % 5 === 0) continue;  // 留白制造"视差"
      const x = off + c * cell + (r % 2) * 6;
      const y = off + r * cell;
      const rad = 3.2 + ((r * 7 + c * 13) % 5) * 0.55;
      const isE = inE(r, c);
      const col = isE ? "#211f1b" : colors[(r * 11 + c * 7) % colors.length];
      dots += `<circle cx="${x}" cy="${y}" r="${rad.toFixed(1)}" fill="${col}" opacity="${isE ? .95 : .55}"/>`;
    }
  }
  svg.innerHTML = dots;
}

function bindDrag() {
  let from = null;
  document.querySelectorAll(".card[draggable]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      from = parseInt(card.dataset.i, 10);
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", String(from)); } catch (err) {}
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.querySelectorAll(".card.drag-over-top,.card.drag-over-bottom").forEach((c) =>
        c.classList.remove("drag-over-top", "drag-over-bottom"));
    });
    card.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const rect = card.getBoundingClientRect();
      const before = e.clientY < rect.top + rect.height / 2;
      card.classList.toggle("drag-over-top", before);
      card.classList.toggle("drag-over-bottom", !before);
    });
    card.addEventListener("dragleave", () => {
      card.classList.remove("drag-over-top", "drag-over-bottom");
    });
    card.addEventListener("drop", async (e) => {
      e.preventDefault();
      const to = parseInt(card.dataset.i, 10);
      if (from === null || from === to) return;
      try {
        await api("POST", "/api/move", { index: from, to });
        markDirty(); render();
      } catch (err) { toast(err.message, "err"); }
    });
  });
}

/* ---------- 密钥显隐 ---------- */
let keyVisible = {};
function toggleKey(i) {
  keyVisible[i] = !keyVisible[i];
  const s = sites[i];
  $("keyval-" + i).textContent = keyVisible[i] ? s.api_key_value : s.api_key_masked;
  $("keytoggle-" + i).innerHTML = keyVisible[i] ? ICONS.eyeOff : ICONS.eye;
}

/* ---------- 配置 ---------- */
async function loadConfig() {
  try {
    const cfg = await api("GET", "/api/config");
    sites = cfg.sites;
    dirty = false;
    $("envBadge").style.display = "";
    $("envBadge").textContent = cfg.env_path.includes("codex-deepseek-vision") ? "共享配置" : "自定义 env";
    $("envPath").textContent = "档案路径 " + cfg.env_path;
    $("proxyPort").textContent = cfg.proxy_listening ? String(cfg.proxy_port) : "未运行";
    $("proxyDot").className = "dot " + (cfg.proxy_listening ? "on" : "off");
    $("proxyPid").textContent = cfg.proxy_pid || "—";
    buildSnellen();
    render();
  } catch (e) { toast("读取档案失败: " + e.message, "err", 5000); }
}

/* 视力表头:E 行从大到小 */
function buildSnellen() {
  const row = $("eRow");
  const sizes = [34, 28, 23, 19, 16, 13, 11, 9];
  row.innerHTML = sizes.map((s, i) =>
    `<span class="e">${eMark(s, ROTATIONS[i % 4])}</span>`).join("");
}

function markDirty() { dirty = true; $("dirtyBadge").style.display = ""; }

async function save() {
  const btn = $("btnSave");
  btn.disabled = true;
  const old = btn.innerHTML;
  btn.innerHTML = '<span class="spin"></span> 存档中';
  try {
    const r = await api("POST", "/api/save", {});
    dirty = false;
    $("dirtyBadge").style.display = "none";
    const now = new Date();
    $("lastSave").textContent = "已存档 " + now.toLocaleTimeString();
    stamp();
    toast("已存档" + (r.backup ? " · 旧档: " + r.backup : ""), "ok");
  } catch (e) { toast("存档失败: " + e.message, "err", 5000); }
  btn.disabled = false;
  btn.innerHTML = old;
}

/* ---------- 验光 ---------- */
async function testSite(i) {
  const el = $("lat-" + i);
  el.innerHTML = '<span class="spin"></span>';
  try {
    const r = await api("POST", "/api/test", { index: i });
    if (r.ok) {
      el.innerHTML = `<span class="check">✓ ${r.latency_ms}ms</span>`;
      saveResult(sites[i].base_url, true, r.latency_ms);
      toast("站点 " + (i + 1) + " 视力 5.0 · " + r.latency_ms + "ms", "ok", 3000);
    } else {
      el.innerHTML = `<span style="color:var(--seal)">✗ ${r.latency_ms}ms</span>`;
      saveResult(sites[i].base_url, false, r.latency_ms);
      toast("站点 " + (i + 1) + " 视力 3.0: " + r.error, "err", 7000);
    }
    render();
  } catch (e) {
    el.textContent = "";
    toast("验光失败: " + e.message, "err", 5000);
  }
}

async function testAll() {
  const btn = $("btnTestAll");
  const prog = $("testProgress");
  btn.disabled = true;
  prog.style.display = "";
  let done = 0;
  const jobs = sites.map(async (s, i) => {
    await testSite(i);
    done++;
    prog.textContent = `验光中 ${done}/${sites.length}`;
  });
  await Promise.all(jobs);
  prog.style.display = "none";
  btn.disabled = false;
  toast("全部验光完毕", "ok", 2500);
}

/* ---------- 站点操作 ---------- */
function openAdd() { $("addForm").style.display = "block"; setTimeout(() => $("addBase").focus(), 60); }

async function addSite() {
  const base_url = $("addBase").value.trim();
  const model = $("addModel").value.trim();
  const api_key = $("addKey").value.trim();
  if (!base_url || !model) { toast("Base URL 和模型名必填", "warn"); return; }
  if (!api_key) { toast("API 密钥必填", "warn"); return; }
  try {
    await api("POST", "/api/site", { base_url, model, api_key });
    $("addBase").value = $("addModel").value = $("addKey").value = "";
    $("addForm").style.display = "none";
    markDirty();
    render();
    toast("已建档,记得存档", "ok", 2500);
  } catch (e) { toast(e.message, "err"); }
}

let confirmDel = {};
async function delSite(i) {
  const btn = $("delbtn-" + i);
  if (!confirmDel[i]) {
    confirmDel[i] = true;
    btn.innerHTML = "确认注销?";
    setTimeout(() => { confirmDel[i] = false; btn.innerHTML = ICONS.trash + " 注销"; }, 3000);
    return;
  }
  try { await api("DELETE", "/api/site/" + i); markDirty(); render(); toast("已注销,记得存档", "ok", 2500); }
  catch (e) { toast(e.message, "err"); }
}

function editSite(i) {
  const s = sites[i];
  const box = $("edit-" + i);
  box.innerHTML = `<div class="table" style="margin-top:10px;padding-top:10px;border-top:1px dashed var(--line)">
      <div class="tr"><div class="k">BASE URL</div>
        <div class="v"><input id="e${i}Base" value="${escapeHtml(s.base_url || "")}" spellcheck="false" style="flex:1"></div></div>
      <div class="tr"><div class="k">模型</div>
        <div class="v"><input id="e${i}Model" value="${escapeHtml(s.model || "")}" spellcheck="false" style="flex:1"></div></div>
      <div class="tr"><div class="k">密钥</div>
        <div class="v"><input id="e${i}Key" type="password" placeholder="${s.api_key ? "留空保持不变" : "sk-..."}" autocomplete="off" spellcheck="false" style="flex:1"></div></div>
    </div>
    <div class="ops">
      <button class="primary" onclick="saveEdit(${i})">保存</button>
      <button onclick="$('edit-${i}').innerHTML=''">取消</button>
    </div>`;
}

async function saveEdit(i) {
  const body = {
    base_url: $("e" + i + "Base").value.trim(),
    model: $("e" + i + "Model").value.trim(),
    api_key: $("e" + i + "Key").value.trim(),
  };
  try {
    await api("PUT", "/api/site/" + i, body);
    $("edit-" + i).innerHTML = "";
    markDirty(); render();
    toast("已修改,记得存档", "ok", 2500);
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- 导入导出 ---------- */
async function exportConfig() {
  try {
    const r = await api("GET", "/api/export");
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "kv-agent-vision-config-" + new Date().toISOString().slice(0, 10) + ".json";
    a.click();
    URL.revokeObjectURL(url);
    toast("档案已导出 ✓", "ok", 2500);
  } catch (e) { toast("导出失败: " + e.message, "err"); }
}

$("btnImport").onclick = () => $("importFile").click();
$("importFile").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const r = await api("POST", "/api/import", data);
    markDirty();
    render();
    toast("已导入 " + r.count + " 份档案,记得存档", "ok", 3500);
  } catch (err) { toast("导入失败: " + err.message, "err", 5000); }
};

/* ---------- 设备日志 ---------- */
$("btnProxyLog").onclick = async () => {
  const box = $("proxyLogBox");
  if (box.style.display !== "none") { box.style.display = "none"; return; }
  box.style.display = "";
  box.textContent = "读取中...";
  try {
    const r = await api("GET", "/api/proxy-log");
    box.textContent = r.log || "(无日志)";
    box.scrollTop = box.scrollHeight;
  } catch (err) { box.textContent = "读取失败: " + err.message; }
};

/* ---------- 事件绑定 ---------- */
$("btnAdd").onclick = openAdd;
$("btnAddOk").onclick = addSite;
$("btnAddCancel").onclick = () => { $("addForm").style.display = "none"; };
$("btnSave").onclick = save;
$("btnTestAll").onclick = testAll;
$("btnReload").onclick = () => { loadConfig(); toast("已重读档案", "ok", 2000); };
$("btnExport").onclick = exportConfig;
$("btnRestartProxy").onclick = async () => {
  const btn = $("btnRestartProxy");
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/restart-proxy", {});
    toast((r.log || []).join("；") || "设备状态未知", r.ok ? "ok" : "warn", r.ok ? 5000 : 8000);
    loadConfig();
  } catch (e) { toast("重启失败: " + e.message, "err", 5000); }
  btn.disabled = false;
};
$("btnTheme").onclick = cycleTheme;

applyTheme(localStorage.getItem(THEME_KEY) || "auto");
loadConfig();
</script>
</body>
</html>
"""




def default_env_path():
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "codex-deepseek-vision" / "env"
    return Path.home() / ".config" / "codex-deepseek-vision" / "env"


class ConfigStore:
    """共享 env 文件的读写(只管理 VISION* 与 LANG,保留其余键与注释)。"""

    def __init__(self, env_path):
        self.env_path = Path(env_path)
        self.sites = []
        self.others = []  # (key, value) 或 ("#", 注释文本) 或 ("", 空行)
        self.lang = "zh"
        self._load()

    # ---- 读取 ----
    def _load(self):
        self.sites = []
        self.others = []
        self.lang = "zh"
        if not self.env_path.is_file():
            return
        lines = self.env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        raw = {}  # index -> {field: value}
        for line in lines:
            stripped = line.strip()
            if not stripped:
                self.others.append(("", ""))
                continue
            if stripped.startswith("#"):
                self.others.append(("#", stripped))
                continue
            if "=" not in stripped:
                self.others.append(("", stripped))
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "LANG":
                self.lang = value or "zh"
                continue
            match = _KEY_RE.match(key)
            if match:
                index = int(match.group(1) or 0)
                raw.setdefault(index, {})[match.group(2)] = value
            else:
                self.others.append((key, value))
        for index in sorted(raw):
            site = raw[index]
            self.sites.append({
                "base_url": site.get("BASE_URL", ""),
                "api_key": site.get("API_KEY", ""),
                "model": site.get("MODEL", ""),
            })

    def reload(self):
        self._load()

    # ---- 写出 ----
    def render_text(self):
        lines = ["# 视觉 API 配置(共享,所有 Agent 共用;由 kv-agent-vision GUI 管理。"
                 "主站点 VISION_*,备用站点 VISION2_* / VISION3_* ...,故障自动切换)"]
        for index, site in enumerate(self.sites):
            # 与 vision.py 约定一致:主站点 VISION_*,备用站点从 VISION2_* 开始
            prefix = "VISION" if index == 0 else f"VISION{index + 1}"
            lines.append(f"{prefix}_API_KEY={site['api_key']}")
            lines.append(f"{prefix}_BASE_URL={site['base_url']}")
            lines.append(f"{prefix}_MODEL={site['model']}")
        if self.lang:
            lines.append(f"LANG={self.lang}")
        for item in self.others:
            kind, value = item
            if kind == "#":
                lines.append(value)
            elif kind:
                lines.append(f"{kind}={value}")
            else:
                lines.append(value)
        return "\n".join(lines) + "\n"

    def save(self):
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        backup = ""
        if self.env_path.is_file():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = f"env.bak-{stamp}"
            self.env_path.rename(self.env_path.parent / backup)
            # 只保留最近 10 份备份
            baks = sorted(self.env_path.parent.glob("env.bak-*"), reverse=True)
            for old in baks[10:]:
                try:
                    old.unlink()
                except OSError:
                    pass
        self.env_path.write_text(self.render_text(), encoding="utf-8")
        return backup

    # ---- 变更 ----
    def add_site(self, base_url, model, api_key):
        self.sites.append({"base_url": base_url, "api_key": api_key, "model": model})

    def update_site(self, index, base_url=None, model=None, api_key=None):
        site = self.sites[index]
        if base_url is not None:
            site["base_url"] = base_url
        if model is not None:
            site["model"] = model
        if api_key:
            site["api_key"] = api_key

    def delete_site(self, index):
        del self.sites[index]

    def move_site(self, index, direction=None, to=None):
        if index < 0 or index >= len(self.sites):
            raise ValueError("站点序号无效")
        if to is not None:
            if to < 0 or to >= len(self.sites):
                raise ValueError("目标位置无效")
            site = self.sites.pop(index)
            self.sites.insert(to, site)
            return
        target = index - 1 if direction == "up" else index + 1
        if target < 0 or target >= len(self.sites):
            raise ValueError("已在边界,无法移动")
        self.sites[index], self.sites[target] = self.sites[target], self.sites[index]

    # ---- 展示 ----
    def public_sites(self):
        result = []
        for site in self.sites:
            complete = all(site[k] for k in ("base_url", "api_key", "model"))
            result.append({
                "base_url": site["base_url"],
                "model": site["model"],
                "api_key": bool(site["api_key"]),
                "api_key_value": site["api_key"],
                "api_key_masked": self._mask_key(site["api_key"]),
                "complete": complete,
                "issues": [] if complete else ["字段不完整,该站点不会生效"],
            })
        return result

    @staticmethod
    def _mask_key(key):
        if not key:
            return "未设置"
        if len(key) <= 8:
            return "***"
        return key[:4] + "..." + key[-4:]


def test_site(store, index):
    site = store.sites[index]
    if not site["api_key"]:
        return {"ok": False, "latency_ms": 0, "error": "该站点未配置 API 密钥"}
    with _TEST_LOCK:
        old = {}
        for name in ("VISION_BASE_URL", "VISION_API_KEY", "VISION_MODEL"):
            old[name] = os.environ.get(name)
        os.environ["VISION_BASE_URL"] = site["base_url"]
        os.environ["VISION_API_KEY"] = site["api_key"]
        os.environ["VISION_MODEL"] = site["model"]
        start = time.time()
        try:
            result = vision.describe_image(
                _TEST_IMAGE, prompt="请用一句话简单描述这张图片。", max_tokens=256)
            return {"ok": True, "latency_ms": int((time.time() - start) * 1000),
                    "preview": result[:120]}
        except vision.VisionError as exc:
            return {"ok": False, "latency_ms": int((time.time() - start) * 1000),
                    "error": str(exc)}
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _shared_dir():
    """共享配置/运行时目录:Windows %LOCALAPPDATA%\\codex-deepseek-vision,其它 ~/.config。"""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "codex-deepseek-vision"
    return Path.home() / ".config" / "codex-deepseek-vision"


def proxy_status():
    pid = _port_pid(_PROXY_PORT)
    return {"port": _PROXY_PORT, "listening": pid is not None, "pid": pid,
            "startup_script": str(_startup_script()) if _startup_script() else ""}


def _port_pid(port):
    try:
        result = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                                capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    # 中文 Windows 的 netstat 输出为 GBK,按字节解码并容错(关键字段均为 ASCII)
    out = (result.stdout or b"").decode("utf-8", errors="replace")
    for line in out.splitlines():
        if f"127.0.0.1:{port}" in line and "LISTENING" in line:
            parts = line.split()
            return int(parts[-1]) if parts else None
    return None


def _startup_script():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    path = (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" /
            "Programs" / "Startup" / "codex-deepseek-vision-proxy.cmd")
    return path if path.is_file() else None


def restart_proxy():
    script = _startup_script()
    if not script:
        return {"ok": False, "log": ["未找到开机启动脚本 codex-deepseek-vision-proxy.cmd,请手动重启"]}
    log = []
    pid = _port_pid(_PROXY_PORT)
    if pid:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
        log.append(f"已停止旧代理(PID {pid})")
        time.sleep(0.8)
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags)
    time.sleep(2.5)
    new_pid = _port_pid(_PROXY_PORT)
    if new_pid:
        log.append(f"新代理已监听 127.0.0.1:{_PROXY_PORT}(PID {new_pid})")
        return {"ok": True, "log": log}
    return {"ok": False, "log": log + [f"代理未在预期时间内监听 {_PROXY_PORT},请手动检查"]}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "kv-agent-vision-gui/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("gui: " + fmt % args + "\n")

    # ---- helpers ----
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, text):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _store(self):
        return self.server.store  # type: ignore[attr-defined]

    # ---- routing ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(PAGE)
        elif parsed.path == "/api/config":
            store = self._store()
            with _STATE_LOCK:
                proxy_pid = _port_pid(_PROXY_PORT)
                cfg = {
                    "env_path": str(store.env_path),
                    "sites": store.public_sites(),
                    "lang": store.lang,
                    "proxy_listening": proxy_pid is not None,
                    "proxy_port": _PROXY_PORT,
                    "proxy_pid": proxy_pid or 0,
                }
            self._send(200, cfg)
        elif parsed.path == "/api/export":
            store = self._store()
            with _STATE_LOCK:
                payload = {
                    "version": 2,
                    "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "lang": store.lang,
                    "sites": [dict(site) for site in store.sites],
                }
            self._send(200, payload)
        elif parsed.path == "/api/proxy-log":
            log_path = _shared_dir() / "proxy.log"
            tail = ""
            if log_path.is_file():
                try:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    tail = "\n".join(lines[-30:])
                except OSError:
                    tail = "(读取日志失败)"
            self._send(200, {"log": tail})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        store = self._store()
        body = self._json_body()
        try:
            if parsed.path == "/api/site":
                with _STATE_LOCK:
                    base_url = (body.get("base_url") or "").strip()
                    model = (body.get("model") or "").strip()
                    api_key = (body.get("api_key") or "").strip()
                    if not base_url or not model:
                        raise ValueError("Base URL 与模型名必填")
                    if not api_key:
                        raise ValueError("API 密钥必填")
                    store.add_site(base_url, model, api_key)
                self._send(200, {"ok": True})
            elif parsed.path == "/api/save":
                with _STATE_LOCK:
                    backup = store.save()
                self._send(200, {"ok": True, "env_path": str(store.env_path), "backup": backup})
            elif parsed.path == "/api/move":
                with _STATE_LOCK:
                    index = int(body.get("index", 0))
                    if "to" in body:
                        store.move_site(index, to=int(body.get("to")))
                    else:
                        store.move_site(index, body.get("direction", "up"))
                self._send(200, {"ok": True})
            elif parsed.path == "/api/import":
                with _STATE_LOCK:
                    raw_sites = body.get("sites")
                    if not isinstance(raw_sites, list):
                        raise ValueError("导入数据缺少 sites 列表")
                    new_sites = []
                    for item in raw_sites:
                        if not isinstance(item, dict):
                            raise ValueError("站点格式不正确")
                        base_url = (item.get("base_url") or "").strip()
                        model = (item.get("model") or "").strip()
                        api_key = (item.get("api_key") or "").strip()
                        if not base_url or not model or not api_key:
                            raise ValueError("站点缺少 base_url / model / api_key")
                        new_sites.append({"base_url": base_url, "api_key": api_key, "model": model})
                    store.sites = new_sites
                    if body.get("lang"):
                        store.lang = str(body["lang"]).strip()[:16]
                self._send(200, {"ok": True, "count": len(new_sites)})
            elif parsed.path == "/api/test":
                index = int(body.get("index", 0))
                with _STATE_LOCK:
                    if index < 0 or index >= len(store.sites):
                        raise ValueError("站点序号无效")
                    result = test_site(store, index)
                self._send(200, result)
            elif parsed.path == "/api/restart-proxy":
                result = restart_proxy()
                self._send(200, result)
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        match = re.match(r"^/api/site/(\d+)$", parsed.path)
        if not match:
            self._send(404, {"error": "not found"})
            return
        store = self._store()
        body = self._json_body()
        try:
            with _STATE_LOCK:
                index = int(match.group(1))
                if index < 0 or index >= len(store.sites):
                    raise ValueError("站点序号无效")
                base_url = (body.get("base_url") or "").strip()
                model = (body.get("model") or "").strip()
                api_key = (body.get("api_key") or "").strip()
                store.update_site(index, base_url=base_url, model=model, api_key=api_key)
            self._send(200, {"ok": True})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._send(400, {"error": str(exc)})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        match = re.match(r"^/api/site/(\d+)$", parsed.path)
        if not match:
            self._send(404, {"error": "not found"})
            return
        store = self._store()
        try:
            with _STATE_LOCK:
                index = int(match.group(1))
                if index < 0 or index >= len(store.sites):
                    raise ValueError("站点序号无效")
                store.delete_site(index)
            self._send(200, {"ok": True})
        except (ValueError, IndexError) as exc:
            self._send(400, {"error": str(exc)})


def _test_image_url():
    """测试用图片:优先同目录 vision-test.png,否则内置 1x1 PNG。"""
    candidates = [
        Path(__file__).resolve().parent / "vision-test.png",
        Path(__file__).resolve().parent / ".." / "agent-vision" / "vision-test.png",
    ]
    for path in candidates:
        if path.is_file():
            mime, _ = mimetypes.guess_type(path.name) or ("image/png", None)
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    return "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode()


_TEST_IMAGE = _test_image_url()


def main():
    parser = argparse.ArgumentParser(description="kv-agent-vision 配置中心(GUI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19123)
    parser.add_argument("--env-file", default="", help="管理指定的 env 文件(默认共享配置)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    env_path = args.env_file or os.environ.get("CODEX_DEEPSEEK_VISION_ENV") or default_env_path()
    store = ConfigStore(env_path)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"警告: 监听 {args.host},配置含 API 密钥,不建议对局域网开放", file=sys.stderr)

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    server.store = store  # type: ignore[attr-defined]
    actual = server.server_address[1]

    url = f"http://127.0.0.1:{actual}/"
    print(f"kv-agent-vision 配置中心已启动: {url}")
    print(f"共享配置: {env_path}")
    print("按 Ctrl+C 退出")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
