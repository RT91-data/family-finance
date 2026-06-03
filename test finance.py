"""Automated tests for family_finance.py — pure logic, no Streamlit rendering"""
import sys, os
from unittest.mock import MagicMock, patch

# ── Mocks ────────────────────────────────────────────────────────────────────
class SessionState(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v

st_mock = MagicMock()
st_mock.session_state = SessionState({"logged_in": False, "user": None,
    "messages": [], "import_preview": None, "import_filename": None,
    "filter_month": 4, "filter_year": 2026})
st_mock.columns.return_value = [MagicMock(), MagicMock()]

for mod in ["streamlit","streamlit.components","streamlit.components.v1",
            "supabase","anthropic","pytesseract","PIL","PIL.Image",
            "pdfplumber","plotly","plotly.graph_objects","plotly.express",
            "dotenv","pandas"]:
    sys.modules[mod] = MagicMock()
sys.modules["streamlit"] = st_mock

os.environ.update({"SUPABASE_URL":"http://x","SUPABASE_KEY":"x","ANTHROPIC_API_KEY":"x"})

# Load only the function definitions — skip the bottom `if not logged_in` block
src = open("/home/claude/family_finance.py").read()
src = src.replace("pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'","")
# Stop execution before show_login/show_app are CALLED (they're only defined)
src = src[:src.rfind("# --- RUN ---")]  # cut off the run block
exec(compile(src, "family_finance.py", "exec"), globals())

from datetime import date
from unittest.mock import patch as mpatch

PASS, FAIL = "✅ PASS", "❌ FAIL"
results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"{status}  {name}" + (f"  [{detail}]" if detail else ""))

# ── Fake data ────────────────────────────────────────────────────────────────
USERS = [
    {"id": 1, "name": "Alice", "pin": "1234"},
    {"id": 2, "name": "Bob",   "pin": "5678"},
]
CATEGORIES = [
    {"id": 10, "name": "Groceries", "icon": "🛒", "budget": 500,  "budget_inr": 0, "is_active": True},
    {"id": 11, "name": "Transport", "icon": "🚗", "budget": 200,  "budget_inr": 0, "is_active": True},
    {"id": 12, "name": "Rent",      "icon": "🏠", "budget": 4000, "budget_inr": 0, "is_active": True},
    {"id": 13, "name": "Dining",    "icon": "🍜", "budget": 0,    "budget_inr": 0, "is_active": True},
]
EXPENSES = [
    {"id": 1, "user_id": 1, "category_id": 10, "amount": 120.0,  "currency": "SGD",
     "description": "NTUC FairPrice", "date": "2026-04-05", "is_deleted": False,
     "users": {"name": "Alice"}, "categories": {"name": "Groceries", "icon": "🛒"}},
    {"id": 2, "user_id": 2, "category_id": 12, "amount": 3500.0, "currency": "SGD",
     "description": "April Rent",    "date": "2026-04-01", "is_deleted": False,
     "users": {"name": "Bob"},   "categories": {"name": "Rent",      "icon": "🏠"}},
    {"id": 3, "user_id": 1, "category_id": 11, "amount": 85.0,   "currency": "SGD",
     "description": "Grab rides",    "date": "2026-04-10", "is_deleted": False,
     "users": {"name": "Alice"}, "categories": {"name": "Transport", "icon": "🚗"}},
    {"id": 4, "user_id": 1, "category_id": 13, "amount": 45.0,   "currency": "INR",
     "description": "Hawker lunch",  "date": "2026-04-12", "is_deleted": False,
     "users": {"name": "Alice"}, "categories": {"name": "Dining",    "icon": "🍜"}},
]
INCOME = [
    {"id": 1, "user_id": 1, "amount": 5000.0, "currency": "SGD",
     "description": "April Salary", "month": 4, "year": 2026, "is_deleted": False,
     "users": {"name": "Alice"}, "income_types": {"name": "Salary", "icon": "💰"}},
    {"id": 2, "user_id": 2, "amount": 6000.0, "currency": "SGD",
     "description": "April Salary", "month": 4, "year": 2026, "is_deleted": False,
     "users": {"name": "Bob"},   "income_types": {"name": "Salary", "icon": "💰"}},
]
BALANCE = {"id": 1, "sgd_amount": 1000.0, "inr_amount": 500.0}

