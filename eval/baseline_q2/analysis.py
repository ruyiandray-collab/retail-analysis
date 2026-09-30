# -*- coding: utf-8 -*-
"""新客月度同期群复购分析 —— UCI Online Retail II
运行: python analysis.py   输出: 同目录 report.html
"""
import pandas as pd, numpy as np, json, html, os
HERE = os.path.dirname(os.path.abspath(__file__))
D = str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'data') + '/'
END = pd.Timestamp('2011-12-09')
P = lambda s: pd.Period(s, 'M')

# ---------------- 1. 读取与清洗 ----------------
a = pd.read_csv(D + 'Year_2009-2010.csv', dtype={'Invoice': str, 'StockCode': str})
b = pd.read_csv(D + 'Year_2010-2011.csv', dtype={'Invoice': str, 'StockCode': str})
for x in (a, b):
    x['InvoiceDate'] = pd.to_datetime(x.InvoiceDate)
log = {'raw_rows': len(a) + len(b)}
a = a[a.InvoiceDate < '2010-12-01']            # 两个 sheet 在 2010-12-01~09 重叠，取后者
log['overlap_removed'] = log['raw_rows'] - len(a) - len(b)
df = pd.concat([a, b])
n0 = len(df); df = df.drop_duplicates(); log['dup_removed'] = n0 - len(df)
n0 = len(df); df = df[df['Customer ID'].notna()]; log['no_customer'] = n0 - len(df)
n0 = len(df); df = df[~df.Invoice.str.startswith('C')]; log['cancel'] = n0 - len(df)
n0 = len(df); df = df[(df.Quantity > 0) & (df.Price > 0)]; log['nonpos'] = n0 - len(df)
n0 = len(df)
df = df[df.StockCode.str.match(r'^\d{5}') | df.StockCode.str.startswith('DCGS') | df.StockCode.str.startswith('gift')]
log['non_product'] = n0 - len(df)   # 邮费 POST/DOT、手工调整 M、银行费用等
log['clean_rows'] = len(df)
df['cid'] = df['Customer ID'].astype(int)
df['amt'] = df.Quantity * df.Price
log['customers'] = int(df.cid.nunique())

inv = (df.groupby(['cid', 'Invoice'])
         .agg(dt=('InvoiceDate', 'min'), amt=('amt', 'sum'), lines=('StockCode', 'size'),
              country=('Country', 'first')).reset_index().sort_values(['cid', 'dt']))
inv['day'] = inv.dt.dt.normalize()
days = inv[['cid', 'day']].drop_duplicates()


# ---------------- 2. 客户首单与复购 ----------------
def build(first_inv, days_all):
    """复购 = 首单日之后另一日期的有效订单；N 天指标只对首单距截止日 >= N 天的客户计算"""
    f = first_inv.copy()
    m = days_all.merge(f[['day']].rename(columns={'day': 'fday'}), left_on='cid', right_index=True)
    later = m[m.day > m.fday]
    f['gap'] = (later.groupby('cid').day.min() - f['day']).dt.days
    for w in (60, 90, 180, 365):
        ok = f['day'] <= END - pd.Timedelta(days=w)
        f[f'r{w}'] = np.where(ok, (f.gap <= w).astype(float), np.nan)
    return f


first = inv.groupby('cid').first()
first['cohort'] = first.dt.dt.to_period('M')
first = build(first, days)
invm = inv.merge(first[['day']].rename(columns={'day': 'fday'}), left_on='cid', right_index=True)
w365 = invm[(invm.day > invm.fday) & (invm.day <= invm.fday + pd.Timedelta(days=365))]
first['rev365'] = w365.groupby('cid').amt.sum().reindex(first.index).fillna(0)
first['ord365'] = w365.groupby('cid').day.nunique().reindex(first.index).fillna(0)
first.loc[first.r365.isna(), ['rev365', 'ord365']] = np.nan
first['uk'] = first.country == 'United Kingdom'
# 首单中圣诞相关商品的金额占比
d1 = df[df.Invoice.isin(set(first.Invoice))].copy()
d1['xmas'] = d1.Description.str.contains('CHRISTMAS|XMAS|ADVENT|SANTA|REINDEER|SNOWFLAKE|NATIVITY', case=False, na=False)
first['xmas'] = (d1.amt * d1.xmas).groupby(d1.cid).sum() / d1.groupby('cid').amt.sum()

