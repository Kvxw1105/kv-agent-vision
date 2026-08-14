# kv-agent-vision

> Give pure-text LLM agents eyes: image understanding, OCR & image Q&A for any agent, via a zero-dependency MCP server or standalone script.

给纯文本 AI Agent 一双"眼睛"——通过 OpenAI-compatible 视觉 API 把图片转成高质量中文描述,让没有多模态能力的模型也能**看图 / OCR / 图片问答**。**零第三方依赖**,仅用 Python 标准库。

## ✨ 特性

- **双形态交付,覆盖最广**
  - 🧩 **MCP server**(推荐):纯标准库 stdio 实现,Cursor / Claude Code / Claude Desktop / Codex / Cline 等主流客户端**即插即用**,Agent 把"看图"当原生工具直接调用
  - 🐍 **独立脚本 / Skill**:`vision.py` 零依赖,复制到任意环境即可用,配 `SKILL.md` / `PROMPT.md` 可接入任意 Skill 框架
- **深度结构化描述**(默认 7 层次):整体概览 / 九宫格空间布局 / 对象细节(位置·占比·颜色)/ 文字与 UI(逐条带位置)/ 数据数字 / 隐含信息(区分事实与推测)/ 易漏细节
- 支持**针对性问答 `-q`**、**OCR(带位置标注)**、**简短概览**、**多图并发**
- **坐标 / 色彩增强档**(`--coords` / `--colors`,可组合,默认关闭):百分比坐标
  `(x%,y%,w%,h%)` 供定位/点击/裁切,精确 HEX 色值供设计复刻;按需开启控制上下文占比
- 内置 **5 次自动重试**、强制直连绕过系统代理、`max_tokens` 充足(16384)

## 🚀 快速开始

### 方式一:MCP server(推荐)

1. 克隆并准备配置:

```bash
git clone https://github.com/Kvxw1105/kv-agent-vision.git
cd kv-agent-vision
cp .env.example .env   # 编辑 .env 填入 VISION_API_KEY
```

2. 接入你的客户端(以 `mcp_server.py` 的绝对路径为准):

**Cursor** — Settings → MCP → Add server:

```json
{
  "mcpServers": {
    "kv-agent-vision": {
      "command": "python",
      "args": ["/absolute/path/to/kv-agent-vision/mcp_server.py"]
    }
  }
}
```

**Claude Code** — 项目根 `.mcp.json`,或运行 `claude mcp add kv-agent-vision -- python /absolute/path/to/mcp_server.py`:

```json
{
  "mcpServers": {
    "kv-agent-vision": {
      "command": "python",
      "args": ["/absolute/path/to/kv-agent-vision/mcp_server.py"]
    }
  }
}
```

其他支持 MCP 的客户端同理:命令 = `python`,参数 = `mcp_server.py` 绝对路径。

3. 使用:客户端里直接调用 `describe_image` 工具,传入 `image`(路径或 URL),可选 `question` / `ocr` / `simple`。

### 方式二:独立脚本 / Skill

```bash
cp .env.example .env   # 填入 VISION_API_KEY
export PYTHONIOENCODING=utf-8   # Windows 控制台防中文乱码

python vision.py <图片路径>                        # 深度结构化描述(默认)
python vision.py <图片路径> -q "主色调和布局?"      # 针对性问答
python vision.py <图片路径> --ocr                  # OCR(带位置)
python vision.py <图片路径> --simple               # 简短概览
python vision.py <图片路径> --coords               # 坐标增强:对象/文字/UI 附加百分比坐标 (x%,y%,w%,h%)
python vision.py <图片路径> --colors               # 色彩增强:对象颜色附加精确 HEX 色值
python vision.py <图片路径> --auto                 # 自适应:视觉模型按图片内容自决是否附加坐标/色值
python vision.py <图1> <图2> <图3>                 # 多图并发
```

> **坐标 / 色彩增强档**(`--coords` / `--colors`,可组合):默认关闭以控制上下文占比
> (全开约 +40% 输出)。坐标档服务**定位/点击/裁切**(UI 自动化),色彩档服务
> **设计复刻/取色**;需要时按任务开启。`--auto` 让视觉模型按图片内容自决
> (UI 截图自动开坐标、纯内容图保持简洁),显式档位优先。

接入 Skill 框架:把 `SKILL.md` + `vision.py` + `.env` 放进目标 Agent 的 skills 目录;详细使用提示词见 `PROMPT.md`。

### 方式三:一键安装到某 Agent 的 skills 目录

```bash
bash install.sh "<目标Agent的skills目录>"          # bash / macOS / Linux / Git Bash
powershell -ExecutionPolicy Bypass -File .\install.ps1 "<目标Agent的skills目录>"   # Windows
```

> 仓库不包含真实 `.env`(已被 `.gitignore` 排除);安装后请 `cp .env.example .env` 并填入自己的 `VISION_API_KEY`。

## ⚙️ 配置

`.env`(模板见 `.env.example`):

```ini
VISION_API_KEY=sk-xxx          # 视觉 API 密钥(必填)
VISION_BASE_URL=https://api.nayutoai.xyz/v1
VISION_MODEL=openai/gpt-5.6-luna
LANG=zh
```