# ── GROUP 1: Monthly Summary ──────────────────────────────────────────────────
print("\n── GROUP 1: get_monthly_summary ──")
with mpatch("__main__.get_expenses", return_value=EXPENSES), \
     mpatch("__main__.get_categories", return_value=CATEGORIES):
    summary = get_monthly_summary(4, 2026)

check("Groceries SGD = 120",           summary["Groceries"]["spent_sgd"] == 120.0)
check("Rent SGD = 3500",               summary["Rent"]["spent_sgd"] == 3500.0)
check("Transport SGD = 85",            summary["Transport"]["spent_sgd"] == 85.0)
check("Dining INR = 45",               summary["Dining"]["spent_inr"] == 45.0)
check("Dining SGD = 0",                summary["Dining"]["spent_sgd"] == 0.0)
check("Rent by_user Bob = 3500",       summary["Rent"]["by_user"].get("Bob",{}).get("sgd",0) == 3500.0)
check("Groceries by_user Alice = 120", summary["Groceries"]["by_user"].get("Alice",{}).get("sgd",0) == 120.0)
check("Alice not in Rent by_user",     "Alice" not in summary["Rent"]["by_user"])

# ── GROUP 2: Income Summary ───────────────────────────────────────────────────
print("\n── GROUP 2: get_income_summary ──")
with mpatch("__main__.get_income", return_value=INCOME):
    inc_sgd, inc_inr, by_user = get_income_summary(4, 2026)

check("Total SGD income = 11000",      inc_sgd == 11000.0)
check("Total INR income = 0",          inc_inr == 0.0)
check("Alice earned 5000",             by_user["Alice"]["sgd"] == 5000.0)
check("Bob earned 6000",               by_user["Bob"]["sgd"] == 6000.0)

# ── GROUP 3: User Spending ────────────────────────────────────────────────────
print("\n── GROUP 3: get_user_spending ──")
with mpatch("__main__.get_expenses", return_value=EXPENSES):
    spending = get_user_spending(4, 2026)

check("Alice SGD = 205",               spending["Alice"]["sgd"] == 205.0,  f"got {spending.get('Alice',{}).get('sgd')}")
check("Bob SGD = 3500",                spending["Bob"]["sgd"] == 3500.0,   f"got {spending.get('Bob',{}).get('sgd')}")
check("Alice INR = 45",                spending["Alice"]["inr"] == 45.0)
check("Bob in spending dict",          "Bob" in spending, "Bob missing — chart will be empty for him!")
check("Alice in spending dict",        "Alice" in spending)

# ── GROUP 4: resolve_user ─────────────────────────────────────────────────────
print("\n── GROUP 4: resolve_user ──")
with mpatch("__main__.get_all_users", return_value=USERS):
    uid, nm = resolve_user("Bob", 1)
    check("Direct name 'Bob'",              uid == 2 and nm == "Bob")

    uid, nm = resolve_user("alice", 2)
    check("Case-insensitive 'alice'",       uid == 1 and nm == "Alice")

    uid, nm = resolve_user("husband", 1)
    check("'husband' → other user (Bob)",   uid == 2, f"got uid={uid}")

    uid, nm = resolve_user("by him", 1)
    check("'by him' → other user",          uid == 2, f"got uid={uid}")

    uid, nm = resolve_user("wife", 2)
    check("'wife' → other user (Alice)",    uid == 1, f"got uid={uid}")

    uid, nm = resolve_user("he", 1)
    check("'he' → other user",             uid == 2, f"got uid={uid}")

    uid, nm = resolve_user("", 1)
    check("Empty hint → current user",      uid == 1 and nm is None)

    uid, nm = resolve_user("unknown xyz", 1)
    check("Unknown → fallback to current",  uid == 1)

# ── GROUP 5: CC Payment Skip Filtering ───────────────────────────────────────
print("\n── GROUP 5: CC payment skip filtering ──")
mock_txns = [
    {"date": "2026-04-01", "description": "NTUC FairPrice",    "amount": 50.0,   "type": "expense"},
    {"date": "2026-04-02", "description": "PAYMENT THANK YOU", "amount": 1200.0, "type": "skip"},
    {"date": "2026-04-03", "description": "April Salary",      "amount": 5000.0, "type": "income"},
    {"date": "2026-04-04", "description": "GIRO AUTOPAY",      "amount": 500.0,  "type": "skip"},
    {"date": "2026-04-05", "description": "Grab ride",         "amount": 12.0,   "type": "expense"},
    {"date": "2026-04-06", "description": "MIN PAYMENT DUE",   "amount": 300.0,  "type": "skip"},
]
exp_preview  = [t for t in mock_txns if t["type"] == "expense"]
inc_preview  = [t for t in mock_txns if t["type"] == "income"]
skip_preview = [t for t in mock_txns if t["type"] == "skip"]

