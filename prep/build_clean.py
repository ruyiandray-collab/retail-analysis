"""把 UCI Online Retail II 原始明细清洗成客户级分析用的行表。

清洗口径与 data-analysis skill 自带案例 (examples/case_study/build_dataset.py) 完全一致，
这样清洗后的净收入可以和案例公开的 18,928,551.86 对账：
1. 剔除非商品代码（邮费、手工调整、坏账等）；
2. 只保留 Quantity != 0 且 Price > 0；
3. 按 Invoice+StockCode+Quantity+日期+Price+客户ID 去完全重复行。

输出 data/clean_lines.csv（含缺客户 ID 的行，由各分析自行过滤）和 data/clean_log.json。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = [ROOT / "data" / "Year_2009-2010.csv", ROOT / "data" / "Year_2010-2011.csv"]
NON_PRODUCT_CODES = {
    "M", "D", "POST", "DOT", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "PADS", "S", "B", "ADJUST", "ADJUST2", "TEST001", "TEST002",
}
DUPLICATE_KEY = ["Invoice", "StockCode", "Quantity", "Date", "Price", "CustomerID"]


def main() -> None:
    frame = pd.concat([pd.read_csv(p, dtype={"Invoice": str, "StockCode": str}).assign(Sheet=i) for i, p in enumerate(RAW)], ignore_index=True)
    log: dict = {"raw_rows": len(frame)}
    frame = frame.rename(columns={"Customer ID": "CustomerID"})
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"])
    frame["Date"] = frame["InvoiceDate"].dt.normalize()

    non_product = frame["StockCode"].isin(NON_PRODUCT_CODES)
    log["non_product_rows"] = int(non_product.sum())
    frame = frame[~non_product]

    valid = (frame["Quantity"] != 0) & (frame["Price"] > 0)
    log["zero_value_rows"] = int((~valid).sum())
    frame = frame[valid].copy()

    dup = frame.duplicated(subset=DUPLICATE_KEY, keep="first")
    log["duplicate_rows"] = int(dup.sum())
    # 两个 sheet 在 2010-12-01..12-09 完全重叠（同一批行存了两份）。拆开看：去掉第一个 sheet 的重叠副本后还剩多少真正的重复记录
    overlap_copy = (frame["Sheet"] == 0) & (frame["Date"] >= "2010-12-01")
    log["true_duplicate_rows"] = int(frame[~overlap_copy].duplicated(subset=DUPLICATE_KEY, keep="first").sum())
    log["sheet_overlap_duplicate_rows"] = log["duplicate_rows"] - log["true_duplicate_rows"]
    frame = frame[~dup].copy()

    frame["Amount"] = frame["Quantity"] * frame["Price"]
    frame["IsReturn"] = frame["Quantity"] < 0
    log["clean_rows"] = len(frame)
    log["net_revenue"] = round(float(frame["Amount"].sum()), 2)
    log["missing_customer_rows"] = int(frame["CustomerID"].isna().sum())
    log["missing_customer_share_percent"] = round(100 * log["missing_customer_rows"] / len(frame), 2)
    log["date_min"] = str(frame["Date"].min().date())
    log["date_max"] = str(frame["Date"].max().date())

    frame["CustomerID"] = frame["CustomerID"].astype("Int64")
    cols = ["Invoice", "StockCode", "Quantity", "Price", "Amount", "IsReturn", "InvoiceDate", "Date", "CustomerID", "Country"]
    frame[cols].to_csv(ROOT / "data" / "clean_lines.csv", index=False)
    (ROOT / "data" / "clean_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
