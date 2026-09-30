# -*- coding: utf-8 -*-
"""
UCI Online Retail II —— 客户价值 & 沉睡高价值客户分析
问题：截至 2011-12-09，哪些客户群贡献主要收入？高价值客户里多少已很久没下单？下季度召回优先级？
输出：metrics.json（关键数字）、recall_list.csv（召回名单）、report.html 由 build_report() 生成
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
OUT = Path(__file__).resolve().parent
SNAP = pd.Timestamp("2011-12-10")          # 观察日 = 数据最后一天 2011-12-09 的次日
CUT_12M = pd.Timestamp("2010-12-10")      # 近 12 个月窗口起点

# ---------------------------------------------------------------- 1. 读取与清洗
def load():
    a = pd.read_csv(DATA / "Year_2009-2010.csv", dtype={"Invoice": str, "StockCode": str})
    b = pd.read_csv(DATA / "Year_2010-2011.csv", dtype={"Invoice": str, "StockCode": str})
    for d in (a, b):
        d["InvoiceDate"] = pd.to_datetime(d["InvoiceDate"])
    log = {"raw_rows": int(len(a) + len(b))}
    # 两个 sheet 在 2010-12-01 ~ 2010-12-09 完全重叠（发票集合一致），只保留第二个 sheet 的这段
    a = a[a["InvoiceDate"] < "2010-12-01"]
    df = pd.concat([a, b], ignore_index=True)
    log["after_overlap_rows"] = int(len(df))
    n0 = len(df)
    df = df.drop_duplicates()
    log["exact_dup_removed"] = int(n0 - len(df))
    # 非商品行：邮费、手工调整、银行手续费、礼品券、测试等
    non_product = {"POST", "DOT", "M", "m", "C2", "D", "S", "BANK CHARGES", "AMAZONFEE",
                   "PADS", "CRUK", "B", "SP1002"}
    is_np = (df["StockCode"].isin(non_product)
             | df["StockCode"].str.startswith(("ADJUST", "TEST", "gift_0001")))
    log["non_product_rows_removed"] = int(is_np.sum())
    df = df[~is_np]
    bad = df["Invoice"].str.startswith("A") | (df["Price"] <= 0)
    log["zero_price_or_baddebt_removed"] = int(bad.sum())
    df = df[~bad].copy()
    df["Revenue"] = df["Quantity"] * df["Price"]      # 退货(C 开头)为负，得到净收入
    df["is_cancel"] = df["Invoice"].str.startswith("C")
    log["clean_rows"] = int(len(df))
    return df, log


# ---------------------------------------------------------------- 2. 客户级指标
def customer_table(df, snap, start=None):
    d = df[df["InvoiceDate"] < snap]
    if start is not None:
        d = d[d["InvoiceDate"] >= start]
    d = d[d["Customer ID"].notna()]
    buys = d[~d["is_cancel"]]
    g = d.groupby("Customer ID")
    t = pd.DataFrame({
        "monetary": g["Revenue"].sum(),
        "country": g["Country"].agg(lambda s: s.mode().iat[0]),
    })
    gb = buys.groupby("Customer ID")
    t["first"] = gb["InvoiceDate"].min()
    t["last"] = gb["InvoiceDate"].max()
    t["frequency"] = gb["Invoice"].nunique()
    t = t.dropna(subset=["last"])
    t["recency"] = (snap - t["last"]).dt.days
    t["tenure"] = (snap - t["first"]).dt.days
    # 平均下单间隔（天），仅 >=2 单客户
    t["avg_gap"] = np.where(t["frequency"] > 1,
                            (t["last"] - t["first"]).dt.days / (t["frequency"] - 1), np.nan)
    return t


def main():
    df, log = load()
    M = {"clean": log}

    total_rev = df["Revenue"].sum()
    rev_12m_all = df.loc[df["InvoiceDate"] >= CUT_12M, "Revenue"].sum()
    known = df["Customer ID"].notna()
    M["total_net_revenue"] = round(total_rev, 0)
    M["revenue_12m"] = round(rev_12m_all, 0)
    M["share_rev_with_id"] = round(df.loc[known, "Revenue"].sum() / total_rev, 4)
    M["share_rev_with_id_12m"] = round(
        df.loc[known & (df["InvoiceDate"] >= CUT_12M), "Revenue"].sum() / rev_12m_all, 4)

    # 全历史（2009-12-01 ~ 2011-12-09）客户表，价值按全期净收入衡量
    c = customer_table(df, SNAP)
    c = c[c["monetary"] > 0].copy()        # 去掉净额<=0（全退货）的客户
    # 近 12 个月收入
    c12 = df[(df["InvoiceDate"] >= CUT_12M) & known].groupby("Customer ID")["Revenue"].sum()
    c["rev_12m"] = c12.reindex(c.index).fillna(0)
    # 前 12 个月（2009-12 ~ 2010-12）收入
    cprev = df[(df["InvoiceDate"] < CUT_12M) & known].groupby("Customer ID")["Revenue"].sum()
    c["rev_prev12m"] = cprev.reindex(c.index).fillna(0)
    M["n_customers"] = int(len(c))

    # ---- 2a. 帕累托：价值十分位
    c = c.sort_values("monetary", ascending=False)
    c["cum_share"] = c["monetary"].cumsum() / c["monetary"].sum()
    n = len(c)
    rank_pct = np.arange(1, n + 1) / n
    c["value_tier"] = pd.cut(rank_pct, [0, 0.01, 0.05, 0.20, 0.50, 1.0],
                             labels=["Top1%", "Top1-5%", "Top5-20%", "Top20-50%", "Bottom50%"])
    tier = c.groupby("value_tier", observed=True).agg(
        customers=("monetary", "size"), revenue=("monetary", "sum"),
        min_rev=("monetary", "min"), median_freq=("frequency", "median"),
        median_recency=("recency", "median"))
    tier["rev_share"] = tier["revenue"] / c["monetary"].sum()
    M["tiers"] = tier.reset_index().round(4).to_dict("records")
    M["top20_share"] = round(float(tier.loc[["Top1%", "Top1-5%", "Top5-20%"], "rev_share"].sum()), 4)
    M["top1_share"] = round(float(tier.loc["Top1%", "rev_share"]), 4)
    M["bottom50_share"] = round(float(tier.loc["Bottom50%", "rev_share"]), 4)
    M["hv_threshold"] = round(float(tier.loc["Top5-20%", "min_rev"]), 0)

    # ---- 2b. RFM 分群（全期）
    r = pd.qcut(c["recency"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    f = pd.qcut(c["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    m = pd.qcut(c["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    c["R"], c["F"], c["M"] = r, f, m
    fm = (c["F"] + c["M"]) / 2

    def seg(row_r, row_fm):
        if row_r >= 4 and row_fm >= 4:
            return "冠军客户"
        if row_r >= 3 and row_fm >= 3:
            return "忠诚客户"
        if row_r <= 2 and row_fm >= 4:
            return "高价值流失风险"
        if row_r <= 2 and row_fm >= 3:
            return "中价值沉睡"
        if row_r >= 4 and row_fm < 3:
            return "新客/低频活跃"
        if row_r == 3:
            return "需关注"
        return "低价值流失"
    c["segment"] = [seg(a, b) for a, b in zip(c["R"], fm)]
    sg = c.groupby("segment").agg(customers=("monetary", "size"), revenue=("monetary", "sum"),
                                  rev_12m=("rev_12m", "sum"),
                                  median_recency=("recency", "median"),
                                  median_freq=("frequency", "median"),
                                  median_monetary=("monetary", "median"))
    sg["cust_share"] = sg["customers"] / n
    sg["rev_share"] = sg["revenue"] / c["monetary"].sum()
    sg["rev12_share"] = sg["rev_12m"] / c["rev_12m"].sum()
    sg = sg.sort_values("revenue", ascending=False)
    M["segments"] = sg.reset_index().round(4).to_dict("records")

    # ---- 2c. 国家
    ctry = c.groupby(np.where(c["country"] == "United Kingdom", "英国", "海外"))["monetary"].agg(["size", "sum"])
    ctry["share"] = ctry["sum"] / ctry["sum"].sum()
    M["uk_vs_intl"] = ctry.reset_index().rename(columns={"index": "region"}).round(4).to_dict("records")
    top_ctry = (c[c["country"] != "United Kingdom"].groupby("country")["monetary"].sum()
                .sort_values(ascending=False).head(6))
    M["top_intl_countries"] = {k: round(v, 0) for k, v in top_ctry.items()}

    # ---- 3. 高价值客户 = 全期净收入 Top 20%
    hv = c[c["value_tier"].isin(["Top1%", "Top1-5%", "Top5-20%"])].copy()
    M["hv_n"] = int(len(hv))
    bins = [-1, 30, 90, 180, 365, 10_000]
    labels = ["≤30天", "31-90天", "91-180天", "181-365天", ">365天"]
    hv["rec_bucket"] = pd.cut(hv["recency"], bins, labels=labels)
    rb = hv.groupby("rec_bucket", observed=False).agg(customers=("monetary", "size"),
                                                      revenue=("monetary", "sum"),
                                                      rev_12m=("rev_12m", "sum"),
                                                      rev_prev12m=("rev_prev12m", "sum"))
    rb["cust_share"] = rb["customers"] / len(hv)
    rb["rev_share_of_hv"] = rb["revenue"] / hv["monetary"].sum()
    M["hv_recency"] = rb.reset_index().round(4).to_dict("records")
    M["hv_dormant90_n"] = int((hv["recency"] > 90).sum())
    M["hv_dormant90_share"] = round(float((hv["recency"] > 90).mean()), 4)
    M["hv_dormant90_rev"] = round(float(hv.loc[hv["recency"] > 90, "monetary"].sum()), 0)
    M["hv_dormant90_rev_prev12m"] = round(float(hv.loc[hv["recency"] > 90, "rev_prev12m"].sum()), 0)
    M["hv_dormant180_n"] = int((hv["recency"] > 180).sum())
    # 相对沉睡：距上次下单 > 2 倍自身平均间隔 且 > 60 天
    rel = (hv["frequency"] > 1) & (hv["recency"] > 2 * hv["avg_gap"]) & (hv["recency"] > 60)
    M["hv_rel_dormant_n"] = int(rel.sum())
    hv["overdue_ratio"] = hv["recency"] / hv["avg_gap"]

    # ---- 4. 历史回流率回测：以 2010-12-10 为观察日，看各沉睡段在之后 90 天 / 12 个月是否再下单
    snap0 = CUT_12M
    c0 = customer_table(df, snap0)
    c0 = c0[c0["monetary"] > 0].sort_values("monetary", ascending=False)
    c0["hv"] = np.arange(1, len(c0) + 1) / len(c0) <= 0.20
    fut = df[(df["InvoiceDate"] >= snap0) & df["Customer ID"].notna() & ~df["is_cancel"]]
    first_after = fut.groupby("Customer ID")["InvoiceDate"].min()
    rev_after = df[(df["InvoiceDate"] >= snap0) & df["Customer ID"].notna()].groupby("Customer ID")["Revenue"].sum()
    c0["back_90"] = first_after.reindex(c0.index) < snap0 + pd.Timedelta(days=90)
    c0["back_365"] = first_after.reindex(c0.index).notna()
    c0["rev_after"] = rev_after.reindex(c0.index).fillna(0)
    bins0 = [-1, 30, 90, 180, 10_000]
    labels0 = ["≤30天", "31-90天", "91-180天", ">180天"]
    c0["rec_bucket"] = pd.cut(c0["recency"], bins0, labels=labels0)
    bt = c0.groupby(["hv", "rec_bucket"], observed=False).agg(
        customers=("monetary", "size"), back_90=("back_90", "mean"),
        back_365=("back_365", "mean"), avg_rev_after=("rev_after", "mean"))
    M["backtest"] = bt.reset_index().round(4).to_dict("records")

    # ---- 5. 召回名单与优先级（高价值 & 距上次下单 > 90 天）
    rc = hv[hv["recency"] > 90].copy()
    # 用回测中「高价值」各 recency 段的 12 个月回流率作为自然回流概率参考
    bt_hv = bt.loc[True]
    def p_back(rec):
        if rec <= 180:
            return float(bt_hv.loc["91-180天", "back_365"])
        return float(bt_hv.loc[">180天", "back_365"])
    rc["hist_back_rate"] = rc["recency"].map(p_back)
    # 年化价值：客户在活跃期间的年均净收入
    active_years = ((rc["last"] - rc["first"]).dt.days.clip(lower=0) + 30) / 365
    rc["annual_value"] = rc["monetary"] / active_years.clip(lower=1)
    # 优先级
    def prio(row):
        if row["recency"] <= 180 and row["frequency"] >= 3:
            return "P1"
        if row["recency"] <= 365 and row["frequency"] >= 3:
            return "P2"
        if row["recency"] <= 180:
            return "P2"
        return "P3"
    rc["priority"] = rc.apply(prio, axis=1)
    rc["score"] = rc["annual_value"] * rc["hist_back_rate"]
    rc = rc.sort_values(["priority", "score"], ascending=[True, False])
    pr = rc.groupby("priority").agg(customers=("monetary", "size"),
                                    hist_revenue=("monetary", "sum"),
                                    annual_value=("annual_value", "sum"),
                                    median_recency=("recency", "median"),
                                    median_freq=("frequency", "median"),
                                    uk=("country", lambda s: (s == "United Kingdom").mean()))
    M["priority"] = pr.reset_index().round(3).to_dict("records")
    out = rc.reset_index()[["Customer ID", "priority", "country", "recency", "last", "frequency",
                            "monetary", "rev_12m", "rev_prev12m", "avg_gap", "annual_value",
                            "hist_back_rate", "score"]]
    out["Customer ID"] = out["Customer ID"].astype(int)
    out["last"] = out["last"].dt.date
    out = out.round(2)
    out.to_csv(OUT / "recall_list.csv", index=False, encoding="utf-8-sig")
    M["recall_top15"] = out.head(15).astype(str).to_dict("records")

    # 高价值中最近才流失的「冠军→沉睡」：近 12 个月前曾是主力、近期骤降
    M["segments_hv_cross"] = hv.groupby("segment").size().to_dict()

    # 月度收入（趋势背景）
    mon = df.set_index("InvoiceDate")["Revenue"].resample("MS").sum()
    M["monthly"] = {k.strftime("%Y-%m"): round(v, 0) for k, v in mon.items()}
    # 活跃客户数月度
    act = (df[df["Customer ID"].notna() & ~df["is_cancel"]]
           .groupby(pd.Grouper(key="InvoiceDate", freq="MS"))["Customer ID"].nunique())
    M["monthly_active"] = {k.strftime("%Y-%m"): int(v) for k, v in act.items()}

    (OUT / "metrics.json").write_text(json.dumps(M, ensure_ascii=False, indent=1, default=str),
                                      encoding="utf-8")
    return M


# ---------------------------------------------------------------- 6. 生成 HTML 报告
def fmt_gbp(x):
    x = float(x)
    if abs(x) >= 1e6:
        return f"£{x/1e6:.2f}M"
    if abs(x) >= 1e3:
        return f"£{x/1e3:.0f}k"
    return f"£{x:,.0f}"


def pct(x, d=1):
    return f"{float(x)*100:.{d}f}%"


def hbar_svg(rows, max_v, fmt, color="var(--accent)", w=560, label_w=120, bar_h=22, gap=10):
    """rows: [(label, value, note)] -> 水平条形图 SVG"""
    h = len(rows) * (bar_h + gap) + 4
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i, (lab, v, note) in enumerate(rows):
        y = i * (bar_h + gap)
        bw = max(1.0, (w - label_w - 190) * float(v) / max_v)
        out.append(f'<text x="{label_w-8}" y="{y+bar_h*0.7}" text-anchor="end" class="lab">{lab}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="3" fill="{color}"/>')
        out.append(f'<text x="{label_w+bw+6:.1f}" y="{y+bar_h*0.7}" class="val">{fmt(v)}{note}</text>')
    out.append("</svg>")
    return "".join(out)


def pair_svg(rows, w=600, label_w=110, bar_h=14):
    """rows: [(label, a, b)] 两条对比条：客户占比 vs 收入占比"""
    step = bar_h * 2 + 14
    h = len(rows) * step + 30
    sc = (w - label_w - 70)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">',
           f'<rect x="{label_w}" y="2" width="12" height="10" fill="var(--muted-bar)"/>'
           f'<text x="{label_w+16}" y="11" class="val">客户数占比</text>'
           f'<rect x="{label_w+110}" y="2" width="12" height="10" fill="var(--accent)"/>'
           f'<text x="{label_w+126}" y="11" class="val">收入占比</text>']
    for i, (lab, a, b) in enumerate(rows):
        y = 26 + i * step
        out.append(f'<text x="{label_w-8}" y="{y+bar_h+4}" text-anchor="end" class="lab">{lab}</text>')
        out.append(f'<rect x="{label_w}" y="{y}" width="{max(1,sc*a):.1f}" height="{bar_h}" rx="2" fill="var(--muted-bar)"/>')
        out.append(f'<text x="{label_w+max(1,sc*a)+5:.1f}" y="{y+bar_h-3}" class="val">{pct(a)}</text>')
        out.append(f'<rect x="{label_w}" y="{y+bar_h+2}" width="{max(1,sc*b):.1f}" height="{bar_h}" rx="2" fill="var(--accent)"/>')
        out.append(f'<text x="{label_w+max(1,sc*b)+5:.1f}" y="{y+2*bar_h-1}" class="val strong">{pct(b)}</text>')
    out.append("</svg>")
    return "".join(out)


def month_svg(monthly, w=640, h=200):
    ks = list(monthly.keys())
    vs = [float(monthly[k]) for k in ks]
    mx = max(vs)
    pad_l, pad_b = 44, 28
    bw = (w - pad_l) / len(ks)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for t in (0.5, 1.0):
        y = h - pad_b - (h - pad_b - 10) * t * 1.4e6 / mx
        out.append(f'<line x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{pad_l-4}" y="{y+4:.1f}" text-anchor="end" class="val">£{t*1.4:.1f}M</text>')
    for i, (k, v) in enumerate(zip(ks, vs)):
        bh = (h - pad_b - 10) * v / mx
        x = pad_l + i * bw
        fill = "var(--accent)" if k[5:] in ("09", "10", "11") else "var(--muted-bar)"
        op = ' opacity="0.45"' if k == "2011-12" else ""
        out.append(f'<rect x="{x+2:.1f}" y="{h-pad_b-bh:.1f}" width="{bw-4:.1f}" height="{bh:.1f}" fill="{fill}"{op}/>')
        if k[5:] in ("01", "07") or k == "2009-12":
            out.append(f'<text x="{x+bw/2:.1f}" y="{h-10}" text-anchor="middle" class="val">{k}</text>')
    out.append("</svg>")
    return "".join(out)


def build_report(M):
    tiers = {t["value_tier"]: t for t in M["tiers"]}
    hvr = M["hv_recency"]
    bt = M["backtest"]
    bt_hv = {b["rec_bucket"]: b for b in bt if str(b["hv"]) == "True"}
    bt_lo = {b["rec_bucket"]: b for b in bt if str(b["hv"]) == "False"}
    pr = {p["priority"]: p for p in M["priority"]}
    seg = M["segments"]
    segd = {s["segment"]: s for s in seg}
    n_cust = M["n_customers"]
    risk = segd["高价值流失风险"]

    tier_rows = [(lab, tiers[k]["customers"] / n_cust, tiers[k]["rev_share"]) for lab, k in
                 [("Top 1%", "Top1%"), ("Top 1–5%", "Top1-5%"), ("Top 5–20%", "Top5-20%"),
                  ("Top 20–50%", "Top20-50%"), ("后 50%", "Bottom50%")]]
    tier_svg = pair_svg(tier_rows)

    rec_rows = [(r["rec_bucket"], r["customers"], f' 人 · 两年净收入 {fmt_gbp(r["revenue"])}') for r in hvr]
    rec_svg = hbar_svg(rec_rows, max(r["customers"] for r in hvr), lambda v: f"{int(v)}", label_w=90)

    order = ["≤30天", "31-90天", "91-180天", ">180天"]
    bt_rows_html = ""
    for b in order:
        h_, l_ = bt_hv[b], bt_lo[b]
        bt_rows_html += (f"<tr><td>{b}</td><td class=num>{int(h_['customers'])}</td>"
                         f"<td class=num>{pct(h_['back_90'])}</td><td class=num><b>{pct(h_['back_365'])}</b></td>"
                         f"<td class=num>{fmt_gbp(h_['avg_rev_after'])}</td>"
                         f"<td class=num>{pct(l_['back_365'])}</td></tr>")
    bt_svg = hbar_svg([(b, bt_hv[b]["back_365"], "") for b in order], 1.0, lambda v: pct(v, 0), label_w=90)

    seg_desc = {"冠军客户": "近期买过 + 高频高额", "忠诚客户": "较近期 + 中高频/额",
                "高价值流失风险": "曾高频高额，但已很久没来", "中价值沉睡": "中等价值，已很久没来",
                "低价值流失": "低频低额且很久没来", "新客/低频活跃": "近期来过但频次/金额低",
                "需关注": "近期度一般、价值偏低"}
    seg_html = "".join(
        f"<tr{' class=hl' if s['segment'] in ('冠军客户', '高价值流失风险') else ''}><td>{s['segment']}</td>"
        f"<td class=muted>{seg_desc.get(s['segment'], '')}</td>"
        f"<td class=num>{int(s['customers']):,}</td><td class=num>{pct(s['cust_share'])}</td>"
        f"<td class=num><b>{pct(s['rev_share'])}</b></td><td class=num>{pct(s['rev12_share'])}</td>"
        f"<td class=num>{int(float(s['median_recency']))}</td><td class=num>{float(s['median_freq']):.0f}</td></tr>"
        for s in seg)

    pr_desc = {"P1": "距上次下单 91–180 天，且历史 ≥3 单",
               "P2": "181–365 天且 ≥3 单；或 91–180 天但仅 1–2 单",
               "P3": "超过 365 天未下单；或 181–365 天且仅 1–2 单"}
    pr_act = {"P1": "客户经理一对一电话/邮件，先问旺季为何没补货，再配合常购品类新品目录与限时返利；季度第一周启动",
              "P2": "自动化个性化邮件 + 阶梯返利；未响应者 3 周后二次触达",
              "P3": "低成本批量邮件 / 流失原因问卷，不投入人工"}
    pr_html = "".join(
        f"<tr{' class=hl' if k == 'P1' else ''}><td><b>{k}</b></td><td>{pr_desc[k]}</td>"
        f"<td class=num>{int(pr[k]['customers'])}</td><td class=num>{fmt_gbp(pr[k]['hist_revenue'])}</td>"
        f"<td class=num>{fmt_gbp(pr[k]['annual_value'])}</td><td class=num>{int(float(pr[k]['median_recency']))}</td>"
        f"<td class=num>{float(pr[k]['median_freq']):.0f}</td><td>{pr_act[k]}</td></tr>" for k in ("P1", "P2", "P3"))

    top_html = "".join(
        f"<tr><td>{r['Customer ID']}</td><td>{r['country']}</td><td class=num>{r['recency']}</td>"
        f"<td>{r['last']}</td><td class=num>{float(r['frequency']):.0f}</td>"
        f"<td class=num>{float(r['avg_gap']):.0f}</td>"
        f"<td class=num>£{float(r['monetary']):,.0f}</td><td class=num>£{float(r['annual_value']):,.0f}</td></tr>"
        for r in M["recall_top15"][:10])

    uk = {u["region"]: u for u in M["uk_vs_intl"]}
    intl = "、".join(f"{k} {fmt_gbp(v)}" for k, v in list(M["top_intl_countries"].items())[:4])
    cl = M["clean"]
    p1 = pr["P1"]
    dormant_rev12 = sum(float(r["rev_12m"]) for r in hvr[2:])
    healthy90 = sum(float(r["cust_share"]) for r in hvr[:2])
    p1_back = float(bt_hv["91-180天"]["back_365"])

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>老客召回优先级分析</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e1da;--card:#fff;--accent:#2f6f5e;--accent-soft:#e6f0ec;
--warn:#b4532a;--warn-soft:#fbeee6;--muted-bar:#c9c6bd}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#17181a;--fg:#ececec;--muted:#a0a0a6;--line:#2e3033;
--card:#1f2123;--accent:#5fb39b;--accent-soft:#1f3a33;--warn:#e38a5f;--warn-soft:#3a2720;--muted-bar:#55565a}}}}
:root[data-theme="dark"]{{--bg:#17181a;--fg:#ececec;--muted:#a0a0a6;--line:#2e3033;--card:#1f2123;--accent:#5fb39b;
--accent-soft:#1f3a33;--warn:#e38a5f;--warn-soft:#3a2720;--muted-bar:#55565a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:920px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:26px;margin:0 0 4px;line-height:1.35}} h2{{font-size:19px;margin:40px 0 12px;padding-top:12px;border-top:1px solid var(--line)}}
.sub{{color:var(--muted);font-size:13px}}
.tldr{{background:var(--accent-soft);border-left:4px solid var(--accent);padding:14px 18px;border-radius:6px;margin:20px 0}}
.tldr ul{{margin:6px 0 0;padding-left:20px}} .tldr li{{margin:4px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}
.kpi .v{{font-size:24px;font-weight:650}} .kpi .l{{font-size:12.5px;color:var(--muted)}}
.kpi.warn .v{{color:var(--warn)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin:8px 0}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12.5px}} td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
tr.hl td{{background:var(--accent-soft)}} .muted{{color:var(--muted)}}
.tbl{{overflow-x:auto}}
.chart{{width:100%;height:auto;max-width:640px;display:block;margin:6px 0 4px}}
.chart .lab{{font-size:12.5px;fill:var(--fg)}} .chart .val{{font-size:11.5px;fill:var(--muted)}} .chart .strong{{fill:var(--fg);font-weight:600}}
.chart .grid{{stroke:var(--line)}}
.cap{{font-size:12.5px;color:var(--muted)}}
code{{font-size:13px}}
</style></head><body><main>
<h1>哪些客户撑起了收入，哪些高价值老客该优先召回</h1>
<div class=sub>数据：UCI Online Retail II，2009-12-01 至 2011-12-09 · 观察日 2011-12-10 · 金额为扣除退货后的净收入（英镑）</div>

<div class=tldr><b>结论先行</b><ul>
<li><b>收入高度集中：</b>净收入前 20% 的客户（{M['hv_n']:,} 人，两年累计净额 ≥ £{M['hv_threshold']:,.0f}）贡献了有 ID 客户收入的 <b>{pct(M['top20_share'])}</b>；其中前 1%（{tiers['Top1%']['customers']} 人）就占 <b>{pct(M['top1_share'])}</b>。后 50% 的客户合计只占 {pct(M['bottom50_share'])}。</li>
<li><b>高价值客户中有 {M['hv_dormant90_n']} 人（{pct(M['hv_dormant90_share'])}）已超过 90 天没下单</b>，也就是错过了 9–11 月全年最旺的采购季。这批人两年累计净收入 {fmt_gbp(M['hv_dormant90_rev'])}；其中 {M['hv_dormant180_n']} 人已超过 180 天。</li>
<li><b>180 天是回流的分水岭：</b>拿一年前（2010-12-10）做回测，沉睡 91–180 天的高价值客户，之后 12 个月内有 {pct(p1_back, 0)} 自然回来；超过 180 天的只有 {pct(bt_hv['>180天']['back_365'], 0)}。</li>
<li><b>下季度召回首选 P1：{int(p1['customers'])} 人</b>，即“91–180 天未下单、历史 ≥3 单”的高价值客户，年化采购额合计约 {fmt_gbp(p1['annual_value'])}。他们还在可挽回窗口内，但每拖一个月就离 180 天更近一步。</li>
</ul></div>

<div class=kpis>
<div class=kpi><div class=v>{pct(M['top20_share'])}</div><div class=l>前 20% 客户的收入占比</div></div>
<div class=kpi><div class=v>{M['hv_n']:,}</div><div class=l>高价值客户数（前 20%）</div></div>
<div class="kpi warn"><div class=v>{M['hv_dormant90_n']}</div><div class=l>其中 &gt;90 天未下单（{pct(M['hv_dormant90_share'])}）</div></div>
<div class="kpi warn"><div class=v>{int(p1['customers'])}</div><div class=l>P1 优先召回人数</div></div>
</div>

<h2>1. 收入由谁贡献：典型的“少数大客户”结构</h2>
<p>按两年累计净收入给 {n_cust:,} 位有 ID 的客户排序，收入集中度很高：</p>
{tier_svg}
<p class=cap>图 1 各价值分层的客户数占比与收入占比。前 20% 门槛为两年累计净额 £{M['hv_threshold']:,.0f}，前 1% 门槛 £{float(tiers['Top1%']['min_rev']):,.0f}。</p>
<p>前 1% 客户中位下单 {float(tiers['Top1%']['median_freq']):.0f} 次，中位 {float(tiers['Top1%']['median_recency']):.0f} 天前刚下过单，是一批高频的批发型买家，目前大多仍很活跃。
地域上，英国客户贡献 {pct(uk['英国']['share'])} 的客户收入，海外占 {pct(uk['海外']['share'])}，主要来自 {intl}。</p>

<p>再用 RFM（最近一次下单 R、下单次数 F、净金额 M，各按五分位打分）把客户分成 7 群：</p>
<div class=tbl><table><tr><th>客户群</th><th>特征</th><th class=num>客户数</th><th class=num>客户占比</th><th class=num>两年收入占比</th><th class=num>近 12 月收入占比</th><th class=num>中位未下单天数</th><th class=num>中位单数</th></tr>
{seg_html}</table></div>
<p><b>“冠军客户”一个群就贡献约七成收入</b>（两年 {pct(segd['冠军客户']['rev_share'])}，近 12 个月 {pct(segd['冠军客户']['rev12_share'])}），加上“忠诚客户”合计约 85%。
需要警惕的是“高价值流失风险”群：{int(risk['customers'])} 人，两年贡献 {pct(risk['rev_share'])}，但近 12 个月只剩 {pct(risk['rev12_share'])}，收入正在从这群人身上流走。</p>

<h2>2. 高价值客户里，有多少已经很久没下单</h2>
<p>{M['hv_n']:,} 位高价值客户（前 20%）按距上次下单天数分布：</p>
{rec_svg}
<p class=cap>图 2 高价值客户按“距上次下单天数”分组（观察日 2011-12-10）。</p>
<ul>
<li>{pct(healthy90, 0)} 的高价值客户在 90 天内下过单，整体健康。</li>
<li><b>{M['hv_dormant90_n']} 人（{pct(M['hv_dormant90_share'])}）超过 90 天没下单。</b>这家公司以礼品、节日装饰类批发为主，9–11 月是全年最旺季（见图 4），旺季完全不来补货是很强的流失信号。</li>
<li>这 {M['hv_dormant90_n']} 人在前一年（2009-12 至 2010-12）贡献了 {fmt_gbp(M['hv_dormant90_rev_prev12m'])}，近 12 个月只剩 {fmt_gbp(dormant_rev12)}，下滑已经发生。</li>
<li>换一个相对口径：“距上次下单已超过自己平均下单间隔的 2 倍，且 &gt;60 天”，掉队的高价值客户为 {M['hv_rel_dormant_n']} 人，与 90 天口径量级一致，结论不依赖阈值的选择。</li>
</ul>

<h2>3. 沉睡多久还救得回来：用历史数据回测</h2>
<p>把观察日倒退一年到 2010-12-10，按当时的沉睡时长分组，看这些客户在随后 90 天 / 12 个月内是否自然回来下单。这相当于“不干预”情况下的基线：</p>
{bt_svg}
<p class=cap>图 3 高价值客户按当时的沉睡时长分组，之后 12 个月内再次下单的比例。</p>
<div class=tbl><table><tr><th>当时沉睡时长</th><th class=num>高价值客户数</th><th class=num>90 天内回流</th><th class=num>12 个月内回流</th><th class=num>之后 12 个月人均净收入</th><th class=num>对照：非高价值客户 12 个月回流</th></tr>
{bt_rows_html}</table></div>
<p><b>解读：</b>沉睡 91–180 天的高价值客户，多数（{pct(p1_back, 0)}）仍会回来，人均还能带来 {fmt_gbp(bt_hv['91-180天']['avg_rev_after'])}；超过 180 天后，回流率降到 {pct(bt_hv['>180天']['back_365'], 0)}，人均只剩 {fmt_gbp(bt_hv['>180天']['avg_rev_after'])}。
所以召回资源应该集中在“刚沉睡、还没过 180 天”的人身上。另外，到 2012 年 1 月时 P1 客户会再多沉睡约 1 个月，其中一部分会跨过 180 天，<b>召回应在季度初尽早启动</b>。</p>

<h2>4. 召回名单与优先级</h2>
<p>召回池：高价值客户（前 20%）中距上次下单超过 90 天的 {M['hv_dormant90_n']} 人，按“可挽回程度 × 价值”分三档。完整名单见同目录 <code>recall_list.csv</code>（含客户 ID、国家、上次下单日期、单数、历史收入、年化价值、排序分）。</p>
<div class=tbl><table><tr><th>档位</th><th>规则</th><th class=num>人数</th><th class=num>两年净收入</th><th class=num>年化采购额合计</th><th class=num>中位未下单天数</th><th class=num>中位单数</th><th>建议动作</th></tr>
{pr_html}</table></div>
<p class=cap>年化采购额 = 客户两年净收入 ÷ 活跃年数（首单到末单，不足 1 年按 1 年计），表示“如果回来，一年大约值多少”。档内按 年化采购额 × 历史回流率 排序。</p>

<p><b>P1 名单前 10 位</b>（按排序分）：</p>
<div class=tbl><table><tr><th>客户 ID</th><th>国家</th><th class=num>未下单天数</th><th>上次下单</th><th class=num>历史单数</th><th class=num>平均间隔(天)</th><th class=num>两年净收入</th><th class=num>年化采购额</th></tr>
{top_html}</table></div>
<p>这些客户过去大多每 2–8 周下一单，现在已经 3–6 个月没有动静，远远偏离了他们自己的采购节奏，并不是本来就低频的客户。</p>

<h2>5. 建议</h2>
<ol>
<li><b>2012 Q1 召回以 P1 的 {int(p1['customers'])} 人为核心</b>，由客户经理逐一联系。先问清“为什么旺季没有补货”（换了供应商？价格？缺货？），再决定给什么激励，而不是直接群发优惠券。按历史基线约 {pct(p1_back, 0)} 的回流率，这批人对应的年化采购额约 {fmt_gbp(float(p1['annual_value']) * p1_back)}；召回的目标是在基线之上把回流率和回流后的采购额再往上推。</li>
<li><b>P2（{int(pr['P2']['customers'])} 人）用自动化个性化邮件 + 阶梯返利</b>，控制成本。<b>P3（{int(pr['P3']['customers'])} 人）</b>历史回流率只有 15% 左右，不建议投入人工，做一次流失原因问卷，把答案用于改进产品和服务。</li>
<li><b>一定要留对照组。</b>P1 客户即使不做任何动作，也有约七成会自己回来。如果不留对照，召回效果会被严重高估。建议 P1、P2 内各随机留出 15–20% 不触达，季度末比较两组的回流率与净收入差，得出真实增量，再决定下季度是否加大投入。</li>
<li><b>Q1 是淡季</b>（2011 年 1–4 月月收入只有当年 11 月的 34–48%），回流客户的首单可能偏小。考核建议看“是否恢复下单”和“回流后 90 天采购额”，不要只看首单金额。</li>
<li><b>建立常态预警：</b>对前 20% 客户，一旦距上次下单超过自身平均间隔 2 倍或超过 90 天，自动进入召回池，不要等到 180 天之后再处理。</li>
</ol>

<h2>6. 口径与局限</h2>
<ul class=cap>
<li>数据清洗：原始 {cl['raw_rows']:,} 行。两个 sheet 在 2010-12-01～09 完全重叠，只保留一份，剩 {cl['after_overlap_rows']:,} 行；再去除完全重复行 {cl['exact_dup_removed']:,}、邮费/手工调整/银行手续费/礼品券/测试等非商品行 {cl['non_product_rows_removed']:,}、单价≤0 或坏账调整行 {cl['zero_price_or_baddebt_removed']:,}，最终 {cl['clean_rows']:,} 行。退货（C 开头发票）以负收入计入，所有收入均为净收入。</li>
<li>全部净收入 {fmt_gbp(M['total_net_revenue'])}，其中 {pct(1 - float(M['share_rev_with_id']))} 来自没有 Customer ID 的订单，无法归属到客户，不在客户分析范围内；文中“收入占比”指有 ID 客户收入中的占比。两年累计净额 ≤0（全部退货）的客户已剔除。</li>
<li>“高价值”按两年累计净收入前 20% 定义，会偏向老客户：2011 年才进来的大客户可能因累计时间短没进前 20%，但他们大多仍活跃，对召回名单影响不大。</li>
<li>回测中当时“沉睡 &gt;180 天”的高价值客户只有 {int(bt_hv['>180天']['customers'])} 人（数据从 2009-12 才开始，一年前能观察到的最长沉睡不足一年），15% 这个比例不确定性较大，只作方向性参考。</li>
<li>回测的回流率是“自然回流”，其中也包含公司当年常规营销的影响；它是基线，不是召回活动的效果。</li>
</ul>
<p class=cap>图 4 月度净收入（绿色为 9–11 月旺季；最后一根为只有 9 天的 2011-12，不完整）：</p>
{month_svg(M['monthly'])}
</main></body></html>"""
    (OUT / "report.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    M = main()
    build_report(json.loads(json.dumps(M, ensure_ascii=False, default=str)))
    print("done:", OUT / "report.html")