# ---------------- 3. 左删失：“新客”里混了多少老客 ----------------
# 只用 2010-12 以后的数据判定“首购月”，再用全量数据检查这些人在 2009-12~2010-11 是否买过。
# 2011 年某月的回看期长度 = 2010 年同月的回看期长度，所以混入比例可平移到 2010 年同期群。
i2 = inv[inv.dt >= '2010-12-01']
f2 = i2.groupby('cid').first(); f2['cm'] = f2.dt.dt.to_period('M')
f2 = build(f2, i2[['cid', 'day']].drop_duplicates())
f2['truly_new'] = f2.index.map(first.cohort) == f2.cm
contam = f2.groupby('cm').agg(n=('truly_new', 'size'), new_share=('truly_new', 'mean'))
old_vs_new = f2[f2.cm <= P('2011-08')].pivot_table(index='cm', columns='truly_new', values='r90', aggfunc='mean')
old_vs_new.columns = ['r_old' if not c else 'r_new' for c in old_vs_new.columns]
contam_2010 = {p - 12: 1 - v for p, v in contam.new_share.items()}


# ---------------- 4. 季节基线：同一窗口里活跃老客的下单概率 ----------------
def base(d, W=90):
    prev = days[(days.day > d - pd.Timedelta(days=365)) & (days.day <= d)].cid.unique()
    fut = days[(days.day > d) & (days.day <= d + pd.Timedelta(days=W))].cid.unique()
    return np.isin(prev, fut).mean()


B90 = {d: base(d) for d in pd.date_range('2010-12-01', '2011-09-10')}
first['b90'] = first.day.map(B90)


def wilson(p, n, z=1.96):
    d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


# ---------------- 5. 汇总 ----------------
# A. 真新客（此前 >= 12 个月无购买）：2010-12 ~ 2011-11
new11 = first[(first.day >= '2010-12-01') & (first.cohort <= P('2011-11'))]
A = new11.groupby('cohort').agg(n=('amt', 'size'), n90=('r90', 'count'), r90=('r90', 'mean'),
                                r180=('r180', 'mean'), base90=('b90', 'mean'),
                                fo=('amt', 'median'), uk=('uk', 'mean'))
A['idx'] = A.r90 / A.base90
A['ci_lo'] = [wilson(r.r90, r.n90)[0] if r.n90 else np.nan for _, r in A.iterrows()]
A['ci_hi'] = [wilson(r.r90, r.n90)[1] if r.n90 else np.nan for _, r in A.iterrows()]

# B. 2010 年同期群，365 天复购（每个窗口都恰含一个完整旺季，季节上公平）
c10 = first[(first.cohort >= P('2010-01')) & (first.cohort <= P('2010-11'))]
B = c10.groupby('cohort').agg(n=('amt', 'size'), r365=('r365', 'mean'), ord365=('ord365', 'mean'),
                              rev_med=('rev365', 'median'), rev_mean=('rev365', 'mean'),
                              fo=('amt', 'median'), uk=('uk', 'mean'), xmas=('xmas', 'mean'))
B['early'] = c10.groupby('cohort').gap.apply(lambda s: (s <= 60).mean())
B['late'] = c10.groupby('cohort').gap.apply(lambda s: ((s > 60) & (s <= 365)).mean())
B['contam'] = [contam_2010.get(p, np.nan) for p in B.index]
B['r365_adj20'] = B.r365 - B.contam * 0.20   # 敏感性：假设混入老客的 365 天复购率高出 20pp

# C. 解释检验
e = new11[new11.r90.notna()].copy()
qlab = ['首单最低25%', '25-50%', '50-75%', '首单最高25%']
e['q'] = pd.qcut(e.amt, 4, labels=qlab)
e['grp'] = e.cohort.dt.month.map(lambda mth: '12月' if mth == 12 else '1-2月' if mth <= 2 else '3-5月' if mth <= 5 else '6-9月')
strat = e.pivot_table(index='grp', columns='q', values='r90', aggfunc='mean', observed=False).reindex(['12月', '1-2月', '3-5月', '6-9月'])
q4 = first[first.cohort.isin([P('2010-09'), P('2010-10'), P('2010-11')]) & first.r365.notna()].copy()
q4['xg'] = pd.cut(q4.xmas, [-.01, 0, 0.3, 1.01], labels=['首单无圣诞品', '圣诞品占比<30%', '圣诞品占比≥30%'])
xm = q4.groupby('xg', observed=False).agg(n=('r365', 'size'), r365=('r365', 'mean'))
c10v = c10[c10.r365.notna() & (c10.cohort >= P('2010-03'))].copy()
c10v['q'] = pd.qcut(c10v.amt, 4, labels=qlab)
foq = c10v.groupby('q', observed=False).r365.mean()

