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
<title>kv-agent-vision · 配置控制台</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2337d67a' stroke-width='1.6'%3E%3Cpath d='M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z'/%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3C/svg%3E">
<style>
  /* ============ Design Tokens ============ */
  :root {
    --bg-base: #0b0d10;
    --bg-elev: rgba(16,19,25,.86);
    --surface: rgba(20,24,31,.88);
    --surface-2: rgba(25,30,38,.9);
    --surface-hover: rgba(29,35,44,.92);
    --surface-active: rgba(35,42,53,.95);
    --border-subtle: #20262f;
    --border-strong: #2e3642;
    --text-primary: #e8ebf0;
    --text-secondary: #9aa3b2;
    --text-tertiary: #626c7a;
    --signal-positive: #37d67a;
    --signal-warning: #e8a33d;
    --signal-critical: #ff5d5d;
    --signal-info: #54c8e0;
    --signal-offline: #6b7280;
    --signal-accent: #e8ebf0;
    --positive-soft: rgba(55,214,122,.12);
    --warning-soft: rgba(232,163,61,.12);
    --critical-soft: rgba(255,93,93,.12);
    --info-soft: rgba(84,200,224,.12);
    --font-ui: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    --font-mono: "Cascadia Mono", "JetBrains Mono", Consolas, "Courier New", monospace;
    --motion-instant: 60ms;
    --motion-fast: 120ms;
    --motion-normal: 180ms;
    --motion-panel: 240ms;
    --ease-standard: cubic-bezier(.2,.7,.3,1);
    --ease-sharp: cubic-bezier(.4,0,.6,1);
    --header-h: 44px;
    --rail-w: 84px;
    --status-h: 26px;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      --bg-base: #f4f6f9; --bg-elev: rgba(255,255,255,.86); --surface: rgba(255,255,255,.9);
      --surface-2: rgba(238,241,245,.92); --surface-hover: rgba(233,237,242,.95);
      --surface-active: rgba(223,229,236,.97);
      --border-subtle: #e2e7ee; --border-strong: #c4cdd8;
      --text-primary: #1a2029; --text-secondary: #525d6b; --text-tertiary: #8a94a3;
      --signal-positive: #128a4b; --signal-warning: #a8680f; --signal-critical: #d0342e;
      --signal-info: #177a94; --signal-offline: #8a94a3; --signal-accent: #1a2029;
      --positive-soft: rgba(18,138,75,.1); --warning-soft: rgba(168,104,15,.1);
      --critical-soft: rgba(208,52,46,.1); --info-soft: rgba(23,122,148,.1);
    }
  }
  :root[data-theme="light"] {
    --bg-base: #f4f6f9; --bg-elev: rgba(255,255,255,.86); --surface: rgba(255,255,255,.9);
    --surface-2: rgba(238,241,245,.92); --surface-hover: rgba(233,237,242,.95);
    --surface-active: rgba(223,229,236,.97);
    --border-subtle: #e2e7ee; --border-strong: #c4cdd8;
    --text-primary: #1a2029; --text-secondary: #525d6b; --text-tertiary: #8a94a3;
    --signal-positive: #128a4b; --signal-warning: #a8680f; --signal-critical: #d0342e;
    --signal-info: #177a94; --signal-offline: #8a94a3; --signal-accent: #1a2029;
    --positive-soft: rgba(18,138,75,.1); --warning-soft: rgba(168,104,15,.1);
    --critical-soft: rgba(208,52,46,.1); --info-soft: rgba(23,122,148,.1);
  }
  * { box-sizing: border-box; }
  html { scrollbar-color: var(--border-strong) transparent; }
  body { margin: 0; height: 100vh; overflow: hidden; background: var(--bg-base);
         color: var(--text-primary); font: 13px/1.5 var(--font-ui);
         -webkit-font-smoothing: antialiased; }
  button { background: transparent; border: 1px solid var(--border-strong); color: var(--text-primary);
           padding: 5px 12px; border-radius: 3px; cursor: pointer; font-size: 12.5px;
           font-family: var(--font-ui); display: inline-flex; align-items: center; gap: 6px;
           transition: background var(--motion-fast) var(--ease-standard),
                       border-color var(--motion-fast), color var(--motion-fast),
                       transform var(--motion-instant) var(--ease-sharp); }
  button:hover { background: var(--surface-hover); border-color: var(--text-tertiary); }
  button:active { transform: translateY(1px); }
  button.primary { background: var(--signal-positive); border-color: var(--signal-positive); color: #06120b; }
  button.primary:hover { background: var(--signal-positive); opacity: .85; }
  button.danger:hover { border-color: var(--signal-critical); color: var(--signal-critical); background: var(--critical-soft); }
  button:disabled { opacity: .4; cursor: not-allowed; transform: none !important; }
  button svg { flex: none; }
  input { background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-primary);
          padding: 5px 9px; border-radius: 3px; font: 12.5px var(--font-mono); }
  input:focus { outline: none; border-color: var(--signal-info); box-shadow: 0 0 0 1px var(--signal-info); }
  .mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
  .label { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 1.5px;
           text-transform: uppercase; color: var(--text-tertiary); }
  .hidden-file { display: none; }

  /* ============ App Shell ============ */
  #bg3d { position: fixed; inset: 0; z-index: 0; pointer-events: none; }
  .shell { display: grid; height: 100vh; grid-template-rows: var(--header-h) 1fr var(--status-h);
           grid-template-columns: var(--rail-w) 1fr; grid-template-areas:
             "head head" "rail main" "status status"; position: relative; z-index: 1; }
  header { grid-area: head; display: flex; align-items: center; gap: 14px; padding: 0 16px;
           background: var(--bg-elev); border-bottom: 1px solid var(--border-subtle); }
  .brand { display: flex; align-items: center; gap: 10px; font-size: 13.5px; font-weight: 600;
           letter-spacing: .5px; }
  .brand svg { color: var(--signal-positive); }
  .brand .ver { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-tertiary);
                font-weight: 400; letter-spacing: 1px; }
  .head-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
  .env-tag { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 1px;
             color: var(--text-tertiary); border: 1px solid var(--border-subtle); padding: 2px 8px; }
  .dirty-tag { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 1px;
               color: var(--signal-warning); border: 1px solid var(--signal-warning); padding: 2px 8px;
               display: none; }
  .palette-hint { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-tertiary);
                  border: 1px solid var(--border-subtle); padding: 2px 8px; }

  /* Navigation Rail */
  nav { grid-area: rail; background: var(--bg-elev); border-right: 1px solid var(--border-subtle);
        display: flex; flex-direction: column; align-items: stretch; padding: 10px 8px; gap: 4px; }
  .nav-item { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 9px 4px;
              border: 1px solid transparent; border-radius: 4px; cursor: pointer; color: var(--text-tertiary);
              font-size: 10px; font-family: var(--font-mono); letter-spacing: 1px;
              transition: background var(--motion-fast), color var(--motion-fast); }
  .nav-item:hover { background: var(--surface-hover); color: var(--text-secondary); }
  .nav-item.active { background: var(--surface-active); color: var(--text-primary);
                     border-color: var(--border-strong); }
  .nav-item.active svg { color: var(--signal-positive); }

  /* Workspace */
  main { grid-area: main; overflow-y: auto; padding: 14px 18px 20px; }
  .pane { display: none; }
  .pane.active { display: block; animation: paneIn var(--motion-normal) var(--ease-standard) both; }
  @keyframes paneIn { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
  .section-head { display: flex; align-items: center; gap: 10px; margin: 2px 0 10px; }
  .section-head .label { color: var(--signal-info); }
  .section-head .count { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); }
  .section-head .spacer { flex: 1; }
  .toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }

  /* 遥测面板 */
  .panel { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 4px;
           padding: 12px 14px; }
  .panel-title { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 1.5px;
                 color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 10px;
                 display: flex; align-items: center; gap: 8px; }
  .tel-row { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
  .tel { display: flex; flex-direction: column; gap: 2px; }
  .tel .k { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; color: var(--text-tertiary); }
  .tel .v { font-family: var(--font-mono); font-size: 15px; font-variant-numeric: tabular-nums;
            color: var(--text-primary); }
  .tel .v.ok { color: var(--signal-positive); } .tel .v.warn { color: var(--signal-warning); }
  .tel .v.err { color: var(--signal-critical); }

  /* 状态灯 */
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--signal-offline); }
  .dot.on { background: var(--signal-positive); animation: breathe 2.2s ease infinite; }
  .dot.probing { background: var(--signal-warning); animation: blink .5s steps(2) infinite; }
  .dot.down { background: var(--signal-critical); }
  .dot.pending { background: var(--signal-info); }
  .status-chip.pending { color: var(--signal-info); border-color: var(--signal-info); }
  /* 待配置密钥横幅 */
  .banner-warn { border: 1px solid var(--signal-warning); background: var(--warning-soft);
                 color: var(--signal-warning); padding: 8px 14px; border-radius: 4px;
                 margin-bottom: 12px; font-size: 12.5px; font-family: var(--font-mono);
                 letter-spacing: .3px; display: flex; align-items: center; gap: 8px; }
  .banner-warn b { font-weight: 600; }
  @keyframes breathe { 0%,100% { box-shadow: 0 0 0 0 var(--positive-soft); }
                       55% { box-shadow: 0 0 0 5px rgba(55,214,122,0); } }
  @keyframes blink { 50% { opacity: .25; } }

  /* 节点数据表 */
  .node-row { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 4px;
              margin-bottom: 8px; animation: rowIn var(--motion-normal) var(--ease-standard) both; }
  .node-row.dragging { opacity: .4; border-style: dashed; }
  .node-row.drag-over-top { box-shadow: inset 0 2px 0 var(--signal-info); }
  .node-row.drag-over-bottom { box-shadow: inset 0 -2px 0 var(--signal-info); }
  @keyframes rowIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
  .node-main { display: flex; align-items: center; gap: 12px; padding: 10px 14px; flex-wrap: wrap; }
  .drag-handle { cursor: grab; color: var(--text-tertiary); display: inline-flex; padding: 2px; }
  .drag-handle:hover { color: var(--text-primary); }
  .drag-handle:active { cursor: grabbing; }
  .node-id { font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px;
             color: var(--signal-info); min-width: 62px; }
  .role-tag { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; padding: 1px 7px;
              border: 1px solid var(--border-strong); color: var(--text-secondary); }
  .role-tag.main { border-color: var(--signal-positive); color: var(--signal-positive); }
  .node-host { font-family: var(--font-mono); font-size: 12.5px; color: var(--text-primary);
               word-break: break-all; min-width: 0; flex: 1 1 240px; }
  .node-host .model { color: var(--text-tertiary); font-size: 11px; margin-left: 10px; }
  .node-metrics { display: flex; align-items: center; gap: 10px; }
  .spark { display: inline-flex; align-items: flex-end; gap: 2px; height: 16px; }
  .spark i { width: 3px; background: var(--signal-info); border-radius: 1px; opacity: .7; }
  .spark i.hot { background: var(--signal-positive); }
  .status-chip { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 1px;
                 padding: 2px 8px; border: 1px solid var(--border-strong); color: var(--text-tertiary);
                 display: inline-flex; align-items: center; gap: 6px; }
  .status-chip.live { color: var(--signal-positive); border-color: var(--signal-positive); }
  .status-chip.probing { color: var(--signal-warning); border-color: var(--signal-warning); }
  .status-chip.down { color: var(--signal-critical); border-color: var(--signal-critical); }
  .node-ops { display: flex; gap: 5px; margin-left: auto; }
  .node-ops button { padding: 4px 8px; font-size: 12px; }
  .node-detail { border-top: 1px solid var(--border-subtle); padding: 10px 14px; display: none; }
  .node-detail.open { display: block; animation: paneIn var(--motion-fast) var(--ease-standard); }
  .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
  .detail-field label { display: block; font-family: var(--font-mono); font-size: 10px;
                        letter-spacing: 1px; color: var(--text-tertiary); margin-bottom: 3px; }
  .detail-field input { width: 100%; }
  .detail-ops { display: flex; gap: 8px; margin-top: 12px; }
  .key-val { display: flex; align-items: center; gap: 8px; }
  .key-toggle { cursor: pointer; color: var(--text-tertiary); display: inline-flex; padding: 2px; }
  .key-toggle:hover { color: var(--text-primary); }
  .row-error { font-family: var(--font-mono); font-size: 11px; color: var(--signal-critical);
               padding: 6px 14px 2px; display: none; word-break: break-all; }
  .row-error.show { display: block; }

  /* 空状态 */
  .empty { text-align: center; padding: 60px 20px; border: 1px dashed var(--border-strong);
           border-radius: 4px; }
  .empty .glyph { color: var(--text-tertiary); margin-bottom: 14px; }
  .empty h2 { font-size: 14px; margin: 0 0 6px; font-weight: 600; letter-spacing: .5px; }
  .empty p { color: var(--text-tertiary); margin: 0 auto 18px; max-width: 440px; font-size: 12.5px; }
  .empty .seq { display: inline-flex; gap: 14px; margin-bottom: 20px; font-family: var(--font-mono);
                font-size: 11px; color: var(--text-tertiary); letter-spacing: 1px; }
  .empty .seq b { color: var(--signal-info); font-weight: 400; }

  /* 日志 */
  .log-view { background: var(--bg-elev); border: 1px solid var(--border-subtle); border-radius: 4px;
              font: 11.5px/1.6 var(--font-mono); color: var(--text-secondary); padding: 12px 14px;
              min-height: 200px; max-height: 60vh; overflow: auto; white-space: pre-wrap;
              word-break: break-all; }
  .log-empty { color: var(--text-tertiary); }

  /* Status Bar */
  .statusbar { grid-area: status; display: flex; align-items: center; gap: 18px; padding: 0 14px;
               background: var(--bg-elev); border-top: 1px solid var(--border-subtle);
               font-family: var(--font-mono); font-size: 10.5px; color: var(--text-tertiary);
               letter-spacing: .5px; white-space: nowrap; overflow: hidden; }
  .statusbar .sb-item { display: inline-flex; align-items: center; gap: 6px; }
  .statusbar .sb-val { color: var(--text-secondary); }
  .statusbar .sb-val.ok { color: var(--signal-positive); }
  .statusbar .sb-val.err { color: var(--signal-critical); }
  .statusbar .spacer { flex: 1; }

  /* Toast */
  .msg { position: fixed; bottom: 40px; left: 50%; transform: translateX(-50%) translateY(8px);
         padding: 8px 16px; font-size: 12.5px; font-family: var(--font-mono); opacity: 0;
         pointer-events: none; transition: opacity var(--motion-normal), transform var(--motion-normal);
         background: var(--surface-active); border: 1px solid var(--border-strong);
         color: var(--text-primary); max-width: min(92vw, 560px); z-index: 99; }
  .msg.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .msg.ok { border-color: var(--signal-positive); color: var(--signal-positive); }
  .msg.err { border-color: var(--signal-critical); color: var(--signal-critical); }
  .msg.warn { border-color: var(--signal-warning); color: var(--signal-warning); }

  /* Command Palette */
  .palette { position: fixed; inset: 0; background: rgba(5,7,9,.55); display: none;
             align-items: flex-start; justify-content: center; padding-top: 15vh; z-index: 120; }
  .palette.open { display: flex; }
  .palette-box { width: min(560px, 92vw); background: var(--surface); border: 1px solid var(--border-strong);
                 border-radius: 6px; box-shadow: 0 18px 50px rgba(0,0,0,.5); overflow: hidden;
                 animation: paneIn var(--motion-panel) var(--ease-standard); }
  .palette-input { width: 100%; border: none; border-bottom: 1px solid var(--border-subtle);
                   border-radius: 0; padding: 12px 16px; font-size: 14px; background: var(--surface); }
  .palette-input:focus { outline: none; box-shadow: none; }
  .palette-list { max-height: 320px; overflow-y: auto; padding: 6px; }
  .palette-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 4px;
                  cursor: pointer; font-size: 13px; }
  .palette-item .cmd-label { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10.5px;
                             letter-spacing: 1px; margin-left: auto; }
  .palette-item.active, .palette-item:hover { background: var(--surface-hover); }
  .palette-empty { padding: 16px; color: var(--text-tertiary); font-size: 12.5px; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
  @media (max-width: 720px) {
    :root { --rail-w: 0px; }
    nav { display: none; }
    .palette-hint { display: none; }
    .node-metrics { display: none; }
    .node-ops { margin-left: 0; }
  }
</style>
</head>
<body>
<canvas id="bg3d" aria-hidden="true"></canvas>
<div class="shell">
  <header>
    <div class="brand">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>
      KV-AGENT-VISION <span class="ver">CTRL v1.0</span>
    </div>
    <div class="head-right">
      <span id="envTag" class="env-tag" style="display:none"></span>
      <span id="dirtyTag" class="dirty-tag">● UNSAVED</span>
      <span class="palette-hint">CTRL+K</span>
      <button id="btnTheme" title="切换明暗主题" style="padding:4px 8px"></button>
    </div>
  </header>

  <nav>
    <div class="nav-item active" data-tab="nodes" title="节点列表">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="7" r="2.4"/><circle cx="12" cy="17" r="2.4"/><path d="M8 7.4l7.4 1M7.4 8.2l3.4 7M14 9.2l-1.6 5.6"/></svg>
      NODES
    </div>
    <div class="nav-item" data-tab="overview" title="状态概览">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      OVERVIEW
    </div>
    <div class="nav-item" data-tab="log" title="代理日志">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/></svg>
      LOG
    </div>
  </nav>

  <main id="workspace">
    <!-- NODES -->
    <div class="pane active" id="pane-nodes">
      <div class="toolbar">
        <button class="primary" id="btnAdd">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
          添加节点
        </button>
        <button id="btnTestAll">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
          全部探测
        </button>
        <button id="btnSave">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
          保存
        </button>
        <button id="btnRestartProxy">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 014-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 01-4 4H3"/></svg>
          重启代理
        </button>
        <button id="btnExport" title="导出完整配置(含密钥,仅本地备份用)">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3m0 0L8 7m4-4l4 4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
          导出
        </button>
        <button id="btnExportRedacted" title="导出不含密钥的配置包,发给其他电脑自动装配">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v7a1 1 0 001 1h14a1 1 0 001-1v-7"/><path d="M16 6l-4-4-4 4m4-4v11"/></svg>
          分发导出
        </button>
        <button id="btnImport">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l4-4m-4 4l-4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
          导入
        </button>
        <input type="file" id="importFile" class="hidden-file" accept=".json,application/json">
        <span style="flex:1"></span>
        <span id="testProgress" class="label" style="display:none"></span>
      </div>

      <div id="keyBanner" class="banner-warn" style="display:none"></div>

      <div class="section-head">
        <span class="label">NODE REGISTRY</span>
        <span class="count" id="siteCount">0 节点</span>
        <span class="spacer"></span>
        <span class="label" id="proxyInline"></span>
      </div>

      <div id="addForm" class="panel" style="display:none;margin-bottom:12px">
        <div class="panel-title">REGISTER NODE · 添加节点</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">
          <div class="detail-field"><label>BASE URL</label>
            <input id="addBase" placeholder="https://api.example.com/v1" spellcheck="false"></div>
          <div class="detail-field"><label>MODEL</label>
            <input id="addModel" placeholder="model-name" spellcheck="false"></div>
          <div class="detail-field"><label>API KEY</label>
            <input id="addKey" type="password" placeholder="sk-..." autocomplete="off" spellcheck="false"></div>
        </div>
        <div class="detail-ops">
          <button class="primary" id="btnAddOk">注册</button>
          <button id="btnAddCancel">取消</button>
        </div>
      </div>

      <div id="nodes"></div>
    </div>

    <!-- OVERVIEW -->
    <div class="pane" id="pane-overview">
      <div class="section-head"><span class="label">SYSTEM OVERVIEW</span><span class="spacer"></span></div>
      <div class="grid-2">
        <div class="panel">
          <div class="panel-title"><span id="ovProxyDot" class="dot off"></span> VISION PROXY · 视觉代理</div>
          <div class="tel-row">
            <div class="tel"><span class="k">STATUS</span><span class="v" id="ovProxyStatus">OFFLINE</span></div>
            <div class="tel"><span class="k">PORT</span><span class="v" id="ovProxyPort">—</span></div>
            <div class="tel"><span class="k">PID</span><span class="v" id="ovProxyPid">—</span></div>
            <div class="tel"><span class="k">ENV</span><span class="v" id="ovEnv" style="font-size:12px">—</span></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-title">NODE TELEMETRY · 节点遥测</div>
          <div class="tel-row">
            <div class="tel"><span class="k">REGISTERED</span><span class="v" id="ovNodes">0</span></div>
            <div class="tel"><span class="k">UP</span><span class="v ok" id="ovUp">0</span></div>
            <div class="tel"><span class="k">DOWN</span><span class="v" id="ovDown">0</span></div>
            <div class="tel"><span class="k">AVG LATENCY</span><span class="v" id="ovLatency">—</span></div>
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title">RECENT PROBES · 最近探测</div>
        <div id="probeHistory" class="log-view" style="min-height:120px;max-height:40vh"></div>
      </div>
    </div>

    <!-- LOG -->
    <div class="pane" id="pane-log">
      <div class="section-head"><span class="label">PROXY LOG · 代理日志</span>
        <span class="spacer"></span>
        <button id="btnLogRefresh" style="padding:4px 10px">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6"/></svg>
          刷新
        </button>
      </div>
      <div id="logView" class="log-view"><span class="log-empty">加载中...</span></div>
    </div>
  </main>

  <div class="statusbar">
    <span class="sb-item"><span id="sbProxyDot" class="dot off"></span>PROXY <span class="sb-val" id="sbProxy">OFFLINE</span></span>
    <span class="sb-item">PID <span class="sb-val mono" id="sbPid">—</span></span>
    <span class="sb-item">NODES <span class="sb-val" id="sbNodes">0</span></span>
    <span class="sb-item">LATENCY <span class="sb-val mono" id="sbLatency">—</span></span>
    <span class="sb-item" id="sbSync">SYNCED</span>
    <span class="spacer"></span>
    <span class="sb-item mono" id="sbClock"></span>
  </div>

  <div id="msg" class="msg"></div>

  <div class="palette" id="palette">
    <div class="palette-box">
      <input class="palette-input" id="paletteInput" placeholder="输入命令… (添加 / 测试 / 保存 / 主题)" spellcheck="false">
      <div class="palette-list" id="paletteList"></div>
    </div>
  </div>
</div>

<script>
"use strict";
let sites = [];
let dirty = false;
let activeTab = "nodes";
const RESULTS_KEY = "kv-gui-test-results";
const THEME_KEY = "kv-gui-theme";

const $ = (id) => document.getElementById(id);
const ICONS = {
  eye: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-10-8-10-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 10 8 10 8a18.5 18.5 0 01-2.16 3.19M1 1l22 22"/></svg>',
  drag: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  edit: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5z"/></svg>',
  trash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/></svg>',
  sun: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>'
};

function toast(text, kind, ms) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg show " + (kind || "ok");
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = "msg"; }, ms || 3500);
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
  $("btnTheme").title = dark ? "切换到亮色" : "切换到暗色";
}
function cycleTheme() {
  const cur = localStorage.getItem(THEME_KEY) || "auto";
  const next = cur === "auto" ? "dark" : (cur === "dark" ? "light" : "auto");
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

/* ---------- 遥测数据 ---------- */
function loadResults() {
  try { return JSON.parse(localStorage.getItem(RESULTS_KEY) || "{}"); }
  catch (e) { return {}; }
}
function saveResult(baseUrl, ok, latency) {
  const r = loadResults();
  const hist = r[baseUrl] || { ok: null, latency: 0, ts: 0, history: [] };
  hist.ok = !!ok; hist.latency = latency || 0; hist.ts = Date.now();
  hist.history = (hist.history || []).concat(latency || 0).slice(-10);
  r[baseUrl] = hist;
  try { localStorage.setItem(RESULTS_KEY, JSON.stringify(r)); } catch (e) {}
}
function nodeState(s) {
  if (!s.base_url || !s.model) return { label: "INVALID", cls: "", dot: "off", pending: false };
  if (!s.has_key) return { label: "KEY PENDING", cls: "", dot: "pending", pending: true };
  const r = loadResults()[s.base_url];
  if (!r || r.ok === null) return { label: "UNTESTED", cls: "", dot: "off", latency: null, history: [] };
  if (r.ok) return { label: "LIVE", cls: "live", dot: "on", latency: r.latency, history: r.history || [] };
  return { label: "DOWN", cls: "down", dot: "down", latency: r.latency, history: r.history || [] };
}
function sparkHtml(history) {
  if (!history || !history.length) return '<span class="spark"></span>';
  const max = Math.max(...history, 1);
  const bars = history.slice(-8).map((v) => {
    const h = Math.max(2, Math.round((v / max) * 15));
    const hot = v === Math.max(...history) && v > 0;
    return `<i style="height:${h}px" class="${hot ? "hot" : ""}"></i>`;
  }).join("");
  return `<span class="spark">${bars}</span>`;
}

/* ---------- 渲染:节点 ---------- */
function renderNodes() {
  const box = $("nodes");
  if (!sites.length) {
    box.innerHTML = `
      <div class="empty">
        <div class="glyph">
          <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"
               stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="7" r="2.4"/><circle cx="12" cy="17" r="2.4"/><path d="M8 7.4l7.4 1M7.4 8.2l3.4 7M14 9.2l-1.6 5.6"/></svg>
        </div>
        <h2>尚未注册任何视觉节点</h2>
        <p>注册后,所有装配了本能力的 Agent 将通过这些节点看图。第 1 个为主节点,
           其余为备用——主节点故障时自动切换。</p>
        <div class="seq"><b>01</b> REGISTER <b>02</b> PROBE <b>03</b> SAVE <b>04</b> RESTART</div>
        <button class="primary" onclick="openAdd()">注册节点</button>
      </div>`;
  } else {
    box.innerHTML = sites.map((s, i) => {
      const st = nodeState(s);
      const role = i === 0 ? '<span class="role-tag main">MAIN</span>'
                           : '<span class="role-tag">BACKUP</span>';
      const inc = s.complete ? "" : '<span class="role-tag">INVALID</span>';
      return `<div class="node-row" data-i="${i}" draggable="true">
        <div class="node-main">
          <span class="drag-handle" title="拖拽排序">${ICONS.drag}</span>
          <span class="dot ${st.dot}"></span>
          <span class="node-id">NODE-${String(i + 1).padStart(2, "0")}</span>
          ${role}${inc}
          <span class="node-host">${escapeHtml(s.base_url || "(empty)")}
            <span class="model">${escapeHtml(s.model || "")}</span></span>
          <span class="node-metrics">
            ${sparkHtml(st.history)}
            <span class="mono" style="font-size:11px;color:var(--text-secondary);min-width:52px;text-align:right">
              ${st.latency !== null ? st.latency + "ms" : "—"}</span>
            <span class="status-chip ${st.cls}${st.pending ? " pending" : ""}">${st.label}</span>
          </span>
          <span class="node-ops">
            <button onclick="testSite(${i})">探测</button>
            <button onclick="toggleDetail(${i})">${ICONS.edit} 编辑</button>
            <button class="danger" id="delbtn-${i}" onclick="delSite(${i})">${ICONS.trash}</button>
          </span>
        </div>
        <div class="row-error" id="err-${i}"></div>
        <div class="node-detail" id="detail-${i}">
          <div class="detail-grid">
            <div class="detail-field"><label>BASE URL</label>
              <input id="e${i}Base" value="${escapeHtml(s.base_url || "")}" spellcheck="false"></div>
            <div class="detail-field"><label>MODEL</label>
              <input id="e${i}Model" value="${escapeHtml(s.model || "")}" spellcheck="false"></div>
            <div class="detail-field"><label>API KEY (留空保持不变)</label>
              <div class="key-val"><input id="e${i}Key" type="password"
                placeholder="${s.api_key ? "set; blank = keep" : "sk-..."}" autocomplete="off" spellcheck="false" style="flex:1">
                ${s.api_key ? `<span class="key-toggle" id="kt-${i}" title="显示当前密钥" onclick="toggleEditKey(${i})">${ICONS.eye}</span>` : ""}
              </div></div>
          </div>
          <div class="detail-ops">
            <button class="primary" onclick="saveEdit(${i})">保存修改</button>
            <button onclick="toggleDetail(${i})">关闭</button>
          </div>
        </div>
      </div>`;
    }).join("");
    bindDrag();
  }
  $("siteCount").textContent = sites.length + " 节点";
  /* 同步节点状态给 3D 背景层 */
  window.__KV_3D = sites.map((s) => ({ url: s.base_url, state: nodeState(s).label }));
  if (window.__KV_3D_REBUILD) window.__KV_3D_REBUILD(window.__KV_3D);
  updateBanner();
  updateOverview();
}

function toggleDetail(i) {
  const d = $("detail-" + i);
  d.classList.toggle("open");
}

/* 密钥显隐(编辑面板内) */
let keyVisible = {};
function toggleEditKey(i) {
  keyVisible[i] = !keyVisible[i];
  const s = sites[i];
  const el = $("e" + i + "Key");
  if (keyVisible[i]) { el.type = "text"; el.value = s.api_key_value; }
  else { el.type = "password"; el.value = ""; }
  $("kt-" + i).innerHTML = keyVisible[i] ? ICONS.eyeOff : ICONS.eye;
}

function bindDrag() {
  let from = null;
  document.querySelectorAll(".node-row[draggable]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      from = parseInt(card.dataset.i, 10);
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", String(from)); } catch (err) {}
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.querySelectorAll(".node-row.drag-over-top,.node-row.drag-over-bottom").forEach((c) =>
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
        markDirty(); renderNodes();
      } catch (err) { toast(err.message, "err"); }
    });
  });
}