加载优先级(所有装配了本能力的 Agent **共用同一份共享配置**):
1. 显式指定:`--env-file` 参数或环境变量 `CODEX_DEEPSEEK_VISION_ENV`
2. 共享配置:Windows `%LOCALAPPDATA%\codex-deepseek-vision\env` / 其它系统 `~/.config/codex-deepseek-vision/env`
3. 本地兜底:脚本同目录 `.env`、当前目录 `.env`(仅当前副本局部覆盖用)

## 🖥 配置中心(GUI)

零依赖本地 Web 界面,集中管理共享配置。界面为**高密度科技终端**风格
(参照机构交易终端 / 运维控制台):碳黑分层 + 信号色系统、三栏 Application Shell
(Navigation Rail / Workspace / 底部 Status Bar)、节点数据表、实时遥测与 Command Palette。

```bash
python gui.py                 # 或 Windows 双击 start-gui.bat
```

- 默认地址 `http://127.0.0.1:19123`,仅本机可访问(配置含 API 密钥,勿对局域网开放)
- **3D 背景层(Three.js)**:节点网络拓扑——代理为中枢、站点为环绕节点,数据包沿边流动,
  节点颜色随真实探测状态变化(LIVE 磷光绿 / PROBING 琥珀 / DOWN 红);Three.js 从本地
  `three.module.min.js` 加载(离线可用),缺失时自动降级为纯终端 UI
- **节点管理**:注册/编辑/注销、拖拽排序(第 1 个为主节点,其余自动成为故障切换备用)
- **探测(测试)**:逐个或全部探测,状态流转 PROBING→LIVE/DOWN,延迟 sparkline 与最近探测记录真实可查
- **Command Palette**:`Ctrl+K` 快速执行命令(添加/探测/保存/重启/导入导出/主题…)
- **遥测面板**:视觉代理(19100)状态、PID、节点汇总、平均延迟、代理日志
- **导入/导出**:JSON 备份、迁移与分享
- **配置分发(配置/凭据分离)**:「分发导出」生成**不含密钥**的配置包(JSON),
  可安全发给其他电脑 → 对方 GUI「导入」→ 节点显示 `KEY PENDING` 并出现顶部横幅提示 →
  在本机录入 API 密钥后保存即完成装配。**密钥永不离开本机**
- **状态栏**:PROXY / PID / NODES / LATENCY / SYNCED 实时状态
- 碳黑暗色(默认)+ 白底亮色双主题,跟随系统或手动切换
- 保存后新调用立即生效;Codex 视觉代理(127.0.0.1:19100)需重启才加载新配置,界面内可直接「重启代理」

**多站点故障切换**:主站点重试耗尽后自动切换到备用站点,全部失败才报错。备用站点用 `VISION2_*` 配置(编号可继续后延 `VISION3_*` ...),字段齐全即生效:

```ini
VISION2_API_KEY=sk-xxx                          # 备用站点 API 密钥
VISION2_BASE_URL=https://apihub.agnes-ai.com/v1
VISION2_MODEL=agnes-2.5-flash
```

切换时向 stderr 打印 `[vision] 主站点失败，已切换到备用站点 ...` 便于诊断。

> 站点返回非 JSON 内容(如 HTML 拦截页)也按故障处理:自动重试后切换到备用站点。

## 📁 目录结构

```
kv-agent-vision/
├── gui.py             # 配置中心(GUI,零依赖,管理共享配置)
├── start-gui.bat      # Windows 一键启动 GUI
├── mcp_server.py      # MCP server(stdio,零依赖)—— 推荐形态
├── vision.py          # 核心脚本(描述/问答/OCR/多图,零依赖)
├── .env.example       # 配置模板(复制为 .env)
├── SKILL.md           # Skill 定义(支持 SKILL.md 协议的框架)
├── PROMPT.md          # 详细使用提示词(贴进 Agent 的 system prompt / AGENTS.md)
├── vision-test.png    # 内置测试图(验证安装)
├── install.sh         # 一键安装脚本(bash)
├── install.ps1        # 一键安装脚本(PowerShell)
└── LICENSE            # MIT
```

## ✅ 验证

```bash
PYTHONIOENCODING=utf-8 python vision.py vision-test.png --simple
```

正常返回中文描述(识别出 `Agent Vision Test` / `Hello 2026` / `Agent Ready` 三行文字)即配置正确。

## 🛠 常见故障

| 现象 | 原因 / 处理 |
|---|---|
| `缺少配置 VISION_API_KEY...` | `.env` 缺失或环境变量没设;确认与脚本同目录 |
| 中文乱码(Windows) | 运行前设 `PYTHONIOENCODING=utf-8` |
| SSL EOF / 5xx / 连接重置 | 视觉 API 偶发抖动,已内置 5 次自动重试,稍等重跑 |
| 主站点持续连不上 | 自动切换到备用站点(配置了 `VISION2_*` 时),stderr 会打印切换提示 |
| 返回空内容 | 推理模型需足够 `max_tokens`(默认 16384),不要调小 |
| 网络错误(Windows 代理) | 强制直连绕过系统代理;仍失败请检查本地代理拦截 |

## 📄 License

[MIT](LICENSE) © 2026 [Kvxw1105](https://github.com/Kvxw1105)
