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
<title>kv-agent-vision 配置中心</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --text:#1f2329; --muted:#6b7280;
          --accent:#2563eb; --ok:#16a34a; --warn:#d97706; --err:#dc2626; --chip:#eef2f7; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }
  .wrap { max-width:960px; margin:0 auto; padding:24px 16px 60px; }
  header { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:6px; }
  h1 { font-size:20px; margin:0; }
  .sub { color:var(--muted); font-size:12px; margin:2px 0 18px; word-break:break-all; }
  .bar { display:flex; gap:8px; align-items:center; margin:16px 0 12px; flex-wrap:wrap; }
  button { border:1px solid var(--line); background:#fff; color:var(--text);
           padding:6px 14px; border-radius:8px; cursor:pointer; font-size:13px; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button.primary:hover { opacity:.9; color:#fff; }
  button.danger:hover { border-color:var(--err); color:var(--err); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:14px 16px; margin-bottom:10px; }
  .row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .badge { display:inline-block; padding:1px 10px; border-radius:999px; font-size:12px;
           background:var(--chip); color:var(--muted); white-space:nowrap; }
  .badge.primary { background:#dbeafe; color:#1d4ed8; }
  .badge.warn { background:#fef3c7; color:var(--warn); }
  .field { flex:1 1 240px; min-width:0; }
  .field .k { font-size:11px; color:var(--muted); }
  .field .v { font-family:Consolas,"Courier New",monospace; font-size:13px;
              word-break:break-all; cursor:pointer; }
  .field input { width:100%; padding:5px 8px; border:1px solid var(--line);
                 border-radius:6px; font:13px Consolas,"Courier New",monospace; }
  .ops { display:flex; gap:6px; flex-wrap:wrap; }
  .hint { font-size:12px; color:var(--muted); }
  .ok { color:var(--ok); } .err { color:var(--err); } .warn { color:var(--warn); }
  .msg { display:none; padding:10px 14px; border-radius:10px; margin:10px 0; font-size:13px; }
  .msg.show { display:block; }
  .msg.ok { background:#f0fdf4; border:1px solid #bbf7d0; color:var(--ok); }
  .msg.err { background:#fef2f2; border:1px solid #fecaca; color:var(--err); }
  .msg.warn { background:#fffbeb; border:1px solid #fde68a; color:var(--warn); }
  .spin { display:inline-block; width:12px; height:12px; border:2px solid var(--line);
          border-top-color:var(--accent); border-radius:50%; animation:sp 0.8s linear infinite;
          vertical-align:-2px; }
  @keyframes sp { to { transform:rotate(360deg); } }
  details { margin-top:10px; }
  summary { cursor:pointer; color:var(--muted); font-size:13px; }
  code { background:var(--chip); padding:1px 6px; border-radius:5px; font-size:12px; }
  .dirty { border-color:var(--warn) !important; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>👁 kv-agent-vision 配置中心</h1>
    <span id="envBadge" class="badge"></span>
    <span id="dirtyBadge" class="badge warn" style="display:none">有未保存修改</span>
  </header>
  <div class="sub" id="envPath"></div>

  <div id="msg" class="msg"></div>

  <div class="bar">
    <button class="primary" id="btnAdd">＋ 添加站点</button>
    <button id="btnSave" class="primary">💾 保存配置</button>
    <button id="btnTestAll">🧪 测试全部</button>
    <button id="btnReload">↻ 重新加载</button>
    <button id="btnRestartProxy">🔄 重启代理</button>
    <span id="proxyStatus" class="hint"></span>
    <span style="flex:1"></span>
  </div>

  <div id="sites"></div>

  <div class="card" id="addForm" style="display:none">
    <div style="font-weight:600;margin-bottom:10px">添加视觉 API 站点</div>
    <div class="row">
      <div class="field"><div class="k">Base URL(端点)</div>
        <input id="addBase" placeholder="https://api.nayutoai.xyz/v1"></div>
      <div class="field"><div class="k">模型名</div>
        <input id="addModel" placeholder="openai/gpt-5.6-luna"></div>
      <div class="field"><div class="k">API 密钥</div>
        <input id="addKey" type="password" placeholder="sk-..." autocomplete="off"></div>
      <div class="ops">
        <button class="primary" id="btnAddOk">添加</button>
        <button id="btnAddCancel">取消</button>
      </div>
    </div>
    <div class="hint" id="addHint"></div>
  </div>

  <details>
    <summary>说明: 共享配置</summary>
    <div class="hint" style="margin-top:8px">
      所有装配了本能力的本地 Agent 共用同一份 env 配置,保存后新调用立即生效;
      Codex 视觉代理(127.0.0.1:19100)需重启才加载新配置,点上方「🔄 重启代理」即可。
    </div>
  </details>
</div>

<script>
"use strict";
let sites = [];
let dirty = false;

const $ = (id) => document.getElementById(id);

function msg(text, kind, ms) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg show " + (kind || "ok");
  if (ms) setTimeout(() => { el.className = "msg"; }, ms);
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

function render() {
  const box = $("sites");
  if (!sites.length) {
    box.innerHTML = '<div class="card hint">还没有配置任何站点。点击「＋ 添加站点」开始。</div>';
    $("dirtyBadge").style.display = dirty ? "" : "none";
    return;
  }
  box.innerHTML = sites.map((s, i) => {
    const badge = i === 0 ? '<span class="badge primary">主站点</span>'
                          : `<span class="badge">备用 ${i}</span>`;
    const warn = s.complete ? "" : '<span class="badge warn">配置不完整(未生效)</span>';
    const issues = (s.issues || []).map((x) =>
      `<div class="warn" style="font-size:12px">⚠ ${escapeHtml(x)}</div>`).join("");
    return `<div class="card" data-i="${i}">
      <div class="row">
        ${badge}${warn}
        <span style="flex:1"></span>
        <span class="hint" id="lat-${i}"></span>
      </div>
      <div class="row" style="margin-top:8px;align-items:flex-start">
        <div class="field"><div class="k">Base URL</div>
          <div class="v" title="点击复制">${escapeHtml(s.base_url || "(空)")}</div></div>
        <div class="field"><div class="k">模型</div>
          <div class="v">${escapeHtml(s.model || "(空)")}</div></div>
        <div class="field"><div class="k">API 密钥</div>
          <div class="v">${escapeHtml(s.api_key_masked || "未设置")}</div></div>
        <div class="ops">
          <button onclick="testSite(${i})">测试</button>
          <button onclick="editSite(${i})">编辑</button>
          <button onclick="moveSite(${i},'up')" ${i === 0 ? "disabled" : ""}>↑</button>
          <button onclick="moveSite(${i},'down')" ${i === sites.length - 1 ? "disabled" : ""}>↓</button>
          <button class="danger" onclick="delSite(${i})">删除</button>
        </div>
      </div>
      <div id="edit-${i}"></div>
      ${issues}
    </div>`;
  }).join("");
  $("dirtyBadge").style.display = dirty ? "" : "none";
}

function toggleKey(i) {
  const s = sites[i];
  s._show = !s._show;
  render();
  // 恢复显示状态
  if (s._show) {
    const rows = document.querySelectorAll(".card");
    const v = rows[i].querySelectorAll(".field")[2].querySelector(".v");
    v.innerHTML = `${escapeHtml(s.api_key)} <span class="hint" style="cursor:pointer" onclick="toggleKey(${i})">隐藏</span>`;
  }
}

async function loadConfig() {
  try {
    const cfg = await api("GET", "/api/config");
    sites = cfg.sites;
    dirty = false;
    $("envPath").textContent = "共享配置: " + cfg.env_path;
    $("envBadge").textContent = cfg.env_path.includes("codex-deepseek-vision") ? "共享配置" : "自定义 env";
    $("proxyStatus").textContent = cfg.proxy_listening
      ? `视觉代理运行中(${cfg.proxy_port})` : "视觉代理未运行";
    render();
  } catch (e) { msg("加载配置失败: " + e.message, "err"); }
}

function markDirty() { dirty = true; $("dirtyBadge").style.display = ""; }

async function save() {
  $("btnSave").disabled = true;
  try {
    const r = await api("POST", "/api/save", {});
    dirty = false;
    $("dirtyBadge").style.display = "none";
    msg("已保存到 " + r.env_path + (r.backup ? "，备份: " + r.backup : ""), "ok", 4000);
  } catch (e) { msg("保存失败: " + e.message, "err", 5000); }
  $("btnSave").disabled = false;
}

async function testSite(i) {
  const el = $("lat-" + i);
  el.innerHTML = '<span class="spin"></span> 测试中...';
  try {
    const r = await api("POST", "/api/test", { index: i });
    if (r.ok) el.innerHTML = `<span class="ok">✔ ${r.latency_ms}ms</span>`;
    else el.innerHTML = `<span class="err">✘ ${r.latency_ms}ms</span>`;
    if (!r.ok) msg("站点 " + (i + 1) + " 测试失败: " + r.error, "err", 6000);
  } catch (e) {
    el.textContent = "";
    msg("测试请求失败: " + e.message, "err", 5000);
  }
}

async function testAll() {
  $("btnTestAll").disabled = true;
  for (let i = 0; i < sites.length; i++) await testSite(i);
  $("btnTestAll").disabled = false;
}

async function moveSite(i, dir) {
  try { await api("POST", "/api/move", { index: i, direction: dir }); markDirty(); render(); }
  catch (e) { msg(e.message, "err", 4000); }
}

async function delSite(i) {
  if (!confirm("删除站点 " + (i + 1) + "? 保存后生效。")) return;
  try { await api("DELETE", "/api/site/" + i); markDirty(); render(); }
  catch (e) { msg(e.message, "err", 4000); }
}

function editSite(i) {
  const s = sites[i];
  const box = $("edit-" + i);
  box.innerHTML = `<div class="row" style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)">
      <div class="field"><div class="k">Base URL</div>
        <input id="e${i}Base" value="${escapeHtml(s.base_url || "")}"></div>
      <div class="field"><div class="k">模型</div>
        <input id="e${i}Model" value="${escapeHtml(s.model || "")}"></div>
      <div class="field"><div class="k">API 密钥(留空保持不变)</div>
        <input id="e${i}Key" type="password" placeholder="${s.api_key ? "已设置,留空保持不变" : "sk-..."}" autocomplete="off"></div>
      <div class="ops">
        <button class="primary" onclick="saveEdit(${i})">保存</button>
        <button onclick="$('edit-${i}').innerHTML=''">取消</button>
      </div>
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
  } catch (e) { msg(e.message, "err", 4000); }
}

async function addSite() {
  const base_url = $("addBase").value.trim();
  const model = $("addModel").value.trim();
  const api_key = $("addKey").value.trim();
  if (!base_url || !model) { msg("Base URL 和模型名必填", "warn", 3000); return; }
  if (!api_key) { msg("API 密钥必填", "warn", 3000); return; }
  try {
    await api("POST", "/api/site", { base_url, model, api_key });
    $("addBase").value = $("addModel").value = $("addKey").value = "";
    $("addForm").style.display = "none";
    markDirty();
    render();
  } catch (e) { msg(e.message, "err", 4000); }
}

$("btnAdd").onclick = () => { $("addForm").style.display = "block"; $("addBase").focus(); };
$("btnAddOk").onclick = addSite;
$("btnAddCancel").onclick = () => { $("addForm").style.display = "none"; };
$("btnSave").onclick = save;
$("btnTestAll").onclick = testAll;
$("btnReload").onclick = loadConfig;
$("btnRestartProxy").onclick = async () => {
  $("btnRestartProxy").disabled = true;
  try {
    const r = await api("POST", "/api/restart-proxy", {});
    msg((r.log || []).join("；") || "代理状态未知", r.ok ? "ok" : "warn", r.ok ? 5000 : 8000);
    loadConfig();
  } catch (e) { msg("重启代理失败: " + e.message, "err", 5000); }
  $("btnRestartProxy").disabled = false;
};
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

    def move_site(self, index, direction):
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
                cfg = {
                    "env_path": str(store.env_path),
                    "sites": store.public_sites(),
                    "lang": store.lang,
                    "proxy_listening": _port_pid(_PROXY_PORT) is not None,
                    "proxy_port": _PROXY_PORT,
                }
            self._send(200, cfg)
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
                    store.move_site(index, body.get("direction", "up"))
                self._send(200, {"ok": True})
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
