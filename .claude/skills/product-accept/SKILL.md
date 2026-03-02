---
name: product-accept
description: 产品验收 — 产品验收专家 + 系统架构师并行验收已实现功能
argument-hint: <功能名或变更范围> (如 "收藏夹功能", "新 Dashboard 页面")
model: sonnet
---

# 产品验收 (Product Acceptance)

对 **$ARGUMENTS** 进行产品体验+技术实现双维度验收。

## 工作流程

1. **并行启动两个 agent**（使用 Agent tool，在同一条消息中发起两个调用）:
   - `product-reviewer` — 从用户视角验收：功能完整性、用户体验、视觉布局、可发现性
   - `architect-designer` — 从技术视角验收：实现是否符合架构规范、数据模型是否合理、是否引入技术债

   两个 agent 的 prompt 都应包含:
   - 验收目标: $ARGUMENTS
   - 要求先阅读相关代码和文档，再输出结构化报告

2. **合并输出**:

   ## 产品验收: {功能名}
   ### 验收结论: ✅ 通过 / ⚠️ 有条件通过 / ❌ 不通过
   ### 体验验收（来自 product-reviewer）
   {体验评估要点}
   ### 技术验收（来自 architect-designer）
   {技术评估要点}
   ### 问题清单（合并去重，按优先级排序）
   #### P0 — 必须修复
   #### P1 — 建议修复
   #### P2 — 可优化
