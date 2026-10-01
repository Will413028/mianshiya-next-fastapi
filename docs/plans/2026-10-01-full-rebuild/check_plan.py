"""Check source disposition and roadmap coverage without external dependencies."""
import argparse
import json
import re
from pathlib import Path

base = Path(__file__).parent
plan = base.with_suffix(".md")
parser = argparse.ArgumentParser()
parser.add_argument("inventory", nargs="?", type=Path, default=base / "source-inventory.json")
parser.add_argument("--complete", action="store_true")
parser.add_argument("--completion", type=Path, default=base / "completion.json")
args = parser.parse_args()
inventory_path = args.inventory
data = json.loads(inventory_path.read_text())
text = plan.read_text()
overview = (base / "inventory.md").read_text()
errors = []
if data.get("revision") != "4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9":
    errors.append("source revision mismatch")
step_ids = set(re.findall(r'\*\*S(\d+)\.', text))
if step_ids != {str(n) for n in range(13)}:
    errors.append("missing or unexpected roadmap step")
decisions = set(re.findall(r'\*\*D(\d+) ', text))
for group in ("endpoints", "pages", "tables"):
    rows = data.get(group, [])
    if not rows:
        errors.append(f"empty inventory: {group}")
    keys = [row.get("source", "") + ":" + str(row.get("line", row.get("route", ""))) for row in rows]
    if len(keys) != len(set(keys)):
        errors.append(f"duplicate inventory row: {group}")
    for row in rows:
        if not row.get("destination") or not row.get("source"):
            errors.append(f"missing disposition/source: {group}")
        if row.get("step", "")[1:] not in step_ids:
            errors.append(f"invalid step: {row}")
        if row.get("decision") and row["decision"][1:] not in decisions:
            errors.append(f"unknown decision: {row}")
for n in range(1, 26):
    if not re.search(rf'\| R{n:02} \|.*\| S\d+ \|', overview):
        errors.append(f"requirement lacks step: R{n:02}")
for n in range(1, 11):
    if not re.search(rf'\| B{n:02} \|.*\|.*S\d+ \|', overview):
        errors.append(f"defect lacks disposition: B{n:02}")
for step in re.split(r'^- \[[ x]\] \*\*S\d+\.', text, flags=re.M)[1:]:
    body = step.split("\n## 決定", 1)[0]
    for field in ("被擋於", "範圍", "消費端", "不能動", "驗收", "停止條件"):
        if field not in body:
            errors.append(f"missing step field: {field}")
repo = base.parents[2]
for file in (repo / "README.md", plan, base / "inventory.md"):
    for target in re.findall(r'\]\(([^)]+)\)', file.read_text()):
        if target.startswith(("http://", "https://", "#")):
            continue
        if not (file.parent / target.split("#", 1)[0]).exists():
            errors.append(f"broken relative link: {file.name}: {target}")
expected_ids = {f"{group}:{row['source']}:{row.get('line', row.get('route', ''))}" for group in ("endpoints", "pages", "tables") for row in data[group]}
expected_ids |= {f"{prefix}{n:02}" for prefix, count in (("R", 25), ("B", 10)) for n in range(1, count + 1)}
completion = json.loads(args.completion.read_text())
entries = completion["entries"]
if completion.get("revision") != data.get("revision"):
    errors.append("completion revision mismatch")
if {row["id"] for row in entries} != expected_ids or len(entries) != len(expected_ids):
    errors.append("completion inventory missing/duplicate/stale entries")
for row in entries:
    if row.get("status") not in {"planned", "implemented", "verified", "excluded", "accepted"}:
        errors.append(f"invalid completion state: {row['id']}")
if args.complete:
    if "狀態：未決" in text:
        errors.append("unresolved decisions remain")
    for row in entries:
        if row.get("status") not in {"verified", "excluded", "accepted"}:
            errors.append(f"not complete: {row['id']}")
            continue
        if row["status"] == "verified":
            if not row.get("target") or not row.get("operation") or not (repo / row["target"]).is_file():
                errors.append(f"missing implemented target/operation: {row['id']}")
            evidence = row.get("evidence", [])
            if not evidence or any(not isinstance(item, dict) or not item.get("command") or not item.get("report") or not (repo / item["report"]).is_file() for item in evidence):
                errors.append(f"missing verification command/report: {row['id']}")
        else:
            if row["status"] == "accepted" and not row["id"].startswith("B"):
                errors.append(f"only defect rows can be accepted: {row['id']}")
            if not row.get("reason") or not row.get("evidence"):
                errors.append(f"missing approved exclusion/acceptance reason: {row['id']}")
            for item in row.get("evidence", []):
                if not isinstance(item, dict) or not item.get("decision") or not (repo / item["decision"]).is_file():
                    errors.append(f"missing decision record: {row['id']}")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
pending = sum(bool(row.get("decision")) for group in ("endpoints", "tables") for row in data[group])
print(f"PASS: {len(data['endpoints'])} endpoints, {len(data['pages'])} pages, {len(data['tables'])} tables; "
      f"25 requirements, 10 defects, 13 steps. {pending} source rows have explicit decision dependencies.")
print("This checks document coverage only; it does not approve decisions or verify product behavior.")
