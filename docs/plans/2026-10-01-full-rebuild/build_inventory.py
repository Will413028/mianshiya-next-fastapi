"""Extract route/schema metadata only; never reads credential configuration."""
import json
import re
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
expected = "4bd2893d01f4d9d6be7c4f75b194ccebcc0d3bd9"
if revision != expected:
    raise SystemExit("Source revision changed; reconcile the plan first")
java = source / "mianshiya-next-backend/src/main/java/com/yupi/mianshiya"
steps = {
    "UserController": "S2", "QuestionBankController": "S3",
    "QuestionController": "S4", "QuestionBankQuestionController": "S5",
    "MockInterviewController": "S10", "FileController": "S3",
}
endpoints = []
for file in sorted((java / "controller").glob("*.java")):
    lines = file.read_text().splitlines()
    root = ""
    for line in lines:
        match = re.match(r'\s*@RequestMapping\("([^"]*)"\)', line)
        if match:
            root = match.group(1)
            break
    for number, line in enumerate(lines, 1):
        match = re.match(r'\s*@(Get|Post|Put|Delete|Patch|Request)Mapping\("([^"]*)"\)', line)
        if not match:
            continue
        method, path = match.groups()
        if method == "Request" and number < next(i for i, item in enumerate(lines, 1) if "public class " in item):
            continue
        if method == "Request":
            method = "ANY"
        step = steps.get(file.stem, "S11")
        decision = ""
        if file.stem == "UserController" and "wx_open" in path:
            decision = "D1"
            step = "S11"
        elif file.stem in {"FileController", "PostController", "PostFavourController", "PostThumbController", "WxMpController", "TestSaTokenLoginController"}:
            decision = "D1"
        if file.stem == "UserController" and path in {"/edit", "/update/my"}:
            step = "S6"
        if "sign_in" in path:
            step = "S6"
        if "search" in path:
            step = "S7"
        if "sentinel" in path:
            step = "S9"
        if "batch" in path:
            step = "S5"
        if "ai/generate" in path:
            step = "S10"
        if decision:
            step = "S11"
        api_path = "/api/" + "/".join(part.strip("/") for part in (root, path) if part.strip("/"))
        endpoints.append({"controller": file.stem, "method": method.upper(), "path": api_path,
                          "source": file.relative_to(source).as_posix(), "line": number,
                          "destination": "待 D1 確認" if decision else "依產品能力重做；新 API 不要求同名",
                          "step": step, "decision": decision})
pages = []
app = source / "mianshiya-next-frontend/src/app"
for file in sorted(app.rglob("page.tsx")):
    route = "/" + file.parent.relative_to(app).as_posix()
    route = "/" if route == "/." else route
    step = "S4"
    if route.startswith("/admin/user") or route in {"/user/login", "/user/register"}:
        step = "S2"
    elif route.startswith("/user/center"):
        step = "S6"
    elif route.startswith("/mockInterview") or route == "/admin/question/ai":
        step = "S10"
    elif route == "/admin/bank" or route == "/banks" or route == "/" or (route.startswith("/bank/") and "/question/" not in route):
        step = "S3"
    elif route == "/questions":
        step = "S7"
    pages.append({"route": route, "source": file.relative_to(source).as_posix(), "destination": "重做", "step": step})
ddl = source / "mianshiya-next-backend/sql/create_table.sql"
tables = [{"name": m.group(1), "source": ddl.relative_to(source).as_posix(),
           "line": ddl.read_text()[:m.start()].count("\n") + 1,
           "destination": "新 schema，欄位與約束待 D2 確認", "step": "S2" if m.group(1) == "user" else "S10" if m.group(1) == "mock_interview" else "S5" if m.group(1) == "question_bank_question" else "S3" if m.group(1) == "question_bank" else "S4",
           "decision": "D2"} for m in re.finditer(r'create table if not exists (\w+)', ddl.read_text(), re.I)]
payload = {"revision": revision, "command": "python3 build_inventory.py <reference-checkout>",
           "endpoints": endpoints, "pages": pages, "tables": tables}
(Path(__file__).parent / "source-inventory.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
completion_path = Path(__file__).parent / "completion.json"
if not completion_path.exists():
    entries = []
    for group in ("endpoints", "pages", "tables"):
        for row in payload[group]:
            key = f"{group}:{row['source']}:{row.get('line', row.get('route', ''))}"
            entries.append({"id": key, "status": "planned", "target": "", "operation": "", "evidence": [], "reason": ""})
    for prefix, count in (("R", 25), ("B", 10)):
        entries.extend({"id": f"{prefix}{n:02}", "status": "planned", "target": "", "operation": "", "evidence": [], "reason": ""} for n in range(1, count + 1))
    completion_path.write_text(json.dumps({"revision": revision, "entries": entries}, ensure_ascii=False, indent=2) + "\n")
print(f"Inventoried {len(endpoints)} endpoint mappings, {len(pages)} pages, {len(tables)} tables")
