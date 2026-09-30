"""Run 2 稳健性复核：把 Mechanism / Falsifier 提出的关键检验用可复算代码重做，写入 robustness_output.json。

1. 差距出现在哪一段：60 天内复购率 Q4 vs Q2；60 天内未复购者在第 61–180 天的复购率 Q4 vs Q2；
2. 淡季代理：2010-10/11 与 2011-01/02 有 ID 的购买发票数；
3. 左截断残留：剔除 2010-03/04 后，Q4 vs 2010-05..06；
4. 复购定义收紧：首购后第 30–365 天内有购买才算复购，Q4 vs Q2；
5. 小样本：2010-12 同期群（46 人）的 Wilson 95% 区间。
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


def main() -> None:
    d, buys = a.load()
    c = a.customers(d, buys)
    first = c["fd"]
    b = buys.join(first, on="CustomerID")
    gaps = b[b["date"] > b["fd"]].assign(gap=lambda x: (x["date"] - x["fd"]).dt.days)
    second_gap = gaps.groupby("CustomerID")["gap"].min()
    c["second_gap"] = second_gap.reindex(c.index)

    pool = c[(c["fd"] >= "2010-03-01") & c["observable365"]].copy()
    pool["q"] = pool["fd"].dt.quarter
    q2, q4 = pool[pool["q"] == 2], pool[pool["q"] == 4]

    rep60 = lambda s: s["second_gap"] <= 60
    out = {"rep60_q4_vs_q2": a.two_prop(rep60(q4), rep60(q2))}
    late = lambda s: s[~rep60(s)]["second_gap"].between(61, 180)
    out["rep61_180_among_not_rep60_q4_vs_q2"] = a.two_prop(late(q4), late(q2))

    inv = buys.assign(m=buys["date"].dt.to_period("M").astype(str)).groupby("m").size()
    out["purchase_invoices_by_month"] = {m: int(inv[m]) for m in ("2010-10", "2010-11", "2011-01", "2011-02")}

    may_jun = pool[(pool["fd"] >= "2010-05-01") & (pool["fd"] < "2010-07-01")]
    out["q4_vs_may_jun"] = a.two_prop(q4["rep365"], may_jun["rep365"])

    # 首购后第 30–365 天内有任意购买（不只看第一次复购：先补单再隔月复购的客户也算）
    rep30_ids = set(gaps[gaps["gap"].between(30, 365)]["CustomerID"])
    rep30 = lambda s: pd.Series(s.index.isin(rep30_ids), index=s.index)
    out["q4_vs_q2_gap_ge30"] = a.two_prop(rep30(q4), rep30(q2))

    dec = pool[pool["cohort"] == "2010-12"]
    out["dec_2010"] = {"customers": int(len(dec)), "repeat_customers": int(dec["rep365"].sum()),
                       "rep365_percent": round(100 * float(dec["rep365"].mean()), 2), "ci95_percent": wilson(int(dec["rep365"].sum()), len(dec))}
    # —— Reviewer 要求补入证据包的数字 ——
    nov = pool[pool["cohort"] == "2010-11"]
    out["dec_vs_nov"] = a.two_prop(dec["rep365"], nov["rep365"])
    # 12 个月净额：Q4 vs Q2 的中位数差（bootstrap 2000 次，seed 0）与均值
    import numpy as np
    rng = np.random.default_rng(0)
    v4, v2 = q4["net365"].to_numpy(), q2["net365"].to_numpy()
    diffs = sorted(float(np.median(rng.choice(v4, len(v4))) - np.median(rng.choice(v2, len(v2)))) for _ in range(2000))
    out["net365_q4_vs_q2"] = {
        "q4_median": round(float(np.median(v4)), 2), "q2_median": round(float(np.median(v2)), 2),
        "median_diff": round(float(np.median(v4) - np.median(v2)), 2), "median_diff_ci95": [round(diffs[49], 2), round(diffs[1949], 2)],
        "q4_mean": round(float(v4.mean()), 2), "q2_mean": round(float(v2.mean()), 2),
        "q4_to_q2_median_ratio": round(float(np.median(v4) / np.median(v2)), 2), "q4_to_q2_mean_ratio": round(float(v4.mean() / v2.mean()), 2)}
    # 无条件拆分：首次复购落在哪一段（占全体新客）
    seg = lambda s, lo, hi: s["second_gap"].between(lo, hi)
    out["first_repeat_61_180_q4_vs_q2"] = a.two_prop(seg(q4, 61, 180), seg(q2, 61, 180))
    out["first_repeat_181_365_q4_vs_q2"] = a.two_prop(seg(q4, 181, 365), seg(q2, 181, 365))
    # 固定日历窗口：2011-01-01..2011-09-30 内有购买的比例（同一日历期比较，排除「窗口落在哪个季节」）
    cal = set(buys[(buys["date"] >= "2011-01-01") & (buys["date"] <= "2011-09-30")]["CustomerID"])
    act = lambda s: pd.Series(s.index.isin(cal), index=s.index)
    out["calendar_2011_jan_sep_nov_vs_mar"] = a.two_prop(act(pool[pool["cohort"] == "2010-11"]), act(pool[pool["cohort"] == "2010-03"]))
    # 缺 CustomerID 的行按季度的占比（检查同期群构成是否随季节被缺失扭曲）
    raw = pd.read_csv(a.ROOT / "data" / "clean_lines.csv", usecols=["Date", "CustomerID"], parse_dates=["Date"])
    r10 = raw[(raw["Date"] >= "2010-04-01") & (raw["Date"] < "2011-01-01")]
    out["missing_id_share_by_quarter_2010"] = {f"Q{q}": round(100 * float(g["CustomerID"].isna().mean()), 2) for q, g in r10.groupby(r10["Date"].dt.quarter)}
    # —— 第 2 轮 Reviewer 要求补入证据包的数字 ——
    ratios_med, ratios_mean = [], []
    rng = np.random.default_rng(1)
    for _ in range(2000):
        s4, s2 = rng.choice(v4, len(v4)), rng.choice(v2, len(v2))
        ratios_med.append(float(np.median(s4) / np.median(s2)))
        ratios_mean.append(float(s4.mean() / s2.mean()))
    ratios_med.sort(); ratios_mean.sort()
    q3v = pool[pool["q"] == 3]["net365"]
    out["ratio_ci"] = {"median_ratio_ci95": [round(ratios_med[49], 2), round(ratios_med[1949], 2)],
                       "mean_ratio_ci95": [round(ratios_mean[49], 2), round(ratios_mean[1949], 2)],
                       "q3_to_q2_median_ratio": round(float(q3v.median() / np.median(v2)), 2)}
    mar_apr = pool[pool["cohort"].isin(["2010-03", "2010-04"])]["rep365"]
    out["mar_apr_vs_may_jun"] = a.two_prop(mar_apr, may_jun["rep365"])
    out["mar_apr_vs_jul"] = a.two_prop(mar_apr, pool[pool["cohort"] == "2010-07"]["rep365"])
    # 时机代理：两组新客各自第 61–180 天所落日历月的月均购买发票数
    out["invoices_per_month"] = {
        "q2_days61_180_2010_06_to_12": round(float(inv[[f"2010-{m:02d}" for m in range(6, 13)]].mean()), 1),
        "q4_days61_180_2011_01_to_04": round(float(inv[[f"2011-{m:02d}" for m in range(1, 5)]].mean()), 1)}
    # 缺 CustomerID 的季度占比：行 / 发票 / 金额三种口径
    raw2 = pd.read_csv(a.ROOT / "data" / "clean_lines.csv", usecols=["Invoice", "Date", "Amount", "CustomerID"], parse_dates=["Date"])
    r = raw2[(raw2["Date"] >= "2010-04-01") & (raw2["Date"] < "2011-01-01")].assign(q=lambda x: "Q" + x["Date"].dt.quarter.astype(str), miss=lambda x: x["CustomerID"].isna())
    by_inv = r.groupby(["q", "Invoice"])["miss"].all().groupby("q").mean()
    by_amt = r.assign(m_amt=r["Amount"] * r["miss"]).groupby("q")[["m_amt", "Amount"]].sum()
    out["missing_id_by_quarter_three_ways"] = {q: {"rows_percent": round(100 * float(g["miss"].mean()), 2),
                                                   "invoices_percent": round(100 * float(by_inv[q]), 2),
                                                   "amount_percent": round(100 * float(by_amt.loc[q, "m_amt"] / by_amt.loc[q, "Amount"]), 2)}
                                               for q, g in r.groupby("q")}
    (OUT / "robustness_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
