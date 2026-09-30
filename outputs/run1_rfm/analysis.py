"""Run 1：RFM 客户分层 + 分层回测。

问题：截至 2011-12-09，哪些客户群贡献了主要收入？高价值客户里有多少已经很久没下单？
      用于决定下个季度老客召回名单的优先级。

口径（全部显式写死，便于复算）：
- 数据：data/clean_lines.csv（清洗口径见 prep/build_clean.py），只用有 CustomerID 的行。
- 观察窗：reference_date 前 365 天，[ref-365d, ref)。
- R = ref − 最近一张「购买发票」日期（天）；购买发票 = 不全是退货行（Quantity < 0）的发票；本数据中发票不会混合购买与退货行，两种写法结果一致。
- F = 窗口内购买发票张数。
- M = 窗口内净额（购买 − 退货/取消），不用毛额：毛额会把「下单后当天整单取消」的客户排到榜首。
- 打分：R、M 用五分位（5 最好）；F 用固定切点 1/2/3–4/5–9/10+ → 1..5，
  因为窗口内 35% 的客户 F=1，分位切点在大量并列值上是任意的。
- M ≤ 0 的客户不打分，归入「净额非正」。
- 分层：high = 分数 ≥ 4，low = 分数 ≤ 2。
- 回测：同一套规则在 reference 2011-06-10 上打分，观察之后 183 天（至 2011-12-09）是否再次购买与净额。
  这是「历史上各层后续实际表现」的观察值，不是营销响应率。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
F_CUTS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 10**9)]
SEGMENT_ORDER = ["核心高价值", "高价值流失风险", "高消费中活跃", "近期新客/低频", "中间层", "沉睡低价值", "净额非正"]


def load() -> pd.DataFrame:
    d = pd.read_csv(ROOT / "data" / "clean_lines.csv", parse_dates=["InvoiceDate", "Date"])
    return d[d["CustomerID"].notna()].copy()


def f_score(f: pd.Series) -> pd.Series:
    out = pd.Series(0, index=f.index)
    for score, (lo, hi) in enumerate(F_CUTS, start=1):
        out[(f >= lo) & (f <= hi)] = score
    return out


def quintile(series: pd.Series, higher_is_better: bool) -> pd.Series:
    ranked = series.rank(method="average", ascending=higher_is_better, pct=True)
    return np.ceil(ranked * 5).clip(1, 5).astype(int)


def segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4:
        return "核心高价值"
    if r <= 2 and f >= 4 and m >= 4:
        return "高价值流失风险"
    if r >= 4 and f <= 2:
        return "近期新客/低频"
    if r <= 2 and f <= 2:
        return "沉睡低价值"
    if m >= 4:
        return "高消费中活跃"
    return "中间层"


def score_customers(d: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    w = d[(d["Date"] >= ref - pd.Timedelta(days=365)) & (d["Date"] < ref)]
    inv = w.groupby(["CustomerID", "Invoice"]).agg(date=("Date", "max"), is_return=("IsReturn", "all")).reset_index()
    buys = inv[~inv["is_return"]]
    c = buys.groupby("CustomerID").agg(last=("date", "max"), F=("Invoice", "nunique"))
    gross = w[~w["IsReturn"]].groupby("CustomerID")["Amount"].sum()
    net = w.groupby("CustomerID")["Amount"].sum()
    c["gross"] = gross.reindex(c.index)
    c["M"] = net.reindex(c.index)
    c["R"] = (ref - c["last"]).dt.days
    positive = c["M"].round(2) > 0  # 净额按分四舍五入：浮点残差（约 1e-14）不算正值（Falsifier 发现）
    c["r_score"] = 0
    c["f_score"] = 0
    c["m_score"] = 0
    c.loc[positive, "r_score"] = quintile(-c.loc[positive, "R"], higher_is_better=True)
    c.loc[positive, "f_score"] = f_score(c.loc[positive, "F"])
    c.loc[positive, "m_score"] = quintile(c.loc[positive, "M"], higher_is_better=True)
    c["segment"] = "净额非正"
    c.loc[positive, "segment"] = [segment(r, f, m) for r, f, m in c.loc[positive, ["r_score", "f_score", "m_score"]].itertuples(index=False)]
    return c


def summarize(c: pd.DataFrame) -> list[dict]:
    total_m = float(c["M"].sum())
    rows = []
    for name in SEGMENT_ORDER:
        s = c[c["segment"] == name]
        if s.empty:
            continue
        rows.append({
            "segment": name,
            "customers": int(len(s)),
            "share_of_customers_percent": round(100 * len(s) / len(c), 2),
            "net_revenue": round(float(s["M"].sum()), 2),
            "share_of_net_revenue_percent": round(100 * float(s["M"].sum()) / total_m, 2),
            "median_recency_days": float(s["R"].median()),
            "median_frequency": float(s["F"].median()),
            "median_net_revenue": round(float(s["M"].median()), 2),
        })
    return rows


def cutoffs(c: pd.DataFrame) -> dict:
    p = c[c["M"].round(2) > 0]
    out = {}
    for col, score in (("R", "r_score"), ("M", "m_score")):
        out[col] = {int(k): [round(float(v.min()), 2), round(float(v.max()), 2)] for k, v in p.groupby(score)[col]}
    out["F"] = {i: [lo, hi if hi < 10**9 else None] for i, (lo, hi) in enumerate(F_CUTS, start=1)}
    return out


def backtest(d: pd.DataFrame, ref: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    c = score_customers(d, ref)
    after = d[(d["Date"] >= ref) & (d["Date"] <= end)]
    buyers = set(after[~after["IsReturn"]]["CustomerID"].unique())
    future_net = after.groupby("CustomerID")["Amount"].sum()
    c["repurchased"] = c.index.isin(buyers)
    c["future_net"] = future_net.reindex(c.index).fillna(0.0)
    total_future = float(c["future_net"].sum())
    rows = []
    for name in SEGMENT_ORDER:
        s = c[c["segment"] == name]
        if s.empty:
            continue
        rows.append({
            "segment": name,
            "customers": int(len(s)),
            "repurchase_rate_percent": round(100 * float(s["repurchased"].mean()), 2),
            "future_net_per_customer": round(float(s["future_net"].mean()), 2),
            "share_of_future_net_percent": round(100 * float(s["future_net"].sum()) / total_future, 2),
        })
    overall = {
        "customers": int(len(c)),
        "repurchase_rate_percent": round(100 * float(c["repurchased"].mean()), 2),
        "future_net_total": round(total_future, 2),
    }
    return rows, overall


def main() -> None:
    d = load()
    ref = pd.Timestamp("2011-12-10")
    c = score_customers(d, ref)
    total_m = float(c["M"].sum())
    top = c.sort_values("M", ascending=False)
    conc = {f"top_{int(q*100)}pct_share_percent": round(100 * float(top["M"].iloc[: int(len(top) * q)].sum()) / total_m, 2) for q in (0.01, 0.05, 0.1, 0.2)}
    gross_rank = c.sort_values("gross", ascending=False)
    trap = gross_rank.head(10)
    trap = trap[trap["M"] < 0.01 * trap["gross"]]
    at_risk = c[c["segment"] == "高价值流失风险"]
    bt_rows, bt_overall = backtest(d, pd.Timestamp("2011-06-10"), pd.Timestamp("2011-12-09"))
    out = {
        "reference_date": "2011-12-10",
        "window": "2010-12-10..2011-12-09",
        "customers_scored_window": int(len(c)),
        "customers_nonpositive_net": int((c["M"].round(2) <= 0).sum()),
        "customers_single_purchase": int((c["F"] == 1).sum()),
        "single_purchase_share_percent": round(100 * float((c["F"] == 1).mean()), 2),
        "net_revenue_window": round(total_m, 2),
        "concentration": conc,
        "score_cutoffs": cutoffs(c),
        "segments": summarize(c),
        "at_risk_detail": {
            "customers": int(len(at_risk)),
            "net_revenue": round(float(at_risk["M"].sum()), 2),
            "median_recency_days": float(at_risk["R"].median()),
            "recency_min_days": int(at_risk["R"].min()),
            "recency_max_days": int(at_risk["R"].max()),
        },
        "gross_vs_net_trap": [
            {"customer": int(i), "gross": round(float(r["gross"]), 2), "net": round(float(r["M"]), 2), "gross_rank": int(list(gross_rank.index).index(i)) + 1}
            for i, r in trap.iterrows()
        ],
        "backtest": {"reference_date": "2011-06-10", "outcome_window": "2011-06-10..2011-12-09", "segments": bt_rows, "overall": bt_overall},
    }
    c.reset_index()[["CustomerID", "R", "F", "M", "r_score", "f_score", "m_score", "segment"]].to_csv(OUT / "customer_segments.csv", index=False)
    # 给 skill 的 rfm 算子准备发票级输入（只含购买发票），作为独立复核
    w = d[(d["Date"] >= ref - pd.Timedelta(days=365)) & (d["Date"] < ref)]
    inv = w.groupby(["CustomerID", "Invoice"]).agg(Date=("Date", "max"), is_return=("IsReturn", "all"), Amount=("Amount", "sum")).reset_index()
    inv[~inv["is_return"]][["CustomerID", "Invoice", "Date", "Amount"]].to_csv(OUT / "purchase_invoices.csv", index=False)
    (OUT / "analysis_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
