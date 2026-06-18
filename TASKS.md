# K38 Sprint Board — 任务看板

> 用 GitHub Projects 导入此文件即可创建看板
> 打开 https://github.com/k38mail-star/k38-ops/projects → 创建项目 → 选 Board → 导入

## 📋 待办

### 修复 node_status.py 冷启动问题
- **仓库**: k38-ops
- **文件**: api/node_status.py
- **说明**: 启动预采集 + 15秒缓存，确保首次请求不超时
- **已搞定**: ✅ 已部署 v5 版本

### 合并三万八的前端改到 ECS
- **仓库**: k38-football
- **说明**: 三万八做了 Flask 版前端优化，需要手动将 templates/ 和 static/ 的改动合并到 ECS 版本
- **注意**: 三万八的代码包含 .venv，只取 templates/ 和 static/ 文件

### 三万八 Codex Key 验证
- **节点**: 三万八
- **说明**: 确认 Codex Key 正确配置，能正常跑 `codex exec`

## 🔄 进行中

### 小四 cc 审核 ops 代码
- **仓库**: k38-ops
- **文件**: api/dashboard.py, api/node_status.py
- **状态**: dashboard.py 已改好（Key 移环境变量、SSH 参数化）
- **问题**: node_status.py 被改坏，已回滚

## 👀 审核

### 大傻 collector v2.0
- **仓库**: k38-football
- **文件**: collector.py, daemon.py, models.py
- **改动**: +231行，retry/backoff，错误处理优化
- **状态**: ✅ 已合并部署

### 二傻 prediction v2.0
- **仓库**: k38-football
- **文件**: backtest.py, models.py
- **改动**: +384行，预测算法增强
- **状态**: ✅ 已合并部署

## ✅ 已完成

- [x] 大傻/二傻 Codex 安装配置
- [x] 三万八 Codex 安装配置
- [x] 小四 Codex + Claude Code 安装配置
- [x] 十六万 Claude Code Key 更新
- [x] ops.k38.ai SSL 修复
- [x] k38.ai 首页（方案 I）上线
- [x] 所有节点实时数据采集（CPU/MEM/DISK）
- [x] 节点状态进度条（从右往左）
- [x] k38-ops GitHub repo v1.5.0
- [x] k38-football GitHub repo v1.0
