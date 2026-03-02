---
name: code-accept
description: 代码验收 — 代码评审 + 代码测试 + 文档维护三方并行验收
argument-hint: [文件或目录] (可选，默认验收最近 git 变更)
model: sonnet
---

# 代码验收 (Code Acceptance)

对 **$ARGUMENTS** 进行代码质量+文档完整性三维度验收。如果未提供参数，验收最近的 git 变更。

## 工作流程

1. **并行启动三个 agent**（使用 Agent tool，在同一条消息中发起三个调用）:
   - `code-reviewer` — 代码风格验收：命名规范、日志规范、代码一致性
   - `code-tester` — 代码质量验收：静态分析、接口契约、数据完整性、缺陷发现
   - `doc-maintainer` — 文档同步验收：评估代码变更对项目文档的影响，列出需要更新的文档

   三个 agent 的 prompt 都应包含:
   - 验收目标: $ARGUMENTS（如果为空则说明"验收最近的 git 变更，先运行 git diff --name-only 确定范围"）
   - 要求输出结构化报告

2. **合并输出**:

   ## 代码验收: {变更描述}
   ### 验收结论: ✅ 通过 / ⚠️ 有条件通过 / ❌ 不通过
   ### 代码风格（来自 code-reviewer）
   {评审要点}
   ### 代码质量（来自 code-tester）
   {测试要点}
   ### 文档影响（来自 doc-maintainer）
   {文档更新建议}
   ### 问题清单（合并去重，按严重程度排序）
   #### 🔴 必须修改
   #### 🟡 建议修改
   #### 🔵 可优化
