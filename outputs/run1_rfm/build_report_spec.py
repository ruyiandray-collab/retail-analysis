"""生成 report_spec.json：图表数据直接从 evidence.json / analysis_output.json 读取，不手抄数字。"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
load = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))
E = {e["id"]: e for e in load("evidence.json")["evidence"]}
a = load("analysis_output.json")
rb = load("robustness_output.json")
quality = load("03_quality.json")
clean_log = json.loads((HERE.parents[1] / "data" / "clean_log.json").read_text(encoding="utf-8"))
fmt = lambda x: f"{x:,.2f}"

segments = [s for s in a["segments"] if s["segment"] != "净额非正"]
noise = {s["segment"]: s for s in rb["backtest_noise"]}
flags = {f["type"]: f for f in quality["flags"]}

spec = {
    "meta": {
        "title": f"老客召回：{E['E014']['over_60_days']} 名高价值客户超 60 天未购，名单该按天数和个人节奏定，而不是按 RFM 分层",
        "subtitle": "RFM 分层 + 回测 + 稳健性复核。本报告只描述历史结构与自然复购，不输出召回响应率或增量。",
        "decision": "决策 · 下季度老客召回名单优先级",
        "window": "2010-12-10 至 2011-12-09（回测：2011-06-10 至 2011-12-09）",
        "source": "UCI Online Retail II（CC BY 4.0），清洗口径见 prep/build_clean.py",
        "quality": {"flag": "review", "note": f"缺 CustomerID 的行占 {E['E002']['missing_customer_share_percent']}%，窗口内对应 {E['E016']['missing_id_share_of_window_net_percent']}% 净额，无法进入客户分层"},
    },
    "diversity": {"theme": "apple-graphite", "style": "apple", "motion": "restrained", "density": 4},
    "kpis": [
        {"label": "有 ID 购买客户", "value": E["E001"]["customers_scored"], "unit": "人", "delta": f"单次购买 {E['E001']['single_purchase_share_percent']}%", "direction": "flat"},
        {"label": "核心高价值层净额份额", "value": E["E004"]["share_of_net_revenue_percent"], "unit": "percent", "delta": f"{E['E004']['customers']} 人 · 阈值敏感 {E['E013']['core_share_high_eq5_percent']}%–{E['E013']['core_share_high_ge3_percent']}%", "direction": "flat"},
        {"label": "高价值客户超 60 天未购", "value": E["E014"]["over_60_days"], "unit": "人", "delta": f"其中沉默≥本人间隔 2 倍：{E['E019']['hv_over_60_days_and_ge_2x_own_gap']} 人", "direction": "down", "good_when_down": True},
        {"label": "缺 ID 净额占比", "value": E["E016"]["missing_id_share_of_window_net_percent"], "unit": "percent", "delta": "无法进入召回名单", "direction": "flat"},
    ],
    "findings": [
        {"title": f"收入集中在少数客户：前 20% 客户贡献 {E['E003']['top_20pct_share_percent']}% 净额",
         "body": f"核心高价值层 {E['E004']['customers']} 人（{E['E004']['share_of_customers_percent']}%）贡献有 ID 净额 {E['E004']['share_of_net_revenue_percent']}%；以全部净额为分母是 {E['E016']['core_share_of_all_net_percent']}%。只按金额取同样人数就能占 {E['E019']['m_only_top_749_share_of_net_revenue_percent']}%，份额主要由 M 决定。",
         "level": "L0", "tone": "neutral", "evidence_ids": ["E003", "E004", "E016", "E019"], "limitations": ["阈值改动时份额在 40.34%–78.86% 之间"]},
        {"title": f"「很久没下单」的高价值客户：超 60 天 {E['E014']['over_60_days']} 人，超 90 天 {E['E014']['over_90_days']} 人",
         "body": f"F、M 分数均≥4 的高价值客户共 {E['E014']['high_value_customers']} 人。分位口径的「流失风险层」78 人会随阈值在 {E['E013']['at_risk_high_eq5']}–{E['E013']['at_risk_high_ge3']} 人之间变化，不宜直接当名单规模。",
         "level": "L0", "tone": "negative", "evidence_ids": ["E014", "E013", "E005"], "limitations": ["天数阈值需运营按召回产能确认"]},
        {"title": "回测不支持「流失风险层比中间层更容易回来」",
         "body": f"2011-06-10 打分后 183 天，流失风险层复购率 {E['E010']['at_risk_repurchase_rate_percent']}%（区间 {E['E015']['at_risk_ci95_low_percent']}%–{E['E015']['at_risk_ci95_high_percent']}%），与中间层 {E['E010']['mid_repurchase_rate_percent']}% 重叠；人均后续净额虽是中间层的 {E['E010']['at_risk_vs_mid_future_net_ratio']} 倍，但前 3 名客户占 {E['E015']['top3_share_of_segment_future_net_percent']}%。",
         "level": "L1", "tone": "negative", "evidence_ids": ["E010", "E015"], "limitations": ["58 人样本，功效低", "自然复购，不是营销响应"]},
        {"title": f"另一种筛选口径（未经回测）：沉默期达到本人购买间隔 2 倍以上的高价值客户 {E['E019']['hv_over_60_days_and_ge_2x_own_gap']} 人（超 90 天为 {E['E019']['hv_over_90_days_and_ge_2x_own_gap']} 人）",
         "body": f"流失风险层 78 人里 {E['E017']['silence_ge_2x_own_gap']} 人沉默期≥本人间隔 2 倍，但 {E['E019']['at_risk_last_purchase_aug_sep_2011']} 人最后一次购买在 2011 年 8–9 月，部分可能只是等旺季。这是高置信候选，不是流失判定。",
         "level": "L2", "tone": "neutral", "evidence_ids": ["E013", "E014", "E017", "E019"], "limitations": ["召回增量需实验验证"]},
    ],
    "background": {"narrative": "决策方要确定下季度老客召回名单：召回谁、先召回谁。本报告用 RFM（最近一次购买 R、购买频次 F、净额 M）描述客户价值结构，用「同一规则半年前打分、看之后半年实际表现」的回测检验分层是否有区分力，再用阈值敏感性、置信区间、季节窗口和缺失 ID 四类反例检验结论强度。数据只有交易记录，没有营销触达和响应，所以本报告不回答「召回能带来多少增量」。"},
    "data_overview": {
        "narrative": f"原始 {E['E002']['raw_rows']:,} 行，按 skill 自带案例同一口径清洗后 {E['E002']['clean_rows']:,} 行，净收入 {fmt(E['E002']['net_revenue'])}，与案例公开值逐位一致。客户分析只用有 CustomerID 的行。",
        "table": {"title": "质量门禁（da_quality：DEGRADED）", "columns": [{"key": "flag", "label": "标记"}, {"key": "detail", "label": "内容"}, {"key": "handling", "label": "处理"}],
                  "rows": [
                      {"flag": "field_missing", "detail": f"CustomerID 缺失率 {E['E002']['missing_customer_share_percent']}%；窗口内缺 ID 行 {E['E016']['missing_id_uk_row_share_percent']}% 来自英国", "handling": "客户级结论只覆盖有 ID 部分；份额同时给出全部净额口径"},
                      {"flag": "date_gap", "detail": f"{flags['date_gap']['count']} 个日历日无交易，多为周六与节假日", "handling": "R 按日历天数计，影响很小"},
                      {"flag": "duplicate_date", "detail": "同一天多行", "handling": "行级明细的正常形态，不是重复写入"},
                      {"flag": "metric_outlier", "detail": "单行金额极端值", "handling": "M 按客户净额聚合并用分位打分，极端值只影响所在客户的分数"},
                  ]},
        "notes": ["净额 = 购买 − 退货/取消；M 不用毛额，否则整单取消的客户（如 16446：毛额 168,472.50，净额 2.90）会被排进头部。",
                  "F 用固定切点 1/2/3–4/5–9/10+：35.53% 的客户只买过 1 次，分位切点在并列值上没有意义。",
                  "R 与 M 用五分位打分（5 最好），并列取平均名次；只对净额 > 0 的客户打分。本期切点：R 分 5/4/3/2/1 = " + " / ".join(f"{v[0]:.0f}–{v[1]:.0f} 天" for k, v in sorted(a["score_cutoffs"]["R"].items(), key=lambda x: -int(x[0]))) + "；M 分 5/4/3/2/1 = " + " / ".join(f"{v[0]:,.2f}–{v[1]:,.2f}" for k, v in sorted(a["score_cutoffs"]["M"].items(), key=lambda x: -int(x[0]))) + "。",
                  "分层规则（high = 分数≥4，low = 分数≤2，按顺序匹配）：核心高价值 = R、F、M 均 high；高价值流失风险 = R low 且 F、M high；近期新客/低频 = R high 且 F low；沉睡低价值 = R、F 均 low；高消费中活跃 = 其余中 M high；其余为中间层。",
                  "回测：在 2011-06-10 用同一规则、同样 365 天窗口（2010-06-10..2011-06-09）重新打分，看 2011-06-10..2011-12-09 是否有购买发票及净额。",
                  f"两个 sheet 在 2010-12-01..09 完全重叠（同一批行存了两份），清洗中的 {E['E002']['duplicate_rows']:,} 行完全重复里有 {clean_log['sheet_overlap_duplicate_rows']:,} 行是这份重叠，真正的重复记录 {clean_log['true_duplicate_rows']:,} 行。"],
    },
    "analysis": [
        {"heading": "结构：六成净额来自不到两成客户",
         "narrative": "各层对有 ID 净额的贡献。核心高价值与高消费中活跃两层合计贡献八成以上；人数最多的沉睡低价值层贡献不到一成。",
         "charts": [{"type": "bars", "title": "各分层占有 ID 净额的份额（%）", "data": [
             {"label": f"{s['segment']}（{s['customers']} 人）", "value": s["share_of_net_revenue_percent"], "display": f"{s['share_of_net_revenue_percent']}%"} for s in segments],
             "note": "窗口 2010-12-10..2011-12-09；分母 7,965,817.00；净额非正 16 人未列出。", "source": "E004–E009"}]},
        {"heading": "阈值敏感：同一份数据，核心层份额可以是四成也可以是八成",
         "narrative": "每次只改一个参数。结论数字对阈值很敏感，所以报告里的「62.26%」「78 人」都只在本口径下成立。",
         "charts": [{"type": "bars", "title": "核心高价值层净额份额随高分阈值变化（%）", "data": [
             {"label": s["setting"], "value": s["core_share_of_net_revenue_percent"], "display": f"{s['core_share_of_net_revenue_percent']}% · 流失风险 {s['at_risk_customers']} 人"} for s in rb["threshold_sensitivity"]],
             "note": "low 阈值只影响流失风险层人数，不影响核心层份额。", "source": "E013"}]},
        {"heading": "回测：分层能区分「会回来的人」吗",
         "narrative": "2011-06-10 用同一规则打分，看之后 183 天是否再购买。核心层与沉睡层区分明显；流失风险层区间很宽，与中间层、近期新客不可区分；把结果窗口截到旺季前，它的排名从第 3 掉到第 5。",
         "charts": [{"type": "bars", "title": "各层回测复购率（%）", "data": [
             {"label": s["segment"], "value": s["repurchase_rate_percent"], "display": f"{s['repurchase_rate_percent']}%（{s['repurchase_ci95_percent'][0]}–{s['repurchase_ci95_percent'][1]}）"} for s in rb["backtest_noise"]],
             "note": "括号内为 Wilson 95% 区间；自然复购，不是营销响应率。", "source": "E010 / E015"}],
         "tables": [{"title": "回测明细", "columns": [{"key": "seg", "label": "分层"}, {"key": "n", "label": "人数"}, {"key": "full", "label": "183 天复购率"}, {"key": "pre", "label": "旺季前 91 天复购率"}],
                     "rows": [{"seg": s["segment"], "n": s["customers"], "full": f"{s['repurchase_rate_percent']}%", "pre": f"{s['pre_peak_repurchase_rate_percent']}%"} for s in rb["backtest_noise"]],
                     "numeric_columns": ["n"]}]},
        {"heading": "名单怎么定：固定天数 + 个人节奏",
         "narrative": f"与其用分位切点，不如先定天数，再看沉默期是否明显长于这个客户自己的购买间隔。高价值客户里，超过 60 天未购且沉默期≥本人间隔 2 倍的有 {E['E019']['hv_over_60_days_and_ge_2x_own_gap']} 人。另有 {E['E019']['high_spend_segment_hv_r_score_3']} 名高价值客户最近一次购买在 33–68 天前，分位规则把他们归进了高消费中活跃层，下一轮可能进入名单。",
         "charts": [{"type": "bars", "title": "高价值客户（F、M 分≥4，共 987 人）中的候选人数", "data": [
             {"label": "超 60 天未购", "value": E["E014"]["over_60_days"]},
             {"label": "超 60 天且沉默≥本人间隔 2 倍", "value": E["E019"]["hv_over_60_days_and_ge_2x_own_gap"]},
             {"label": "超 90 天未购", "value": E["E014"]["over_90_days"]},
             {"label": "超 90 天且沉默≥本人间隔 2 倍", "value": E["E019"]["hv_over_90_days_and_ge_2x_own_gap"]},
             {"label": "超 120 天未购", "value": E["E014"]["over_120_days"]}],
             "note": "本人间隔 = 2009-12-01 起全部购买日期之间间隔的中位数。", "source": "E014 / E019"}]},
    ],
    "conclusions": [
        {"text": "召回对象优先从高价值客户（F、M 分≥4）中选，按「超过 N 天未购 + 沉默期≥本人间隔 2 倍」筛选；N 取 60 天时 61 人，取 90 天时 40 人，由召回产能决定。", "evidence_ids": ["E014", "E019"]},
        {"text": "不直接使用分位口径的 78 人流失风险层：人数随阈值在 9–316 之间变化，回测复购率与中间层不可区分。", "evidence_ids": ["E013", "E015"]},
        {"text": "召回增量不能从本数据推出。104 人对半分只能检出 26.14 个百分点的差异；要检出 10 个百分点需每组 389 人，应把 holdout 放在更大的候选池（例如全部超 60 天未购的有价值客户）或跨季度累计。", "evidence_ids": ["E020"]},
    ],
    "next_steps": [
        {"question": "召回到底能带来多少增量复购？", "data_needed": "召回触达记录 + 随机 holdout（每组≥389 人，90 天复购率与净额为验收指标）"},
        {"question": "沉默的高价值客户是流失了还是在等旺季？", "data_needed": "2012 年 1–3 月交易数据，看 2011 年 8–9 月最后购买的 60 人是否在旺季后回归"},
        {"question": "缺 CustomerID 的 15.02% 净额是什么渠道？", "data_needed": "订单来源 / 渠道字段；若是门店或第三方平台，需要单独的客户识别方式"},
    ],
    "appendix": {
        "tables": [{"title": "证据索引", "columns": [{"key": "id", "label": "证据"}, {"key": "kind", "label": "类型"}, {"key": "scope", "label": "范围"}],
                    "rows": [{"id": e["id"], "kind": e["kind"], "scope": e["scope"]} for e in load("evidence.json")["evidence"]]}],
        "notes": [
            "独立角色分析（mode: native_subagents）：Locator / Mechanism / Falsifier 由 Claude Code 并行派发的独立 subagent 完成，彼此不读对方工件；Reviewer 最后执行。工件：agents/locator.json、agents/mechanism.json、agents/falsifier.json、agents/reviewer.json、agents/execution.json。",
            "Reviewer 对 14 条草稿结论给出 6 pass / 8 downgrade / 0 block，全部接受：C013 由 L2 降为 L1，召回建议由 L3 降为 L2。",
            "Falsifier 发现 4 名净额为浮点残差（约 1e-14）的客户被当作正值打分，已修正为「净额非正」。",
            "skill 自带 rfm 算子复核（E012）：客户数 4,261 一致。复核中发现该算子打分方向与并列处理有缺陷（最近、最频繁、金额最高的客户被标为 dormant），已修复并提交补丁（contrib/fix-rfm-score-direction.patch）；算子用毛额与≥3 阈值，分层不与本报告直接比较。",
            "da_verify：15 条结论全部可溯源；repeated_window_checks 警告——多条结论引用同一时间窗，单条结论的显著性不能叠加。",
        ],
    },
}
(HERE / "report_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