/* ---------- 概览 ---------- */
function updateOverview() {
  const results = loadResults();
  let up = 0, down = 0, lat = [];
  sites.forEach((s) => {
    const r = results[s.base_url];
    if (r && r.ok !== null) {
      if (r.ok) { up++; if (r.latency) lat.push(r.latency); }
      else down++;
    }
  });
  $("ovNodes").textContent = sites.length;
  $("ovUp").textContent = up;
  $("ovDown").textContent = down;
  $("ovDown").className = "v " + (down ? "err" : "");
  $("ovLatency").textContent = lat.length
    ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) + "ms" : "—";
  const rows = Object.entries(results).sort((a, b) => b[1].ts - a[1].ts).slice(0, 8);
  $("probeHistory").innerHTML = rows.length
    ? rows.map(([url, r]) =>
        `<div style="display:flex;gap:10px;padding:2px 0">
           <span style="color:${r.ok ? "var(--signal-positive)" : "var(--signal-critical)"}">${r.ok ? "LIVE" : "DOWN"}</span>
           <span style="flex:1;overflow:hidden;text-overflow:ellipsis">${escapeHtml(url)}</span>
           <span>${r.latency || "—"}ms</span>
           <span style="color:var(--text-tertiary)">${new Date(r.ts).toLocaleTimeString()}</span>
         </div>`).join("")
    : '<span class="log-empty">尚无探测记录 — 对节点执行「探测」后这里会显示真实延迟。</span>';
}

