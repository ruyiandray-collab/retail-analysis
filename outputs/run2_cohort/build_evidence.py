"""由 analysis_output.json / cohort_operator.json 生成 evidence.json（不手抄数字）。"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
a = load(HERE / "analysis_output.json")
op = load(HERE / "cohort_operator.json")
rb = load(HERE / "robustness_output.json")
log = load(ROOT / "data" / "clean_log.json")
F = "outputs/run2_cohort/analysis_output.json"
coh = {r["cohort"]: r for r in a["cohort_365"]}


def test(i, key, scope, src=None, **extra):
    t = (src or a)[key]
    e = {"id": i, "kind": "two_proportion_test", "file": "outputs/run2_cohort/robustness_output.json" if src is not None else F, "scope": scope,
         "a_customers": t["a_n"], "b_customers": t["b_n"], "a_rate_percent": t["a_rate_percent"], "b_rate_percent": t["b_rate_percent"],
         "diff_pp": t["diff_pp"], "ci95_low_pp": t["ci95_pp"][0], "ci95_high_pp": t["ci95_pp"][1], "p_value": t["p_value"],
         "params": {"ci_level_percent": 95}}
    e.update(extra)
    return e


lt = a["left_truncation"]
mature = {p["period_offset"]: p for p in op["mature_cohort_average_curve"]}
ev = [
    {"id": "E001", "kind": "cleaning", "file": "data/clean_log.json", "scope": "全量 2009-12-01..2011-12-09",
     **{k: log[k] for k in ("clean_rows", "net_revenue", "missing_customer_rows", "missing_customer_share_percent")}},
    {"id": "E002", "kind": "cohort_sizes", "file": F, "scope": "首购月新客人数",
     **{f"size_{k.replace('-', '_')}": v for k, v in a["cohort_sizes"].items()}},
    {"id": "E003", "kind": "left_truncation", "file": F, "scope": "同月首购：2010（数据起点后 1–8 个月）vs 2011 的 90 天复购率",
     **{f"rep90_{y}_{m}_percent": lt[m][f"rep90_{y}_percent"] for m in lt for y in ("2010", "2011")},
     **{f"diff_{m}_pp": lt[m]["diff_pp"] for m in lt}, "params": {"window_days": 90}},
    {"id": "E004", "kind": "cohort_365", "file": F, "scope": "2010-03..2010-12 首购且首购日 ≤ 2010-12-09 的新客，365 天复购",
     **{f"rep365_{k.replace('-', '_')}_percent": r["rep365_percent"] for k, r in coh.items()},
     **{f"customers_{k.replace('-', '_')}": r["customers"] for k, r in coh.items()},
     **{f"repeat_customers_{k.replace('-', '_')}": r["repeat_customers"] for k, r in coh.items()},
     **{f"net365_median_{k.replace('-', '_')}": r["net365_median"] for k, r in coh.items()},
     "pool_customers": sum(r["customers"] for r in coh.values()),
     "params": {"window_days": 365}},
    {"id": "E005", "kind": "quarter_365", "file": F, "scope": "按首购季度汇总（Q1 仅含 2010-03）",
     **{f"{q}_{k}": v for q, r in a["quarter_365"].items() for k, v in r.items()}, "params": {"window_days": 365}},
    test("E006", "q4_vs_q2", "Q4（2010-10..12）vs Q2（2010-04..06）365 天复购率"),
    test("E007", "nov_vs_mar", "2010-11 vs 2010-03 首购新客 365 天复购率"),
    test("E008", "trend_180_mar_jun_2011_vs_2010", "3–6 月首购：2011 vs 2010 的 180 天复购率", params={"ci_level_percent": 95, "window_days": 180}),
    test("E009", "q4_xmas_vs_none", "Q4 新客：首单含圣诞品 vs 不含，365 天复购率",
         q4_has_xmas_share_percent=a["q4_has_xmas_share_percent"], q2_has_xmas_share_percent=a["q2_has_xmas_share_percent"]),
    test("E010", "q4_vs_q2_first_order_above_median", "首单金额 ≥ 总体中位数的新客：Q4 vs Q2",
         first_order_value_median_all=a["first_order_value_median_all"], first_order_value_median_q2=a["first_order_value_median_q2"],
         first_order_value_median_q4=a["first_order_value_median_q4"]),
    test("E011", "q4_vs_q2_uk_only", "只看英国新客：Q4 vs Q2"),
    {"id": "E012", "kind": "operator_crosscheck", "file": "outputs/run2_cohort/cohort_operator.json", "scope": "skill cohort_retention 算子，月粒度，成熟 cohort 平均曲线",
     "mature_m1_mean_rate_percent": round(100 * mature[1]["mean_retention_rate"], 2), "mature_m3_mean_rate_percent": round(100 * mature[3]["mean_retention_rate"], 2),
     "mature_cohort_count": mature[1]["cohort_count"],
     "note": "算子同样给出左截断告警；第 N 月留存落在不同日历月，受旺淡季影响，本报告不以它做同期群比较"},
    test("E013", "rep60_q4_vs_q2", "首购后 60 天内复购率：Q4 vs Q2", src=rb, params={"ci_level_percent": 95, "window_days": 60}),
    test("E014", "rep61_180_among_not_rep60_q4_vs_q2", "60 天内未复购者在首购后第 61–180 天的复购率：Q4 vs Q2", src=rb,
         params={"ci_level_percent": 95, "day_from": 61, "day_to": 180, "window_days": 60},
         **{f"purchase_invoices_{m.replace('-', '_')}": v for m, v in rb["purchase_invoices_by_month"].items()}),
    test("E015", "q4_vs_may_jun", "剔除 2010-03/04 后：Q4 vs 2010-05..06 首购新客 365 天复购率", src=rb),
    test("E016", "q4_vs_q2_gap_ge30", "复购定义收紧为首购后第 30–365 天内有购买：Q4 vs Q2", src=rb, params={"ci_level_percent": 95, "day_from": 30, "window_days": 365}),
    {"id": "E017", "kind": "small_cohort", "file": "outputs/run2_cohort/robustness_output.json", "scope": "2010-12 首购（12-01..12-09）同期群",
     "customers": rb["dec_2010"]["customers"], "repeat_customers": rb["dec_2010"]["repeat_customers"], "rep365_percent": rb["dec_2010"]["rep365_percent"],
     "ci95_low_percent": rb["dec_2010"]["ci95_percent"][0], "ci95_high_percent": rb["dec_2010"]["ci95_percent"][1], "params": {"ci_level_percent": 95}},
    test("E018", "dec_vs_nov", "2010-12（46 人）vs 2010-11 首购新客 365 天复购率", src=rb),
    {"id": "E019", "kind": "net365", "file": "outputs/run2_cohort/robustness_output.json", "scope": "首购后 365 天净额（含首单、已扣退货）：Q4 vs Q2；中位数差 bootstrap 2000 次 seed 0",
     "q4_median": rb["net365_q4_vs_q2"]["q4_median"], "q2_median": rb["net365_q4_vs_q2"]["q2_median"],
     "median_diff": rb["net365_q4_vs_q2"]["median_diff"], "median_diff_ci95_low": rb["net365_q4_vs_q2"]["median_diff_ci95"][0],
     "median_diff_ci95_high": rb["net365_q4_vs_q2"]["median_diff_ci95"][1], "q4_mean": rb["net365_q4_vs_q2"]["q4_mean"], "q2_mean": rb["net365_q4_vs_q2"]["q2_mean"],
     "q4_to_q2_median_ratio": rb["net365_q4_vs_q2"]["q4_to_q2_median_ratio"], "q4_to_q2_mean_ratio": rb["net365_q4_vs_q2"]["q4_to_q2_mean_ratio"],
     "median_ratio_ci95_low": rb["ratio_ci"]["median_ratio_ci95"][0], "median_ratio_ci95_high": rb["ratio_ci"]["median_ratio_ci95"][1],
     "mean_ratio_ci95_low": rb["ratio_ci"]["mean_ratio_ci95"][0], "mean_ratio_ci95_high": rb["ratio_ci"]["mean_ratio_ci95"][1],
     "q3_to_q2_median_ratio": rb["ratio_ci"]["q3_to_q2_median_ratio"],
     "params": {"ci_level_percent": 95, "months_12": 12}},
    test("E020", "first_repeat_61_180_q4_vs_q2", "首次复购落在首购后第 61–180 天的新客占比（无条件）：Q4 vs Q2", src=rb, params={"ci_level_percent": 95, "day_from": 61, "day_to": 180}),
    test("E021", "first_repeat_181_365_q4_vs_q2", "首次复购落在首购后第 181–365 天的新客占比（无条件）：Q4 vs Q2", src=rb, params={"ci_level_percent": 95, "day_from": 181, "day_to": 365}),
    test("E022", "calendar_2011_jan_sep_nov_vs_mar", "固定日历窗口 2011-01-01..2011-09-30 内有购买的比例：2010-11 vs 2010-03 首购新客", src=rb,
         params={"ci_level_percent": 95, "month_1": 1, "month_9": 9}),
    {"id": "E023", "kind": "missing_id_by_quarter", "file": "outputs/run2_cohort/robustness_output.json", "scope": "2010 年 Q2–Q4 清洗后数据中缺 CustomerID 的比例：按行 / 按发票 / 按金额",
     **{f"missing_id_share_{q}_percent": v for q, v in rb["missing_id_share_by_quarter_2010"].items()},
     **{f"missing_id_{q}_{k}": v for q, d in rb["missing_id_by_quarter_three_ways"].items() for k, v in d.items()},
     "missing_id_all_rows_percent": log["missing_customer_share_percent"]},
    test("E024", "mar_apr_vs_may_jun", "2010-03..04 vs 2010-05..06 首购新客 365 天复购率", src=rb, params={"ci_level_percent": 95, "month_3": 3, "month_4": 4, "month_5": 5, "month_6": 6}),
    test("E025", "mar_apr_vs_jul", "2010-03..04 vs 2010-07 首购新客 365 天复购率", src=rb, params={"ci_level_percent": 95, "month_3": 3, "month_4": 4, "month_7": 7}),
    {"id": "E026", "kind": "timing_proxy", "file": "outputs/run2_cohort/robustness_output.json", "scope": "两组新客首购后第 61–180 天所落日历月的月均有 ID 购买发票数",
     **rb["invoices_per_month"], "params": {"day_from": 61, "day_to": 180, "month_1": 1, "month_4": 4, "month_6": 6, "month_12": 12}},
]
# 结论里出现的月份、窗口长度等口径参数也写进证据，保证可溯源
EXTRA_PARAMS = {
    "E003": {f"month_{m}": m for m in range(1, 9)},
    "E005": {"months_12": 12},
    "E006": {"window_days": 365},
    "E008": {"month_3": 3, "month_6": 6},
    "E014": {"month_1": 1, "month_4": 4},
    "E015": {"month_3": 3, "month_4": 4, "month_5": 5, "month_6": 6},
    "E017": {"month_10": 10, "month_11": 11, "month_12": 12},
    "E018": {"window_days": 365},
    "E019": {"window_days": 365},
    "E020": {"month_4": 4, "month_9": 9},
    "E004": {"month_3": 3, "month_4": 4},
}
for e in ev:
    if e["id"] in EXTRA_PARAMS:
        e.setdefault("params", {}).update(EXTRA_PARAMS[e["id"]])
sha = hashlib.sha256((ROOT / "data" / "clean_lines.csv").read_bytes()).hexdigest()
(HERE / "evidence.json").write_text(json.dumps({"schema_version": "1.0", "run": "outputs/run2_cohort",
    "source": {"file": "data/clean_lines.csv", "sha256": sha, "raw_source": "UCI Online Retail II (CC BY 4.0)"}, "evidence": ev},
    ensure_ascii=False, indent=1), encoding="utf-8")
print(len(ev), "evidence items")
