"""Run 2：新客同期群复购 —— 哪个月获得的新客后续复购最好/最差，差异和什么同步？

决策：下一年获客预算在各季度怎么分配（按新客 12 个月价值，而不只按获客量）。

口径（显式写死）：
- 数据：data/clean_lines.csv，只用有 CustomerID 的行；购买发票 = 不全是退货行（Quantity < 0）的发票；本数据中发票不会混合购买与退货行，两种写法结果一致。
- 同期群 = 客户首次购买发票所在月份。
- 主指标：首购日后 365 天内（不含首购当天）是否再有购买发票 = 365 天复购率。
  不用「第 N 月留存」做主指标：第 N 月落在哪个日历月由首购月决定，会把旺淡季混进同期群比较；
  365 天窗口让每个同期群都经历完整一年。
- 主比较只用 2010-03..2010-12 首购、且首购日 ≤ 2010-12-09 的客户（有完整 365 天观察）。
  2009-12 起数据才开始，2009-12..2010-02 的「新客」混入了老客（左截断），证据见 left_truncation。
- 圣诞品：StockCode 在原始数据任一描述里含 CHRISTMAS / XMAS / ADVENT。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
XMAS = re.compile(r"CHRISTMAS|XMAS|ADVENT", re.I)
LAST_DAY = pd.Timestamp("2011-12-09")


def two_prop(a: pd.Series, b: pd.Series) -> dict:
    """a − b 的差（百分点）、95% 置信区间与双侧 p 值（正态近似）。"""
    p1, p2, n1, n2 = a.mean(), b.mean(), len(a), len(b)
    diff = p1 - p2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pooled = (a.sum() + b.sum()) / (n1 + n2)
    se0 = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = diff / se0 if se0 else float("nan")
    p = math.erfc(abs(z) / math.sqrt(2))
    return {
        "a_n": int(n1), "b_n": int(n2),
        "a_rate_percent": round(100 * p1, 2), "b_rate_percent": round(100 * p2, 2),
        "diff_pp": round(100 * diff, 2),
        "ci95_pp": [round(100 * (diff - 1.96 * se), 2), round(100 * (diff + 1.96 * se), 2)],
        "p_value": float(f"{p:.3g}"),
    }


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.concat([
        pd.read_csv(ROOT / "data" / name, dtype={"StockCode": str}, usecols=["StockCode", "Description"])
        for name in ("Year_2009-2010.csv", "Year_2010-2011.csv")
    ]).dropna()
    xmas = raw.groupby("StockCode")["Description"].apply(lambda s: bool(s.str.contains(XMAS).any()))
    d = pd.read_csv(ROOT / "data" / "clean_lines.csv", parse_dates=["Date"], dtype={"StockCode": str})
    d = d[d["CustomerID"].notna()].copy()
    d["xmas"] = d["StockCode"].map(xmas).fillna(False).astype(bool)
    inv = d.groupby(["CustomerID", "Invoice"]).agg(date=("Date", "max"), is_return=("IsReturn", "all")).reset_index()
    return d, inv[~inv["is_return"]]


def customers(d: pd.DataFrame, buys: pd.DataFrame) -> pd.DataFrame:
    first = buys.groupby("CustomerID")["date"].min().rename("fd")
    b = buys.join(first, on="CustomerID")
    c = first.to_frame()
    c["cohort"] = c["fd"].dt.to_period("M").astype(str)
    for h in (90, 180, 365):
        later = b[(b["date"] > b["fd"]) & (b["date"] <= b["fd"] + pd.Timedelta(days=h))]
        c[f"rep{h}"] = c.index.isin(later["CustomerID"].unique())
        c[f"orders{h}"] = later.groupby("CustomerID")["Invoice"].nunique().reindex(c.index).fillna(0)
        c[f"observable{h}"] = c["fd"] + pd.Timedelta(days=h) <= LAST_DAY
    lines = d.merge(first, left_on="CustomerID", right_index=True)
    in365 = lines[(lines["Date"] >= lines["fd"]) & (lines["Date"] <= lines["fd"] + pd.Timedelta(days=365))]
    c["net365"] = in365.groupby("CustomerID")["Amount"].sum().reindex(c.index)
    fo = lines[(lines["Date"] == lines["fd"]) & (~lines["IsReturn"])]
    fo_amt = fo.groupby("CustomerID")["Amount"].sum()
    c["first_order_value"] = fo_amt.reindex(c.index)
    c["first_order_xmas_share"] = (fo.assign(x=fo["Amount"] * fo["xmas"]).groupby("CustomerID")["x"].sum() / fo_amt).reindex(c.index)
    c["uk"] = (d.groupby("CustomerID")["Country"].first() == "United Kingdom").reindex(c.index)
    return c


def main() -> None:
    d, buys = load()
    c = customers(d, buys)
    out: dict = {}

    sizes = c.groupby("cohort").size()
    out["cohort_sizes"] = {k: int(v) for k, v in sizes.items()}

    # 左截断：同一日历月首购，2010（历史 ≤ 2 个月）vs 2011（历史 ≥ 13 个月）的 90 天复购率
    lt = {}
    for month in ("01", "02", "03", "04", "05", "06", "07", "08"):
        a = c[(c["cohort"] == f"2010-{month}") & c["observable90"]]["rep90"]
        b = c[(c["cohort"] == f"2011-{month}") & c["observable90"]]["rep90"]
        lt[month] = {"rep90_2010_percent": round(100 * a.mean(), 2), "rep90_2011_percent": round(100 * b.mean(), 2),
                     "diff_pp": round(100 * (a.mean() - b.mean()), 2), "n_2010": int(len(a)), "n_2011": int(len(b))}
    out["left_truncation"] = lt

    main_pool = c[(c["fd"] >= "2010-03-01") & c["observable365"]].copy()
    rows = []
    for cohort, s in main_pool.groupby("cohort"):
        rows.append({
            "cohort": cohort, "customers": int(len(s)),
            "rep365_percent": round(100 * s["rep365"].mean(), 2),
            "repeat_customers": int(s["rep365"].sum()),
            "orders365_mean": round(float(s["orders365"].mean()), 2),
            "net365_median": round(float(s["net365"].median()), 2),
            "first_order_value_median": round(float(s["first_order_value"].median()), 2),
            "first_order_xmas_share_mean_percent": round(100 * float(s["first_order_xmas_share"].mean()), 2),
            "uk_share_percent": round(100 * float(s["uk"].mean()), 2),
        })
    out["cohort_365"] = rows

    main_pool["q"] = main_pool["fd"].dt.quarter
    quarters = {}
    for q, s in main_pool.groupby("q"):
        quarters[f"Q{q}"] = {"customers": int(len(s)), "rep365_percent": round(100 * s["rep365"].mean(), 2),
                             "repeat_customers": int(s["rep365"].sum()), "net365_median": round(float(s["net365"].median()), 2)}
    out["quarter_365"] = quarters
    q2, q4 = main_pool[main_pool["q"] == 2], main_pool[main_pool["q"] == 4]
    out["q4_vs_q2"] = two_prop(q4["rep365"], q2["rep365"])
    mar, nov = main_pool[main_pool["cohort"] == "2010-03"], main_pool[main_pool["cohort"] == "2010-11"]
    out["nov_vs_mar"] = two_prop(nov["rep365"], mar["rep365"])

    # 年度趋势：3–6 月首购，2011 vs 2010 的 180 天复购率
    y10 = c[(c["fd"] >= "2010-03-01") & (c["fd"] <= "2010-06-30") & c["observable180"]]["rep180"]
    y11 = c[(c["fd"] >= "2011-03-01") & (c["fd"] <= "2011-06-30") & c["observable180"]]["rep180"]
    out["trend_180_mar_jun_2011_vs_2010"] = two_prop(y11, y10)

    # 机制候选 1：Q4 新客首单多为圣诞品、一次性采购
    q4 = q4.assign(has_xmas=q4["first_order_xmas_share"] > 0)
    out["q4_xmas_vs_none"] = two_prop(q4[q4["has_xmas"]]["rep365"], q4[~q4["has_xmas"]]["rep365"])
    out["q4_has_xmas_share_percent"] = round(100 * float(q4["has_xmas"].mean()), 2)
    q2x = main_pool[main_pool["q"] == 2]
    out["q2_has_xmas_share_percent"] = round(100 * float((q2x["first_order_xmas_share"] > 0).mean()), 2)

    # 机制候选 2：Q4 新客首单金额更小
    med = float(main_pool["first_order_value"].median())
    out["first_order_value_median_all"] = round(med, 2)
    out["first_order_value_median_q2"] = round(float(q2["first_order_value"].median()), 2)
    out["first_order_value_median_q4"] = round(float(q4["first_order_value"].median()), 2)
    big_q4 = q4[q4["first_order_value"] >= med]["rep365"]
    big_q2 = q2[q2["first_order_value"] >= med]["rep365"]
    out["q4_vs_q2_first_order_above_median"] = two_prop(big_q4, big_q2)

    # 机制候选 3：国家结构
    out["q4_vs_q2_uk_only"] = two_prop(q4[q4["uk"] == True]["rep365"], q2[q2["uk"] == True]["rep365"])  # noqa: E712

    # 给 skill 的 cohort_retention 算子准备输入（购买发票级）
    buys[["CustomerID", "date"]].rename(columns={"date": "Date"}).to_csv(OUT / "purchase_events.csv", index=False)
    c.reset_index().to_csv(OUT / "customer_cohorts.csv", index=False)
    (OUT / "analysis_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
