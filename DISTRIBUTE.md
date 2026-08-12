# 远程装配提示词(DISTRIBUTE)

> 用法:把下方「提示词正文」整段复制,发给另一台电脑上的 Agent(纯文本模型)。
> 对方 Agent 会按步骤自动完成 kv-agent-vision 视觉能力装配;唯一需要人工参与的是
> **API 密钥录入**(密钥必须在本机完成,不随配置包传输)。
>
> 配套文件:分发配置包由本机配置中心「分发导出」生成(`kv-agent-vision-config-redacted-*.json`)。

## 地址与端口说明(重要)

| 项 | 固定性 | 对方 Agent 应如何获取 |
|---|---|---|
| GitHub 仓库 | 固定 | `https://github.com/Kvxw1105/kv-agent-vision` |
| 配置中心端口 | 默认 19123,被占用自动后延 | **以启动输出打印的实际地址为准** |
| 视觉代理端口 | 默认 19100,可能自定义 | 以 `/api/config` 返回的 `proxy_port` 为准 |
| 共享配置路径 | 默认 Windows `%LOCALAPPDATA%\codex-deepseek-vision\env` / 其它 `~/.config/codex-deepseek-vision/env` | 以 `/api/config` 返回的 `env_path` 为准 |
| 技能目录 | **不固定**(因 Agent 平台而异) | 本机查找;找不到就问用户 |

> 原则:提示词中的路径/端口均为"默认值",**实际值以发现结果和 `/api/config` 返回值为准**,
> 不要假设任何地址固定不变。

---

## 提示词正文(从这里开始复制)

```
# 任务:为本机装配 kv-agent-vision 视觉能力(配置由另一台机器分发)

你是本机的 Agent。当前模型是纯文本模型(无多模态),无法直接"看"图片。
请完成以下装配任务,严格按步骤执行:每步完成并验证后再进入下一步,全程用中文回复。

## 背景
- 视觉能力 = kv-agent-vision 项目:通过 OpenAI 兼容视觉 API 把图片转成文字描述。
- 配置结构(站点 Base URL / 模型 / 主备顺序)由另一台机器以"分发配置包"(JSON)提供;
- API 密钥**必须在本机录入**,配置包里没有密钥。
- 完成后,本 Agent 将获得看图能力(Skill 脚本 / MCP 工具 / GUI 配置中心)。
- 注意:下文出现的端口与路径都是"默认值",实际值以发现结果为准,不要假设固定。

## 步骤 0 · 前置检查(是否存在能力)
1. 查找本机是否已安装 kv-agent-vision 技能:
   - 依次检查常见技能目录:Windows 的 `%LOCALAPPDATA%\codex-deepseek-vision\`
     以及各 Agent 平台的 skills 目录(如 `~/.agents/skills/`、`~/.codex/`、
     `~/.claude/skills/`、`~/.cursor/` 等),查找含 vision.py 与 gui.py 的目录;
   - 也检查系统里是否有 `codex-deepseek-vision-proxy.cmd`(Windows 启动项)。
2. 未找到:从开源仓库获取并安装:
   - `git clone https://github.com/Kvxw1105/kv-agent-vision`
   - 运行 `install.sh <技能目录>`(或 Windows 的 `install.ps1`)
   - 确保 vision.py / gui.py / mcp_server.py / SKILL.md 就位
3. 报告:OBSERVED(已存在)/ CHANGED(本次安装),并记录实际技能目录路径。

## 步骤 1 · 启动配置中心(GUI)
1. 后台运行 `python <技能目录>/gui.py`(Windows 也可用共享目录的 start-gui.bat)。
2. 从**启动输出读取实际地址**(默认 http://127.0.0.1:19123/;
   若该端口被占用会自动后延,以输出为准)。
3. 验证:实际端口已监听;确认浏览器已打开(未打开则告知用户地址)。
4. 记录实际端口为 <GUI_PORT>;后续 API 均用 `http://127.0.0.1:<GUI_PORT>/`。
5. 调用 `GET http://127.0.0.1:<GUI_PORT>/api/config`,记录:
   - env_path(共享配置实际路径)
   - proxy_port(视觉代理实际端口)
   - 现有节点数

