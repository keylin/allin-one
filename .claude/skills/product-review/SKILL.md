---
name: product-review
description: 产品评审 — 产品设计师 + 系统架构师并行评审方案
argument-hint: <方案描述或需求> (如 "收藏夹标签系统", "全局搜索功能")
model: sonnet
---

# 产品评审 (Product Review)

对 **$ARGUMENTS** 进行产品+技术双维度方案评审。

## 工作流程

1. **并行启动两个 agent**（使用 Agent tool，在同一条消息中发起两个调用）:
   - `product-designer` — 从产品视角评估：需求分析、用户旅程、MVP 定义、竞品参考
   - `architect-designer` — 从技术视角评估：架构影响、数据建模、API 设计、实现成本与风险

   两个 agent 的 prompt 都应包含:
   - 评审目标: $ARGUMENTS
   - 要求输出结构化报告（按各自 agent 定义的输出格式）

2. **合并输出**:
   汇总两份报告为统一的评审结论:

   ## 产品评审: {方案名}
   ### 产品视角（来自 product-designer）
   {产品评估要点}
   ### 技术视角（来自 architect-designer）
   {技术评估要点}
   ### 综合结论
   - 可行性判断: ✅ 推荐 / ⚠️ 需调整 / ❌ 不建议
   - 关键风险
   - 建议的下一步
