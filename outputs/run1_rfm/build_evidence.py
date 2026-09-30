"""由 analysis_output.json / robustness_output.json / rfm_operator.json 生成 evidence.json（不手抄数字）。"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
a = load(HERE / "analysis_output.json")
rb = load(HERE / "robustness_output.json")
op = load(HERE / "rfm_operator.json")
power52 = load(HERE / "power_n52_out.json")
power10 = load(HERE / "power_mde10_out.json")
log = load(ROOT / "data" / "clean_log.json")
seg = {s["segment"]: s for s in a["segments"]}
bt = {s["segment"]: s for s in a["backtest"]["segments"]}
noise = {s["segment"]: s for s in rb["backtest_noise"]}
opseg = {s["segment"]: s for s in op["segments"]}
sens = {s["setting"]: s for s in rb["threshold_sensitivity"]}
F = "outputs/run1_rfm/analysis_output.json"


def segev(i, name, **extra):
    s = seg[name]
    e = {"id": i, "kind": "segment", "file": F, "scope": f"{name} / {a['window']}"}
    e.update({k: s[k] for k in ("customers", "share_of_customers_percent", "net_revenue", "share_of_net_revenue_percent",
                                "median_recency_days", "median_frequency", "median_net_revenue")})
    e.update(extra)
    return e


ev = [
    {"id": "E001", "kind": "profile", "file": "data/clean_lines.csv", "scope": "有 CustomerID 的购买客户 / " + a["window"],
     "customers_scored": a["customers_scored_window"], "net_revenue_window": a["net_revenue_window"],
     "customers_single_purchase": a["customers_single_purchase"], "single_purchase_share_percent": a["single_purchase_share_percent"],
     "customers_nonpositive_net": a["customers_nonpositive_net"], "formula": "客户级聚合：F=购买发票数，M=净额"},
    {"id": "E002", "kind": "cleaning", "file": "data/clean_log.json", "scope": "全量 2009-12-01..2011-12-09",
     **{k: log[k] for k in ("raw_rows", "clean_rows", "duplicate_rows", "net_revenue", "missing_customer_rows", "missing_customer_share_percent")},
     "note": "与 skill 自带案例公开值一致：clean_rows 1,021,333 / net_revenue 18,928,551.86 / 缺 ID 227,172 行"},
    {"id": "E003", "kind": "concentration", "file": F, "scope": "按窗口净额排序的客户 / " + a["window"], **a["concentration"]},
    segev("E004", "核心高价值"),
    segev("E005", "高价值流失风险", recency_min_days=a["at_risk_detail"]["recency_min_days"], recency_max_days=a["at_risk_detail"]["recency_max_days"]),
    segev("E006", "高消费中活跃"),
    segev("E007", "沉睡低价值"),
    segev("E008", "近期新客/低频"),
    segev("E009", "中间层"),
    {"id": "E010", "kind": "backtest", "file": F, "scope": "同规则在 2011-06-10 打分，观察 2011-06-10..2011-12-09",
     "overall_customers": a["backtest"]["overall"]["customers"], "overall_repurchase_rate_percent": a["backtest"]["overall"]["repurchase_rate_percent"],
     "core_customers": bt["核心高价值"]["customers"], "core_repurchase_rate_percent": bt["核心高价值"]["repurchase_rate_percent"],
     "core_future_net_per_customer": bt["核心高价值"]["future_net_per_customer"], "core_share_of_future_net_percent": bt["核心高价值"]["share_of_future_net_percent"],
     "at_risk_customers": bt["高价值流失风险"]["customers"], "at_risk_repurchase_rate_percent": bt["高价值流失风险"]["repurchase_rate_percent"],
     "at_risk_future_net_per_customer": bt["高价值流失风险"]["future_net_per_customer"],
     "high_spend_repurchase_rate_percent": bt["高消费中活跃"]["repurchase_rate_percent"], "high_spend_future_net_per_customer": bt["高消费中活跃"]["future_net_per_customer"],
     "new_low_repurchase_rate_percent": bt["近期新客/低频"]["repurchase_rate_percent"], "new_low_future_net_per_customer": bt["近期新客/低频"]["future_net_per_customer"],
     "mid_repurchase_rate_percent": bt["中间层"]["repurchase_rate_percent"], "mid_future_net_per_customer": bt["中间层"]["future_net_per_customer"],
     "dormant_repurchase_rate_percent": bt["沉睡低价值"]["repurchase_rate_percent"], "dormant_future_net_per_customer": bt["沉睡低价值"]["future_net_per_customer"],
     "at_risk_vs_mid_future_net_ratio": round(bt["高价值流失风险"]["future_net_per_customer"] / bt["中间层"]["future_net_per_customer"], 2),
     "at_risk_vs_dormant_future_net_ratio": round(bt["高价值流失风险"]["future_net_per_customer"] / bt["沉睡低价值"]["future_net_per_customer"], 2)},
    {"id": "E011", "kind": "gross_vs_net", "file": F, "scope": "按窗口毛额排名前 10 中净额 < 毛额 1% 的客户",
     **{f"customer_{t['customer']}_{k}": t[k] for t in a["gross_vs_net_trap"] for k in ("gross", "net", "gross_rank")}},
    {"id": "E012", "kind": "operator_crosscheck", "file": "outputs/run1_rfm/rfm_operator.json", "scope": "skill rfm 算子（已修复方向 bug），输入为购买发票级毛额",
     "entity_count": op["entity_count"], "operator_high_value_active_customers": opseg["high_value_active"]["size"],
     "operator_high_value_active_share_of_customers_percent": round(opseg["high_value_active"]["share_of_entities"] * 100, 2),
     "operator_high_value_active_share_of_monetary_percent": round(opseg["high_value_active"]["share_of_monetary"] * 100, 2),
     "note": "算子 high 阈值为分数≥3，本报告为≥4；M 为毛额而非净额，分层不直接可比。修复前算子把最近、最频繁、金额最高的客户标为 dormant"},
    {"id": "E013", "kind": "sensitivity", "file": "outputs/run1_rfm/robustness_output.json", "scope": "只改一个阈值，其余保持原口径",
     "core_share_high_ge3_percent": sens["high≥3"]["core_share_of_net_revenue_percent"], "core_customers_high_ge3": sens["high≥3"]["core_customers"],
     "core_share_high_eq5_percent": sens["high=5"]["core_share_of_net_revenue_percent"], "core_customers_high_eq5": sens["high=5"]["core_customers"],
     "at_risk_high_ge3": sens["high≥3"]["at_risk_customers"], "at_risk_high_eq5": sens["high=5"]["at_risk_customers"],
     "at_risk_low_le1": sens["low≤1"]["at_risk_customers"], "at_risk_low_le3": sens["low≤3"]["at_risk_customers"]},
    {"id": "E014", "kind": "fixed_day_threshold", "file": "outputs/run1_rfm/robustness_output.json", "scope": "F 分≥4 且 M 分≥4 的高价值客户，按距上次购买天数",
     **rb["fixed_day_at_risk"]},
    {"id": "E015", "kind": "backtest_noise", "file": "outputs/run1_rfm/robustness_output.json", "scope": "2011-06-10 打分回测；旺季前窗口截至 2011-09-09",
     "at_risk_ci95_low_percent": noise["高价值流失风险"]["repurchase_ci95_percent"][0], "at_risk_ci95_high_percent": noise["高价值流失风险"]["repurchase_ci95_percent"][1],
     "mid_ci95_low_percent": noise["中间层"]["repurchase_ci95_percent"][0], "mid_ci95_high_percent": noise["中间层"]["repurchase_ci95_percent"][1],
     "dormant_ci95_low_percent": noise["沉睡低价值"]["repurchase_ci95_percent"][0], "dormant_ci95_high_percent": noise["沉睡低价值"]["repurchase_ci95_percent"][1],
     "at_risk_pre_peak_repurchase_rate_percent": noise["高价值流失风险"]["pre_peak_repurchase_rate_percent"],
     "mid_pre_peak_repurchase_rate_percent": noise["中间层"]["pre_peak_repurchase_rate_percent"],
     "at_risk_future_net_median": rb["at_risk_backtest_detail"]["future_net_median"],
     "top3_share_of_segment_future_net_percent": rb["at_risk_backtest_detail"]["top3_share_of_segment_future_net_percent"],
     "pre_peak_rank": rb["at_risk_backtest_detail"]["pre_peak_rank"], "full_window_rank": rb["at_risk_backtest_detail"]["full_window_rank"],
     "mid_future_net_median": rb["reviewer_requested"]["mid_future_net_median"],
     "at_risk_future_net_mean_boot_ci95_low": rb["reviewer_requested"]["at_risk_future_net_mean_boot_ci95"][0],
     "at_risk_future_net_mean_boot_ci95_high": rb["reviewer_requested"]["at_risk_future_net_mean_boot_ci95"][1]},
    {"id": "E016", "kind": "missing_id_bias", "file": "outputs/run1_rfm/robustness_output.json", "scope": "窗口 " + a["window"] + " 全部行", **rb["missing_customer_id"]},
    {"id": "E017", "kind": "own_rhythm", "file": "outputs/run1_rfm/robustness_output.json", "scope": "高价值流失风险层：R / 本人历史购买间隔中位数（2009-12-01 起全量历史）",
     **rb["own_rhythm"]},
    {"id": "E018", "kind": "country_mix", "file": "outputs/run1_rfm/robustness_output.json", "scope": "客户主要下单国家为英国的占比 / " + a["window"],
     **rb["country_mix"]},
    {"id": "E019", "kind": "reviewer_requested", "file": "outputs/run1_rfm/robustness_output.json", "scope": "Reviewer 要求补入证据包的数字 / " + a["window"],
     **{k: v for k, v in rb["reviewer_requested"].items() if not isinstance(v, list)}},
    {"id": "E020", "kind": "power_mde", "file": "outputs/run1_rfm/power_n52_out.json + power_mde10_out.json", "scope": "召回 holdout 实验功效，基线复购率 45%，α=0.05，功效 80%，双侧",
     "baseline_rate_percent": 45, "n_per_arm_given": 52,
     "detectable_absolute_effect_pp": round(100 * power52["given_sample_size"]["detectable_absolute_effect"], 2),
     "target_effect_pp": 10, "n_per_arm_needed": power10["given_mde"]["n_control"], "n_total_needed": power10["given_mde"]["n_total"]},
]
# 口径参数也写进证据：结论里出现的阈值、窗口天数、置信水平都必须能溯源
PARAMS = {
    "E001": {"single_purchase_invoices": 1},
    "E003": {"top_cut_1_percent": 1, "top_cut_5_percent": 5, "top_cut_10_percent": 10, "top_cut_20_percent": 20},
    "E004": {"high_score_threshold": 4},
    "E010": {"outcome_window_days": 183},
    "E011": {"trap_customer_id": 16446},
    "E013": {"alt_high_threshold_3": 3, "alt_high_threshold_5": 5, "base_high_threshold": 4, "base_at_risk_customers": sens["原口径 high≥4 low≤2"]["at_risk_customers"]},
    "E014": {"high_score_threshold": 4, "day_threshold_60": 60, "day_threshold_90": 90, "day_threshold_120": 120},
    "E015": {"ci_level_percent": 95, "top_n_customers": 3},
    "E017": {"multiple_2": 2, "multiple_3": 3, "multiple_1_5": 1.5},
    "E019": {"multiple_2": 2, "day_threshold_60": 60, "day_threshold_90": 90, "high_score_threshold": 4, "r_score_3": 3, "top_n": 749,
             "r_score_3_min_days": a["score_cutoffs"]["R"]["3"][0], "r_score_3_max_days": a["score_cutoffs"]["R"]["3"][1]},
    "E020": {"power_percent": 80, "arms": 2},
}
for e in ev:
    e.update({"params": PARAMS.get(e["id"], {})} if e["id"] in PARAMS else {})
sha = hashlib.sha256((ROOT / "data" / "clean_lines.csv").read_bytes()).hexdigest()
(HERE / "evidence.json").write_text(json.dumps({"schema_version": "1.0", "run": "outputs/run1_rfm",
    "source": {"file": "data/clean_lines.csv", "sha256": sha, "raw_source": "UCI Online Retail II (CC BY 4.0)"}, "evidence": ev},
    ensure_ascii=False, indent=1), encoding="utf-8")
print(len(ev), "evidence items")
