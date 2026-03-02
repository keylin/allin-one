---
name: code-review
description: 代码评审 — 代码评审专家 + 代码测试专家并行审查代码质量
argument-hint: [文件或目录] (可选，默认审查最近 git 变更)
model: sonnet
---

# 代码评审 (Code Review)

对 **$ARGUMENTS** 进行代码风格+质量双维度评审。如果未提供参数，审查最近的 git 变更。

## 工作流程

1. **并行启动两个 agent**（使用 Agent tool，在同一条消息中发起两个调用）:
   - `code-reviewer` — 审查代码风格：命名规范、日志规范、代码一致性、代码气味
   - `code-tester` — 审查代码质量：静态分析、接口契约、数据完整性、缺陷发现

   两个 agent 的 prompt 都应包含:
   - 审查目标: $ARGUMENTS（如果为空则说明"审查最近的 git 变更，先运行 git diff --name-only 确定范围"）
   - 要求输出结构化报告（按各自 agent 定义的输出格式）

2. **合并输出**:

   ## 代码评审: {变更描述}
   ### 风格与规范（来自 code-reviewer）
   {评审要点}
   ### 质量与正确性（来自 code-tester）
   {测试要点}
   ### 问题清单（合并去重，按严重程度排序）
   #### 🔴 必须修改
   #### 🟡 建议修改
   #### 🔵 可优化
   ### 通过项
   {做得好的地方}