# D. 季度汇总
Q = []
for qn, ms in [('Q1', [1, 2, 3]), ('Q2', [4, 5, 6]), ('Q3', [7, 8, 9]), ('Q4', [10, 11, 12])]:
    ea = e[e.cohort.dt.month.isin(ms)]
    ca = c10v[c10v.cohort.dt.month.isin(ms)]
    Q.append(dict(q=qn, new11=int(new11.cohort.dt.month.isin(ms).sum()),
                  new10=int(c10.cohort.dt.month.isin([x for x in ms if x >= 3 and x <= 11]).sum()),
                  r90=ea.r90.mean(), n90=len(ea),
                  r365=ca.r365.mean() if len(ca) else np.nan,
                  rev_med=ca.rev365.median() if len(ca) else np.nan))
Q = pd.DataFrame(Q).set_index('q')
monthly_rev = inv.assign(m=inv.dt.dt.to_period('M')).groupby('m').amt.sum()

pd.set_option('display.width', 220)
print(json.dumps(log, indent=1))
for t in (A, B, contam.join(old_vs_new), strat, xm, foq, Q):
    print(t.round(3), '\n')


# ---------------- 6. 图表（内联 SVG） ----------------
def svg_chart(labels, series, ymax, fmt=lambda v: f'{v:.0%}', w=720, h=280, greyed=()):
    L, R, T, Bm = 52, 16, 20, 44
    pw, ph = w - L - R, h - T - Bm
    n = len(labels); bw = pw / n
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    for i in range(5):
        v = ymax * i / 4; y = T + ph - ph * v / ymax
        out.append(f'<line x1="{L}" x2="{w-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{L-6}" y="{y+4:.1f}" class="ax" text-anchor="end">{fmt(v)}</text>')
    bars = [s for s in series if s[3] == 'bar']; nb = max(len(bars), 1)
    for name, vals, col, typ in series:
        if typ == 'bar':
            k = [s[0] for s in bars].index(name); sub = bw * 0.72 / nb
            for i, v in enumerate(vals):
                if v is None or np.isnan(v): continue
                x = L + i * bw + bw * 0.14 + k * sub; y = T + ph - ph * min(v, ymax) / ymax
                op = ' opacity="0.35"' if i in greyed else ''
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{sub-2:.1f}" height="{T+ph-y:.1f}" fill="var({col})" rx="2"{op}><title>{labels[i]} {name}: {fmt(v)}</title></rect>')
                if nb == 1:
                    out.append(f'<text x="{x+sub/2-1:.1f}" y="{y-4:.1f}" class="val" text-anchor="middle">{fmt(v)}</text>')
        else:
            pts = [(L + i * bw + bw / 2, T + ph - ph * v / ymax) for i, v in enumerate(vals) if not np.isnan(v)]
            out.append('<polyline fill="none" stroke="var(%s)" stroke-width="2.5" stroke-dasharray="5 4" points="%s"/>'
                       % (col, ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)))
            for x, y in pts:
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var({col})"/>')
    for i, lb in enumerate(labels):
        out.append(f'<text x="{L+i*bw+bw/2:.1f}" y="{h-Bm+16}" class="ax" text-anchor="middle">{lb}</text>')
    lx = L
    for name, _, col, typ in series:
        out.append(f'<rect x="{lx}" y="{h-14 if typ=="bar" else h-10}" width="12" height="{10 if typ=="bar" else 3}" fill="var({col})"/>'
                   f'<text x="{lx+16}" y="{h-5}" class="ax">{html.escape(name)}</text>')
        lx += 30 + len(name) * 11
    out.append('</svg>')
    return ''.join(out)


isnan = lambda v: v is None or (isinstance(v, float) and np.isnan(v))
pct = lambda v: '—' if isnan(v) else f'{v:.1%}'
num = lambda v: '—' if isnan(v) else f'{v:,.0f}'
gbp = lambda v: '—' if isnan(v) else f'£{v:,.0f}'
f2d = lambda v: '—' if isnan(v) else f'{v:.2f}'
ml = lambda p: f'{p.year % 100:02d}/{p.month:02d}'