/* ---------- 配置加载 ---------- */
async function loadConfig() {
  try {
    const cfg = await api("GET", "/api/config");
    sites = cfg.sites;
    dirty = false;
    $("dirtyTag").style.display = "none";
    $("envTag").style.display = "";
    $("envTag").textContent = cfg.env_path.includes("codex-deepseek-vision") ? "ENV:SHARED" : "ENV:CUSTOM";
    const online = cfg.proxy_listening;
    $("ovProxyDot").className = "dot " + (online ? "on" : "down");
    $("sbProxyDot").className = "dot " + (online ? "on" : "off");
    $("ovProxyStatus").textContent = online ? "ONLINE" : "OFFLINE";
    $("ovProxyStatus").className = "v " + (online ? "ok" : "err");
    $("sbProxy").textContent = online ? "ONLINE" : "OFFLINE";
    $("sbProxy").className = "sb-val " + (online ? "ok" : "err");
    $("ovProxyPort").textContent = online ? String(cfg.proxy_port) : "—";
    $("ovProxyPid").textContent = cfg.proxy_pid || "—";
    $("sbPid").textContent = cfg.proxy_pid || "—";
    $("proxyInline").textContent = online ? `PROXY:ONLINE :${cfg.proxy_port}` : "PROXY:OFFLINE";
    $("proxyInline").style.color = online ? "var(--signal-positive)" : "var(--signal-critical)";
    $("ovEnv").textContent = cfg.env_path.includes("codex-deepseek-vision") ? "SHARED" : "CUSTOM";
    renderNodes();
    updateStatusBar();
  } catch (e) { toast("读取配置失败: " + e.message, "err", 5000); }
}