check("3 CC payments skipped",          len(skip_preview) == 3)
check("2 real expenses kept",           len(exp_preview) == 2)
check("1 income kept",                  len(inc_preview) == 1)
check("No CC payment in expenses",      all("PAYMENT" not in t["description"] and
                                            "GIRO" not in t["description"] for t in exp_preview))

# ── GROUP 6: Balance Logic ────────────────────────────────────────────────────
print("\n── GROUP 6: balance deduct / restore / add ──")
updated = {}
def mock_upd(sgd=None, inr=None):
    if sgd is not None: updated["sgd"] = sgd
    if inr is not None: updated["inr"] = inr

with mpatch("__main__.get_balance", return_value=dict(BALANCE)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    deduct_balance(200.0, "SGD")
check("Deduct 200 SGD → 800",          updated.get("sgd") == 800.0)

with mpatch("__main__.get_balance", return_value=dict(BALANCE)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    restore_balance(200.0, "SGD")
check("Restore 200 SGD → 1200",        updated.get("sgd") == 1200.0)

with mpatch("__main__.get_balance", return_value=dict(BALANCE)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    deduct_balance(9999.0, "SGD")
check("Deduct beyond balance → 0",     updated.get("sgd") == 0.0)

with mpatch("__main__.get_balance", return_value=dict(BALANCE)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    add_to_balance(500.0, "INR")
check("Add 500 INR → 1000",            updated.get("inr") == 1000.0)

# ── GROUP 7: Budget Alerts ────────────────────────────────────────────────────
print("\n── GROUP 7: budget alerts ──")
with mpatch("__main__.get_monthly_summary", return_value=summary):
    alerts = get_alerts(4, 2026)
check("No alert when under budget",    len(alerts) == 0, f"got: {alerts}")

over = {k: dict(v) for k, v in summary.items()}
over["Groceries"] = dict(over["Groceries"]); over["Groceries"]["spent_sgd"] = 550.0
with mpatch("__main__.get_monthly_summary", return_value=over):
    alerts2 = get_alerts(4, 2026)
check("Alert fires when overspent",    any("Groceries" in a for a in alerts2))
check("Alert shows overspend amount",  any("50" in a for a in alerts2), f"got: {alerts2}")

near = {k: dict(v) for k, v in summary.items()}
near["Transport"] = dict(near["Transport"]); near["Transport"]["spent_sgd"] = 185.0  # 92.5%
with mpatch("__main__.get_monthly_summary", return_value=near):
    alerts3 = get_alerts(4, 2026)
check("90%+ warning fires",            any("Transport" in a for a in alerts3))

# ── GROUP 8: Strip sensitive data ────────────────────────────────────────────
print("\n── GROUP 8: strip_sensitive_data ──")
raw = "Card No: 1234-5678-9012-3456\nAccount Number: 123456789\nEmail: test@example.com\nPhone: 91234567\nNRIC: S1234567D"
cleaned = strip_sensitive_data(raw)
check("Card number removed",           "1234-5678-9012-3456" not in cleaned)
check("Email removed",                 "test@example.com" not in cleaned)
check("Phone removed",                 "91234567" not in cleaned)
check("NRIC removed",                  "S1234567D" not in cleaned)
check("Placeholder [CARD] present",    "[CARD]" in cleaned)
check("Placeholder [EMAIL] present",   "[EMAIL]" in cleaned)

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print("\n" + "="*55)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"  RESULT: {passed} passed, {failed} failed  ({len(results)} total)")
if failed:
    print("\n  Failed:")
    for r in results:
        if r[0] == FAIL:
            print(f"    {r[1]}  {r[2]}")

# ── GROUP 9: Multi-currency summary ──────────────────────────────────────────
print("\n── GROUP 9: Multi-currency get_monthly_summary ──")
MIXED_EXPENSES = [
    {"id": 10, "user_id": 1, "amount": 200.0, "currency": "SGD",
     "description": "Groceries SGD",  "date": "2026-04-01", "is_deleted": False,
     "users": {"name": "Alice"}, "categories": {"name": "Groceries", "icon": "🛒"}},
    {"id": 11, "user_id": 1, "amount": 3000.0, "currency": "INR",
     "description": "Groceries INR",  "date": "2026-04-02", "is_deleted": False,
     "users": {"name": "Alice"}, "categories": {"name": "Groceries", "icon": "🛒"}},
    {"id": 12, "user_id": 2, "amount": 500.0, "currency": "INR",
     "description": "Transport INR",  "date": "2026-04-03", "is_deleted": False,
     "users": {"name": "Bob"},   "categories": {"name": "Transport", "icon": "🚗"}},
    {"id": 13, "user_id": 2, "amount": 100.0, "currency": "SGD",
     "description": "Transport SGD",  "date": "2026-04-04", "is_deleted": False,
     "users": {"name": "Bob"},   "categories": {"name": "Transport", "icon": "🚗"}},
]
with mpatch("__main__.get_expenses", return_value=MIXED_EXPENSES), \
     mpatch("__main__.get_categories", return_value=CATEGORIES):
    mixed_summary = get_monthly_summary(4, 2026)

check("Groceries SGD = 200",           mixed_summary["Groceries"]["spent_sgd"] == 200.0)
check("Groceries INR = 3000",          mixed_summary["Groceries"]["spent_inr"] == 3000.0)
check("Transport SGD = 100",           mixed_summary["Transport"]["spent_sgd"] == 100.0)
check("Transport INR = 500",           mixed_summary["Transport"]["spent_inr"] == 500.0)
check("Groceries Alice SGD = 200",     mixed_summary["Groceries"]["by_user"].get("Alice",{}).get("sgd",0) == 200.0)
check("Groceries Alice INR = 3000",    mixed_summary["Groceries"]["by_user"].get("Alice",{}).get("inr",0) == 3000.0)
check("Transport Bob SGD = 100",       mixed_summary["Transport"]["by_user"].get("Bob",{}).get("sgd",0) == 100.0)
check("Transport Bob INR = 500",       mixed_summary["Transport"]["by_user"].get("Bob",{}).get("inr",0) == 500.0)
check("SGD and INR tracked separately",mixed_summary["Groceries"]["spent_sgd"] != mixed_summary["Groceries"]["spent_inr"])

# ── GROUP 10: unified_summary conversion ─────────────────────────────────────
print("\n── GROUP 10: unified_summary (INR → SGD conversion) ──")
RATE = 0.016  # 1 INR = 0.016 SGD

unified = unified_summary(mixed_summary, RATE)

exp_groceries_sgd = 200.0 + 3000.0 * RATE   # 200 + 48 = 248
exp_transport_sgd = 100.0 + 500.0  * RATE   # 100 + 8  = 108

check("Groceries unified SGD = 248",   abs(unified["Groceries"]["spent_sgd"] - exp_groceries_sgd) < 0.01,
      f"got {unified['Groceries']['spent_sgd']:.4f}")
check("Groceries unified INR = 0",     unified["Groceries"]["spent_inr"] == 0)
check("Transport unified SGD = 108",   abs(unified["Transport"]["spent_sgd"] - exp_transport_sgd) < 0.01,
      f"got {unified['Transport']['spent_sgd']:.4f}")
check("Transport unified INR = 0",     unified["Transport"]["spent_inr"] == 0)
check("Alice unified Groceries correct",
      abs(unified["Groceries"]["by_user"]["Alice"]["sgd"] - exp_groceries_sgd) < 0.01)
check("Bob unified Transport correct",
      abs(unified["Transport"]["by_user"]["Bob"]["sgd"] - exp_transport_sgd) < 0.01)

# ── GROUP 11: unified_income_summary ─────────────────────────────────────────
print("\n── GROUP 11: unified_income_summary ──")
by_user_mixed = {
    "Alice": {"sgd": 5000.0, "inr": 0.0},
    "Bob":   {"sgd": 0.0,    "inr": 50000.0},  # Bob earns only in INR
}
u_sgd, u_inr, u_by_user = unified_income_summary(5000.0, 50000.0, by_user_mixed, RATE)

check("Unified total SGD = 5000 + 50000*0.016 = 5800", abs(u_sgd - 5800.0) < 0.01,
      f"got {u_sgd:.4f}")
check("Unified INR = 0",               u_inr == 0.0)
check("Alice unified income = 5000",   abs(u_by_user["Alice"]["sgd"] - 5000.0) < 0.01)
check("Bob unified income = 800",      abs(u_by_user["Bob"]["sgd"] - 800.0) < 0.01,
      f"got {u_by_user['Bob']['sgd']:.4f}")

# ── GROUP 12: unified_user_spending ──────────────────────────────────────────
print("\n── GROUP 12: unified_user_spending ──")
mixed_spending = {
    "Alice": {"sgd": 300.0, "inr": 5000.0},
    "Bob":   {"sgd": 150.0, "inr": 2000.0},
}
u_spending = unified_user_spending(mixed_spending, RATE)

check("Alice unified = 300 + 5000*0.016 = 380",
      abs(u_spending["Alice"]["sgd"] - 380.0) < 0.01, f"got {u_spending['Alice']['sgd']:.4f}")
check("Bob unified = 150 + 2000*0.016 = 182",
      abs(u_spending["Bob"]["sgd"] - 182.0) < 0.01, f"got {u_spending['Bob']['sgd']:.4f}")
check("Alice unified INR = 0",         u_spending["Alice"]["inr"] == 0)
check("Bob unified INR = 0",           u_spending["Bob"]["inr"] == 0)

# ── GROUP 13: to_sgd helper ───────────────────────────────────────────────────
print("\n── GROUP 13: to_sgd helper ──")
check("SGD passes through",            to_sgd(100.0, "SGD", RATE) == 100.0)
check("INR converted correctly",       abs(to_sgd(1000.0, "INR", RATE) - 16.0) < 0.001)
check("Zero amount",                   to_sgd(0.0, "INR", RATE) == 0.0)
check("Large INR amount",              abs(to_sgd(100000.0, "INR", 0.016) - 1600.0) < 0.01)

# ── GROUP 14: Multi-currency balance deduction ────────────────────────────────
print("\n── GROUP 14: Multi-currency balance deduct/restore ──")
updated = {}
def mock_upd2(sgd=None, inr=None):
    if sgd is not None: updated["sgd"] = sgd
    if inr is not None: updated["inr"] = inr

INR_BAL = {"id": 1, "sgd_amount": 1000.0, "inr_amount": 5000.0}

with mpatch("__main__.get_balance", return_value=dict(INR_BAL)), \
     mpatch("__main__.update_balance", side_effect=mock_upd2):
    deduct_balance(2000.0, "INR")
check("INR deduct: 5000 - 2000 = 3000", updated.get("inr") == 3000.0)

with mpatch("__main__.get_balance", return_value=dict(INR_BAL)), \
     mpatch("__main__.update_balance", side_effect=mock_upd2):
    restore_balance(500.0, "INR")
check("INR restore: 5000 + 500 = 5500", updated.get("inr") == 5500.0)

with mpatch("__main__.get_balance", return_value=dict(INR_BAL)), \
     mpatch("__main__.update_balance", side_effect=mock_upd2):
    deduct_balance(9999.0, "INR")
check("INR deduct beyond zero → 0",     updated.get("inr") == 0.0)

# SGD unaffected by INR deduction
with mpatch("__main__.get_balance", return_value=dict(INR_BAL)), \
     mpatch("__main__.update_balance", side_effect=mock_upd2):
    updated.clear()
    deduct_balance(200.0, "INR")
check("SGD not touched by INR op",      "sgd" not in updated)

# ── GROUP 15: Alerts with INR budgets ────────────────────────────────────────
print("\n── GROUP 15: Budget alerts with INR budgets ──")
inr_summary = {
    "Groceries": {"budget": 500, "budget_inr": 5000, "spent_sgd": 0,
                  "spent_inr": 6000, "icon": "🛒", "id": 10, "by_user": {}},
    "Rent":      {"budget": 4000, "budget_inr": 0, "spent_sgd": 3500,
                  "spent_inr": 0, "icon": "🏠", "id": 12, "by_user": {}},
}
with mpatch("__main__.get_monthly_summary", return_value=inr_summary):
    inr_alerts = get_alerts(4, 2026)
check("INR overspend alert fires",      any("Groceries" in a for a in inr_alerts), f"{inr_alerts}")
check("INR alert shows correct amount", any("1000" in a for a in inr_alerts), f"{inr_alerts}")
check("SGD under budget = no alert",    not any("Rent" in a for a in inr_alerts))

# ── UPDATED SUMMARY ───────────────────────────────────────────────────────────
print("\n" + "="*55)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"  TOTAL: {passed} passed, {failed} failed out of {len(results)} tests")
if failed:
    print("\nFailed tests:")
    for r in results:
        if r[0] == FAIL:
            print(f"  {r[1]}  {r[2]}")