def table(dfx, cols, heads, cls=''):
    hh = ''.join(f'<th>{x}</th>' for x in heads)
    rows = ''
    for idx, r in dfx.iterrows():
        lab = ml(idx) if isinstance(idx, pd.Period) else str(idx)
        rows += f'<tr><td>{lab}</td>' + ''.join(f'<td>{f(r[c])}</td>' for c, f in cols) + '</tr>'
    return f'<div class="tw"><table class="{cls}"><thead><tr><th></th>{hh}</tr></thead><tbody>{rows}</tbody></table></div>'


Aev = A[A.n90 > 0]
chart1 = svg_chart([ml(p) for p in Aev.index],
                   [('真新客90天复购率', Aev.r90.values, '--c1', 'bar'),
                    ('同窗口活跃老客下单率（季节基线）', Aev.base90.values, '--c2', 'line')],
                   0.8, greyed=[len(Aev) - 1])
chart2 = svg_chart([ml(p) for p in B.index], [('365天复购率', B.r365.values, '--c1', 'bar')], 1.0, greyed=[0, 1])
chart3 = svg_chart([ml(p) for p in B.index], [('首单后365天复购收入中位数(£)', B.rev_med.values, '--c2', 'bar')],
                   1000, fmt=lambda v: f'£{v:,.0f}', greyed=[0, 1])
chart4 = svg_chart([ml(p) for p in B.index],
                   [('首单后60天内复购', B.early.values, '--c2', 'bar'),
                    ('首次复购在61–365天', B.late.values, '--c1', 'bar')], 0.6, greyed=[0, 1])
mr = monthly_rev.iloc[1:-1]
chart5 = svg_chart([ml(p) for p in mr.index], [('月销售额(£千)', mr.values / 1000, '--c3', 'bar')],
                   1250, fmt=lambda v: f'{v:,.0f}', w=760)

tA = table(A, [('n', num), ('n90', num), ('r90', pct), ('ci_lo', pct), ('ci_hi', pct), ('base90', pct), ('idx', f2d),
               ('r180', pct), ('fo', gbp), ('uk', pct)],
           ['新客数', '可评估90天', '90天复购率', '95%CI下', '95%CI上', '季节基线', '季节调整指数', '180天复购率', '首单中位数', '英国占比'])
tB = table(B, [('n', num), ('contam', pct), ('r365', pct), ('r365_adj20', pct), ('ord365', f2d), ('rev_med', gbp),
               ('rev_mean', gbp), ('fo', gbp), ('uk', pct), ('xmas', pct)],
           ['新客数', '估计老客混入', '365天复购率', '敏感性调整后*', '365天复购次数(均)', '复购收入中位数',
            '复购收入均值', '首单中位数', '英国占比', '首单圣诞品占比'])
tS = table(strat, [(c, pct) for c in strat.columns], list(strat.columns))
tX = table(xm, [('n', num), ('r365', pct)], ['客户数', '365天复购率'])
tQ = table(Q, [('new11', num), ('r90', pct), ('n90', num), ('new10', num), ('r365', pct), ('rev_med', gbp)],
           ['真新客数(12/10–11/11)', '90天复购率(真新客)', '可评估人数', '2010新客数(3–11月)', '365天复购率(2010)', '复购收入中位数(2010)'])
tC = table(contam.join(old_vs_new)[lambda x: x.index <= P('2011-11')],
           [('n', num), ('new_share', pct), ('r_new', pct), ('r_old', pct)],
           ['模拟“首购”人数', '其中真新客占比', '真新客90天复购', '混入老客90天复购'])

# ---------------- 7. 报告 ----------------
a_ = lambda p, c: A.loc[P(p), c]
b_ = lambda p, c: B.loc[P(p), c]
ukr = pd.concat([A.uk, B.uk])
for_rng = pd.concat([A.fo, B.fo[2:]])
ci_w = ((A.ci_hi - A.ci_lo) / 2)[A.n90 >= 70]
q4_val = (b_('2010-10', 'rev_med') + b_('2010-11', 'rev_med')) / 2
sp_val = (b_('2010-03', 'rev_med') + b_('2010-04', 'rev_med')) / 2

H = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>新客获客月份与复购</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1f2328;--mut:#5b6470;--card:#ffffff;--line:#e3e1dc;--c1:#2f6db3;--c2:#c2672b;--c3:#8a8f98;--good:#2e7d4f;--bad:#b3362f}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181c;--fg:#e8e6e1;--mut:#a3a9b3;--card:#1e2126;--line:#33373e;--c1:#6ea3e0;--c2:#e39a62;--c3:#9aa0a9;--good:#6cc190;--bad:#ea7a72}}}}
:root[data-theme="dark"]{{--bg:#16181c;--fg:#e8e6e1;--mut:#a3a9b3;--card:#1e2126;--line:#33373e;--c1:#6ea3e0;--c2:#e39a62;--c3:#9aa0a9;--good:#6cc190;--bad:#ea7a72}}
body{{background:var(--bg);color:var(--fg);font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0}}
main{{max-width:900px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:25px;margin:0 0 4px;line-height:1.35}} h2{{font-size:20px;margin:38px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}} h3{{font-size:16px;margin:22px 0 6px}}
.sub{{color:var(--mut);font-size:13px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:14px 0}}
.tldr li{{margin:7px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:14px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}
.kpi b{{display:block;font-size:23px;line-height:1.4}} .kpi span{{color:var(--mut);font-size:12.5px}}
.good{{color:var(--good)}} .bad{{color:var(--bad)}}
.chart{{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}}
.chart .grid{{stroke:var(--line)}} .chart .ax{{fill:var(--mut);font-size:11px}} .chart .val{{fill:var(--fg);font-size:10px}}
.tw{{overflow-x:auto}} table{{border-collapse:collapse;font-size:13px;width:100%;margin:8px 0}}
th,td{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right;white-space:nowrap}} th:first-child,td:first-child{{text-align:left}}
th{{color:var(--mut);font-weight:600}}
.note{{color:var(--mut);font-size:13px}}
.budget td{{text-align:left;white-space:normal;vertical-align:top}} .budget td:nth-child(2){{font-weight:700;font-size:17px;white-space:nowrap}}
</style></head><body><main>
<h1>哪个月获得的新客复购最好？获客时点与复购质量分析</h1>
<div class="sub">数据：UCI Online Retail II（英国线上礼品批发/零售商），2009-12-01 至 2011-12-09；清洗后 {log['clean_rows']:,} 行，{log['customers']:,} 名有 ID 的客户</div>

<div class="card tldr"><b>结论先行</b><ul>
<li><b>最差：12 月，其次是 11 月。</b>2010 年 12 月获得的真新客，90 天复购率只有 <b class="bad">{pct(a_('2010-12','r90'))}</b>（n={a_('2010-12','n90'):.0f}）。扣除 1–2 月淡季的影响后，也只有正常水平的一半（季节调整指数 {a_('2010-12','idx'):.2f}）。按 12 个月看，2010 年 11 月的新客复购率为 <b class="bad">{pct(b_('2010-11','r365'))}</b>，复购收入中位数只有 <b class="bad">{gbp(b_('2010-11','rev_med'))}</b>，都是 3–11 月里最低的。</li>
<li><b>最好：取决于你看多长的周期。</b>看 12 个月价值，<b>3–4 月</b>的新客最好：365 天复购率 {pct(b_('2010-03','r365'))} 和 {pct(b_('2010-04','r365'))}，复购收入中位数 {gbp(b_('2010-03','rev_med'))} 和 {gbp(b_('2010-04','rev_med'))}，约为 11 月新客的 4–5 倍。看 90 天复购，<b>6–9 月</b>的新客回头最快（2011 年 7 月为 {pct(a_('2011-07','r90'))}）。</li>
<li><b>差异主要来自获客时点，不是首单大小。</b>这家店的季节性很强，9–11 月的月销售额是其他月份的约 1.4–2 倍。旺季前（6–9 月）进来的客户，紧接着就是补货旺季，所以短期复购高；12 月进来的客户，后面是 1–2 月淡季。10–11 月进来的客户更多是只为这一季下单：60 天内回头的比例不低（11 月 {pct(b_('2010-11','early'))}），但在 61–365 天里才首次回来的只有 {pct(b_('2010-11','late'))}，5 月新客是 {pct(b_('2010-05','late'))}。首单金额、国家、首单里圣诞品的比例在各月之间差别都不大；按这些因素分层后，月份差异依然存在。</li>
<li><b>预算建议：Q1 20%，Q2 35%，Q3 35%，Q4 10%。</b>钱往 3–8 月集中，Q4 少投，12 月基本不投（见第 5 节）。按复购收入中位数算，Q4 新客的 12 个月价值约为春季新客的 {q4_val/sp_val:.0%}。只有 Q4 的单客获客成本低于春季的这个比例，多投 Q4 才划算。</li>
</ul></div>

<div class="kpis">
<div class="kpi"><span>12月真新客 90 天复购率</span><b class="bad">{pct(a_('2010-12','r90'))}</b><span>季节调整指数 {a_('2010-12','idx'):.2f}（1.00 = 正常）</span></div>
<div class="kpi"><span>7月真新客 90 天复购率</span><b class="good">{pct(a_('2011-07','r90'))}</b><span>季节调整指数 {a_('2011-07','idx'):.2f}</span></div>
<div class="kpi"><span>365 天复购率：3月 vs 11月</span><b><span class="good" style="font-size:23px;color:var(--good)">{pct(b_('2010-03','r365'))}</span> vs <span style="font-size:23px;color:var(--bad)">{pct(b_('2010-11','r365'))}</span></b><span>2010 年同期群，新客 {b_('2010-03','n'):.0f} / {b_('2010-11','n'):.0f} 人</span></div>
<div class="kpi"><span>每名新客 365 天复购收入中位数：3月 vs 11月</span><b>{gbp(b_('2010-03','rev_med'))} vs {gbp(b_('2010-11','rev_med'))}</b><span>不含首单</span></div>
</div>

<h2>1. 口径，以及一个会让结论出错的陷阱</h2>
<ul>
<li><b>清洗：</b>合并两张表并删去 2010-12-01~09 的重叠部分；删去完全重复行 {log['dup_removed']:,} 行、无客户 ID 行 {log['no_customer']:,} 行、取消单（发票号以 C 开头）{log['cancel']:,} 行、数量或价格 ≤0 的行 {log['nonpos']:,} 行，以及邮费、手工调整、银行费用等非商品行 {log['non_product']:,} 行。</li>
<li><b>新客与同期群：</b>按客户在数据中第一张有效订单所在的月份分组。<b>复购</b>指首单日之后、另一个日期的有效订单。N 天复购率只统计首单距数据截止日（2011-12-09）至少 N 天的客户，避免观察期不够长的人拉低数字。</li>
<li><b>陷阱：数据开头的“新客”，很多其实是老客。</b>数据从 2009-12 开始，看不到更早的购买。我用后一年的数据做了一次重演：假设只能看到 2010-12 之后的记录，那么 2011 年 1 月被判为“新客”的人里，只有 {pct(contam.loc[P('2011-01'),'new_share'])} 是真正的新客；到 11 月，这个比例也只有 {pct(contam.loc[P('2011-11'),'new_share'])}。原因是这家店有大量一年只在旺季下一次单的批发客户。所以 <b>2009-12 同期群完全不能用，2010 年 1–2 月也严重失真</b>：混进来的老客复购率明显更高（见附表），“1 月新客复购最好”这种结论就是这样被制造出来的。</li>
<li><b>因此我用了两套互补的样本：</b><br>① <b>真新客样本</b>：2010-12 至 2011-11 首购、此前至少 12 个月没有购买记录的客户，共 {len(new11):,} 人。样本干净，但只能看 90 天或 180 天复购。<br>② <b>2010 年样本</b>：2010 年 3–11 月首购的客户，可以看完整 365 天。每个人的 365 天窗口都恰好包含一个完整旺季，季节上是公平的。缺点是混有一部分老客，这一点做了敏感性检验。</li>
</ul>

<h2>2. 短期（90 天）复购：6–9 月的新客回头最快，12 月最差</h2>
{chart1}
<p class="note">柱：真新客首单后 90 天内复购的比例。虚线：同一个 90 天窗口里，活跃老客（过去 12 个月买过的客户）再次下单的比例，代表那段时间的整体热度。2011-09 只能评估 9 月 1–10 日首购的 {a_('2011-09','n90'):.0f} 人，所以颜色较浅；2011 年 10–11 月观察期不足 90 天。</p>
<ul>
<li>90 天复购率从 12 月的 {pct(a_('2010-12','r90'))} 一路升到 7 月的 {pct(a_('2011-07','r90'))}，而且和季节基线同步变化：整体越热，新客回头越快。</li>
<li>用“新客复购率 ÷ 同期基线”做季节调整后，差距缩小了，但没有消失：<b>12 月 {a_('2010-12','idx'):.2f}</b>，2 月 {a_('2011-02','idx'):.2f}，3–5 月约 1.0–1.06，<b>6–7 月约 {a_('2011-07','idx'):.2f}–{a_('2011-06','idx'):.2f}</b>。也就是说，12 月新客即使考虑了淡季，表现依然差；夏季新客即使扣掉旺季的加成，表现依然更好。</li>
<li>12 月（95% 置信区间 {pct(a_('2010-12','ci_lo'))}–{pct(a_('2010-12','ci_hi'))}）与 6–8 月（下限都在 37% 以上）的差距在统计上显著。相邻月份之间（例如 3 月和 4 月）的差距在误差范围内。</li>
</ul>
{tA}

<h2>3. 12 个月复购：3–4 月最好，9–11 月最差</h2>
{chart2}
{chart3}
<p class="note">浅色的 2010 年 1–2 月估计混入了超过 65% 的老客，仅供参考，不参与排名。</p>
<ul>
<li>在 3–11 月中，365 天复购率从 3 月的 {pct(b_('2010-03','r365'))} 逐月下降到 11 月的 {pct(b_('2010-11','r365'))}；复购收入中位数从 {gbp(b_('2010-03','rev_med'))} 降到 {gbp(b_('2010-11','rev_med'))}。</li>
<li><b>敏感性检验：</b>2010 年样本混有老客，越早的月份混得越多（3 月约 {pct(b_('2010-03','contam'))}，11 月约 {pct(b_('2010-11','contam'))}）。不过在 2011 年的重演中，一旦回看期达到 3 个月以上，这些混入老客的 90 天复购率与真新客相当或更低（见附表）。即使保守地假设混入老客的 365 天复购率比真新客高 20 个百分点并扣除这部分，3 月仍有 {pct(b_('2010-03','r365_adj20'))}，11 月为 {pct(b_('2010-11','r365_adj20'))}，排序不变。</li>
</ul>
{tB}
<p class="note">* 敏感性调整后 = 365 天复购率 − 估计混入比例 × 20pp。复购收入指首单之后 365 天内的有效订单金额，不含首单。均值受少数大批发客户影响很大，所以以中位数为主。</p>

<h2>4. 为什么会有差异？</h2>
<h3>原因一（主因）：获客时点决定了新客接下来遇到的是旺季还是淡季</h3>
{chart5}
<p class="note">清洗后的月销售额（£千）。2009-12 和 2011-12 的数据不完整，已略去。</p>
<p>这家店以礼品和家居小件为主，大量客户是小型零售商，9–11 月是为圣诞备货的旺季。6–9 月进来的客户，多是在旺季前来试单的店主，很快就会补货，所以 90 天复购高。12 月进来的客户下的是年底前的最后一单，紧接着就是 1–2 月淡季，所以复购最差。</p>
<h3>原因二：旺季进来的新客，更多是只为这一季下单</h3>
{chart4}
<p>9–11 月的新客在首单后 60 天内回头的比例并不低（{pct(b_('2010-11','early'))}–{pct(b_('2010-10','early'))}），因为同一个旺季里会再补一次货。但旺季过去之后才首次回来的只有 {pct(b_('2010-10','late'))}–{pct(b_('2010-09','late'))}，而 5 月的新客有 {pct(b_('2010-05','late'))} 在 61–365 天内回来。春夏进来的客户更像全年持续进货的店铺；旺季进来的客户，更多只是为了这一季。</p>
<h3>已经排除的解释</h3>
<ul>
<li><b>不是首单大小造成的。</b>各月新客的首单中位数都在 {gbp(for_rng.min())}–{gbp(for_rng.max())} 之间。首单大小本身确实影响复购：2010 年 3–11 月样本中，首单最低 25% 的客户 365 天复购率为 {pct(foq.iloc[0])}，最高 25% 为 {pct(foq.iloc[3])}。但在同一个首单金额分层里，“12 月最差、6–9 月最好”的顺序在四个分层里都成立（下表为真新客的 90 天复购率；12 月每格只有约 19 人，仅看方向）：</li>
</ul>
{tS}
<ul>
<li><b>不是“买圣诞品的人不回头”。</b>在 2010 年 9–11 月的新客中，首单含圣诞品和不含圣诞品的客户，365 天复购率几乎一样：</li>
</ul>
{tX}
<ul><li><b>也不是国家构成的变化。</b>各月新客的英国占比都在 {ukr.min():.0%}–{ukr.max():.0%} 之间，和复购率的高低没有对应关系。</li></ul>

<h2>5. 下一年获客预算怎么分</h2>
{tQ}
<p class="note">真新客样本中，Q4 包含 2010-12，但 2011 年 10–11 月观察期不足，因此 Q4 的 90 天复购率只反映 12 月。2010 年样本不含 1–2 月（已失真）和 12 月。</p>
<div class="card">
<table class="budget"><thead><tr><th>季度</th><th>建议占比</th><th>理由与投放节奏</th></tr></thead><tbody>
<tr><td>Q1</td><td>20%</td><td>集中投在 3 月：12 个月价值最高（365 天复购率 {pct(b_('2010-03','r365'))}）。1–2 月的短期复购一般（2 月季节调整指数 {a_('2011-02','idx'):.2f}），只做少量投放。</td></tr>
<tr><td>Q2</td><td>35%</td><td>4 月的 12 个月价值仍然靠前；到 6 月，短期复购开始走强（调整指数 {a_('2011-06','idx'):.2f}）。这是全年客户质量最稳定的一段。</td></tr>
<tr><td>Q3</td><td>35%</td><td>旺季前获客，90 天复购最高（7 月 {pct(a_('2011-07','r90'))}）。新客首单后很快进入补货季，回本最快。9 月起 12 个月价值开始下滑，所以前多后少，重点放在 7–8 月。</td></tr>
<tr><td>Q4</td><td>10%</td><td>10–11 月新客数量处于全年高位，但 12 个月复购收入中位数只有 {gbp(b_('2010-10','rev_med'))}（10 月）和 {gbp(b_('2010-11','rev_med'))}（11 月）。只保留 10 月的少量投放，<b>12 月基本停投</b>。Q4 的预算和精力更适合用来激活已有客户。</td></tr>
</tbody></table></div>
<ul>
<li><b>决策口径：</b>用“单客 12 个月价值 ÷ 单客获客成本”给季度排序。Q4 新客的价值约为 3–4 月新客的 {q4_val/sp_val:.0%}，所以 Q4 的单客获客成本要低于春季的 {q4_val/sp_val:.0%}，多投 Q4 才值得。数据里没有获客成本，请用你们各季度的实际 CAC 代入核算；如果 Q4 的 CAC 明显更低，可以相应上调 Q4 的比例。</li>
<li><b>和季度无关的杠杆：</b>首单金额和复购强相关。不管在哪个季度，都可以用满额优惠、起订量引导，把新客的首单做大。</li>
<li><b>补救 Q4 新客：</b>对 10–12 月进来的新客，在次年 2–4 月做一次召回（春季新品、补货提醒），把只为旺季下单的客户转成全年客户。</li>
</ul>

<h2>6. 局限</h2>
<ul>
<li>数据只有约两年。12 个月指标只能用 2010 年同期群，而这部分混有老客（已做敏感性检验）；干净的真新客样本只能看 90–180 天，2011 年 10–11 月的新客还无法评估。每个月只有一年的样本，月度结论可能受当年偶然因素影响，季度层面的结论更可靠。</li>
<li>单月真新客只有 {int(A.n90[A.n90>=70].min())}–{int(A.n90.max())} 人，90 天复购率的 95% 置信区间约为 ±{ci_w.min()*100:.0f}–{ci_w.max()*100:.0f} 个百分点，相邻月份的差异不能过度解读。</li>
<li>数据里没有获客渠道和获客成本，无法区分付费新客和自然新客。上面的预算比例是基于客户质量的方向性建议。</li>
<li>约 23% 的原始交易行没有客户 ID，没有纳入同期群分析。</li>
</ul>

<h2>附：老客混入模拟（左删失检验）</h2>
{tC}
<p class="note">方法：只用 2010-12-01 之后的数据来判定“首购月”，再用全量数据检查这些人在 2009-12~2010-11 是否买过。2010 年同一月份的回看期长度与此相同，所以混入比例可以直接平移到 2010 年同期群。</p>
<p class="sub">分析代码：同目录 analysis.py</p>
</main></body></html>'''
with open(os.path.join(HERE, 'report.html'), 'w', encoding='utf-8') as fh:
    fh.write(H)
print('report written')