## 步骤 2 · 导入配置包
1. 询问用户:是否已有分发配置包(JSON 文件)?让用户提供文件路径。
2. 有配置包:读取文件,`POST http://127.0.0.1:<GUI_PORT>/api/import`
   (body 为配置包内容;站点 api_key 为空是正常的)。
3. 无配置包:引导用户提供站点信息(Base URL / 模型 / 密钥),你代为添加
   (`POST /api/site`)。
4. 报告:导入节点数、其中待配置密钥数(missing_keys)。

## 步骤 3 · 录入 API 密钥(必须本机完成,不可跳过)
1. 告知用户:配置包不含密钥,`KEY PENDING` 节点需要在本机录入。
2. 推荐方式(密钥不进会话记录):
   用户在配置中心页面点节点「编辑」→ 填入 API 密钥 → 「保存」。
3. 备选方式(用户明确同意时):用户把密钥文本告诉你,你通过
   `PUT /api/site/<index>` 写入(提醒:密钥会出现在会话记录中,请用户自行权衡)。
4. 等待用户确认录入完成(你无法臆造密钥,不得使用占位符)。
5. 验证:`GET /api/config` 确认所有节点 `has_key=true`;若仍有缺失,回到本步。

## 步骤 4 · 保存并确保代理运行
1. `POST http://127.0.0.1:<GUI_PORT>/api/save`(保存配置,自动备份)。
2. 检查视觉代理:实际端口来自 `/api/config` 的 `proxy_port`(默认 19100);
   未运行或配置已变则 `POST /api/restart-proxy`。
3. 验证:代理端口监听中。

## 步骤 5 · 探测验证(端到端)
1. `POST http://127.0.0.1:<GUI_PORT>/api/test`(逐个节点,body `{"index": i}`),
   或引导用户点击「全部探测」。
2. 期望:所有节点 `LIVE`(状态码 ok)。
3. 有节点 DOWN:读取返回的 error,报告原因(站点故障/网络/密钥错误),
   **不要自行更换或删除站点**,询问用户是否确认该站点可用。

## 步骤 6 · Agent 侧验证(确认本 Agent 真的能用)
1. 运行视觉脚本:
   `python <技能目录>/vision.py <技能目录>/vision-test.png --simple`
   (若环境支持 MCP,也可调用 describe_image 工具)
2. 期望:返回中文描述,能识别出 "Agent Vision Test" / "Hello 2026" / "Agent Ready"。
3. 报告验证结果。

## 完成标准(全部满足才算完成,输出装配报告)
- [ ] 配置中心运行中(实际端口已记录)
- [ ] 配置包已导入,节点数与来源机器一致
- [ ] 所有节点 has_key=true 且已保存(有备份)
- [ ] 视觉代理运行中(实际 proxy_port 已记录)
- [ ] 全部节点探测 LIVE
- [ ] vision.py / MCP 成功描述测试图(识别三行文字)

## 安全与纪律
- 绝不把真实 API 密钥写入日志、截图、聊天以外的不必要位置;推荐用户用 GUI 录入。
- 密钥缺失时停下等用户,不用占位符、不猜密钥。
- 站点 DOWN 时报告原因并询问,不擅自改配置。
- 完成后按步骤输出:每步标注 OBSERVED / CHANGED / FIXED_VERIFIED / BLOCKED,
  并附上实际端口、共享配置路径与技能目录。
```

---

## 常见问题

- **对方 Agent 没有 Python?** 视觉能力依赖 Python 3(标准库即可),需先安装 Python。
- **对方无法访问 GitHub?** 直接把仓库压缩包或技能文件传过去,跳过步骤 0 的 clone。
- **密钥可以在聊天里给 Agent 吗?** 可以但会留在会话记录;推荐在 GUI 页面直接录入。
- **多台机器都要装?** 每台重复执行本提示词即可;分发配置包可反复使用。
- **端口被占用?** 配置中心会自动后延端口;提示词要求以启动输出的实际地址为准。
