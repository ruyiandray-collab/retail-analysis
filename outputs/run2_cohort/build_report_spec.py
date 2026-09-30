"""生成 report_spec.json：图表数据直接从 evidence.json / analysis_output.json / robustness_output.json 读取。"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
load = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))
E = {e["id"]: e for e in load("evidence.json")["evidence"]}
a = load("analysis_output.json")
rb = load("robustness_output.json")
op = load("cohort_operator.json")
quality = load("03_quality.json")

cohorts = a["cohort_365"]
q2 = E["E005"]["Q2_rep365_percent"]
oct_index = [c["cohort"] for c in cohorts].index("2010-10")
lt = a["left_truncation"]

# 第 N 月留存矩阵（算子输出）：用来展示「第 N 月落在哪个日历月」的季节干扰
matrix_rows, cells = [], {}
for c in op["cohorts"]:
    label = c["cohort"][:7]
    if not ("2010-03" <= label <= "2010-12"):
        continue
    matrix_rows.append(label)
    for p in c["periods"]:
        if 1 <= p["period_offset"] <= 6:
            cells[f"{label}|M{p['period_offset']}"] = round(100 * p["retention_rate"], 1)

spec = {
    "meta": {
        "title": "Q4 新客一年内复购率比 Q2 低约 15 个百分点，差距出在首购后第 2–6 个月，三个直觉解释都不成立",
        "subtitle": "同期群 365 天复购 + 反证检验。季节与年度趋势无法完全分离，本报告不输出因果结论，预算建议为条件式。",
        "decision": "反证 · 下一年获客预算的季度分配",
        "window": "首购 2010-03 至 2010-12，观察至 2011-12-09",
        "source": "UCI Online Retail II（CC BY 4.0），清洗口径见 prep/build_clean.py",
        "quality": {"flag": "review", "note": f"左截断：1–2 月「新客」混入老客，已剔除；全表 {E['E023']['missing_id_all_rows_percent']}% 的行缺 CustomerID"},
    },
    "diversity": {"theme": "slate-amber", "style": "editorial", "motion": "none", "density": 6},
    "kpis": [
        {"label": "主比较池新客", "value": E["E004"]["pool_customers"], "unit": "人", "delta": "2010-03..12 首购，满 365 天", "direction": "flat"},
        {"label": "Q2 新客 365 天复购率", "value": q2, "unit": "percent", "delta": "基线", "direction": "flat"},
        {"label": "Q4 新客 365 天复购率", "value": E["E005"]["Q4_rep365_percent"], "unit": "percent", "delta": f"{E['E006']['diff_pp']} 个百分点 vs Q2", "direction": "down"},
        {"label": "Q4 / Q2 新客 12 个月净额（中位数）", "value": E["E019"]["q4_to_q2_median_ratio"], "unit": "倍", "delta": f"区间 {E['E019']['median_ratio_ci95_low']}–{E['E019']['median_ratio_ci95_high']}", "direction": "down"},
    ],
    "findings": [
        {"title": f"Q4 新客复购率比 Q2 低 {abs(E['E006']['diff_pp'])} 个百分点，换口径仍在",
         "body": f"95% 区间低 {abs(E['E006']['ci95_high_pp'])} 到低 {abs(E['E006']['ci95_low_pp'])} 个百分点。剔除 3–4 月后为低 {abs(E['E015']['diff_pp'])}，复购定义收紧到首购后第 30–365 天为低 {abs(E['E016']['diff_pp'])}。",
         "level": "L1", "tone": "negative", "evidence_ids": ["E006", "E015", "E016"], "limitations": ["只有 2010 一个年度"]},
        {"title": "差距出在首购后第 61–180 天，之后没有显著追回",
         "body": f"60 天内 Q4 与 Q2 无显著差异（{E['E013']['a_rate_percent']}% vs {E['E013']['b_rate_percent']}%）；首次复购落在第 61–180 天的 Q4 只有 {E['E020']['a_rate_percent']}%，Q2 为 {E['E020']['b_rate_percent']}%；第 181–365 天 Q4 只多 {E['E021']['diff_pp']} 个百分点。",
         "level": "L2", "tone": "negative", "evidence_ids": ["E013", "E020", "E021"], "limitations": ["只描述时段，不判断原因"]},
        {"title": "圣诞品、首单金额、国家都不能解释主要差距",
         "body": f"首单含圣诞品与否只差 {E['E009']['diff_pp']} 个百分点；首单金额在中位数以上时 Q4 仍低 {abs(E['E010']['diff_pp'])}；只看英国仍低 {abs(E['E011']['diff_pp'])}。",
         "level": "L1", "tone": "neutral", "evidence_ids": ["E009", "E010", "E011"], "limitations": ["逐个控制，未做联合控制"]},
        {"title": "原因有两种候选未能分离：淡季时机，或客户构成不同",
         "body": f"Q4 新客的第 61–180 天落在 2011 年 1–4 月，月均购买发票 {E['E026']['q4_days61_180_2011_01_to_04']:,} 张，Q2 新客对应的 2010 年 6–12 月为 {E['E026']['q2_days61_180_2010_06_to_12']:,} 张；但在同一日历期 2011-01..09 内，11 月首购新客有购买的只占 {E['E022']['a_rate_percent']}%，3 月首购为 {E['E022']['b_rate_percent']}%。",
         "level": "L1", "tone": "neutral", "evidence_ids": ["E026", "E022"], "limitations": ["需要第二个年度的同期群来分离"]},
    ],
    "background": {"narrative": "决策方要定下一年获客预算在各季度怎么分：哪个月获得的新客后续复购最好、最差，差异从何而来。这份报告的写法是「先立结论、再逐个推翻」：先用 365 天复购率比较同期群，再用左截断、口径敏感、小样本、年度趋势、日历窗口五类反证去削弱它，留下站得住的部分。数据没有获客成本、渠道和投放记录，因此预算只能给条件式规则。"},
    "data_overview": {
        "narrative": "只用有 CustomerID 的行。同期群 = 首次购买发票所在月；主指标 = 首购日后 365 天内（不含首购当天）是否再有购买发票。不用「第 N 月留存」做主指标：第 N 月落在哪个日历月由首购月决定，会把旺淡季混进同期群比较。",
        "table": {"title": "质量与口径风险", "columns": [{"key": "risk", "label": "风险"}, {"key": "evidence", "label": "数据表现"}, {"key": "handling", "label": "处理"}],
                  "rows": [
                      {"risk": "左截断", "evidence": f"1 月、2 月首购新客 90 天复购率比 2011 年同月高 {lt['01']['diff_pp']}、{lt['02']['diff_pp']} 个百分点", "handling": "主比较从 2010-03 开始；另测剔除 3–4 月"},
                      {"risk": "右截断", "evidence": "数据截至 2011-12-09", "handling": "只保留首购日 ≤ 2010-12-09 的客户"},
                      {"risk": "缺 CustomerID", "evidence": f"Q4 按行 {E['E023']['missing_id_Q4_rows_percent']}%、按金额 {E['E023']['missing_id_Q4_amount_percent']}%，但按发票只有 {E['E023']['missing_id_Q4_invoices_percent']}%（Q2：{E['E023']['missing_id_Q2_rows_percent']}% / {E['E023']['missing_id_Q2_amount_percent']}% / {E['E023']['missing_id_Q2_invoices_percent']}%）", "handling": "三种口径方向不一致，作为全局限制披露"},
                      {"risk": "小同期群", "evidence": f"2010-12 只有 {E['E017']['customers']} 人", "handling": "不单独点名最差月"},
                      {"risk": "质量门禁 DEGRADED", "evidence": "日期缺口（周六、节假日）、行级极端值", "handling": "按客户聚合，按日历天数计算窗口"},
                  ]},
        "notes": ["圣诞品：StockCode 在原始数据任一行的 Description 里含 CHRISTMAS、XMAS 或 ADVENT（不区分大小写），按商品编码而不是按单行描述判定；共 198 个编码。「首单含圣诞品」= 首购当天的购买金额中圣诞品金额 > 0。换成按单行描述判定会得到不同数字（盲审复算为 +2.15 个百分点），结论方向不变：区间含 0。",
                  "复购收入按净额计（购买 − 退货/取消）；首购当天的其他发票不算复购。",
                  "skill 自带 cohort_retention 算子复核：成熟同期群平均 M1 留存 21.08%（E012），算子同样给出左截断告警。"],
    },
    "analysis": [
        {"heading": "现象：365 天复购率从春季到年末一路走低",
         "narrative": "每个点是一个首购月的新客。虚线为 Q2 基线。10 月起明显低于基线。",
         "charts": [{"type": "line", "title": "各首购月新客 365 天复购率（%）", "baseline": {"value": q2, "label": f"Q2 {q2}%"},
                     "marker": {"index": oct_index, "label": "Q4 开始"},
                     "data": [{"label": c["cohort"][2:], "value": c["rep365_percent"]} for c in cohorts],
                     "note": "2010-12 只有 46 人，区间 36.12%–63.88%。", "source": "E004 / E017"}],
         "tables": [{"title": "按首购季度", "columns": [{"key": "q", "label": "季度"}, {"key": "n", "label": "新客"}, {"key": "rep", "label": "365 天复购率"}, {"key": "k", "label": "复购人数"}, {"key": "v", "label": "12 个月净额中位数"}],
                     "rows": [{"q": q + ("（仅 3 月）" if q == "Q1" else ""), "n": r["customers"], "rep": f"{r['rep365_percent']}%", "k": r["repeat_customers"], "v": r["net365_median"]} for q, r in a["quarter_365"].items()],
                     "numeric_columns": ["n", "k", "v"]}]},
        {"heading": "反证一：为什么不用「第 N 月留存」",
         "narrative": "算子给出的第 N 月留存矩阵里，斜线方向（同一个日历月）颜色一致变深或变浅——那是旺淡季，不是同期群质量。这正是本报告改用固定 365 天窗口的原因。",
         "charts": [{"type": "matrix", "title": "首购月 × 第 N 月留存（%）", "rows": matrix_rows, "columns": [f"M{i}" for i in range(1, 7)], "cells": cells,
                     "note": "cohort_retention 算子输出；同一日历月落在不同列。", "source": "E012"}]},
        {"heading": "反证二：早期「新客」里混了老客",
         "narrative": "同一个日历月首购，2010 年（数据刚开始）与 2011 年（已有一年历史）比。1–2 月 2010 年明显偏高，说明里面混有老客；3 月起差异回到噪声范围，而 6 月反向差距同样很大，说明这类对比本身噪声不小。",
         "charts": [{"type": "bars", "title": "90 天复购率：2010 年减 2011 年同月（个百分点）",
                     "data": [{"label": f"{m} 月", "value": v["diff_pp"], "display": f"{v['diff_pp']:+}"} for m, v in lt.items()],
                     "note": "2011 年 1 月只有 72 人。", "source": "E003"}]},
        {"heading": "反证三：差距在哪一段、能否被解释",
         "narrative": "把复购按首购后天数拆开：差距集中在第 61–180 天，之后没有追回。三个直觉解释逐个控制后差距都还在；圣诞品因素最多能解释很小一部分。",
         "charts": [{"type": "bars", "title": "Q4 减 Q2（个百分点）",
                     "data": [
                         {"label": "60 天内复购", "value": E["E013"]["diff_pp"], "display": f"{E['E013']['diff_pp']:+}（含 0）"},
                         {"label": "首次复购在第 61–180 天", "value": E["E020"]["diff_pp"], "display": f"{E['E020']['diff_pp']:+}"},
                         {"label": "首次复购在第 181–365 天", "value": E["E021"]["diff_pp"], "display": f"{E['E021']['diff_pp']:+}（含 0）"},
                         {"label": "只看首单金额≥中位数", "value": E["E010"]["diff_pp"], "display": f"{E['E010']['diff_pp']:+}"},
                         {"label": "只看英国新客", "value": E["E011"]["diff_pp"], "display": f"{E['E011']['diff_pp']:+}"},
                         {"label": "Q4 内：首单含圣诞品 − 不含", "value": E["E009"]["diff_pp"], "display": f"{E['E009']['diff_pp']:+}（含 0）"}],
                     "note": "正态近似 95% 区间见证据条目。", "source": "E009–E011 / E013 / E020 / E021"}]},
        {"heading": "反证四：是季节，还是一年比一年差",
         "narrative": f"3–6 月首购新客的 180 天复购率，2011 年只比 2010 年低 {abs(E['E008']['diff_pp'])} 个百分点且不显著，纯年度下行不像主要解释；但缺 2011 年 Q4 的完整观察，季节与趋势无法彻底分开。同一日历期内 11 月首购者本身也更不活跃（{E['E022']['a_rate_percent']}% vs 3 月 {E['E022']['b_rate_percent']}%），客户构成的差异同样可能存在。",
         "tables": [{"title": "两种未分离的解释", "columns": [{"key": "h", "label": "候选解释"}, {"key": "for", "label": "支持"}, {"key": "against", "label": "削弱"}],
                     "rows": [
                         {"h": "时机：首单后遇到淡季", "for": f"缺口所在的 2011 年 1–4 月月均购买发票 {E['E026']['q4_days61_180_2011_01_to_04']:,} 张，Q2 新客对应月份为 {E['E026']['q2_days61_180_2010_06_to_12']:,} 张", "against": "第 181–365 天没有显著追回"},
                         {"h": "构成：Q4 新客本身更少复购", "for": f"同一日历期内活跃比例 {E['E022']['a_rate_percent']}% vs {E['E022']['b_rate_percent']}%", "against": "首单金额、品类、国家都未显示差异"}]}]},
    ],
    "conclusions": [
        {"text": f"点估计最好的是 3–4 月首购的新客（{E['E004']['rep365_2010_03_percent']}%、{E['E004']['rep365_2010_04_percent']}%），比 5–6 月显著高 {E['E024']['diff_pp']} 个百分点，但与 7 月不可区分；最差的是 Q4 整体（{E['E005']['Q4_rep365_percent']}%），不宜单独点名某一个月。", "evidence_ids": ["E004", "E005", "E017", "E018", "E024", "E025"]},
        {"text": f"预算规则：Q4 新客 12 个月净额中位数是 Q2 的 {E['E019']['q4_to_q2_median_ratio']} 倍（区间 {E['E019']['median_ratio_ci95_low']}–{E['E019']['median_ratio_ci95_high']}）。Q4 与 Q2 单客获客成本之比高于 {E['E019']['median_ratio_ci95_high']} 时，把 Q4 边际预算移向 Q2、其次 Q3（Q3 价值只有 Q2 的 {E['E019']['q3_to_q2_median_ratio']} 倍）；低于 {E['E019']['median_ratio_ci95_low']} 时维持 Q4；介于两者之间先做验收测试。净额是收入口径，默认各季毛利率相同。", "evidence_ids": ["E019", "E006"]},
        {"text": "不要用复购人数判断季度好坏：Q4 复购人数多于 Q3 只是因为获客量大。", "evidence_ids": ["E005"]},
    ],
    "next_steps": [
        {"question": "Q4 新客的第 61–180 天缺口是淡季时机还是客户构成？", "data_needed": "2011 年 Q4 新客在 2012 年 1–4 月的复购；若缺口重现且 2011 年 3–4 月新客没有同样缺口，时机解释更强"},
        {"question": "对 Q4 新客在 1–4 月做触达能否缩小缺口？", "data_needed": "随机 holdout：Q4 新客一半在 1–4 月收到触达，比较第 61–180 天复购率"},
        {"question": "按季度的获客成本是多少？", "data_needed": "各季投放金额与新客数，用来套用上面的 0.63–0.82 阈值规则"},
    ],
    "appendix": {
        "tables": [{"title": "证据索引", "columns": [{"key": "id", "label": "证据"}, {"key": "kind", "label": "类型"}, {"key": "scope", "label": "范围"}],
                    "rows": [{"id": e["id"], "kind": e["kind"], "scope": e["scope"]} for e in load("evidence.json")["evidence"]]}],
        "notes": [
            "独立角色分析（mode: native_subagents）：Locator / Mechanism / Falsifier 由并行派发的独立 subagent 完成，彼此不读对方工件；Reviewer 最后执行，共两轮。工件：agents/locator.json、agents/mechanism.json、agents/falsifier.json、agents/reviewer.json（第 1 轮：4 pass / 6 downgrade / 1 block）、agents/reviewer_round2.json（第 2 轮：9 pass / 5 downgrade / 0 block）、agents/execution.json。",
            "第 1 轮 Reviewer 阻断了原预算建议（只说「取决于获客成本」且用复购人数论证），已按其方案改为条件式规则；原「淡季推迟」解读因第 181–365 天未追回而改为两种未分离的候选。",
            "Falsifier 指出「第二单间隔 ≥30 天」的口径应为「首购后第 30–365 天内有任意购买」，已修正（E016）。",
            "da_verify：全部结论可溯源；repeated_window_checks 警告——多条结论引用同一时间窗，单条显著性不能叠加。",
        ],
    },
}
(HERE / "report_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
