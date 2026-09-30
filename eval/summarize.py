"""把两次盲审的 audit.json 按「有 / 无 skill」汇总成 results.md。

盲审时报告被随机标成 A/B，对应关系在各目录的 .key.json；审稿人看不到这个文件。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTIONS = {"audit_q1": "Q1 老客召回（RFM）", "audit_q2": "Q2 新客同期群复购"}
TRAPS = ["missing_id", "cancel_net", "sheet_overlap", "left_truncation", "seasonality", "sensitivity"]


def overclaims(side: dict) -> dict:
    counts = {"causal": 0, "fabricated_precision": 0, "unhedged_small_sample": 0}
    for item in side.get("overclaims", []):
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return counts


rows, totals = [], {"skill": [], "baseline": []}
for folder, title in QUESTIONS.items():
    audit_path = HERE / folder / "audit.json"
    if not audit_path.exists():
        continue
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    key = json.loads((HERE / folder / ".key.json").read_text(encoding="utf-8"))
    for label in ("A", "B"):
        arm = "skill" if "with skill" in key[label] else "baseline"
        side = audit[label]
        oc = overclaims(side)
        traps = sum(int(side["traps"].get(t, 0)) for t in TRAPS)
        record = {"question": title, "arm": arm, "accuracy": side["accuracy"], "recomputable": side["recomputable"],
                  "overclaims": sum(oc.values()), **oc, "traps": traps, "decision": side["decision_usefulness"]}
        rows.append(record)
        totals[arm].append(record)

lines = ["# 盲审结果", "", "| 问题 | 组别 | 准确率 | 可复算率 | 越权结论（因果 / 无依据精确数字 / 小样本） | 陷阱识别（/6） | 决策可用性（/5） |", "|---|---|---|---|---|---|---|"]
for r in rows:
    arm = "有 skill" if r["arm"] == "skill" else "无 skill"
    lines.append(f"| {r['question']} | {arm} | {r['accuracy']:.0%} | {r['recomputable']:.0%} | {r['overclaims']}（{r['causal']} / {r['fabricated_precision']} / {r['unhedged_small_sample']}） | {r['traps']} | {r['decision']} |")
lines += ["", "## 合计", "", "| 组别 | 平均准确率 | 平均可复算率 | 越权结论总数 | 陷阱识别总分 | 决策可用性均分 |", "|---|---|---|---|---|---|"]
for arm, recs in totals.items():
    if not recs:
        continue
    n = len(recs)
    lines.append(f"| {'有 skill' if arm == 'skill' else '无 skill'} | {sum(r['accuracy'] for r in recs) / n:.0%} | {sum(r['recomputable'] for r in recs) / n:.0%} | "
                 f"{sum(r['overclaims'] for r in recs)} | {sum(r['traps'] for r in recs)}/{6 * n} | {sum(r['decision'] for r in recs) / n:.1f} |")
(HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
