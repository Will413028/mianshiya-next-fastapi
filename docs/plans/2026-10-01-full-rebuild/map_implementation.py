"""Map source behaviors to real operations without promoting them to verified."""
import ast
import json
from pathlib import Path

base = Path(__file__).resolve().parent
root = base.parents[2]
inventory = json.loads((base/"source-inventory.json").read_text())
ledger = json.loads((base/"completion.json").read_text())
entries = {entry["id"]: entry for entry in ledger["entries"]}
operations = {}
for path in (root/"apps/api/mianshiya").glob("*.py"):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "operation_id" and isinstance(keyword.value, ast.Constant):
                            operations[keyword.value.value] = str(path.relative_to(root))

mapping = {
    "mockInterview": {"add":"createInterview", "delete":"deleteInterview", "get":"getInterview", "list/page":"listInterviews", "my/list/page/vo":"listMyInterviews", "handleEvent":"handleInterviewEvent"},
    "questionBank": {"add":"createBank", "delete":"deleteBank", "update":"updateBank", "get/vo":"getBank", "list/page":"listAdminBanks", "list/page/vo":"listBanks", "my/list/page/vo":"listMyBanks", "edit":"updateBank"},
    "questionBankQuestion": {"add":"createRelation", "delete":"deleteRelation", "update":"updateRelation", "get/vo":"getRelation", "list/page":"listRelations", "list/page/vo":"listPublicRelations", "my/list/page/vo":"listMyRelations", "remove":"removeBankQuestion", "add/batch":"addBankQuestions", "remove/batch":"removeBankQuestions"},
    "question": {"add":"createQuestion", "delete":"deleteQuestion", "update":"updateQuestion", "get/vo":"getQuestion", "list/page":"listAdminQuestions", "list/page/vo":"listQuestions", "list/page/vo/sentinel":"listQuestions", "my/list/page/vo":"listMyQuestions", "edit":"updateQuestion", "search/page/vo":"searchQuestions", "delete/batch":"batchDeleteQuestions", "ai/generate/question":"generateQuestions"},
    "user": {"register":"register", "login":"login", "logout":"logout", "get/login":"currentSession", "add":"createUser", "delete":"deleteUser", "update":"updateUser", "edit":"updateMyProfile", "get":"getUser", "get/vo":"getPublicUser", "list/page":"listUsers", "list/page/vo":"listPublicUsers", "update/my":"updateMyProfile", "add/sign_in":"recordActivity", "get/sign_in":"getActivity"},
}


def mark(key, target, operation):
    assert (root/target).is_file(), target
    entry = entries[key]
    assert entry["status"] not in {"excluded", "accepted"}
    entry.update(target=target, operation=operation)
    if entry["status"] == "planned":
        entry["status"] = "implemented"
    # Existing verification requires review, never fabrication or deletion here.


for endpoint in inventory["endpoints"]:
    key = f"endpoints:{endpoint['source']}:{endpoint['line']}"
    if entries[key]["status"] == "excluded":
        continue
    resource, action = endpoint["path"].removeprefix("/api/").split("/", 1)
    operation = mapping[resource][action]
    mark(key, operations[operation], operation)

for page in inventory["pages"]:
    key = f"pages:{page['source']}:{page['route']}"
    route = "/admin/questionBank" if page["route"] == "/admin/bank" else page["route"]
    mark(key, "apps/web/components/workspace.tsx", "Workspace GET "+route)

models = {"user":"User", "question_bank":"Bank", "question":"Question", "question_bank_question":"Relation", "mock_interview":"Interview"}
for table in inventory["tables"]:
    mark(f"tables:{table['source']}:{table['line']}", "apps/api/mianshiya/db.py", models[table["name"]])

requirements = {
    "R01":("auth.py","register/login/currentSession/logout"), "R02":("auth.py","createUser/listUsers/getUser/updateUser/deleteUser"),
    "R03":("auth.py","getMyProfile/updateMyProfile"), "R04":("web","Home"), "R05":("content.py","banks CRUD/my/admin queries"),
    "R06":("web","Banks/BankDetail/getBankQuestionNavigation"), "R07":("content.py","questions CRUD/my/admin queries"),
    "R08":("content.py","bank-question-relations CRUD/my/admin queries"), "R09":("content.py","addBankQuestions/removeBankQuestions/batchDeleteQuestions"),
    "R10":("content.py","mark_activity/recordActivity/getActivity"), "R11":("search.py","searchQuestions"), "R12":("search.py","drain_outbox/rebuild_index"),
    "R13":("policies.py","cached_bank"), "R15":("policies.py","guard_request/limit/policies; AI/search circuits"),
    "R16":("policies.py","policies/guard_request; security.Bloom"), "R17":("security.py","create_session/current_user/revoke_user"),
    "R18":("policies.py","guard_request crawl cooldown"), "R19":("ai.py","generateQuestions/run_generation/getGenerationJob"),
    "R20":("ai.py","handleInterviewEvent/completion"), "R21":("ai.py","listMyInterviews/getInterview/deleteInterview/listInterviews"),
}
for key, (module, operation) in requirements.items():
    mark(key, "apps/web/components/workspace.tsx" if module == "web" else "apps/api/mianshiya/"+module, operation)

(base/"completion.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2)+"\n")
print("Mapped actual operations; no item promoted to verified. R14 comparison and all defect evidence remain for explicit audit.")
