# Changelog

本项目的变更记录。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### Added(2026-08-12 · 配置分发)

- **配置/凭据分离(分发导出)**:`/api/export?mode=redact` 生成不含密钥的配置包,
  GUI「分发导出」按钮一键下载;密钥永不离开本机
- **缺密钥导入**:导入的配置包站点无密钥时正常接收,节点显示
  `KEY PENDING`(冷青状态灯 + 状态标签),顶部出现待配置横幅,
  探测操作被拦截并提示"先录入密钥";录入密钥保存后即恢复可用
- 完整导出保留密钥(本地备份用),导出文件均带 `redacted` 标记

### Added(2026-08-12)

- **Three.js 3D 背景层**(节点网络拓扑,Ambient Layer):
  - 代理为中枢、站点为环绕节点,数据包沿边流动(相位循环、确定性 seed 布局)
  - 节点颜色随真实探测状态变化:LIVE 磷光绿 / PROBING 琥珀闪烁 / DOWN 信号红
  - 相机慢自转 + 鼠标视差(约束范围);`prefers-reduced-motion` 下单帧静态
  - Three.js 0.160 本地加载(`three.module.min.js` 由 `/vendor/` 路由提供,离线可用),
    缺失时自动降级为纯终端 UI;页面隐藏时暂停渲染
  - 面板改为半透明 Surface,3D 层透出但不干扰可读性

### Changed(2026-08-11 · 第二次重构)

- **配置中心重构为高密度科技终端**(QUANT TERMINAL / CYBER IDE 方向):
  - 视觉母体:Ciber Operations Console(主)+ 机构终端数据密度(辅)
  - Application Shell:顶栏 + Navigation Rail(NODES/OVERVIEW/LOG)+ Workspace + 底部 Status Bar
  - 信号色系统(磷光绿/琥珀/信号红/冷青),碳黑分层背景,蓝紫渐变与 Glow 归零
  - 节点数据表:NODE-01… 编号、MAIN/BACKUP 角色、PROBING→LIVE/DOWN 状态流转、
    延迟 sparkline(真实测试历史)、最近探测记录
  - Command Palette(Ctrl+K):模糊搜索 + 键盘导航,命令含 Technical Label
  - 状态栏实时显示 PROXY/PID/NODES/LATENCY/SYNCED
  - 图标全 SVG 线性风格(1.6px stroke),无 emoji;业务文案保持中文,技术标签作辅助
  - Motion tokens(--motion-fast/normal/panel + easing)、prefers-reduced-motion 支持

### Added(2026-08-11)

- **GUI 配置中心全面改版(第一版眼科检查单主题,已被终端主题取代)**:
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
