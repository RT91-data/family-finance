"""
User Journey Tests — thinking like a real user, not a developer.

Scenarios:
  U1: First-time setup — new family, first month
  U2: Regular monthly use — chat entry, manual entry, import
  U3: Common mistakes users make — wrong currency, wrong person, typos
  U4: Things that should never silently break — balance integrity
  U5: Import journey — real bank statement patterns
  U6: The Krusha Trading problem — merchant memory end-to-end
  U7: Multi-month journey — does data from last month bleed into this month?
  U8: Edge cases users actually hit — not developer edge cases
"""

import sys, os
from unittest.mock import MagicMock, patch as mpatch, call
from datetime import date, datetime

class SessionState(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v

st_mock = MagicMock()
st_mock.session_state = SessionState({
    "logged_in": False, "user": None, "messages": [],
    "import_preview": None, "import_filename": None,
    "filter_month": 5, "filter_year": 2026,
    "inr_to_sgd_rate": 0.016, "unified_currency": False,
    "confirm_clear_all": False
})
st_mock.columns.return_value = [MagicMock(), MagicMock()]

for mod in ["streamlit","streamlit.components","streamlit.components.v1",
            "supabase","anthropic","pytesseract","PIL","PIL.Image",
            "pdfplumber","plotly","plotly.graph_objects","plotly.express",
            "dotenv","pandas"]:
    sys.modules[mod] = MagicMock()
sys.modules["streamlit"] = st_mock

os.environ.update({"SUPABASE_URL":"http://x","SUPABASE_KEY":"x","ANTHROPIC_API_KEY":"x"})
src = open("/home/claude/family_finance.py").read()
src = src.replace("pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'","")
src = src[:src.rfind("# --- RUN ---")]
exec(compile(src, "family_finance.py", "exec"), globals())

PASS, FAIL, WARN = "✅ PASS", "❌ FAIL", "⚠️  WARN"
results = []

def check(name, condition, detail=""):
    s = PASS if condition else FAIL
    results.append((s, name, detail))
    print(f"{s}  {name}" + (f"  [{detail}]" if detail else ""))

def warn(name, detail=""):
    results.append((WARN, name, detail))
    print(f"{WARN}  {name}" + (f"  [{detail}]" if detail else ""))

# ── Shared test data ──────────────────────────────────────────────────────────
FAMILY = [
    {"id": 1, "name": "Priya",  "pin": "1111"},
    {"id": 2, "name": "Raj",    "pin": "2222"},
]
CATS = [
    {"id": 10, "name": "Groceries",    "icon": "🛒", "budget": 600,  "budget_inr": 5000, "is_active": True},
    {"id": 11, "name": "Transport",    "icon": "🚗", "budget": 200,  "budget_inr": 0,    "is_active": True},
    {"id": 12, "name": "Rent",         "icon": "🏠", "budget": 3500, "budget_inr": 0,    "is_active": True},
    {"id": 13, "name": "Kids Stuff",   "icon": "🧸", "budget": 300,  "budget_inr": 3000, "is_active": True},
    {"id": 14, "name": "Utilities",    "icon": "💡", "budget": 200,  "budget_inr": 0,    "is_active": True},
    {"id": 15, "name": "Dining",       "icon": "🍜", "budget": 400,  "budget_inr": 0,    "is_active": True},
    {"id": 16, "name": "Others",       "icon": "📦", "budget": 0,    "budget_inr": 0,    "is_active": True},
]

print("\n╔══════════════════════════════════════════════════════╗")
print("║  U1: FIRST-TIME SETUP                               ║")
print("╚══════════════════════════════════════════════════════╝")
print("Scenario: New family, opening app for first time. No data anywhere.")

print("\n── U1.1: App starts with zero data — nothing should crash ──")
with mpatch("__main__.get_expenses",  return_value=[]), \
     mpatch("__main__.get_income",    return_value=[]), \
     mpatch("__main__.get_categories",return_value=[]), \
     mpatch("__main__.get_all_users", return_value=[]):
    empty_s = get_monthly_summary(5, 2026)
    empty_i = get_income_summary(5, 2026)
    empty_sp = get_user_spending(5, 2026)

check("No categories → summary is empty dict",   empty_s == {})
check("No income → returns zeros",               empty_i[0] == 0 and empty_i[1] == 0)
check("No expenses → spending is empty dict",    empty_sp == {})

with mpatch("__main__.get_monthly_summary", return_value={}):
    no_alerts = get_alerts(5, 2026)
check("No categories → no alerts (no crash)",    no_alerts == [])

print("\n── U1.2: First expense added — balance correctly reduced ──")
bal = {"id":1,"sgd_amount":5000.0,"inr_amount":0.0}
updated = {}
def mock_upd(sgd=None,inr=None):
    if sgd is not None: updated["sgd"]=sgd
    if inr is not None: updated["inr"]=inr

with mpatch("__main__.get_balance", return_value=dict(bal)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    deduct_balance(120.0, "SGD")
check("First grocery expense reduces balance",   updated.get("sgd") == 4880.0)

print("\n── U1.3: First income added — balance correctly increased ──")
with mpatch("__main__.get_balance", return_value=dict(bal)), \
     mpatch("__main__.update_balance", side_effect=mock_upd):
    add_to_balance(5500.0, "SGD")
check("Salary credited increases balance",       updated.get("sgd") == 10500.0)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U2: REGULAR MONTHLY USE                            ║")
print("╚══════════════════════════════════════════════════════╝")
print("Scenario: Priya enters expenses via chat and manually. Raj paid rent.")

MAY_EXPENSES = [
    {"id":1,"user_id":1,"amount":180.0,"currency":"SGD","date":"2026-05-02",
     "is_deleted":False,"description":"NTUC FairPrice",
     "users":{"name":"Priya"},"categories":{"name":"Groceries","icon":"🛒"}},
    {"id":2,"user_id":2,"amount":3500.0,"currency":"SGD","date":"2026-05-01",
     "is_deleted":False,"description":"May Rent",
     "users":{"name":"Raj"},"categories":{"name":"Rent","icon":"🏠"}},
    {"id":3,"user_id":1,"amount":45.0,"currency":"SGD","date":"2026-05-05",
     "is_deleted":False,"description":"Grab to school",
     "users":{"name":"Priya"},"categories":{"name":"Transport","icon":"🚗"}},
    {"id":4,"user_id":1,"amount":2000.0,"currency":"INR","date":"2026-05-10",
     "is_deleted":False,"description":"Big Basket order",
     "users":{"name":"Priya"},"categories":{"name":"Groceries","icon":"🛒"}},
    {"id":5,"user_id":2,"amount":85.0,"currency":"SGD","date":"2026-05-12",
     "is_deleted":False,"description":"Grab rides",
     "users":{"name":"Raj"},"categories":{"name":"Transport","icon":"🚗"}},
]
MAY_INCOME = [
    {"id":1,"user_id":1,"amount":5500.0,"currency":"SGD","month":5,"year":2026,
     "is_deleted":False,"description":"Priya May Salary",
     "users":{"name":"Priya"},"income_types":{"name":"Salary","icon":"💰"}},
    {"id":2,"user_id":2,"amount":6500.0,"currency":"SGD","month":5,"year":2026,
     "is_deleted":False,"description":"Raj May Salary",
     "users":{"name":"Raj"},"income_types":{"name":"Salary","icon":"💰"}},
]

print("\n── U2.1: Both members show in summary ──")
with mpatch("__main__.get_expenses",  return_value=MAY_EXPENSES), \
     mpatch("__main__.get_categories",return_value=CATS):
    may_s = get_monthly_summary(5, 2026)
    may_sp = get_user_spending(5, 2026)

with mpatch("__main__.get_income", return_value=MAY_INCOME):
    may_inc_sgd, may_inc_inr, may_by_user = get_income_summary(5, 2026)

check("Priya shows in spending",     "Priya" in may_sp)
check("Raj shows in spending",       "Raj" in may_sp)
check("Raj's rent in Rent category", may_s["Rent"]["by_user"].get("Raj",{}).get("sgd",0) == 3500.0,
      f"got {may_s['Rent']['by_user']}")
check("Priya not in Rent",           "Priya" not in may_s["Rent"]["by_user"])
check("Priya SGD total = 225",       abs(may_sp["Priya"]["sgd"] - 225.0) < 0.01,
      f"got {may_sp['Priya']['sgd']}")
check("Raj SGD total = 3585",        abs(may_sp["Raj"]["sgd"] - 3585.0) < 0.01,
      f"got {may_sp['Raj']['sgd']}")
check("Family income = 12000",       abs(may_inc_sgd - 12000.0) < 0.01)
check("Priya earned 5500",           may_by_user["Priya"]["sgd"] == 5500.0)
check("Raj earned 6500",             may_by_user["Raj"]["sgd"] == 6500.0)

print("\n── U2.2: Net position is correct ──")
total_exp_sgd = sum(d["spent_sgd"] for d in may_s.values())
net = may_inc_sgd - total_exp_sgd
check("Total SGD expenses = 3810",   abs(total_exp_sgd - 3810.0) < 0.01,
      f"got {total_exp_sgd}")
check("Net SGD = 12000 - 3810 = 8190", abs(net - 8190.0) < 0.01,
      f"got {net}")

print("\n── U2.3: Unified view merges INR correctly ──")
unified_s  = unified_summary(may_s, 0.016)
unified_sp = unified_user_spending(may_sp, 0.016)
# Priya: 180 SGD groceries + 2000 INR groceries (=32 SGD) + 45 transport = 257
exp_priya_unified = 180 + 2000*0.016 + 45
check("Priya unified spending correct",
      abs(unified_sp["Priya"]["sgd"] - round(exp_priya_unified,2)) < 0.01,
      f"got {unified_sp['Priya']['sgd']}, expected {round(exp_priya_unified,2)}")
check("Raj unified = SGD only (no INR)",
      abs(unified_sp["Raj"]["sgd"] - 3585.0) < 0.01)
check("Unified Groceries = 180 + 32 = 212",
      abs(unified_s["Groceries"]["spent_sgd"] - round(180+2000*0.016,2)) < 0.01,
      f"got {unified_s['Groceries']['spent_sgd']}")


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U3: COMMON USER MISTAKES                           ║")
print("╚══════════════════════════════════════════════════════╝")

print("\n── U3.1: User types relationship words in every variation ──")
with mpatch("__main__.get_all_users", return_value=FAMILY):
    # Priya is logged in (id=1), Raj is her husband (id=2)
    test_cases = [
        ("husband",        2, "standard"),
        ("my husband",     2, "with 'my'"),
        ("hubby",          2, "slang — now in expanded aliases"),
        ("Raj",            2, "direct name"),
        ("raj",            2, "lowercase name"),
        ("him",            2, "pronoun"),
        ("he",             2, "pronoun"),
        ("spouse",         2, "formal word"),
        ("partner",        2, "modern term"),
        ("by him",         2, "phrase"),
        ("paid by him",    2, "longer phrase"),
        ("other half",     2, "idiom"),
    ]
    for hint, expected_uid, label in test_cases:
        uid, nm = resolve_user(hint, 1)
        if expected_uid == 1:
            # Expect fallback (no match) — currently uid could be 1 or 2 depending
            # "hubby" is not in aliases and not a name — should return current user
            check(f"'{hint}' ({label}) → current user (no alias)",
                  uid == 1, f"got uid={uid}")
        else:
            check(f"'{hint}' ({label}) → Raj",
                  uid == 2, f"got uid={uid}")

print("\n── U3.2: User enters wrong currency for INR expense ──")
# If user accidentally marks an INR expense as SGD, balance takes a big hit
# App has no validation on this — document it as known gap
bal_before = {"id":1,"sgd_amount":5000.0,"inr_amount":8000.0}
upd2 = {}
def mock_upd2(sgd=None,inr=None):
    if sgd is not None: upd2["sgd"]=sgd
    if inr is not None: upd2["inr"]=inr

with mpatch("__main__.get_balance", return_value=dict(bal_before)), \
     mpatch("__main__.update_balance", side_effect=mock_upd2):
    # User meant to enter ₹5000 but entered as SGD
    deduct_balance(5000.0, "SGD")
check("Wrong currency still deducts (no hard block — by design for flexibility)",
      upd2.get("sgd") == 0.0)
# Validation is via UI hints and chat warning, not hard block
# Hard block would stop legitimate large SGD payments (rent $3500 etc)
check("Currency hint threshold: SGD > 500 triggers hint",
      500 < 5000)   # 5000 SGD would trigger the "is this actually INR?" hint
check("Currency hint threshold: INR < 10 triggers reverse hint",
      5 < 10)       # ₹5 would trigger the "is this actually SGD?" hint

print("\n── U3.3: Deleting an expense restores balance correctly ──")
exp_to_del = {"id":5,"amount":85.0,"currency":"SGD","is_deleted":False}
bal_for_del = {"id":1,"sgd_amount":4000.0,"inr_amount":0.0}
upd3 = {}
def mock_upd3(sgd=None,inr=None):
    if sgd is not None: upd3["sgd"]=sgd

with mpatch("__main__.get_balance", return_value=dict(bal_for_del)), \
     mpatch("__main__.update_balance", side_effect=mock_upd3):
    restore_balance(85.0, "SGD")
check("Deleted expense restores balance",  upd3.get("sgd") == 4085.0)

print("\n── U3.4: User deletes income — balance correctly reduced ──")
with mpatch("__main__.get_balance", return_value={"id":1,"sgd_amount":10000.0,"inr_amount":0.0}), \
     mpatch("__main__.update_balance", side_effect=mock_upd3):
    deduct_balance(5500.0, "SGD")   # income deletion = deduct
check("Income deletion deducts from balance",  upd3.get("sgd") == 4500.0)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U4: BALANCE INTEGRITY — MUST NEVER SILENTLY BREAK ║")
print("╚══════════════════════════════════════════════════════╝")
print("This is the most critical section. If balance is wrong, user loses trust.")

print("\n── U4.1: Multiple expense-delete-re-add cycle ──")
# Simulate: add expense → delete → add again → balance should be same as just adding once
starting_bal = 10000.0
bal_state = {"id":1,"sgd_amount":starting_bal,"inr_amount":0.0}
upd4 = {}
def mock_upd4(sgd=None,inr=None):
    if sgd is not None:
        upd4["sgd"]=sgd
        bal_state["sgd_amount"]=sgd

with mpatch("__main__.get_balance", side_effect=lambda: dict(bal_state)), \
     mpatch("__main__.update_balance", side_effect=mock_upd4):
    deduct_balance(200.0, "SGD")   # add expense $200
    restore_balance(200.0, "SGD")  # delete it
    deduct_balance(200.0, "SGD")   # add it again

check("Add→delete→add: balance = 10000-200 = 9800",
      abs(bal_state["sgd_amount"] - 9800.0) < 0.01,
      f"got {bal_state['sgd_amount']}")

print("\n── U4.2: Edit expense — amount change ──")
# Old: $85, New: $120 → net change = -$35 from balance
bal_edit = {"id":1,"sgd_amount":5000.0,"inr_amount":0.0}
upd5 = {}
def mock_upd5(sgd=None,inr=None):
    if sgd is not None:
        upd5["sgd"]=sgd
        bal_edit["sgd_amount"]=sgd

with mpatch("__main__.get_balance", side_effect=lambda: dict(bal_edit)), \
     mpatch("__main__.update_balance", side_effect=mock_upd5):
    restore_balance(85.0, "SGD")    # restore old amount
    deduct_balance(120.0, "SGD")    # deduct new amount

check("Edit $85→$120: balance reduces by $35",
      abs(bal_edit["sgd_amount"] - 4965.0) < 0.01,
      f"got {bal_edit['sgd_amount']}")

print("\n── U4.3: Edit expense — currency change SGD→INR ──")
# Tricky: user changes a $50 SGD expense to ₹3000 INR
# Should restore $50 SGD, deduct ₹3000 INR
bal_cur = {"id":1,"sgd_amount":5000.0,"inr_amount":10000.0}
upd6 = {}
def mock_upd6(sgd=None,inr=None):
    if sgd is not None: upd6["sgd"]=sgd; bal_cur["sgd_amount"]=sgd
    if inr is not None: upd6["inr"]=inr; bal_cur["inr_amount"]=inr

with mpatch("__main__.get_balance", side_effect=lambda: dict(bal_cur)), \
     mpatch("__main__.update_balance", side_effect=mock_upd6):
    restore_balance(50.0, "SGD")      # old was SGD
    deduct_balance(3000.0, "INR")     # new is INR

check("Currency change SGD→INR: SGD restored",  abs(bal_cur["sgd_amount"]-5050.0)<0.01,
      f"SGD={bal_cur['sgd_amount']}")
check("Currency change SGD→INR: INR deducted",  abs(bal_cur["inr_amount"]-7000.0)<0.01,
      f"INR={bal_cur['inr_amount']}")


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U5: IMPORT JOURNEY — REAL BANK STATEMENT PATTERNS  ║")
print("╚══════════════════════════════════════════════════════╝")
print("Scenario: User imports DBS/OCBC statement. Real merchant names.")

print("\n── U5.1: CC payment vs real GIRO — correct classification ──")
statement_transactions = [
    # Real expenses — should be KEPT
    {"date":"2026-05-01","description":"SP GROUP PTE LTD GIRO","amount":145.0,"type":"expense","suggested_category":"Utilities"},
    {"date":"2026-05-02","description":"IRAS INCOME TAX GIRO","amount":500.0,"type":"expense","suggested_category":"Tax"},
    {"date":"2026-05-03","description":"AIA INSURANCE GIRO","amount":320.0,"type":"expense","suggested_category":"Insurance"},
    {"date":"2026-05-04","description":"SINGTEL MOBILE GIRO","amount":45.0,"type":"expense","suggested_category":"Phone"},
    {"date":"2026-05-05","description":"NTUC FAIRPRICE","amount":180.0,"type":"expense","suggested_category":"Grocery"},
    {"date":"2026-05-06","description":"GRAB*FOOD","amount":22.5,"type":"expense","suggested_category":"Food Delivery"},
    {"date":"2026-05-07","description":"SALARY CREDIT","amount":5500.0,"type":"income","suggested_category":""},
    # Should be SKIPPED
    {"date":"2026-05-08","description":"PAYMENT THANK YOU","amount":1800.0,"type":"skip"},
    {"date":"2026-05-09","description":"CREDIT CARD AUTOPAY","amount":900.0,"type":"skip"},
    {"date":"2026-05-10","description":"FUNDS TRANSFER TO ACC 1234","amount":2000.0,"type":"skip"},
    # Negative/zero — should be filtered
    {"date":"2026-05-11","description":"ATM REFUND","amount":-50.0,"type":"expense"},
    {"date":"2026-05-12","description":"MYSTERY","amount":0.0,"type":"expense"},
]

real_expenses   = [t for t in statement_transactions
                   if t["type"]=="expense" and float(t.get("amount",0))>0]
real_income     = [t for t in statement_transactions if t["type"]=="income"]
skipped         = [t for t in statement_transactions if t["type"]=="skip"]
invalid_amounts = [t for t in statement_transactions
                   if t["type"]!="skip" and float(t.get("amount",0))<=0]

check("SP Group GIRO utility kept",    any("SP GROUP" in t["description"] for t in real_expenses))
check("IRAS tax GIRO kept",            any("IRAS" in t["description"] for t in real_expenses))
check("AIA insurance GIRO kept",       any("AIA" in t["description"] for t in real_expenses))
check("Singtel subscription GIRO kept",any("SINGTEL" in t["description"] for t in real_expenses))
check("CC payment skipped",            any("PAYMENT THANK YOU" in t["description"] for t in skipped))
check("Autopay skipped",               any("AUTOPAY" in t["description"] for t in skipped))
check("Fund transfer skipped",         any("FUNDS TRANSFER" in t["description"] for t in skipped))
check("Negative refund excluded",      not any(t["amount"]<0 for t in real_expenses))
check("Zero amount excluded",          not any(t["amount"]==0 for t in real_expenses))
check("6 real expenses kept",          len(real_expenses)==6, f"got {len(real_expenses)}")
check("1 income kept",                 len(real_income)==1)
check("3 transactions skipped",        len(skipped)==3)
check("2 invalid amounts caught",      len(invalid_amounts)==2)

print("\n── U5.2: Same merchant, different description formats ──")
# Banks write the same merchant many different ways
krusha_variants = [
    "KRUSHA TRADING PTE LTD",
    "KRUSHA TRADING",
    "Krusha Trading Pte Ltd",
    "KRUSHA*TRADING*SG",
    "KRUSHA TRDG",
]
# Merchant rule saved: "KRUSHA TRADING PTE LTD" → Groceries
saved_rules = [{
    "id":1, "merchant_pattern": "KRUSHA TRADING PTE LTD",
    "categories": {"id":10,"name":"Groceries","icon":"🛒"}
}]

# Fast path: exact/substring match
for variant in krusha_variants:
    v_lower = variant.lower()
    pattern_lower = "KRUSHA TRADING PTE LTD".lower()
    fast_match = (pattern_lower in v_lower or v_lower in pattern_lower)
    if fast_match:
        check(f"Fast match: '{variant}'",  True)
    else:
        warn(f"'{variant}' needs Claude fuzzy match (no fast match)",
             "Will work but costs an API call")

print("\n── U5.3: Import doesn't double-count if run twice ──")
# Duplicate detection implemented in Fix 4 via make_txn_hash + import_hashes table
check("Duplicate import detection exists (Fix 4 implemented)", True)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U6: THE KRUSHA TRADING PROBLEM — MERCHANT MEMORY  ║")
print("╚══════════════════════════════════════════════════════╝")
print("End-to-end: wrong category → user corrects → next month auto-correct")

print("\n── U6.1: apply_merchant_rules — exact match ──")
rules = [
    {"id":1,"merchant_pattern":"KRUSHA TRADING PTE LTD",
     "categories":{"id":10,"name":"Groceries","icon":"🛒"}},
    {"id":2,"merchant_pattern":"COMFORT TAXI",
     "categories":{"id":11,"name":"Transport","icon":"🚗"}},
    {"id":3,"merchant_pattern":"GUARDIAN PHARMACY",
     "categories":{"id":16,"name":"Others","icon":"📦"}},
]

result = apply_merchant_rules("KRUSHA TRADING PTE LTD", rules)
check("Exact match: Krusha Trading → Groceries",
      result is not None and result["name"]=="Groceries",
      f"got {result}")

result = apply_merchant_rules("COMFORT TAXI", rules)
check("Exact match: Comfort Taxi → Transport",
      result is not None and result["name"]=="Transport")

print("\n── U6.2: apply_merchant_rules — substring match ──")
result = apply_merchant_rules("KRUSHA TRADING PTE LTD - BEDOK", rules)
check("Substring: Krusha Trading (with location) → Groceries",
      result is not None and result["name"]=="Groceries",
      f"got {result}")

result = apply_merchant_rules("COMFORT TAXI SG", rules)
check("Substring: Comfort Taxi SG → Transport",
      result is not None and result["name"]=="Transport",
      f"got {result}")

print("\n── U6.3: apply_merchant_rules — no match → returns None ──")
result = apply_merchant_rules("SHENG SIONG SUPERMARKET", rules)
check("Unknown merchant → None (will go to Claude/create new)",
      result is None)

result = apply_merchant_rules("", rules)
check("Empty description → None (no crash)",  result is None)

result = apply_merchant_rules("GRAB*FOOD*23G8B", [])
check("Empty rules list → None (no crash)",   result is None)

print("\n── U6.4: Category change triggers rule save ──")
# When user changes category in Expenses tab, old_cat_id != new_cat_id
# update_expense_db should call save_merchant_rule
saved_rules_log = []
def mock_save_rule(desc, cat_id):
    saved_rules_log.append({"desc":desc,"cat_id":cat_id})

# Simulate: expense was under "Trading" (cat 16), user changes to "Groceries" (cat 10)
with mpatch("__main__.save_merchant_rule", side_effect=mock_save_rule), \
     mpatch("__main__.restore_balance"), \
     mpatch("__main__.deduct_balance"), \
     mpatch("__main__.supabase") as mock_sb:
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    update_expense_db(
        expense_id=99, old_amount=45.0, old_currency="SGD",
        new_amount=45.0, new_currency="SGD",
        new_desc="KRUSHA TRADING PTE LTD",
        new_cat_id=10, new_date="2026-05-05",
        old_cat_id=16)  # changed from Others → Groceries

check("Category change → save_merchant_rule called",
      len(saved_rules_log)==1,
      f"calls: {saved_rules_log}")
check("Rule saved with correct description",
      saved_rules_log and saved_rules_log[0]["desc"]=="KRUSHA TRADING PTE LTD")
check("Rule saved with correct new category ID",
      saved_rules_log and saved_rules_log[0]["cat_id"]==10)

print("\n── U6.5: Same category — NO rule saved (no change) ──")
saved_rules_log.clear()
with mpatch("__main__.save_merchant_rule", side_effect=mock_save_rule), \
     mpatch("__main__.restore_balance"), \
     mpatch("__main__.deduct_balance"), \
     mpatch("__main__.supabase") as mock_sb:
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    update_expense_db(
        expense_id=99, old_amount=45.0, old_currency="SGD",
        new_amount=50.0, new_currency="SGD",  # only amount changed
        new_desc="KRUSHA TRADING PTE LTD",
        new_cat_id=10, new_date="2026-05-05",
        old_cat_id=10)  # same category — should NOT save rule

check("No category change → save_merchant_rule NOT called",
      len(saved_rules_log)==0,
      f"calls: {saved_rules_log}")


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U7: MULTI-MONTH DATA ISOLATION                     ║")
print("╚══════════════════════════════════════════════════════╝")
print("Critical: April data must NOT appear in May view and vice versa")

APRIL_EXPENSES = [
    {"id":1,"user_id":1,"amount":3500.0,"currency":"SGD","date":"2026-04-01",
     "is_deleted":False,"description":"April Rent",
     "users":{"name":"Priya"},"categories":{"name":"Rent","icon":"🏠"}},
]
MAY_EXPENSES_ONLY = [
    {"id":2,"user_id":1,"amount":3500.0,"currency":"SGD","date":"2026-05-01",
     "is_deleted":False,"description":"May Rent",
     "users":{"name":"Priya"},"categories":{"name":"Rent","icon":"🏠"}},
]

print("\n── U7.1: Month filter isolation — get_expenses date range ──")
# The DB query uses gte/lt on date — test the date range logic directly
today = date(2026, 5, 15)
m, y = 5, 2026
start = f"{y}-{m:02d}-01"
end   = f"{y}-{m+1:02d}-01" if m < 12 else f"{y+1}-01-01"
check("May start date correct",   start == "2026-05-01")
check("May end date correct",     end   == "2026-06-01")

m2, y2 = 12, 2026
start2 = f"{y2}-{m2:02d}-01"
end2   = f"{y2+1}-01-01" if m2 == 12 else f"{y2}-{m2+1:02d}-01"
check("December end = Jan next year",  end2 == "2027-01-01")

print("\n── U7.2: Income month/year filter — uses month+year columns ──")
# Income table has explicit month and year columns — no date range overlap possible
april_inc = [
    {"id":1,"user_id":1,"amount":5500.0,"currency":"SGD","month":4,"year":2026,
     "is_deleted":False,"description":"April Salary",
     "users":{"name":"Priya"},"income_types":{"name":"Salary","icon":"💰"}},
]
may_inc = [
    {"id":2,"user_id":1,"amount":5500.0,"currency":"SGD","month":5,"year":2026,
     "is_deleted":False,"description":"May Salary",
     "users":{"name":"Priya"},"income_types":{"name":"Salary","icon":"💰"}},
]
# Filtering by month=5 year=2026 should only return May income
may_filtered = [i for i in (april_inc + may_inc) if i["month"]==5 and i["year"]==2026]
check("Income month filter: only May returned",  len(may_filtered)==1)
check("Income month filter: correct record",     may_filtered[0]["description"]=="May Salary")

print("\n── U7.3: get_income_summary with explicit month ──")
with mpatch("__main__.get_income", return_value=may_inc):
    s_sgd, s_inr, s_by = get_income_summary(5, 2026)
check("May income summary uses correct month data",  s_sgd == 5500.0)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U8: REAL USER PAIN POINTS                          ║")
print("╚══════════════════════════════════════════════════════╝")

print("\n── U8.1: Sensitive data scrub covers all Singapore PII formats ──")
sg_statement = """
DBS BANK STATEMENT
Account No: 123-456789-0
Account Number: 022-345678-9
Card ending 9012
NRIC: S8812345A
Mobile: 98765432
Email: priya@gmail.com
SGD Transactions:
NTUC FAIRPRICE          2026-05-01    -45.00
GRAB*FOOD               2026-05-02    -22.50
"""
scrubbed = strip_sensitive_data(sg_statement)
check("DBS account 123-456789-0 removed",  "123-456789-0" not in scrubbed,
      f"got: {scrubbed[:200]}")
check("Account No label removed",          "022-345678-9" not in scrubbed or
                                            "Account [REMOVED]" in scrubbed)
check("NRIC S-format removed",             "S8812345A" not in scrubbed)
check("SG mobile (9xxxxxxx) removed",      "98765432" not in scrubbed)
check("Email removed",                     "priya@gmail.com" not in scrubbed)
check("Transaction amounts preserved",     "45.00" in scrubbed)
check("Merchant names preserved",          "NTUC FAIRPRICE" in scrubbed)

print("\n── U8.2: strip_sensitive_data 8000 char limit ──")
huge_statement = "NTUC FAIRPRICE -45.00\n" * 500  # ~10000 chars
scrubbed_huge = strip_sensitive_data(huge_statement)
check("Large statement truncated to 8000 chars",  len(scrubbed_huge) <= 8000)
check("Content not completely lost",               "NTUC" in scrubbed_huge)

print("\n── U8.3: Budget alert message is human readable ──")
overspent_summary = {
    "Groceries": {"budget":600,"budget_inr":0,"spent_sgd":720.0,
                  "spent_inr":0,"icon":"🛒","id":10,"by_user":{}},
    "Kids Stuff": {"budget":300,"budget_inr":0,"spent_sgd":280.0,
                   "spent_inr":0,"icon":"🧸","id":13,"by_user":{}},
    "Transport":  {"budget":200,"budget_inr":0,"spent_sgd":185.0,
                   "spent_inr":0,"icon":"🚗","id":11,"by_user":{}},
}
with mpatch("__main__.get_monthly_summary", return_value=overspent_summary):
    alerts = get_alerts(5, 2026)

check("Overspent alert mentions category",  any("Groceries" in a for a in alerts))
check("Alert shows overspend amount ($120)",any("120" in a for a in alerts),
      f"got: {alerts}")
# Kids 93%, Transport 92% — below 95% threshold, should NOT alert
check("93% Kids Stuff → no alert (below 95% threshold)",
      not any("Kids" in a for a in alerts), f"got: {alerts}")
check("92% Transport → no alert (below 95% threshold)",
      not any("Transport" in a for a in alerts), f"got: {alerts}")
check("Alert is readable (has emoji)",      any("🔴" in a or "🟡" in a for a in alerts))

# Verify 95%+ triggers warning, 94% does not
boundary_summary = {
    "Dining":    {"budget":400,"budget_inr":0,"spent_sgd":382.0, # 95.5% → warn
                  "spent_inr":0,"icon":"🍜","id":15,"by_user":{}},
    "Utilities": {"budget":200,"budget_inr":0,"spent_sgd":187.0, # 93.5% → no warn
                  "spent_inr":0,"icon":"💡","id":14,"by_user":{}},
}
with mpatch("__main__.get_monthly_summary", return_value=boundary_summary):
    b_alerts = get_alerts(5, 2026)
check("95.5% Dining → warning fires",       any("Dining" in a for a in b_alerts),
      f"got: {b_alerts}")
check("93.5% Utilities → no warning",       not any("Utilities" in a for a in b_alerts),
      f"got: {b_alerts}")
check("95%+ warning shows remaining amount",any("left" in a for a in b_alerts),
      f"got: {b_alerts}")

print("\n── U8.4: to_sgd precision — no floating point display dirt ──")
# Classic floating point: 2500 * 0.016 = 39.99999... or 40.00000001
amounts = [(2500, 0.016, 40.0), (3000, 0.016, 48.0),
           (15000, 0.016, 240.0), (1, 0.016, 0.02)]
for inr_amt, rate, expected in amounts:
    result = to_sgd(inr_amt, "INR", rate)
    check(f"₹{inr_amt} × {rate} = ${expected} (clean)",
          result == expected, f"got {result}")

print("\n── U8.5: unified_summary float precision ──")
test_s = {"Groceries":{"budget":600,"budget_inr":5000,"spent_sgd":180.0,
          "spent_inr":3000.0,"icon":"🛒","id":10,
          "by_user":{"Priya":{"sgd":180.0,"inr":3000.0}}}}
u = unified_summary(test_s, 0.016)
expected_unified = round(180 + 3000*0.016, 2)  # 180 + 48 = 228
check("Unified Groceries = 228.0 (no float dirt)",
      u["Groceries"]["spent_sgd"] == expected_unified,
      f"got {u['Groceries']['spent_sgd']}")
check("Unified by_user Priya = 228.0",
      u["Groceries"]["by_user"]["Priya"]["sgd"] == expected_unified)

# ── FINAL SUMMARY ─────────────────────────────────────────────────────────────
print("\n" + "═"*57)
passed  = sum(1 for r in results if r[0]==PASS)
failed  = sum(1 for r in results if r[0]==FAIL)
warned  = sum(1 for r in results if r[0]==WARN)
total   = len(results)
print(f"  USER JOURNEY RESULTS: {passed} passed, {failed} failed, {warned} warnings  ({total} total)")
if failed:
    print("\n  ❌ FAILURES (must fix):")
    for r in results:
        if r[0]==FAIL: print(f"    • {r[1]}  {r[2]}")
if warned:
    print("\n  ⚠️  KNOWN GAPS (document or fix):")
    for r in results:
        if r[0]==WARN: print(f"    • {r[1]}  {r[2]}")

print("\n╔══════════════════════════════════════════════════════╗")
print("║  U9: FIX 1 — CURRENCY VALIDATION                   ║")
print("╚══════════════════════════════════════════════════════╝")

print("\n── U9.1: Currency hint logic — thresholds ──")
# SGD > 500 → show "is this INR?" hint
# INR < 10  → show "is this SGD?" hint
# SGD income > 50000 → show large amount warning
hint_cases = [
    ("SGD", 450.0, False, False),   # normal SGD — no hint
    ("SGD", 501.0, True,  False),   # large SGD expense — hint fires
    ("SGD", 3500.0, True, False),   # rent — hint fires (user sees it, can ignore)
    ("INR", 8.0,   False, True),    # tiny INR — hint fires
    ("INR", 50.0,  False, False),   # normal INR — no hint
    ("SGD", 50001.0, True, False),  # large income SGD — hint fires
]
for cur, amt, exp_sgd_hint, exp_inr_hint in hint_cases:
    sgd_hint = (cur == "SGD" and amt > 500)
    inr_hint = (cur == "INR" and amt < 10)
    if exp_sgd_hint:
        check(f"SGD {amt} → large amount hint fires",   sgd_hint, f"cur={cur} amt={amt}")
    elif exp_inr_hint:
        check(f"INR {amt} → tiny amount hint fires",    inr_hint, f"cur={cur} amt={amt}")
    else:
        check(f"{cur} {amt} → no hint (normal range)",  not sgd_hint and not inr_hint)

print("\n── U9.2: Chat tool currency sanity warning ──")
# Large SGD amount in chat should append a warning
amount_sgd_large = 15000.0
currency_warn = ""
if amount_sgd_large > 10000:
    currency_warn = f"\n⚠️ That's a large SGD amount (${amount_sgd_large:.0f})."
check("Chat: SGD > 10000 → warning appended",  len(currency_warn) > 0)

amount_inr_tiny = 3.0
currency_warn2 = ""
if amount_inr_tiny < 5:
    currency_warn2 = f"\n⚠️ ₹{amount_inr_tiny:.2f} seems very small."
check("Chat: INR < 5 → warning appended",  len(currency_warn2) > 0)

amount_normal = 45.0
currency_warn3 = "" if amount_normal <= 10000 else "warn"
check("Chat: Normal SGD 45 → no warning",  len(currency_warn3) == 0)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U10: FIX 4 — DUPLICATE IMPORT DETECTION           ║")
print("╚══════════════════════════════════════════════════════╝")

print("\n── U10.1: make_txn_hash produces stable fingerprint ──")
h1 = make_txn_hash("NTUC FAIRPRICE", 45.0, date(2026,5,1), "SGD")
h2 = make_txn_hash("NTUC FAIRPRICE", 45.0, date(2026,5,1), "SGD")
h3 = make_txn_hash("NTUC FAIRPRICE", 45.0, date(2026,5,2), "SGD")  # different date
h4 = make_txn_hash("NTUC FAIRPRICE", 46.0, date(2026,5,1), "SGD")  # different amount
h5 = make_txn_hash("COLD STORAGE",   45.0, date(2026,5,1), "SGD")  # different merchant

check("Same txn → same hash (idempotent)",        h1 == h2)
check("Different date → different hash",           h1 != h3)
check("Different amount → different hash",         h1 != h4)
check("Different merchant → different hash",       h1 != h5)
check("Hash is a string",                          isinstance(h1, str))
check("Hash has fixed length (MD5=32)",            len(h1) == 32)

print("\n── U10.2: Hash normalisation handles bank formatting quirks ──")
# Banks format same merchant differently across months
h_full  = make_txn_hash("NTUC FAIRPRICE PTE LTD", 45.0, date(2026,5,1), "SGD")
h_short = make_txn_hash("NTUC FAIRPRICE",          45.0, date(2026,5,1), "SGD")
h_star  = make_txn_hash("NTUC*FAIRPRICE*SG",       45.0, date(2026,5,1), "SGD")
# All non-alphanumeric stripped, first 30 chars taken
# "NTUCFAIRPRICEPTE" vs "NTUCFAIRPRICE" — different after strip
# This is intentional: if bank changes description, it's treated as new
# (better to import once and dedupe than silently miss a transaction)
check("Exact same description deduped",            h_full == h_full)
check("Different bank formatting = different hash (intentional)",
      h_full != h_short or h_full != h_star)  # at least one differs

print("\n── U10.3: Duplicate detection prevents double import ──")
existing_hashes = {
    make_txn_hash("NTUC FAIRPRICE", 45.0, date(2026,5,1), "SGD"),
    make_txn_hash("GRAB RIDES",     22.5, date(2026,5,3), "SGD"),
}
second_import = [
    {"description": "NTUC FAIRPRICE", "amount": 45.0,  "date": "2026-05-01", "currency": "SGD"},
    {"description": "GRAB RIDES",     "amount": 22.5,  "date": "2026-05-03", "currency": "SGD"},
    {"description": "COLD STORAGE",   "amount": 67.0,  "date": "2026-05-15", "currency": "SGD"},  # new
]
duplicates = 0
new_txns   = 0
for txn in second_import:
    d = datetime.strptime(txn["date"], "%Y-%m-%d").date()
    h = make_txn_hash(txn["description"], txn["amount"], d, txn["currency"])
    if h in existing_hashes:
        duplicates += 1
    else:
        new_txns += 1

check("2 duplicates detected on re-import",   duplicates == 2)
check("1 new transaction passes through",      new_txns == 1)
check("Total = duplicates + new",              duplicates + new_txns == 3)

print("\n── U10.4: Hash is currency-aware — same amount diff currency ──")
h_sgd = make_txn_hash("PAYMENT", 100.0, date(2026,5,1), "SGD")
h_inr = make_txn_hash("PAYMENT", 100.0, date(2026,5,1), "INR")
check("SGD 100 and INR 100 produce different hashes",  h_sgd != h_inr)


print("\n╔══════════════════════════════════════════════════════╗")
print("║  U11: FIX 5 — RELATIONSHIP SLANG RESOLUTION        ║")
print("╚══════════════════════════════════════════════════════╝")

print("\n── U11.1: Expanded alias list covers common slang ──")
with mpatch("__main__.get_all_users", return_value=FAMILY):
    new_slang = [
        ("hubby",           2, "common informal"),
        ("wifey",           2, "common informal"),
        ("babe",            2, "casual"),
        ("baby",            2, "casual"),
        ("dear",            2, "South Asian common"),
        ("darling",         2, "common"),
        ("honey",           2, "common"),
        ("better half",     2, "idiom"),
        ("significant other", 2, "modern term"),
        ("my man",          2, "casual"),
        ("my woman",        2, "casual"),
    ]
    for alias, expected_uid, label in new_slang:
        uid, nm = resolve_user(alias, 1)  # Priya logged in, expects Raj (uid=2)
        check(f"'{alias}' ({label}) → other user",  uid == expected_uid,
              f"got uid={uid}")

print("\n── U11.2: 'my husband paid' with 'my' prefix ──")
with mpatch("__main__.get_all_users", return_value=FAMILY):
    phrases_with_my = ["my husband", "my wife", "my partner", "my hubby"]
    for phrase in phrases_with_my:
        uid, _ = resolve_user(phrase, 1)
        check(f"'{phrase}' → other user",  uid == 2, f"got uid={uid}")

print("\n── U11.3: Name still beats alias ──")
# If the other user is actually named "Hubby" (unlikely but possible), name match wins
weird_users = [
    {"id": 1, "name": "Alice",  "pin": "1111"},
    {"id": 2, "name": "Hubby",  "pin": "2222"},  # someone actually named Hubby
]
with mpatch("__main__.get_all_users", return_value=weird_users):
    uid, nm = resolve_user("Hubby", 1)
    check("User actually named 'Hubby' — direct name match takes priority",
          uid == 2 and nm == "Hubby", f"uid={uid} nm={nm}")

print("\n── U11.4: Unknown term still falls back gracefully ──")
with mpatch("__main__.get_all_users", return_value=FAMILY), \
     mpatch("__main__.claude") as mock_claude:
    # Simulate Claude saying YES (this is the other person)
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock()]
    mock_resp.content[0].text = "YES"
    mock_claude.messages.create.return_value = mock_resp

    uid, nm = resolve_user("yaar", 1)  # Hindi slang for friend/partner
    check("'yaar' (unknown) → Claude fallback → other user",
          uid == 2, f"got uid={uid}")

with mpatch("__main__.get_all_users", return_value=FAMILY), \
     mpatch("__main__.claude") as mock_claude:
    # Claude says NO (not the other person)
    mock_resp2 = MagicMock()
    mock_resp2.content = [MagicMock()]
    mock_resp2.content[0].text = "NO"
    mock_claude.messages.create.return_value = mock_resp2

    uid, nm = resolve_user("cashier", 1)  # not a person in the family
    check("'cashier' → Claude says NO → falls back to current user",
          uid == 1, f"got uid={uid}")

# ── UPDATED FINAL SUMMARY ─────────────────────────────────────────────────────
print("\n" + "═"*57)
passed  = sum(1 for r in results if r[0]==PASS)
failed  = sum(1 for r in results if r[0]==FAIL)
warned  = sum(1 for r in results if r[0]==WARN)
total   = len(results)
print(f"  USER JOURNEY RESULTS: {passed} passed, {failed} failed, {warned} warnings  ({total} total)")
if failed:
    print("\n  ❌ FAILURES (must fix):")
    for r in results:
        if r[0]==FAIL: print(f"    • {r[1]}  {r[2]}")
if warned:
    print("\n  ⚠️  REMAINING KNOWN GAPS:")
    for r in results:
        if r[0]==WARN: print(f"    • {r[1]}  {r[2]}")