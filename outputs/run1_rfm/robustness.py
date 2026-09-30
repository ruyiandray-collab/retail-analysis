"""Run 1 稳健性复核：把 Falsifier 提出的反例用可复算代码重做一遍，结果写入 robustness_output.json。

1. 阈值敏感性：high/low 阈值换一种合理设定，核心层份额与流失风险层人数怎么变；
2. 固定天数口径：F≥4 且 M≥4 的高价值客户里，R > 60/90/120 天各有多少人；
3. 回测噪声：各层复购率的 Wilson 95% 区间；流失风险层未来净额被前 3 名客户撑起多少；
4. 回测季节性：结果窗口截到旺季前（2011-09-09）时的复购率排序；
5. 缺 CustomerID：窗口内缺 ID 行的净额占比，以全部净额为分母时核心层份额。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

import analysis as a

OUT = Path(__file__).resolve().parent


def wilson(k: int, n: int) -> list[float]:
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(100 * (centre - half), 2), round(100 * (centre + half), 2)]


def resegment(c: pd.DataFrame, high: int, low: int) -> pd.Series:
    r, f, m = c["r_score"], c["f_score"], c["m_score"]
    core = (r >= high) & (f >= high) & (m >= high)
    risk = (r <= low) & (f >= high) & (m >= high)
    return core, risk


def main() -> None:
    d = a.load()
    ref = pd.Timestamp("2011-12-10")
    c = a.score_customers(d, ref)
    scored = c[c["segment"] != "净额非正"]
    total = float(c["M"].sum())
    sens = []
    for label, high, low in (("原口径 high≥4 low≤2", 4, 2), ("high≥3", 3, 2), ("high=5", 5, 2), ("low≤1", 4, 1), ("low≤3", 4, 3)):
        core, risk = resegment(scored, high, low)
        sens.append({"setting": label, "core_customers": int(core.sum()),
                     "core_share_of_net_revenue_percent": round(100 * float(scored.loc[core, "M"].sum()) / total, 2),
                     "at_risk_customers": int(risk.sum())})
    hv = scored[(scored["f_score"] >= 4) & (scored["m_score"] >= 4)]
    fixed_days = {f"over_{t}_days": int((hv["R"] > t).sum()) for t in (60, 90, 120)}
    fixed_days["high_value_customers"] = int(len(hv))

    # 回测：复购率区间 + 流失风险层集中度 + 旺季前窗口
    bt_ref, bt_end, pre_peak_end = pd.Timestamp("2011-06-10"), pd.Timestamp("2011-12-09"), pd.Timestamp("2011-09-09")
    b = a.score_customers(d, bt_ref)
    after = d[(d["Date"] >= bt_ref) & (d["Date"] <= bt_end)]
    pre = d[(d["Date"] >= bt_ref) & (d["Date"] <= pre_peak_end)]
    b["repurchased"] = b.index.isin(after[~after["IsReturn"]]["CustomerID"].unique())
    b["repurchased_pre_peak"] = b.index.isin(pre[~pre["IsReturn"]]["CustomerID"].unique())
    b["future_net"] = after.groupby("CustomerID")["Amount"].sum().reindex(b.index).fillna(0.0)
    backtest = []
    for name in a.SEGMENT_ORDER[:-1]:
        s = b[b["segment"] == name]
        k = int(s["repurchased"].sum())
        backtest.append({"segment": name, "customers": int(len(s)), "repurchase_rate_percent": round(100 * k / len(s), 2),
                         "repurchase_ci95_percent": wilson(k, len(s)),
                         "pre_peak_repurchase_rate_percent": round(100 * float(s["repurchased_pre_peak"].mean()), 2)})
    risk = b[b["segment"] == "高价值流失风险"]["future_net"].sort_values(ascending=False)
    risk_detail = {"future_net_median": round(float(risk.median()), 2),
                   "top3_share_of_segment_future_net_percent": round(100 * float(risk.head(3).sum()) / float(risk.sum()), 2)}
    pre_rank = sorted(backtest, key=lambda x: -x["pre_peak_repurchase_rate_percent"])
    risk_detail["pre_peak_rank"] = [x["segment"] for x in pre_rank].index("高价值流失风险") + 1
    risk_detail["full_window_rank"] = [x["segment"] for x in sorted(backtest, key=lambda x: -x["repurchase_rate_percent"])].index("高价值流失风险") + 1

    # 缺 CustomerID
    raw = pd.read_csv(a.ROOT / "data" / "clean_lines.csv", parse_dates=["Date"])
    w = raw[(raw["Date"] >= ref - pd.Timedelta(days=365)) & (raw["Date"] < ref)]
    all_net = float(w["Amount"].sum())
    missing_net = float(w[w["CustomerID"].isna()]["Amount"].sum())
    core_net = float(c[c["segment"] == "核心高价值"]["M"].sum())
    missing = {"window_net_all_rows": round(all_net, 2), "missing_id_net": round(missing_net, 2),
               "missing_id_share_of_window_net_percent": round(100 * missing_net / all_net, 2),
               "missing_id_uk_row_share_percent": round(100 * float((w[w["CustomerID"].isna()]["Country"] == "United Kingdom").mean()), 2),
               "core_share_of_all_net_percent": round(100 * core_net / all_net, 2)}

    # 个人节奏：流失风险层的沉默期 R 是本人历史购买间隔中位数的几倍（全量历史 2009-12-01 起）
    buys = d[~d["IsReturn"]].groupby(["CustomerID", "Invoice"])["Date"].max().reset_index()
    days = buys.drop_duplicates(["CustomerID", "Date"]).sort_values("Date")
    gap = days.groupby("CustomerID")["Date"].diff().dt.days.groupby(days["CustomerID"]).median()
    at_risk = c[c["segment"] == "高价值流失风险"].copy()
    at_risk["ratio"] = at_risk["R"] / gap.reindex(at_risk.index)
    rhythm = {"customers": int(len(at_risk)), "ratio_median": round(float(at_risk["ratio"].median()), 2),
              "silence_ge_2x_own_gap": int((at_risk["ratio"] >= 2).sum()), "silence_ge_3x_own_gap": int((at_risk["ratio"] >= 3).sum()),
              "silence_lt_1_5x_own_gap": int((at_risk["ratio"] < 1.5).sum())}

    # 国家构成：客户主要下单国家（窗口内出现最多的 Country）
    wc = d[(d["Date"] >= ref - pd.Timedelta(days=365)) & (d["Date"] < ref)]
    main_country = wc.groupby("CustomerID")["Country"].agg(lambda s: s.value_counts().index[0])
    uk = (main_country.reindex(scored.index) == "United Kingdom")
    country = {"uk_share_core_percent": round(100 * float(uk[scored["segment"] == "核心高价值"].mean()), 2),
               "uk_share_all_scored_percent": round(100 * float(uk.mean()), 2)}

    # Reviewer 要求补入证据包的数字
    m_only = scored.sort_values("M", ascending=False).head(749)
    extra = {"m_only_top_749_share_of_net_revenue_percent": round(100 * float(m_only["M"].sum()) / total, 2)}
    mid_future = b[b["segment"] == "中间层"]["future_net"]
    extra["mid_future_net_median"] = round(float(mid_future.median()), 2)
    boot = [float(b[b["segment"] == "高价值流失风险"]["future_net"].sample(frac=1, replace=True, random_state=i).mean()) for i in range(2000)]
    boot.sort()
    extra["at_risk_future_net_mean_boot_ci95"] = [round(boot[49], 2), round(boot[1949], 2)]
    at_risk_last = c.loc[at_risk.index, "last"]
    extra["at_risk_last_purchase_aug_sep_2011"] = int(((at_risk_last >= "2011-08-01") & (at_risk_last < "2011-10-01")).sum())
    hv_ratio = hv["R"] / gap.reindex(hv.index)
    extra["hv_over_60_days_and_ge_2x_own_gap"] = int(((hv["R"] > 60) & (hv_ratio >= 2)).sum())
    extra["hv_over_90_days_and_ge_2x_own_gap"] = int(((hv["R"] > 90) & (hv_ratio >= 2)).sum())
    extra["high_spend_segment_hv_r_score_3"] = int(((scored["segment"] == "高消费中活跃") & (scored["f_score"] >= 4) & (scored["m_score"] >= 4) & (scored["r_score"] == 3)).sum())

    out = {"reviewer_requested": extra, "threshold_sensitivity": sens, "own_rhythm": rhythm, "country_mix": country, "fixed_day_at_risk": fixed_days, "backtest_noise": backtest,
           "at_risk_backtest_detail": risk_detail, "missing_customer_id": missing}
    (OUT / "robustness_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
