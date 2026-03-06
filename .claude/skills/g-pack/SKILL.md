---
name: g-pack
description: Fountain 桌面端发布 — 版本管理 → 构建打包 → DMG → 打标签
argument-hint: [patch|minor|major|x.y.z] (默认 patch)
model: sonnet
---

# Fountain 桌面端发布 (Pack Gate)

为 Fountain Tauri v2 桌面客户端执行发布打包流程。版本升级方式: **$ARGUMENTS**（默认 patch）。

## 工作流

### 阶段 1: 预检分析

#### 1. Git 状态检查
- 运行 `git status` 检查工作区是否干净
- **有未 commit 的变更 → 拒绝构建**，提示先提交或用 `/g-accept` 验收

#### 2. 工具链检查
- 验证以下工具可用: `rustc`, `cargo`, `node`, `npm`, `create-dmg`
- 任一缺失 → 报错并给出安装指引

#### 3. 版本检测与交叉校验
- 从 `fountain/src-tauri/tauri.conf.json` 读取当前版本（权威来源）
- 交叉校验 `fountain/package.json` 和 `fountain/src-tauri/Cargo.toml` 的 version 字段
- 三处版本不一致 → 警告并提示是否继续

#### 4. 目标版本计算
- 解析 `$ARGUMENTS`:
  - `patch` / `minor` / `major` → 基于当前版本做 semver 递增
  - `x.y.z` 格式 → 直接使用（必须大于当前版本）
  - 空 → 默认 `patch`
- 检查 `fountain-v{target}` tag 不存在，否则报错

#### 5. 变更分析
- 运行 `git log fountain-v{current}...HEAD --oneline -- fountain/`
  - 如果 `fountain-v{current}` tag 不存在，使用全部 fountain/ 相关 commit
- 分类变更:

| 分类 | 匹配规则 |
|------|---------|
| Rust 后端 | `fountain/src-tauri/src/**` |
| Vue 前端 | `fountain/src/**` |
| 依赖 | `Cargo.toml`, `Cargo.lock`, `package.json`, `package-lock.json` |
| 配置 | `tauri.conf.json`, `capabilities/`, `entitlements.plist` |

### 阶段 2: 确认并执行

#### 6. 展示构建计划

```
## 构建计划

- 当前版本: {current}
- 目标版本: {target}
- 升级方式: {patch|minor|major|explicit}
- 变更摘要: {N} 个 commit
  - Rust 后端: {列出}
  - Vue 前端: {列出}
  - 依赖: {有/无}
  - 配置: {有/无}
```

#### 7. 用户确认
- 使用 `AskUserQuestion` 确认是否继续

#### 8. 版本同步
- 更新以下 3 个文件的 version 字段为目标版本:
  - `fountain/src-tauri/tauri.conf.json` — `"version": "{target}"`
  - `fountain/package.json` — `"version": "{target}"`
  - `fountain/src-tauri/Cargo.toml` — `version = "{target}"`

#### 9. 执行构建
- 运行 `fountain/scripts/build-release.sh`
- 脚本自动从 `tauri.conf.json` 读取版本号
- 监控构建输出，失败时展示错误日志

#### 10. Git 操作
- `git add` 3 个版本文件
- `git commit -m "release(fountain): v{target}"`
- `git tag fountain-v{target}`
- **不自动 push** — 用户先验证 DMG 再决定

### 阶段 3: 发布报告

```
## 发布报告

### 版本信息
- 版本号: {target}
- Git 标签: fountain-v{target}
- 升级方式: {patch|minor|major|explicit}

### 构建产物
- .app: fountain/src-tauri/target/release/bundle/macos/Fountain.app ({size})
- .dmg: fountain/src-tauri/target/release/bundle/dmg/Fountain_{target}_aarch64.dmg ({size})

### 构建状态
- 状态: ✅ 成功 / ❌ 失败

### 下一步
- 验证 DMG: `open fountain/src-tauri/target/release/bundle/dmg/`
- 推送标签: `git push origin main && git push origin fountain-v{target}`
```
