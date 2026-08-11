# Changelog

本项目的变更记录。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### Added(2026-08-11)

- **GUI 配置中心全面改版(眼科检查单主题)**:
  - 视觉命题:视力表头、检查记录卡、Ishihara 色盲检测空状态、红印章、明室/暗室双主题
  - 站点健康度按"视力等级"呈现(5.0 健康 / 3.0 失明),故障站点 E 字放大
  - 拖拽排序站点(替代 ↑↓ 按钮);密钥显示/隐藏切换
  - 测试结果持久化在本地浏览器;「全部验光」并行+进度
  - 配置导入/导出 JSON;设备面板(PID/日志尾部/一键重启)
  - `prefers-reduced-motion` 支持;响应式小屏布局
- **共享配置**:所有装配了本能力的 Agent 共用同一份 env(Windows
  `%LOCALAPPDATA%\codex-deepseek-vision\env`,其它系统 `~/.config/codex-deepseek-vision/env`),
  支持 `CODEX_DEEPSEEK_VISION_ENV` 统一覆盖
- **多站点故障切换**:主站点(VISION_*)重试耗尽后自动切换备用站点
  (VISION2_* / VISION3_* ...);非 JSON 响应(如 HTML 拦截页)按站点故障处理
- **桌面快捷方式**:`视觉配置中心.lnk` 一键启动 GUI(Windows)

### Removed

- 内置保险丝白名单(ALLOWED_BASE_URLS / ALLOWED_MODELS):配置完全由用户管理,
  不再内置任何域名/模型限制
