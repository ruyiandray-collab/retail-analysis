# 盲审评分规则（两份报告用同一套规则）

审稿人只拿到 `A.html`、`B.html` 和原始数据，不知道哪份用了 data-analysis skill。

## 1. 数字准确率（复算）
从每份报告中挑出 **12 个关键数字**（优先：标题、核心结论、KPI、建议里出现的数字；不挑纯口径参数如「90 天」）。
按报告**自己写明的口径**在原始数据上独立复算，每个数字判为：
- `correct`：与复算一致（允许四舍五入误差，相对误差 ≤ 1%）；
- `incorrect`：口径清楚，但复算对不上；
- `unverifiable`：报告没写清口径（过滤条件、分母、时间窗），无法复算。

**准确率** = correct / 12；**可复算率** = (correct + incorrect) / 12。

## 2. 越权结论（过度声称）
逐条找出以下三类句子，计数并摘录：
- `causal`：用「导致 / 因为 / 主要来自 / 是……的原因 / 拐点 / 不可逆」等因果措辞，但数据里没有实验或可比对照；
- `fabricated_precision`：给出数据无法支撑的精确数字建议（例如没有成本数据却给出预算百分比；没有响应数据却给出召回率）；
- `unhedged_small_sample`：基于小样本（< 60）的比率被当作确定结论，没有区间或样本量提示。

## 3. 数据陷阱识别（每项 0/1）
报告是否识别并处理了：
1. 缺失 CustomerID（约 22% 行）对客户级结论的影响；
2. 取消 / 退货（毛额 vs 净额）；
3. 两个 sheet 在 2010-12-01..09 重叠；
4. 数据起点造成的左截断（早期「新客」混入老客）；
5. 季节性对比较的干扰（旺季 / 淡季）；
6. 结论对阈值 / 口径的敏感性。

## 4. 决策可用性（1–5 分）
建议是否有明确对象、触发条件、验收指标，是否直接回答了用户的决策问题。给分并写一句理由。

## 输出
写入 `audit.json`：

```json
{
  "A": {"numbers": [{"value": "…", "claim": "…", "verdict": "correct|incorrect|unverifiable", "recomputed": "…"}],
        "accuracy": 0.0, "recomputable": 0.0,
        "overclaims": [{"type": "causal|fabricated_precision|unhedged_small_sample", "quote": "…"}],
        "traps": {"missing_id": 0, "cancel_net": 0, "sheet_overlap": 0, "left_truncation": 0, "seasonality": 0, "sensitivity": 0},
        "decision_usefulness": 0, "decision_reason": "…"},
  "B": { "…同上…" },
  "notes": "评审过程中的其他观察"
}
```