function markDirty() { dirty = true; $("dirtyTag").style.display = ""; }

/* 待配置密钥横幅:来自其他机器的脱敏配置包导入后,提醒在本机录入密钥 */
function updateBanner() {
  const n = sites.filter((s) => s.base_url && s.model && !s.has_key).length;
  const el = $("keyBanner");
  if (n) {
    el.style.display = "";
    el.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.6 7.6a5.5 5.5 0 11-7.8 7.8 5.5 5.5 0 017.8-7.8zm0 0L15.5 7.5m3 3L21 8l-3-3-2.5 2.5"/></svg>
      <span><b>KEY PENDING</b> · ${n} 个节点来自分发的配置包,等待在本机录入 API 密钥 —
      点击节点「编辑」填入密钥后「保存」即生效。</span>`;
  } else el.style.display = "none";
}

/* ---------- 保存 ---------- */
async function save() {
  const btn = $("btnSave");
  btn.disabled = true;
  const old = btn.innerHTML;
  btn.innerHTML = '<span class="mono" style="font-size:11px">SYNC…</span>';
  try {
    const r = await api("POST", "/api/save", {});
    dirty = false;
    $("dirtyTag").style.display = "none";
    $("sbSync").textContent = "SYNCED " + new Date().toLocaleTimeString();
    toast("配置已保存" + (r.backup ? " · 备份: " + r.backup : ""), "ok");
  } catch (e) { toast("保存失败: " + e.message, "err", 5000); }
  btn.disabled = false;
  btn.innerHTML = old;
}

/* ---------- 探测 ---------- */
async function testSite(i) {
  const s = sites[i];
  if (!s.base_url || !s.model) { toast("节点信息不完整,请先编辑", "warn"); return; }
  if (!s.has_key) { toast("该节点 API 密钥未配置 — 点击「编辑」录入后保存", "warn", 4000); return; }
  const st = nodeState(s);
  const chips = document.querySelectorAll(`.node-row[data-i="${i}"] .status-chip`);
  const errBox = $("err-" + i);
  errBox.classList.remove("show");
  chips.forEach((c) => { c.className = "status-chip probing"; c.textContent = "PROBING"; });
  try {
    const r = await api("POST", "/api/test", { index: i });
    if (r.ok) {
      saveResult(sites[i].base_url, true, r.latency_ms);
      toast(`NODE-${String(i + 1).padStart(2, "0")} LIVE · ${r.latency_ms}ms`, "ok", 3000);
    } else {
      saveResult(sites[i].base_url, false, r.latency_ms);
      errBox.textContent = "PROBE FAILED: " + r.error;
      errBox.classList.add("show");
      toast(`NODE-${String(i + 1).padStart(2, "0")} DOWN`, "err", 6000);
    }
    renderNodes();
  } catch (e) {
    chips.forEach((c) => { c.className = "status-chip down"; c.textContent = "ERROR"; });
    toast("探测请求失败: " + e.message, "err", 5000);
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
    prog.textContent = `PROBING ${done}/${sites.length}`;
  });
  await Promise.all(jobs);
  prog.style.display = "none";
  btn.disabled = false;
  toast("全部探测完成", "ok", 2500);
}

/* ---------- 节点操作 ---------- */
function openAdd() { $("addForm").style.display = ""; setTimeout(() => $("addBase").focus(), 60); }

async function addSite() {
  const base_url = $("addBase").value.trim();
  const model = $("addModel").value.trim();
  const api_key = $("addKey").value.trim();
  if (!base_url || !model) { toast("Base URL 与模型必填", "warn"); return; }
  if (!api_key) { toast("API KEY 必填", "warn"); return; }
  try {
    await api("POST", "/api/site", { base_url, model, api_key });
    $("addBase").value = $("addModel").value = $("addKey").value = "";
    $("addForm").style.display = "none";
    markDirty();
    renderNodes();
    toast("节点已注册 · 记得保存", "ok", 2500);
  } catch (e) { toast(e.message, "err"); }
}

let confirmDel = {};
async function delSite(i) {
  const btn = $("delbtn-" + i);
  if (!confirmDel[i]) {
    confirmDel[i] = true;
    btn.textContent = "确认?";
    setTimeout(() => { confirmDel[i] = false; btn.innerHTML = ICONS.trash; }, 3000);
    return;
  }
  try { await api("DELETE", "/api/site/" + i); markDirty(); renderNodes(); toast("节点已注销 · 记得保存", "ok", 2500); }
  catch (e) { toast(e.message, "err"); }
}

async function saveEdit(i) {
  const body = {
    base_url: $("e" + i + "Base").value.trim(),
    model: $("e" + i + "Model").value.trim(),
    api_key: $("e" + i + "Key").value.trim(),
  };
  try {
    await api("PUT", "/api/site/" + i, body);
    $("detail-" + i).classList.remove("open");
    markDirty(); renderNodes();
    toast("修改已应用 · 记得保存", "ok", 2500);
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
    toast("已导出完整配置(含密钥,勿外发)", "ok", 3000);
  } catch (e) { toast("导出失败: " + e.message, "err"); }
}

/* 分发导出:不含密钥,可安全发给其他电脑 */
async function exportConfigRedacted() {
  try {
    const r = await api("GET", "/api/export?mode=redact");
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "kv-agent-vision-config-redacted-" + new Date().toISOString().slice(0, 10) + ".json";
    a.click();
    URL.revokeObjectURL(url);
    toast("已导出脱敏配置包(不含密钥,可分发)", "ok", 3000);
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
    renderNodes();
    const pending = r.missing_keys ? ` · ${r.missing_keys} 个节点待配置密钥` : "";
    toast(`已导入 ${r.count} 节点${pending} · 记得保存`, "ok", 4500);
  } catch (err) { toast("导入失败: " + err.message, "err", 5000); }
};

/* ---------- 日志 ---------- */
async function loadLog() {
  const box = $("logView");
  box.innerHTML = '<span class="log-empty">读取中...</span>';
  try {
    const r = await api("GET", "/api/proxy-log");
    box.textContent = r.log || "(无日志)";
    box.scrollTop = box.scrollHeight;
  } catch (err) { box.textContent = "读取失败: " + err.message; }
}

/* ---------- Tab 切换 ---------- */
function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".nav-item").forEach((n) =>
    n.classList.toggle("active", n.dataset.tab === tab));
  document.querySelectorAll(".pane").forEach((p) =>
    p.classList.toggle("active", p.id === "pane-" + tab));
  if (tab === "log") loadLog();
  if (tab === "overview") updateOverview();
}

/* ---------- Command Palette ---------- */
function buildCommands(q) {
  const ql = q.toLowerCase();
  const cmds = [
    { label: "添加节点", hint: "REGISTER", run: () => { switchTab("nodes"); openAdd(); } },
    { label: "全部探测", hint: "PROBE ALL", run: () => { switchTab("nodes"); testAll(); } },
    { label: "保存配置", hint: "SAVE", run: save },
    { label: "重启代理", hint: "RESTART", run: restartProxy },
    { label: "导出配置", hint: "EXPORT", run: exportConfig },
    { label: "分发导出(脱敏)", hint: "SHARE", run: exportConfigRedacted },
    { label: "导入配置", hint: "IMPORT", run: () => $("importFile").click() },
    { label: "查看日志", hint: "LOG", run: () => switchTab("log") },
    { label: "切换主题", hint: "THEME", run: cycleTheme },
    { label: "状态概览", hint: "OVERVIEW", run: () => switchTab("overview") },
    { label: "节点列表", hint: "NODES", run: () => switchTab("nodes") },
  ];
  sites.forEach((s, i) => {
    cmds.push({ label: `探测 NODE-${String(i + 1).padStart(2, "0")}`, hint: "PROBE", run: () => { switchTab("nodes"); testSite(i); } });
    cmds.push({ label: `编辑 NODE-${String(i + 1).padStart(2, "0")}`, hint: "EDIT", run: () => { switchTab("nodes"); toggleDetail(i); } });
  });
  return ql ? cmds.filter((c) => (c.label + c.hint).toLowerCase().includes(ql)) : cmds;
}
let paletteIdx = 0;
function openPalette() {
  $("palette").classList.add("open");
  $("paletteInput").value = "";
  paletteIdx = 0;
  renderPalette("");
  setTimeout(() => $("paletteInput").focus(), 30);
}
function closePalette() { $("palette").classList.remove("open"); }
function renderPalette(q) {
  const cmds = buildCommands(q);
  const list = $("paletteList");
  if (!cmds.length) { list.innerHTML = '<div class="palette-empty">无匹配命令</div>'; return; }
  paletteIdx = Math.min(paletteIdx, cmds.length - 1);
  list.innerHTML = cmds.map((c, i) =>
    `<div class="palette-item ${i === paletteIdx ? "active" : ""}" data-i="${i}">
       <span>${escapeHtml(c.label)}</span><span class="cmd-label">${c.hint}</span>
     </div>`).join("");
  list.querySelectorAll(".palette-item").forEach((el) => {
    el.onclick = () => { const c = buildCommands(q)[parseInt(el.dataset.i, 10)]; closePalette(); c.run(); };
    el.onmouseenter = () => { paletteIdx = parseInt(el.dataset.i, 10); renderPalette(q); };
  });
}
$("paletteInput").addEventListener("input", (e) => { paletteIdx = 0; renderPalette(e.target.value); });
$("paletteInput").addEventListener("keydown", (e) => {
  const cmds = buildCommands($("paletteInput").value);
  if (e.key === "ArrowDown") { e.preventDefault(); paletteIdx = Math.min(paletteIdx + 1, cmds.length - 1); renderPalette($("paletteInput").value); }
  else if (e.key === "ArrowUp") { e.preventDefault(); paletteIdx = Math.max(paletteIdx - 1, 0); renderPalette($("paletteInput").value); }
  else if (e.key === "Enter") { const c = cmds[paletteIdx]; if (c) { closePalette(); c.run(); } }
  else if (e.key === "Escape") { closePalette(); }
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
});
$("palette").addEventListener("click", (e) => { if (e.target === $("palette")) closePalette(); });

/* ---------- 状态栏 ---------- */
function updateStatusBar() {
  const results = loadResults();
  let lat = [];
  sites.forEach((s) => { const r = results[s.base_url]; if (r && r.ok && r.latency) lat.push(r.latency); });
  $("sbNodes").textContent = sites.length;
  $("sbLatency").textContent = lat.length
    ? Math.round(lat.reduce((a, b) => a + b, 0) / lat.length) + "ms" : "—";
}
function tickClock() {
  $("sbClock").textContent = new Date().toLocaleTimeString();
}

/* ---------- 事件绑定 ---------- */
async function restartProxy() {
  const btn = $("btnRestartProxy");
  btn.disabled = true;
  try {
    const r = await api("POST", "/api/restart-proxy", {});
    toast((r.log || []).join("；") || "代理状态未知", r.ok ? "ok" : "warn", r.ok ? 5000 : 8000);
    loadConfig();
  } catch (e) { toast("重启失败: " + e.message, "err", 5000); }
  btn.disabled = false;
}
$("btnAdd").onclick = openAdd;
$("btnAddOk").onclick = addSite;
$("btnAddCancel").onclick = () => { $("addForm").style.display = "none"; };
$("btnSave").onclick = save;
$("btnTestAll").onclick = testAll;
$("btnRestartProxy").onclick = restartProxy;
$("btnExport").onclick = exportConfig;
$("btnExportRedacted").onclick = exportConfigRedacted;
$("btnTheme").onclick = cycleTheme;
$("btnLogRefresh").onclick = loadLog;
document.querySelectorAll(".nav-item").forEach((n) =>
  n.addEventListener("click", () => switchTab(n.dataset.tab)));

applyTheme(localStorage.getItem(THEME_KEY) || "auto");
loadConfig();
tickClock();
setInterval(tickClock, 1000);
setInterval(() => { if (!document.hidden) loadConfig(); }, 10000);
</script>
<script type="module">
/* ============ 3D 背景层:节点网络(Ambient Layer,可降级) ============ */
let THREE;
try { THREE = await import('/vendor/three.module.min.js'); }
catch (e) { console.warn('[3d] three.js 不可用,跳过背景层:', e.message); }
if (THREE) {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canvas = document.getElementById('bg3d');
  const COLOR = {
    LIVE: 0x37d67a, PROBING: 0xe8a33d, DOWN: 0xff5d5d, PENDING: 0x54c8e0,
    UNTESTED: 0x6b7280, INVALID: 0x6b7280,
    HUB: 0x54c8e0, EDGE: 0x2e3642, RING: 0x20262f, PACKET: 0x54c8e0,
  };
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);

  /* 确定性 seed(节点布局可复现) */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* 中枢 */
  const hub = new THREE.Mesh(
    new THREE.SphereGeometry(0.17, 20, 20),
    new THREE.MeshBasicMaterial({ color: COLOR.HUB, transparent: true, opacity: 0.9 })
  );
  scene.add(hub);

  /* 极淡轨道环 */
  const ring = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(
      Array.from({ length: 96 }, (_, i) => {
        const a = (i / 96) * Math.PI * 2;
        return new THREE.Vector3(Math.cos(a) * 6.2, Math.sin(a) * 3.6, 0);
      })),
    new THREE.LineBasicMaterial({ color: COLOR.RING, transparent: true, opacity: 0.5 })
  );
  scene.add(ring);

  const nodeGroup = new THREE.Group();
  scene.add(nodeGroup);
  let lineObj = null;
  let packets = [];
  const nodeObjs = [];   // { mesh, mat, pos, phase, birth }

  function rebuild(sites) {
    for (const o of nodeObjs) { o.mesh.geometry.dispose(); o.mat.dispose(); }
    nodeObjs.length = 0;
    for (const p of packets) { p.mesh.geometry.dispose(); p.mesh.material.dispose(); scene.remove(p.mesh); }
    packets = [];
    if (lineObj) { lineObj.geometry.dispose(); lineObj.material.dispose(); scene.remove(lineObj); lineObj = null; }
    const rand = mulberry32(20260812);
    const n = sites.length;
    const pts = [new THREE.Vector3(0, 0, 0)];
    sites.forEach((_, i) => {
      const a = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2;
      const r = 4.2 + (rand() * 2 - 1) * 1.4;
      const pos = new THREE.Vector3(
        Math.cos(a) * r, Math.sin(a) * r * 0.62, (rand() * 2 - 1) * 1.3);
      pts.push(pos);
      const mat = new THREE.MeshBasicMaterial({
        color: COLOR.UNTESTED, transparent: true, opacity: 0.85 });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 14), mat);
      mesh.position.copy(pos);
      mesh.scale.setScalar(0.001);
      nodeGroup.add(mesh);
      nodeObjs.push({ mesh, mat, pos, phase: rand() * 6.28, birth: performance.now() / 1000 + i * 0.12 });
      /* 数据包:每边 1 个 */
      const pmat = new THREE.MeshBasicMaterial({
        color: COLOR.PACKET, transparent: true, opacity: 0.75 });
      const pm = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 8), pmat);
      pm.visible = false;
      scene.add(pm);
      packets.push({ mesh: pm, from: new THREE.Vector3(0, 0, 0), to: pos, phase: rand(), speed: 0.1 + rand() * 0.08 });
    });
    /* 边:中枢 → 各节点(LineSegments 成对顶点) */
    const seg = [];
    sites.forEach((_, i) => { seg.push(new THREE.Vector3(0, 0, 0), pts[i + 1]); });
    const lineGeo = new THREE.BufferGeometry().setFromPoints(seg);
    lineObj = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({
      color: COLOR.EDGE, transparent: true, opacity: 0.55 }));
    scene.add(lineObj);
  }

  function stateColor(label) {
    if (label === "LIVE") return COLOR.LIVE;
    if (label === "PROBING") return COLOR.PROBING;
    if (label === "DOWN") return COLOR.DOWN;
    if (label === "KEY PENDING") return COLOR.PENDING;
    return COLOR.UNTESTED;
  }

  function resize() {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);
  resize();

  /* 相机:慢自转 + 鼠标视差(约束范围) */
  let yaw = 0, pointer = { x: 0, y: 0 };
  window.addEventListener("pointermove", (e) => {
    pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  });

  const clock = new THREE.Clock();
  const tmpColor = new THREE.Color();
  function animate() {
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.elapsedTime;
    yaw += dt * 0.05;
    const py = Math.max(-0.35, Math.min(0.35, pointer.x * 0.22));
    const pp = Math.max(-0.2, Math.min(0.2, -pointer.y * 0.16));
    const dist = 13.5;
    camera.position.set(Math.sin(yaw + py) * dist, 1.6 + pp * 5, Math.cos(yaw + py) * dist);
    camera.lookAt(0, 0, 0);

    /* 节点:入场 + 呼吸 + 状态色 */
    const states = window.__KV_3D || [];
    for (let i = 0; i < nodeObjs.length; i++) {
      const o = nodeObjs[i];
      const target = Math.min(1, Math.max(0, (t - o.birth) / 0.6));
      const s = target * (1 + Math.sin(t * 1.3 + o.phase) * 0.14);
      o.mesh.scale.setScalar(Math.max(0.001, s));
      const st = states[i] ? states[i].state : "UNTESTED";
      tmpColor.setHex(stateColor(st));
      o.mat.color.lerp(tmpColor, Math.min(1, dt * 4));
      if (st === "PROBING") o.mat.opacity = 0.45 + 0.4 * Math.abs(Math.sin(t * 6));
      else o.mat.opacity = 0.85;
    }
    /* 数据包沿边流动 */
    for (const p of packets) {
      p.phase = (p.phase + dt * p.speed) % 1;
      const x = p.from.x + (p.to.x - p.from.x) * p.phase;
      const y = p.from.y + (p.to.y - p.from.y) * p.phase;
      const z = p.from.z + (p.to.z - p.from.z) * p.phase;
      p.mesh.position.set(x, y, z);
      p.mesh.visible = nodeObjs.length > 0;
    }

    renderer.render(scene, camera);
    if (!reduceMotion && !document.hidden) requestAnimationFrame(animate);
  }

  /* 重建入口:renderNodes 之后由主脚本调用 */
  window.__KV_3D_REBUILD = (sites) => rebuild(sites || []);
  if (reduceMotion) { rebuild(window.__KV_3D || []); renderer.render(scene, camera); }
  else requestAnimationFrame(animate);
}
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
            has_base_model = bool(site["base_url"]) and bool(site["model"])
            has_key = bool(site["api_key"])
            complete = has_base_model and has_key
            issues = []
            if not complete:
                if has_base_model and not has_key:
                    issues = ["API 密钥未配置,请在本机录入"]
                else:
                    issues = ["Base URL 或模型未填写,该站点不会生效"]
            result.append({
                "base_url": site["base_url"],
                "model": site["model"],
                "api_key": bool(site["api_key"]),
                "api_key_value": site["api_key"],
                "api_key_masked": self._mask_key(site["api_key"]),
                "has_key": has_key,
                "complete": complete,
                "issues": issues,
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
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            redact = query.get("mode", [""])[0] == "redact"
            with _STATE_LOCK:
                payload = {
                    "version": 2,
                    "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "lang": store.lang,
                    "redacted": redact,
                    "sites": [{
                        "base_url": site["base_url"],
                        "model": site["model"],
                        "api_key": "" if redact else site["api_key"],
                    } for site in store.sites],
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
        elif parsed.path == "/vendor/three.module.min.js":
            vendor = _shared_dir() / "three.module.min.js"
            if vendor.is_file():
                data = vendor.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send(404, {"error": "three.module.min.js not found"})
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
                    missing = 0
                    for item in raw_sites:
                        if not isinstance(item, dict):
                            raise ValueError("站点格式不正确")
                        base_url = (item.get("base_url") or "").strip()
                        model = (item.get("model") or "").strip()
                        api_key = (item.get("api_key") or "").strip()
                        if not base_url or not model:
                            raise ValueError("站点缺少 base_url / model")
                        if not api_key:
                            missing += 1
                        new_sites.append({"base_url": base_url, "api_key": api_key, "model": model})
                    store.sites = new_sites
                    if body.get("lang"):
                        store.lang = str(body["lang"]).strip()[:16]
                self._send(200, {"ok": True, "count": len(new_sites), "missing_keys": missing})
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
