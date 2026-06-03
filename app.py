import streamlit as st
import os
import json
import re
import io
from datetime import datetime, date
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv
from supabase import create_client
from anthropic import Anthropic
import pytesseract
from PIL import Image
import pdfplumber

# --- TESSERACT PATH ---
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- INIT ---
load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
claude = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

st.set_page_config(page_title="💰 Family Finance", page_icon="💰", layout="centered")

st.markdown("""
<style>
    .main { padding: 0.5rem; }
    .stButton > button { width:100%; border-radius:12px; height:3rem; font-size:1rem; font-weight:600; }
    .balance-card { background:linear-gradient(135deg,#6C63FF,#a29bfe); border-radius:16px; padding:16px; color:white; text-align:center; margin:6px 0; }
    .income-card { background:linear-gradient(135deg,#00b894,#55efc4); border-radius:16px; padding:16px; color:white; text-align:center; margin:6px 0; }
    .person-card { background:linear-gradient(135deg,#fd79a8,#fdcb6e); border-radius:12px; padding:12px; color:white; text-align:center; margin:4px 0; }
    .expense-card { background:#f8f9fa; border-radius:12px; padding:12px; margin:4px 0; border-left:4px solid #6C63FF; }
    .income-item { background:#f0fff4; border-radius:12px; padding:12px; margin:4px 0; border-left:4px solid #00b894; }
    .alert-card { background:#fff3f3; border-radius:12px; padding:10px; margin:4px 0; border-left:4px solid #ff4444; }
    .chat-user { background:#6C63FF; color:white; padding:10px 14px; border-radius:12px; margin:4px 0; margin-left:15%; font-size:0.9rem; }
    .chat-bot { background:#f0f0f0; color:#333; padding:10px 14px; border-radius:12px; margin:4px 0; margin-right:15%; font-size:0.9rem; }
    .filter-bar { background:#f8f9fa; border-radius:12px; padding:10px 14px; margin:8px 0 4px 0; border-left:4px solid #6C63FF; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
_today = date.today()
for key, default in [
    ("logged_in", False), ("user", None), ("messages", []),
    ("import_preview", None), ("import_filename", None),
    ("filter_month", _today.month), ("filter_year", _today.year),
    ("inr_to_sgd_rate", 0.016),   # default: 1 INR = 0.016 SGD (~62.5 INR per SGD)
    ("unified_currency", False),  # when True, all amounts shown in SGD
]:
    if key not in st.session_state:
        st.session_state[key] = default

MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]

# --- DB HELPERS ---
def get_categories():
    return supabase.table("categories").select("*").eq("is_active", True).order("name").execute().data

def get_income_types():
    return supabase.table("income_types").select("*").eq("is_active", True).execute().data

def get_balance():
    result = supabase.table("balance").select("*").order("id").limit(1).execute()
    return result.data[0] if result.data else {"id": 1, "sgd_amount": 0, "inr_amount": 0}

def update_balance(sgd=None, inr=None):
    balance = get_balance()
    data = {"updated_at": datetime.now().isoformat()}
    if sgd is not None: data["sgd_amount"] = sgd
    if inr is not None: data["inr_amount"] = inr
    supabase.table("balance").update(data).eq("id", balance["id"]).execute()

def deduct_balance(amount, currency="SGD"):
    balance = get_balance()
    if currency == "SGD":
        update_balance(sgd=max(0, balance["sgd_amount"] - amount))
    else:
        update_balance(inr=max(0, balance["inr_amount"] - amount))

def restore_balance(amount, currency="SGD"):
    balance = get_balance()
    if currency == "SGD":
        update_balance(sgd=balance["sgd_amount"] + amount)
    else:
        update_balance(inr=balance["inr_amount"] + amount)

def add_to_balance(amount, currency="SGD"):
    balance = get_balance()
    if currency == "SGD":
        update_balance(sgd=balance["sgd_amount"] + amount)
    else:
        update_balance(inr=balance["inr_amount"] + amount)

def get_expenses(month=None, year=None):
    today = date.today()
    m = month or today.month
    y = year or today.year
    start = f"{y}-{m:02d}-01"
    end = f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01"
    return supabase.table("expenses").select(
        "*, users(name), categories(name, icon)"
    ).eq("is_deleted", False).gte("date", start).lt(
        "date", end).order("date", desc=True).execute().data

def add_expense_db(user_id, category_id, amount, description, currency="SGD", expense_date=None):
    supabase.table("expenses").insert({
        "user_id": user_id, "category_id": category_id,
        "amount": float(amount), "description": description,
        "currency": currency, "date": str(expense_date or date.today()),
        "is_deleted": False
    }).execute()
    deduct_balance(float(amount), currency)

def update_expense_db(expense_id, old_amount, old_currency, new_amount, new_currency,
                      new_desc, new_cat_id, new_date, old_cat_id=None):
    restore_balance(old_amount, old_currency)
    supabase.table("expenses").update({
        "amount": float(new_amount), "currency": new_currency,
        "description": new_desc, "category_id": new_cat_id,
        "date": str(new_date)
    }).eq("id", expense_id).execute()
    deduct_balance(float(new_amount), new_currency)
    # If category changed, save a merchant rule so future imports remember this
    if old_cat_id is not None and int(old_cat_id) != int(new_cat_id):
        save_merchant_rule(new_desc, new_cat_id)

def delete_expense_db(expense_id, amount, currency):
    supabase.table("expenses").update({"is_deleted": True}).eq("id", expense_id).execute()
    restore_balance(amount, currency)

def get_income(month=None, year=None):
    today = date.today()
    m = month or today.month
    y = year or today.year
    return supabase.table("income").select(
        "*, users(name), income_types(name, icon)"
    ).eq("is_deleted", False).eq("month", m).eq(
        "year", y).order("date", desc=True).execute().data

def add_income_db(user_id, income_type_id, amount, currency, description, income_date=None):
    d = income_date or date.today()
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    supabase.table("income").insert({
        "user_id": user_id, "income_type_id": income_type_id,
        "amount": float(amount), "currency": currency,
        "description": description, "date": str(d),
        "month": d.month, "year": d.year, "is_deleted": False
    }).execute()
    add_to_balance(float(amount), currency)

def delete_income_db(income_id, amount, currency):
    supabase.table("income").update({"is_deleted": True}).eq("id", income_id).execute()
    deduct_balance(amount, currency)

def get_monthly_summary(month=None, year=None):
    expenses = get_expenses(month, year)
    categories = get_categories()
    summary = {c["name"]: {
        "budget": c["budget"], "budget_inr": c.get("budget_inr", 0),
        "spent_sgd": 0, "spent_inr": 0,
        "icon": c["icon"], "id": c["id"], "by_user": {}
    } for c in categories}
    for exp in expenses:
        cat = exp["categories"]["name"]
        uname = exp["users"]["name"]
        if cat in summary:
            if exp.get("currency", "SGD") == "INR":
                summary[cat]["spent_inr"] += exp["amount"]
            else:
                summary[cat]["spent_sgd"] += exp["amount"]
            if uname not in summary[cat]["by_user"]:
                summary[cat]["by_user"][uname] = {"sgd": 0, "inr": 0}
            if exp.get("currency", "SGD") == "INR":
                summary[cat]["by_user"][uname]["inr"] += exp["amount"]
            else:
                summary[cat]["by_user"][uname]["sgd"] += exp["amount"]
    return summary

def get_income_summary(month=None, year=None):
    income_list = get_income(month, year)
    total_sgd = sum(i["amount"] for i in income_list if i["currency"] == "SGD")
    total_inr = sum(i["amount"] for i in income_list if i["currency"] == "INR")
    by_user = {}
    for i in income_list:
        name = i["users"]["name"]
        if name not in by_user:
            by_user[name] = {"sgd": 0, "inr": 0}
        if i["currency"] == "SGD":
            by_user[name]["sgd"] += i["amount"]
        else:
            by_user[name]["inr"] += i["amount"]
    return total_sgd, total_inr, by_user

def get_user_spending(month=None, year=None):
    expenses = get_expenses(month, year)
    by_user = {}
    for exp in expenses:
        name = exp["users"]["name"]
        if name not in by_user:
            by_user[name] = {"sgd": 0, "inr": 0}
        if exp.get("currency", "SGD") == "INR":
            by_user[name]["inr"] += exp["amount"]
        else:
            by_user[name]["sgd"] += exp["amount"]
    return by_user

def get_all_users():
    return supabase.table("users").select("*").execute().data

def to_sgd(amount, currency, rate):
    """Convert any amount to SGD using the given INR→SGD rate."""
    if currency == "SGD":
        return round(float(amount), 2)
    return round(float(amount) * float(rate), 2)

def unified_summary(summary, rate):
    """Return a version of get_monthly_summary with all INR converted into SGD fields."""
    result = {}
    for cat, d in summary.items():
        converted_inr = d["spent_inr"] * rate
        by_user_unified = {}
        for name, vals in d["by_user"].items():
            by_user_unified[name] = {
                "sgd": round(vals["sgd"] + vals["inr"] * rate, 2),
                "inr": 0
            }
        result[cat] = dict(d)
        result[cat]["spent_sgd"]  = round(d["spent_sgd"] + converted_inr, 2)
        result[cat]["spent_inr"]  = 0
        result[cat]["by_user"]    = by_user_unified
    return result

def unified_income_summary(inc_sgd, inc_inr, by_user, rate):
    """Convert INR income into SGD for unified view."""
    new_sgd = round(inc_sgd + inc_inr * rate, 2)
    new_by_user = {}
    for name, vals in by_user.items():
        new_by_user[name] = {
            "sgd": round(vals["sgd"] + vals["inr"] * rate, 2),
            "inr": 0
        }
    return new_sgd, 0.0, new_by_user

def unified_user_spending(spending, rate):
    """Convert per-user INR spending into SGD for unified view."""
    result = {}
    for name, vals in spending.items():
        result[name] = {
            "sgd": round(vals["sgd"] + vals["inr"] * rate, 2),
            "inr": 0
        }
    return result

def get_alerts(month=None, year=None):
    alerts = []
    for cat, d in get_monthly_summary(month, year).items():
        if d["budget"] > 0:
            pct = d["spent_sgd"] / d["budget"] * 100
            if pct > 100:
                overspent = d["spent_sgd"] - d["budget"]
                alerts.append(f"🔴 {d['icon']} {cat}: Overspent by ${overspent:.2f} SGD!")
            elif pct >= 95:
                # Only warn at 95%+ — 90% was too noisy, triggered on normal months
                remaining = d["budget"] - d["spent_sgd"]
                alerts.append(f"🟡 {d['icon']} {cat}: {pct:.0f}% used — only ${remaining:.2f} left!")
        if d["budget_inr"] > 0 and d["spent_inr"] > d["budget_inr"]:
            overspent_inr = d["spent_inr"] - d["budget_inr"]
            alerts.append(f"🔴 {d['icon']} {cat}: Overspent by ₹{overspent_inr:.2f} INR!")
    return alerts

def get_or_create_category(cat_name):
    categories = get_categories()
    matched = next(
        (c for c in categories if cat_name.lower() in c["name"].lower()
         or c["name"].lower() in cat_name.lower()),
        None
    )
    if matched:
        return matched

    icon_map = {
        "food": "🍜", "dining": "🍜", "restaurant": "🍜", "cafe": "☕",
        "coffee": "☕", "starbucks": "☕", "toast box": "☕", "ya kun": "☕",
        "hawker": "🍜", "kopitiam": "🍜", "foodcourt": "🍜",
        "mcdonalds": "🍔", "mcdonald": "🍔", "burger": "🍔", "kfc": "🍗",
        "pizza": "🍕", "dominos": "🍕", "subway": "🥪",
        "foodpanda": "🍕", "deliveroo": "🍕", "grabfood": "🍕",
        "swiggy": "🍕", "zomato": "🍕",
        "ntuc": "🛒", "fairprice": "🛒", "cold storage": "🛒",
        "giant": "🛒", "sheng siong": "🛒", "don don donki": "🛒",
        "big basket": "🛒", "grofers": "🛒", "blinkit": "🛒",
        "grocery": "🛒", "supermarket": "🛒", "market": "🛒",
        "grab": "🚗", "gojek": "🚗", "taxi": "🚗", "phv": "🚗",
        "comfort": "🚗", "delgro": "🚗", "cabcharge": "🚗",
        "ola": "🚗", "uber": "🚗", "rapido": "🚗",
        "mrt": "🚇", "bus": "🚌", "train": "🚇", "metro": "🚇",
        "ezlink": "🚇", "transit": "🚇", "smrt": "🚇",
        "petrol": "⛽", "shell": "⛽", "caltex": "⛽", "sinopec": "⛽",
        "parking": "🅿️",
        "shopee": "🛍️", "lazada": "🛍️", "amazon": "📦",
        "taobao": "📦", "alibaba": "📦", "zalora": "👗",
        "flipkart": "📦", "myntra": "👗", "ajio": "👗",
        "meesho": "🛍️", "snapdeal": "📦",
        "online": "🛒", "ecommerce": "💻", "delivery": "🚚",
        "shopping": "🛍️", "clothes": "👗", "fashion": "👗",
        "uniqlo": "👕", "zara": "👗", "hm": "👗", "cotton on": "👕",
        "watsons": "💄", "guardian": "💄", "sasa": "💄",
        "ikea": "🏠", "courts": "📺", "harvey norman": "📺",
        "popular": "📚", "kinokuniya": "📚", "books": "📚",
        "bills": "💡", "utilities": "💡", "sp group": "💡",
        "city gas": "💡", "power": "💡", "electricity": "💡",
        "singtel": "📱", "starhub": "📱", "m1": "📱",
        "circles": "📱", "redone": "📱", "gomo": "📱",
        "airtel": "📱", "jio": "📱", "bsnl": "📱", "vodafone": "📱",
        "phone": "📱", "mobile": "📱", "internet": "🌐",
        "broadband": "🌐", "wifi": "🌐",
        "water": "💧", "pub": "💧",
        "health": "💊", "medical": "🏥", "pharmacy": "💊",
        "dental": "🦷", "doctor": "🏥", "clinic": "🏥",
        "hospital": "🏥", "polyclinic": "🏥", "sgh": "🏥",
        "ttsh": "🏥", "nuh": "🏥", "kk": "🏥",
        "apollo": "🏥", "fortis": "🏥", "max": "🏥",
        "unity pharmacy": "💊", "guardian pharmacy": "💊",
        "entertainment": "🎬", "netflix": "🎬", "spotify": "🎵",
        "disney": "🎬", "youtube": "🎬", "amazon prime": "🎬",
        "hotstar": "🎬", "zee5": "🎬", "sonyliv": "🎬",
        "movies": "🎬", "cinema": "🎬", "cathay": "🎬",
        "gv": "🎬", "shaw": "🎬", "golden village": "🎬",
        "games": "🎮", "steam": "🎮", "playstation": "🎮",
        "karaoke": "🎤", "ktv": "🎤",
        "education": "📚", "school": "🏫", "tuition": "📚",
        "course": "📚", "udemy": "💻", "coursera": "💻",
        "skillsfuture": "📚", "learning": "📚",
        "travel": "✈️", "hotel": "🏨", "flight": "✈️",
        "airbnb": "🏠", "agoda": "🏨", "booking": "🏨",
        "singapore airlines": "✈️", "sia": "✈️", "scoot": "✈️",
        "airasia": "✈️", "indigo": "✈️", "air india": "✈️",
        "gym": "💪", "fitness": "💪", "yoga": "🧘",
        "anytime fitness": "💪", "true fitness": "💪",
        "hair": "💇", "salon": "💇", "spa": "💆",
        "nail": "💅", "beauty": "💄",
        "rent": "🏠", "mortgage": "🏠", "housing": "🏠",
        "hdb": "🏠", "condo": "🏠", "property": "🏠",
        "renovation": "🔨", "plumber": "🔧", "electrician": "🔧",
        "insurance": "🛡️", "prudential": "🛡️", "aia": "🛡️",
        "ntuc income": "🛡️", "great eastern": "🛡️",
        "lic": "🛡️", "hdfc life": "🛡️", "sbi life": "🛡️",
        "cpf": "💰", "medisave": "💊", "investment": "📈",
        "stocks": "📈", "mutual fund": "📈", "fd": "💰",
        "kids": "👶", "baby": "👶", "childcare": "👶",
        "toys": "🧸", "toysrus": "🧸", "kiddy palace": "🧸",
        "pet": "🐾", "vet": "🐾", "dog": "🐕", "cat": "🐈",
        "temple": "🙏", "church": "🙏", "mosque": "🙏",
        "donation": "🙏", "charity": "🙏", "zakat": "🙏",
        "atm": "🏧", "cash": "💵", "transfer": "💸",
        "casino": "🎰", "genting": "🎰", "rws": "🎰",
        "alcohol": "🍺", "wine": "🍷", "beer": "🍺",
    }

    icon = "📦"
    for keyword, emoji in icon_map.items():
        if keyword in cat_name.lower():
            icon = emoji
            break

    result = supabase.table("categories").insert({
        "name": cat_name, "icon": icon,
        "budget": 0, "budget_inr": 0, "is_active": True
    }).execute()

    if result.data:
        return result.data[0]
    return {"id": None, "name": cat_name, "icon": icon}

def get_merchant_rules():
    """Load all merchant→category rules from DB."""
    try:
        result = supabase.table("merchant_rules").select(
            "*, categories(name, icon, id)").execute()
        return result.data or []
    except Exception:
        return []  # table may not exist yet — fail gracefully

def make_txn_hash(description, amount, txn_date, currency):
    """
    Create a stable fingerprint for a transaction.
    Same merchant + amount + date + currency = same hash = duplicate.
    Normalises description to handle minor bank formatting differences.
    """
    import hashlib
    desc_clean = re.sub(r'[^a-zA-Z0-9]', '', str(description).upper())[:30]
    raw = f"{desc_clean}|{float(amount):.2f}|{str(txn_date)}|{currency}"
    return hashlib.md5(raw.encode()).hexdigest()

def get_imported_hashes():
    """Load all previously imported transaction hashes from DB."""
    try:
        result = supabase.table("import_hashes").select("txn_hash").execute()
        return {row["txn_hash"] for row in (result.data or [])}
    except Exception:
        return set()  # table may not exist yet — fail gracefully

def save_import_hash(txn_hash):
    """Save a transaction hash after successful import."""
    try:
        supabase.table("import_hashes").insert({"txn_hash": txn_hash}).execute()
    except Exception:
        pass  # never block import for hash save failure


def save_merchant_rule(merchant_description, category_id):
    """
    Save or update a merchant→category rule.
    Called whenever a user manually corrects a category on an expense.
    Uses the full description as the pattern — Claude will do fuzzy matching later.
    """
    if not merchant_description or not category_id:
        return
    try:
        # Check if rule already exists for this merchant
        existing = supabase.table("merchant_rules").select("*").ilike(
            "merchant_pattern", merchant_description).execute()
        if existing.data:
            # Update existing rule
            supabase.table("merchant_rules").update({
                "category_id": category_id,
                "updated_at": datetime.now().isoformat()
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            # Create new rule
            supabase.table("merchant_rules").insert({
                "merchant_pattern": merchant_description.strip(),
                "category_id": category_id,
                "updated_at": datetime.now().isoformat()
            }).execute()
    except Exception:
        pass  # never block the main flow for a rule save failure

def apply_merchant_rules(description, merchant_rules):
    """
    Check a transaction description against saved merchant rules.
    Uses Claude to semantically match the description against known patterns.
    Returns matched category dict or None.
    """
    if not merchant_rules or not description:
        return None

    # First: fast exact/substring check (no API call needed)
    desc_lower = description.lower()
    for rule in merchant_rules:
        pattern = rule.get("merchant_pattern", "").lower()
        if pattern and (pattern in desc_lower or desc_lower in pattern):
            return rule.get("categories")

    # Second: if no fast match, use Claude to fuzzy-match
    # Only do this if there are enough rules to make it worthwhile
    if len(merchant_rules) < 3:
        return None

    try:
        patterns_list = [
            f'  - "{r["merchant_pattern"]}" → {r["categories"]["name"]}'
            for r in merchant_rules if r.get("categories")
        ]
        prompt = f"""Given this transaction description: "{description}"

Does it match any of these known merchant patterns (same merchant, possibly different formatting)?
{chr(10).join(patterns_list)}

Reply with ONLY the merchant_pattern string that matches, or "none" if no match.
Do not explain. Just the pattern string or "none"."""

        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )
        matched_pattern = response.content[0].text.strip().strip('"')
        if matched_pattern.lower() != "none":
            rule = next((r for r in merchant_rules
                        if r["merchant_pattern"].lower() == matched_pattern.lower()), None)
            if rule:
                return rule.get("categories")
    except Exception:
        pass

    return None


def semantic_category_match(suggested_names, existing_categories):
    """
    Use Claude to semantically match a list of suggested category names
    against existing category names. Returns a dict:
      { suggested_name: matched_existing_id_or_None }

    This handles cases like:
      "Shopping" → "Kids Stuff" (if that's what user renamed it to)
      "Food & Dining" → "Dining"
      "Taxi/Grab" → "Transport"
      "Online Shopping" → "Shopee/Lazada" etc.
    """
    if not suggested_names or not existing_categories:
        return {}

    existing_list = [{"id": c["id"], "name": c["name"]} for c in existing_categories]
    suggested_list = list(set(suggested_names))  # deduplicate

    prompt = f"""You are a category matching assistant.

Existing categories in the user's finance app:
{chr(10).join(f'  ID {c["id"]}: {c["name"]}' for c in existing_list)}

Suggested category names from an imported bank statement:
{chr(10).join(f'  - {name}' for name in suggested_list)}

Task: For each suggested name, find the best matching existing category by MEANING and INTENT,
not just string similarity. A user may have renamed categories (e.g. "Shopping" renamed to
"Kids Stuff", "Groceries" to "Weekly Market", "Transport" to "Commute").

Rules:
- Match by what the category IS USED FOR, not exact wording
- If there is a reasonable semantic match, use it
- Only return null if there is genuinely no suitable existing category
- Never create new mappings — only map to existing IDs listed above

Return ONLY a JSON object, no other text:
{{"suggested_name": existing_id_or_null, ...}}

Example: {{"Grocery": 10, "Food & Dining": 13, "Uber/Grab": null}}"""

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        import re as _re, json as _json
        text = response.content[0].text.strip()
        text = _re.sub(r'^```json\s*', '', text)
        text = _re.sub(r'^```\s*', '', text)
        text = _re.sub(r'\s*```$', '', text)
        mapping = _json.loads(text)
        # Convert IDs back to category objects
        id_to_cat = {c["id"]: c for c in existing_categories}
        result = {}
        for sug_name, cat_id in mapping.items():
            if cat_id and cat_id in id_to_cat:
                result[sug_name] = id_to_cat[cat_id]
            else:
                result[sug_name] = None
        return result
    except Exception:
        return {}  # graceful fallback — old string match will handle it


# --- STATEMENT PARSER ---
def extract_text_from_file(uploaded_file):
    filename = uploaded_file.name.lower()
    raw_text = ""
    try:
        if filename.endswith(".pdf"):
            with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: raw_text += text + "\n"
                    for table in page.extract_tables():
                        for row in table:
                            if row:
                                raw_text += " | ".join(
                                    [str(c) if c else "" for c in row]) + "\n"
        elif filename.endswith(".csv"):
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file)
            raw_text = df.to_string()
        elif filename.endswith((".xlsx", ".xls")):
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file)
            raw_text = df.to_string()
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            uploaded_file.seek(0)
            img = Image.open(uploaded_file)
            raw_text = pytesseract.image_to_string(img)
    except Exception as e:
        return None, str(e)
    return raw_text, None

def strip_sensitive_data(text):
    # 16-digit card numbers (with or without spaces/dashes)
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD]', text)
    # Card ending XXXX (partial card — "card ending 9012", "card no. **9012")
    text = re.sub(r'card\s*(?:ending|no\.?|number|#)[:\s]*[\dX*]{4,}\b',
                 'Card [REMOVED]', text, flags=re.IGNORECASE)
    # Account numbers in various formats (DBS: 123-456789-0, POSB: 9 digits, etc)
    text = re.sub(r'Account\s*(?:No\.?|Number|#|:)[:\s]*[\d\-X*]+',
                 'Account [REMOVED]', text, flags=re.IGNORECASE)
    # Standalone DBS/OCBC/bank account patterns: XXX-XXXXXX-X or XXXXXXXXX
    text = re.sub(r'\b\d{3}-\d{6}-\d\b', '[ACCOUNT]', text)   # DBS format
    text = re.sub(r'\b\d{3}-\d{5}-\d\b',  '[ACCOUNT]', text)   # POSB format
    # Email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                 '[EMAIL]', text)
    # Singapore mobile numbers (8/9xxxxxxx — 8 digits starting with 6,8,9)
    text = re.sub(r'\b[689]\d{7}\b', '[PHONE]', text)
    # NRIC/FIN: S/T/F/G + 7 digits + letter
    text = re.sub(r'\b[STFG]\d{7}[A-Z]\b', '[NRIC]', text)
    return text[:8000]

def parse_statement_with_claude(raw_text, currency="SGD"):
    symbol = "$" if currency == "SGD" else "₹"
    prompt = f"""Analyze this bank/credit card statement. Extract ALL transactions.
Return ONLY a JSON array, no other text:
[{{"date":"YYYY-MM-DD","description":"merchant name","amount":12.50,"type":"expense or income",
"suggested_category":"be specific - use merchant type like Grocery/Grab/Netflix/Gym/Shopee/Lazada/Dental/Insurance etc"}}]

Rules:
- type=income for salary, credit, refund, cashback, interest received
- type=expense for purchases, payments, debit
- amount always positive number
- date must be YYYY-MM-DD, use year {date.today().year} if missing
- if a date is more than 1 year in the future, it is almost certainly a parsing error — use today's date instead
- description: clean merchant/payee name only
- suggested_category: be specific and descriptive, use the actual merchant type
- currency is {currency} ({symbol})
- IMPORTANT: Only set type="skip" for transactions that are CREDIT CARD BILL PAYMENTS or INTER-ACCOUNT TRANSFERS that would cause double counting. Specifically skip:
  * Credit card bill payments: "PAYMENT THANK YOU", "CREDIT CARD PAYMENT", "MINIMUM PAYMENT", "FULL PAYMENT", "OUTSTANDING BALANCE"
  * Inter-account fund transfers between your own accounts: "TRANSFER TO", "TRANSFER FROM", "FUNDS TRANSFER", "INTERNET TRANSFER"
  * Generic bank fees that are already captured elsewhere
- Do NOT skip GIRO transactions that are direct bill payments for real expenses — these are genuine expenses:
  * Tax payments (IRAS, income tax) → type="expense", category="Tax"
  * Insurance premiums via GIRO → type="expense", category="Insurance"
  * Utility bills via GIRO (SP Group, PUB, City Gas) → type="expense", category="Utilities"
  * Loan/mortgage GIRO → type="expense", category="Mortgage" or "Loan Repayment"
  * Subscription GIRO (Singtel, StarHub, gym) → type="expense", appropriate category
- Rule of thumb: skip only if the money is going TO a credit card company or between your own accounts. If it's going to a merchant/government/utility, it's a real expense

Statement:
{raw_text}

Return ONLY the JSON array:"""

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        text = response.content[0].text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text), None
    except Exception as e:
        return None, str(e)

# --- CLAUDE TOOLS ---
tools = [
    {"name": "add_expense",
     "description": "Add expense when user mentions spending money. If another person's name is mentioned as the spender, use spent_by field.",
     "input_schema": {"type": "object", "properties": {
         "amount": {"type": "number"},
         "currency": {"type": "string", "enum": ["SGD", "INR"]},
         "category": {"type": "string"},
         "description": {"type": "string"},
         "date": {"type": "string"},
         "spent_by": {"type": "string",
                      "description": "Name of person who spent. Default is current user."}},
         "required": ["amount", "currency", "category", "description"]}},
    {"name": "add_income",
     "description": "Record income/salary. If another person mentioned as earner, use earned_by.",
     "input_schema": {"type": "object", "properties": {
         "amount": {"type": "number"},
         "currency": {"type": "string", "enum": ["SGD", "INR"]},
         "income_type": {"type": "string",
                        "description": "Salary, Bonus, Freelance, Rental, Investment, Other"},
         "description": {"type": "string"},
         "date": {"type": "string"},
         "earned_by": {"type": "string",
                      "description": "Name of person who earned. Default is current user."}},
         "required": ["amount", "currency", "income_type", "description"]}},
    {"name": "find_expenses",
     "description": "Search expenses. Always use FIRST before update/delete.",
     "input_schema": {"type": "object", "properties": {
         "search_term": {"type": "string"},
         "date": {"type": "string"}}}},
    {"name": "update_expense",
     "description": "Update an existing expense.",
     "input_schema": {"type": "object", "properties": {
         "expense_id": {"type": "integer"},
         "amount": {"type": "number"},
         "currency": {"type": "string", "enum": ["SGD", "INR"]},
         "category": {"type": "string"},
         "description": {"type": "string"},
         "date": {"type": "string"}},
         "required": ["expense_id"]}},
    {"name": "delete_expense",
     "description": "Delete an expense.",
     "input_schema": {"type": "object", "properties": {
         "expense_id": {"type": "integer"}},
         "required": ["expense_id"]}},
    {"name": "add_category",
     "description": "Add new expense category.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"},
         "icon": {"type": "string"},
         "budget_sgd": {"type": "number"},
         "budget_inr": {"type": "number"}},
         "required": ["name"]}},
    {"name": "update_category",
     "description": "Update category name, icon or budget.",
     "input_schema": {"type": "object", "properties": {
         "category_name": {"type": "string"},
         "new_name": {"type": "string"},
         "new_icon": {"type": "string"},
         "budget_sgd": {"type": "number"},
         "budget_inr": {"type": "number"}},
         "required": ["category_name"]}},
    {"name": "delete_category",
     "description": "Delete a category.",
     "input_schema": {"type": "object", "properties": {
         "category_name": {"type": "string"}},
         "required": ["category_name"]}},
    {"name": "get_summary",
     "description": "Get monthly income and spending summary.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_spending_by_person",
     "description": "Show how much each person earned and spent.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_recent_expenses",
     "description": "Get recent expenses.",
     "input_schema": {"type": "object", "properties": {
         "limit": {"type": "integer"}}}},
    {"name": "get_balance",
     "description": "Get current family balance.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_alerts",
     "description": "Get budget overspending alerts.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_insights",
     "description": "Get spending insights and recommendations.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_balance",
     "description": "Manually update available balance.",
     "input_schema": {"type": "object", "properties": {
         "sgd_amount": {"type": "number"},
         "inr_amount": {"type": "number"}}}}
]

# Relationship aliases — maps loose terms to the other family member
# Standard English relationship words
RELATIONSHIP_ALIASES = [
    "husband", "wife", "spouse", "partner", "him", "her", "he", "she",
    "by him", "by her", "paid by him", "paid by her", "other half",
    # Informal / slang
    "hubby", "wifey", "babe", "baby", "dear", "darling", "honey",
    "better half", "significant other", "SO", "my man", "my woman",
    # Generic "other person"
    "he paid", "she paid", "my partner", "my husband", "my wife",
]

def resolve_user(name_hint, current_user_id):
    if not name_hint:
        return current_user_id, None
    hint_lower = name_hint.lower().strip()
    all_users = get_all_users()

    # 1. Direct name match (highest priority)
    matched = next(
        (u for u in all_users if hint_lower in u["name"].lower()
         or u["name"].lower() in hint_lower), None)
    if matched:
        return matched["id"], matched["name"]

    # 2. Relationship alias → return the OTHER person
    if any(alias in hint_lower for alias in RELATIONSHIP_ALIASES):
        other = next((u for u in all_users if u["id"] != current_user_id), None)
        if other:
            return other["id"], other["name"]

    # 3. Claude fallback — ask Claude whether this sounds like the other person
    # Only fires when hint is non-empty, no direct/alias match, and there IS another user
    other_users = [u for u in all_users if u["id"] != current_user_id]
    if hint_lower and other_users and len(hint_lower) > 1:
        other_names = ", ".join(u["name"] for u in other_users)
        try:
            resp = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=10,
                messages=[{"role": "user", "content":
                    f'Does "{hint_lower}" refer to someone other than the speaker? '
                    f'Other family members are: {other_names}. '
                    f'Reply only: YES or NO'}]
            )
            if resp.content[0].text.strip().upper() == "YES":
                other = next((u for u in all_users if u["id"] != current_user_id), None)
                if other:
                    return other["id"], other["name"]
        except Exception:
            pass  # never block on this — fall through

    return current_user_id, None

def execute_tool(tool_name, tool_input, user_id):
    categories = get_categories()
    cat_map = {c["name"].lower(): c for c in categories}
    income_types = get_income_types()
    itype_map = {t["name"].lower(): t for t in income_types}
    all_users = get_all_users()
    current_user = next((u for u in all_users if u["id"] == user_id), None)
    current_user_name = current_user["name"] if current_user else "You"

    if tool_name == "add_expense":
        amount = tool_input["amount"]
        currency = tool_input.get("currency", "SGD")
        category_name = tool_input["category"]
        description = tool_input["description"]
        expense_date = tool_input.get("date", str(date.today()))
        spent_by_hint = tool_input.get("spent_by", "")
        actual_user_id, spender_name = resolve_user(spent_by_hint, user_id)
        if not spender_name: spender_name = current_user_name
        matched_cat = next(
            (c for k, c in cat_map.items() if category_name.lower() in k
             or k in category_name.lower()), categories[-1])
        add_expense_db(actual_user_id, matched_cat["id"], amount,
                      description, currency, expense_date)
        symbol = "$" if currency == "SGD" else "₹"
        # Currency sanity warning
        currency_warn = ""
        if currency == "SGD" and amount > 10000:
            currency_warn = f"\n⚠️ That's a large SGD amount (${amount:.0f}). If it was ₹{amount:.0f}, let me know and I'll correct it."
        elif currency == "INR" and amount < 5:
            currency_warn = f"\n⚠️ ₹{amount:.2f} seems very small. If it was ${amount:.2f} SGD, let me know."
        return (f"✅ Added: {symbol}{amount:.2f} for **{description}** → "
                f"{matched_cat['icon']} {matched_cat['name']} (👤 {spender_name}){currency_warn}")

    elif tool_name == "add_income":
        amount = tool_input["amount"]
        currency = tool_input.get("currency", "SGD")
        itype_name = tool_input.get("income_type", "Other")
        description = tool_input["description"]
        income_date = tool_input.get("date", str(date.today()))
        earned_by_hint = tool_input.get("earned_by", "")
        actual_user_id, earner_name = resolve_user(earned_by_hint, user_id)
        if not earner_name: earner_name = current_user_name
        matched_type = next(
            (t for k, t in itype_map.items() if itype_name.lower() in k
             or k in itype_name.lower()), income_types[-1])
        add_income_db(actual_user_id, matched_type["id"], amount,
                     currency, description, income_date)
        symbol = "$" if currency == "SGD" else "₹"
        return (f"✅ Income: {symbol}{amount:.2f} {matched_type['icon']} "
                f"{matched_type['name']} recorded for 👤 {earner_name}")

    elif tool_name == "find_expenses":
        search = tool_input.get("search_term", "").lower()
        filter_date = tool_input.get("date")
        expenses = get_expenses()
        results = []
        for exp in expenses:
            match = (not search or search in exp["description"].lower() or
                    search in exp["categories"]["name"].lower())
            if match and (not filter_date or exp["date"] == filter_date):
                symbol = "$" if exp.get("currency", "SGD") == "SGD" else "₹"
                results.append(
                    f"ID:{exp['id']} | {exp['categories']['icon']} "
                    f"{symbol}{exp['amount']:.2f} — {exp['description']} "
                    f"(👤 {exp['users']['name']}, {exp['date']})")
        return ("No matching expenses." if not results
                else "Found:\n" + "\n".join(results))

    elif tool_name == "update_expense":
        expense_id = tool_input["expense_id"]
        result = supabase.table("expenses").select(
            "*, categories(name)").eq("id", expense_id).execute()
        if not result.data: return f"Expense ID {expense_id} not found."
        exp = result.data[0]
        new_amount = tool_input.get("amount", exp["amount"])
        new_currency = tool_input.get("currency", exp.get("currency", "SGD"))
        new_desc = tool_input.get("description", exp["description"])
        new_date = tool_input.get("date", exp["date"])
        new_cat_id = exp["category_id"]
        if "category" in tool_input:
            matched = next(
                (c for k, c in cat_map.items() if tool_input["category"].lower() in k
                 or k in tool_input["category"].lower()), None)
            if matched: new_cat_id = matched["id"]
        update_expense_db(expense_id, exp["amount"], exp.get("currency", "SGD"),
                         new_amount, new_currency, new_desc, new_cat_id, new_date,
                         old_cat_id=exp["category_id"])
        symbol = "$" if new_currency == "SGD" else "₹"
        return f"✅ Updated to {symbol}{new_amount:.2f} — {new_desc}"

    elif tool_name == "delete_expense":
        expense_id = tool_input["expense_id"]
        result = supabase.table("expenses").select("*").eq("id", expense_id).execute()
        if not result.data: return f"Expense ID {expense_id} not found."
        exp = result.data[0]
        delete_expense_db(expense_id, exp["amount"], exp.get("currency", "SGD"))
        return f"🗑️ Deleted: ${exp['amount']:.2f} — {exp['description']}"

    elif tool_name == "add_category":
        supabase.table("categories").insert({
            "name": tool_input["name"],
            "icon": tool_input.get("icon", "📦"),
            "budget": tool_input.get("budget_sgd", 0),
            "budget_inr": tool_input.get("budget_inr", 0),
            "is_active": True
        }).execute()
        return f"✅ Added: {tool_input.get('icon','📦')} {tool_input['name']}"

    elif tool_name == "update_category":
        matched = next(
            (c for c in categories if tool_input["category_name"].lower()
             in c["name"].lower()), None)
        if not matched: return "Category not found."
        update_data = {}
        if "new_name" in tool_input: update_data["name"] = tool_input["new_name"]
        if "new_icon" in tool_input: update_data["icon"] = tool_input["new_icon"]
        if "budget_sgd" in tool_input: update_data["budget"] = tool_input["budget_sgd"]
        if "budget_inr" in tool_input: update_data["budget_inr"] = tool_input["budget_inr"]
        supabase.table("categories").update(update_data).eq("id", matched["id"]).execute()
        return f"✅ Updated: {matched['name']}"

    elif tool_name == "delete_category":
        matched = next(
            (c for c in categories if tool_input["category_name"].lower()
             in c["name"].lower()), None)
        if not matched: return "Category not found."
        supabase.table("categories").update(
            {"is_active": False}).eq("id", matched["id"]).execute()
        return f"🗑️ Deleted: {matched['icon']} {matched['name']}"

    elif tool_name == "get_summary":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        summary = get_monthly_summary(fm, fy)
        total_sgd_exp = sum(d["spent_sgd"] for d in summary.values())
        total_inr_exp = sum(d["spent_inr"] for d in summary.values())
        inc_sgd, inc_inr, by_user = get_income_summary(fm, fy)
        net_sgd = inc_sgd - total_sgd_exp
        result = f"📊 **{MONTH_NAMES[fm-1]} {fy} Family Summary**\n"
        result += f"💚 Income: ${inc_sgd:.2f} SGD | ₹{inc_inr:.2f} INR\n"
        result += f"💸 Expenses: ${total_sgd_exp:.2f} SGD | ₹{total_inr_exp:.2f} INR\n"
        result += f"💰 Net: **${net_sgd:.2f} SGD** | **₹{inc_inr-total_inr_exp:.2f} INR**\n\n"
        for cat, d in summary.items():
            if d["spent_sgd"] > 0 or d["spent_inr"] > 0:
                pct = (d["spent_sgd"] / d["budget"] * 100) if d["budget"] > 0 else 0
                bar = "🟢" if pct < 70 else "🟡" if pct < 90 else "🔴"
                result += f"{bar} {d['icon']} **{cat}**: ${d['spent_sgd']:.2f}/${d['budget']:.2f} SGD"
                if d["spent_inr"] > 0: result += f" | ₹{d['spent_inr']:.2f} INR"
                result += "\n"
        return result

    elif tool_name == "get_spending_by_person":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        by_user = get_user_spending(fm, fy)
        inc_sgd, inc_inr, income_by_user = get_income_summary(fm, fy)
        result = f"👥 **{MONTH_NAMES[fm-1]} {fy} — Who Earned & Spent**\n\n"
        result += f"🏦 **Family Pool:** ${inc_sgd:.2f} SGD | ₹{inc_inr:.2f} INR\n\n"
        all_names = set(list(by_user.keys()) + list(income_by_user.keys()))
        for name in sorted(all_names):
            spent = by_user.get(name, {"sgd": 0, "inr": 0})
            earned = income_by_user.get(name, {"sgd": 0, "inr": 0})
            result += f"👤 **{name}**\n"
            result += f"  💚 Earned: ${earned['sgd']:.2f} SGD | ₹{earned['inr']:.2f} INR\n"
            result += f"  💸 Spent: ${spent['sgd']:.2f} SGD | ₹{spent['inr']:.2f} INR\n\n"
        return result

    elif tool_name == "get_recent_expenses":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        expenses = get_expenses(fm, fy)[:tool_input.get("limit", 10)]
        if not expenses: return f"No expenses for {MONTH_NAMES[fm-1]} {fy}!"
        result = f"📋 **Recent Expenses ({MONTH_NAMES[fm-1]} {fy}):**\n"
        for exp in expenses:
            symbol = "$" if exp.get("currency", "SGD") == "SGD" else "₹"
            result += (f"• {exp['categories']['icon']} **{symbol}{exp['amount']:.2f}** "
                      f"— {exp['description']} (👤 {exp['users']['name']}, {exp['date']})\n")
        return result

    elif tool_name == "get_balance":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        b = get_balance()
        inc_sgd, inc_inr, _ = get_income_summary(fm, fy)
        summary = get_monthly_summary(fm, fy)
        exp_sgd = sum(d["spent_sgd"] for d in summary.values())
        return (f"💰 **Family Balance:**\n"
                f"🇸🇬 SGD: **${b['sgd_amount']:.2f}** available\n"
                f"🇮🇳 INR: **₹{b['inr_amount']:.2f}** available\n\n"
                f"{MONTH_NAMES[fm-1]} {fy}: earned ${inc_sgd:.2f}, spent ${exp_sgd:.2f}, "
                f"saved ${inc_sgd-exp_sgd:.2f} SGD")

    elif tool_name == "get_alerts":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        alerts = get_alerts(fm, fy)
        return ("✅ All within budget! Great job!" if not alerts
                else "⚠️ **Budget Alerts:**\n" + "\n".join(alerts))

    elif tool_name == "get_insights":
        fm = st.session_state.get("filter_month", date.today().month)
        fy = st.session_state.get("filter_year", date.today().year)
        summary = get_monthly_summary(fm, fy)
        b = get_balance()
        inc_sgd, inc_inr, by_user = get_income_summary(fm, fy)
        user_spending = get_user_spending(fm, fy)
        data = f"Period: {MONTH_NAMES[fm-1]} {fy}\n"
        data += f"Balance: SGD ${b['sgd_amount']:.2f}, INR ₹{b['inr_amount']:.2f}\n"
        data += f"Income: SGD ${inc_sgd:.2f}, INR ₹{inc_inr:.2f}\n"
        for name in set(list(user_spending.keys()) + list(by_user.keys())):
            spent = user_spending.get(name, {"sgd": 0})
            earned = by_user.get(name, {"sgd": 0})
            data += f"{name}: earned ${earned['sgd']:.2f}, spent ${spent['sgd']:.2f} SGD\n"
        for cat, d in summary.items():
            if d["spent_sgd"] > 0:
                data += f"{cat}: ${d['spent_sgd']:.2f}/{d['budget']:.2f} SGD\n"
        return f"Give warm practical financial advice for Singapore family shared pool: {data}"

    elif tool_name == "update_balance":
        update_balance(sgd=tool_input.get("sgd_amount"), inr=tool_input.get("inr_amount"))
        parts = []
        if "sgd_amount" in tool_input: parts.append(f"SGD: ${tool_input['sgd_amount']:.2f}")
        if "inr_amount" in tool_input: parts.append(f"INR: ₹{tool_input['inr_amount']:.2f}")
        return f"✅ Balance updated! {' | '.join(parts)}"

    return "Done!"

# --- AGENT ---
def run_agent(user_message, user_id, user_name, filter_month=None, filter_year=None):
    st.session_state.messages = [
        m for m in st.session_state.messages
        if isinstance(m.get("content"), str)
    ]
    st.session_state.messages.append({"role": "user", "content": user_message})

    fm = filter_month or date.today().month
    fy = filter_year or date.today().year
    filter_label = f"{MONTH_NAMES[fm-1]} {fy}"

    system = f"""You are a warm, smart family finance assistant for a Singapore family.
Current user: {user_name}. Today: {date.today().strftime("%B %d, %Y")}.
Currently viewing: {filter_label} (the user has selected this month via the global filter).
Currencies: SGD ($) and INR (₹). Shared family pool — both incomes go into one pot.

Key rules:
- When user asks for summary, insights, expenses, or income — use data for {filter_label} unless they explicitly ask for a different month
- Spending mentioned → add_expense immediately, no questions asked
- Another person mentioned as spender → use spent_by field (e.g. "Amit paid rent" → spent_by="Amit")
- Relationship words like "husband", "wife", "him", "her", "spouse", "by him", "by her" → pass them as-is in spent_by/earned_by — the system will resolve to the right person automatically
- Income/salary mentioned → add_income immediately
- Another person mentioned as earner → use earned_by field
- Edit expense → find_expenses FIRST to get ID, then update_expense
- Delete expense → find_expenses FIRST to get ID, then delete_expense
- New category → add_category
- "who spent" or person comparison → get_spending_by_person
- Be warm, friendly, use emojis
- Always confirm what was recorded and under whose name
- Always mention which month the summary/data is for"""

    api_msgs = [{"role": m["role"], "content": m["content"]}
               for m in st.session_state.messages
               if isinstance(m.get("content"), str)]

    response_text = ""

    while True:
        resp = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=api_msgs
        )
        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": execute_tool(block.name, block.input, user_id)
                    })
            api_msgs.append({"role": "assistant", "content": resp.content})
            api_msgs.append({"role": "user", "content": results})
        else:
            for block in resp.content:
                if hasattr(block, "text"):
                    response_text += block.text
            break

    st.session_state.messages.append({"role": "assistant", "content": response_text})
    st.markdown(f'<div class="chat-bot">{response_text}</div>',
               unsafe_allow_html=True)
    return response_text

# --- LOGIN ---
def show_login():
    st.markdown("""
    <div style='text-align:center;padding:2rem 0 1rem;'>
        <div style='font-size:4rem;'>💰</div>
        <h1 style='color:#6C63FF;margin:0;'>Family Finance</h1>
        <p style='color:#666;'>SGD & INR • Shared Family Pool Tracker</p>
        <p style='color:#aaa;font-size:0.85rem;'>Select your profile to get started</p>
    </div>""", unsafe_allow_html=True)

    users = supabase.table("users").select("*").execute().data
    if not users:
        st.info("No users found. Add family members in the Settings tab after setup.")
        return

    # Click-to-login — no PIN required (suitable for demo/portfolio)
    cols = st.columns(min(len(users), 3))
    for i, u in enumerate(users):
        with cols[i % len(cols)]:
            st.markdown(f"""
            <div style='background:linear-gradient(135deg,#6C63FF,#a29bfe);
                border-radius:16px;padding:24px 12px;text-align:center;
                color:white;margin:6px 0;cursor:pointer;'>
                <div style='font-size:2.5rem;'>👤</div>
                <div style='font-weight:bold;font-size:1.1rem;margin-top:4px;'>{u["name"]}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Login as {u['name']}", key=f"login_{u['id']}", use_container_width=True):
                st.session_state.update({
                    "logged_in": True,
                    "user": {"id": u["id"], "name": u["name"]},
                    "messages": []
                })
                st.rerun()

# --- MAIN APP ---
def show_app():
    user = st.session_state.user

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### 👋 {user['name']}")
    with col2:
        if st.button("⬅️ Out"):
            st.session_state.update({
                "logged_in": False, "user": None, "messages": []})
            for k in ["sel_id", "sel_name"]:
                st.session_state.pop(k, None)
            st.rerun()

    # --- GLOBAL DATE FILTER ---
    st.markdown("---")
    fcol1, fcol2, fcol3 = st.columns([2, 2, 3])
    with fcol1:
        sel_month = st.selectbox(
            "📅 Month", range(1, 13),
            index=st.session_state.filter_month - 1,
            format_func=lambda m: MONTH_NAMES[m - 1],
            key="global_month")
    with fcol2:
        year_options = list(range(2023, date.today().year + 2))
        sel_year = st.selectbox(
            "📅 Year", year_options,
            index=year_options.index(st.session_state.filter_year),
            key="global_year")
    with fcol3:
        st.markdown(
            f"<div style='color:#6C63FF;font-weight:600;font-size:0.85rem;margin-bottom:4px;'>"
            f"Showing: {MONTH_NAMES[sel_month-1]} {sel_year}</div>",
            unsafe_allow_html=True)
        unified_on = st.toggle(
            "🔀 Show all in SGD",
            value=st.session_state.unified_currency,
            key="unified_toggle",
            help="Convert all INR amounts to SGD using the exchange rate set in Settings")

    if (sel_month != st.session_state.filter_month or
            sel_year != st.session_state.filter_year or
            unified_on != st.session_state.unified_currency):
        st.session_state.filter_month = sel_month
        st.session_state.filter_year = sel_year
        st.session_state.unified_currency = unified_on
        st.rerun()

    fm   = st.session_state.filter_month
    fy   = st.session_state.filter_year
    rate = st.session_state.inr_to_sgd_rate
    show_unified = st.session_state.unified_currency

    # --- ALL DATA FETCHED USING fm / fy ---
    balance = get_balance()
    categories = get_categories()
    cat_options = {c["name"]: c for c in categories}
    income_types = get_income_types()
    itype_options = {t["name"]: t for t in income_types}
    inc_sgd_raw, inc_inr_raw, income_by_user_raw = get_income_summary(fm, fy)
    summary_raw    = get_monthly_summary(fm, fy)
    user_spending_raw = get_user_spending(fm, fy)

    # Apply unified SGD conversion if toggle is on
    if show_unified:
        summary       = unified_summary(summary_raw, rate)
        inc_sgd, inc_inr, income_by_user = unified_income_summary(
            inc_sgd_raw, inc_inr_raw, income_by_user_raw, rate)
        user_spending = unified_user_spending(user_spending_raw, rate)
        cur_sym, cur_label = "$", "SGD (unified)"
    else:
        summary       = summary_raw
        inc_sgd, inc_inr, income_by_user = inc_sgd_raw, inc_inr_raw, income_by_user_raw
        user_spending = user_spending_raw
        cur_sym, cur_label = "$", "SGD"

    total_exp_sgd = sum(d["spent_sgd"] for d in summary.values())
    total_exp_inr = sum(d["spent_inr"] for d in summary.values())
    net_sgd = inc_sgd - total_exp_sgd
    net_inr = inc_inr - total_exp_inr
    alerts = get_alerts(fm, fy)
    # Always include ALL registered users in charts (even if no activity this month)
    all_registered = get_all_users()
    all_names = set([u["name"] for u in all_registered] +
                    list(user_spending.keys()) + list(income_by_user.keys()))

    # Balance cards — show monthly summary + available balance separately
    col1, col2 = st.columns(2)
    with col1:
        net_color_sgd = "#55efc4" if net_sgd >= 0 else "#ff7675"
        card_label = f"🔀 SGD (all converted @ {rate} rate)" if show_unified else "🇸🇬 SGD"
        st.markdown(f"""<div class='balance-card'>
            <div style='font-size:0.85rem;opacity:0.85;'>{card_label} — {MONTH_NAMES[fm-1]} {fy}</div>
            <div style='font-size:0.8rem;margin-top:4px;'>💚 Income: <b>${inc_sgd:.0f}</b> &nbsp;|&nbsp; 💸 Spent: <b>${total_exp_sgd:.0f}</b></div>
            <div style='font-size:1.5rem;font-weight:bold;color:{net_color_sgd};'>{"▲" if net_sgd >= 0 else "▼"} ${abs(net_sgd):.0f} net</div>
            <div style='font-size:0.75rem;opacity:0.85;border-top:1px solid rgba(255,255,255,0.3);margin-top:6px;padding-top:6px;'>🏦 Available: ${balance["sgd_amount"]:.2f}</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        if show_unified:
            st.markdown(f"""<div class='balance-card' style='opacity:0.5;'>
                <div style='font-size:0.85rem;'>🇮🇳 INR</div>
                <div style='font-size:0.9rem;margin-top:8px;'>All INR converted to SGD</div>
                <div style='font-size:0.75rem;opacity:0.85;border-top:1px solid rgba(255,255,255,0.3);margin-top:6px;padding-top:6px;'>🏦 Available: ₹{balance["inr_amount"]:.2f}</div>
            </div>""", unsafe_allow_html=True)
        else:
            net_color_inr = "#55efc4" if net_inr >= 0 else "#ff7675"
            st.markdown(f"""<div class='balance-card'>
                <div style='font-size:0.85rem;opacity:0.85;'>🇮🇳 INR — {MONTH_NAMES[fm-1]} {fy}</div>
                <div style='font-size:0.8rem;margin-top:4px;'>💚 Income: <b>₹{inc_inr:.0f}</b> &nbsp;|&nbsp; 💸 Spent: <b>₹{total_exp_inr:.0f}</b></div>
                <div style='font-size:1.5rem;font-weight:bold;color:{net_color_inr};'>{"▲" if net_inr >= 0 else "▼"} ₹{abs(net_inr):.0f} net</div>
                <div style='font-size:0.75rem;opacity:0.85;border-top:1px solid rgba(255,255,255,0.3);margin-top:6px;padding-top:6px;'>🏦 Available: ₹{balance["inr_amount"]:.2f}</div>
            </div>""", unsafe_allow_html=True)

    # Per person cards
    if all_names:
        cols = st.columns(len(all_names))
        for i, name in enumerate(sorted(all_names)):
            spent = user_spending.get(name, {"sgd": 0, "inr": 0})
            earned = income_by_user.get(name, {"sgd": 0, "inr": 0})
            with cols[i]:
                st.markdown(f"""<div class='person-card'>
                    <div style='font-weight:bold;font-size:1rem;'>👤 {name}</div>
                    <div style='font-size:0.8rem;'>💚 Earned: ${earned['sgd']:.0f}</div>
                    <div style='font-size:0.8rem;'>💸 Spent: ${spent['sgd']:.0f}</div>
                    <div style='font-size:0.75rem;opacity:0.9;'>₹{earned['inr']:.0f} in | ₹{spent['inr']:.0f} out</div>
                </div>""", unsafe_allow_html=True)

    # Alerts
    for alert in alerts[:2]:
        st.markdown(f"<div class='alert-card'>{alert}</div>",
                   unsafe_allow_html=True)

    # Update balance
    with st.expander("⚙️ Update Balance"):
        col1, col2 = st.columns(2)
        with col1:
            new_sgd = st.number_input("SGD", value=float(balance["sgd_amount"]),
                                     min_value=0.0, step=10.0, key="bal_sgd")
        with col2:
            new_inr = st.number_input("INR", value=float(balance["inr_amount"]),
                                     min_value=0.0, step=100.0, key="bal_inr")
        if st.button("💾 Save Balance", type="primary"):
            update_balance(sgd=new_sgd, inr=new_inr)
            st.success("✅ Updated!")
            st.rerun()

    # TABS
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "💬 Chat", "📊 Dashboard", "💚 Income",
        "📋 Expenses", "🏦 Import", "🎯 Budgets", "⚙️ Settings"
    ])

    # --- CHAT TAB ---
    with tab1:
        st.caption("💡 Try: 'My husband paid $3500 rent' or 'I got $5000 salary'")

        messages_container = st.container(height=400)
        with messages_container:
            if not st.session_state.messages:
                st.markdown(
                    "<div style='text-align:center;color:#999;padding:2rem;'>"
                    "👋 Start chatting! Record expenses or ask about your finances.</div>",
                    unsafe_allow_html=True)
            for msg in st.session_state.messages[-20:]:
                if isinstance(msg.get("content"), str):
                    css = "chat-user" if msg["role"] == "user" else "chat-bot"
                    st.markdown(f'<div class="{css}">{msg["content"]}</div>',
                               unsafe_allow_html=True)

        cols = st.columns(2)
        for i, (label, prompt) in enumerate([
            ("📊 Summary", "Show income and spending summary"),
            ("👥 Who Spent", "Show spending by each person"),
            ("⚠️ Alerts", "Check budget alerts"),
            ("💡 Insights", "Give spending insights")
        ]):
            with cols[i % 2]:
                if st.button(label, key=f"qa_{i}"):
                    with messages_container:
                        st.markdown(f'<div class="chat-user">{prompt}</div>',
                                   unsafe_allow_html=True)
                        with st.spinner("Thinking..."):
                            run_agent(prompt, user["id"], user["name"], fm, fy)
                    st.rerun()

        if prompt := st.chat_input(
                "e.g. 'My husband paid $3500 rent' or 'I got $5000 salary'"):
            with messages_container:
                st.markdown(f'<div class="chat-user">{prompt}</div>',
                           unsafe_allow_html=True)
                with st.spinner("Thinking..."):
                    run_agent(prompt, user["id"], user["name"], fm, fy)
            st.rerun()

    # --- DASHBOARD TAB ---
    # Color convention used across ALL charts (never changes):
    # GREEN  #00b894 = Income / Earned
    # PURPLE #6C63FF = Expense / Spent
    # GREY   #e0e0e0 = Budget ceiling
    COLOR_INCOME  = "#00b894"
    COLOR_EXPENSE = "#6C63FF"
    COLOR_BUDGET  = "#e0e0e0"

    with tab2:
        st.markdown(f"### 📊 {MONTH_NAMES[fm-1]} {fy} Dashboard")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("💚 SGD Income", f"${inc_sgd:.0f}")
            st.metric("💸 SGD Spent", f"${total_exp_sgd:.0f}",
                     delta=f"${net_sgd:.0f} saved" if net_sgd >= 0
                     else f"${abs(net_sgd):.0f} over",
                     delta_color="normal" if net_sgd >= 0 else "inverse")
        with col2:
            st.metric("💚 INR Income", f"₹{inc_inr:.0f}")
            st.metric("💸 INR Spent", f"₹{total_exp_inr:.0f}",
                     delta=f"₹{net_inr:.0f} saved" if net_inr >= 0
                     else f"₹{abs(net_inr):.0f} over",
                     delta_color="normal" if net_inr >= 0 else "inverse")

        # Chart 1: Spending per person
        # Uses TWO separate bar groups: one for Income (all green), one for Expense (per-person colour)
        # This way the legend correctly says "Income" and each person's name for expense
        if all_names:
            names = sorted(all_names)
            person_colors = ["#6C63FF", "#fd79a8", "#fdcb6e", "#00cec9", "#e17055"]
            fig_person = go.Figure()

            # Add ONE income bar per person — all green, legend entry per person
            for idx, name in enumerate(names):
                earned = income_by_user.get(name, {"sgd": 0})["sgd"]
                fig_person.add_trace(go.Bar(
                    name=f"{name}",
                    x=[f"{name}\nIncome"], y=[earned],
                    marker_color=COLOR_INCOME,
                    legendgroup=f"inc_{name}",
                    showlegend=False))   # x-axis label is enough

            # Add ONE expense bar per person — unique colour per person
            for idx, name in enumerate(names):
                spent = user_spending.get(name, {"sgd": 0})["sgd"]
                fig_person.add_trace(go.Bar(
                    name=f"{name}",
                    x=[f"{name}\nExpense"], y=[spent],
                    marker_color=person_colors[idx % len(person_colors)],
                    legendgroup=f"exp_{name}",
                    showlegend=False))

            # Build a clean annotation legend manually so nothing is mislabelled
            # Instead: just use clear x-axis labels — "Rupam Income", "Rupam Expense", etc.
            fig_person.update_layout(
                barmode="group", height=360,
                title=dict(text=f"Income vs Expense per Person — SGD ({MONTH_NAMES[fm-1]} {fy})",
                           x=0, font=dict(size=13)),
                margin=dict(l=10, r=10, t=55, b=60),
                xaxis=dict(tickfont=dict(size=11)),
                showlegend=False)

            # Add value labels on top of each bar
            fig_person.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
            st.plotly_chart(fig_person, use_container_width=True)

        # Chart 2: Income vs Expense pie — use go.Pie so colors are pinned, not auto-assigned
        if inc_sgd > 0 or total_exp_sgd > 0:
            fig_pie = go.Figure(go.Pie(
                labels=["Income", "Expense"],
                values=[max(inc_sgd, 0.01), max(total_exp_sgd, 0.01)],
                marker_colors=[COLOR_INCOME, COLOR_EXPENSE],
                textinfo="label+percent",
                hole=0.35))
            fig_pie.update_layout(
                height=320,
                title=dict(text=f"Income vs Expense — SGD ({MONTH_NAMES[fm-1]} {fy})", x=0, font=dict(size=13)),
                margin=dict(l=10, r=10, t=55, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5))
            st.plotly_chart(fig_pie, use_container_width=True)

        # Chart 3: Expense by Category — stacked by person so each member visible
        # Show ALL categories that have any spending (with or without a budget set)
        cats_with_spending = [cat for cat, d in summary.items() if d["spent_sgd"] > 0]
        if cats_with_spending:
            fig_cat = go.Figure()
            # Add budget line as grey bar (only for cats that have a budget)
            budget_vals = [summary[c]["budget"] if summary[c]["budget"] > 0 else None
                          for c in cats_with_spending]
            if any(v for v in budget_vals if v):
                fig_cat.add_trace(go.Bar(
                    name="Budget", x=cats_with_spending,
                    y=[v if v else 0 for v in budget_vals],
                    marker_color=COLOR_BUDGET, opacity=0.6))
            # Stacked expense bars per person
            person_colors = ["#6C63FF", "#fd79a8", "#fdcb6e", "#00cec9", "#e17055"]
            for idx, name in enumerate(sorted(all_names)):
                person_vals = [summary[c]["by_user"].get(name, {"sgd": 0})["sgd"]
                               for c in cats_with_spending]
                fig_cat.add_trace(go.Bar(
                    name=name, x=cats_with_spending, y=person_vals,
                    marker_color=person_colors[idx % len(person_colors)]))
            fig_cat.update_layout(
                barmode="stack", height=360,
                title=dict(text=f"Expense by Category & Person ({MONTH_NAMES[fm-1]} {fy})", x=0, font=dict(size=13)),
                margin=dict(l=10, r=10, t=55, b=90),
                xaxis_tickangle=-35,
                legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1))
            st.plotly_chart(fig_cat, use_container_width=True)

        # Budget progress bars — show ALL categories with spending, even if no budget set
        st.markdown("### Budget Progress")
        cats_to_show = [cat for cat, d in summary.items()
                        if d["spent_sgd"] > 0 or d["spent_inr"] > 0 or d["budget"] > 0]
        if not cats_to_show:
            st.info("No expenses recorded yet for this month.")
        for cat in cats_to_show:
            d = summary[cat]
            has_budget = d["budget"] > 0
            if has_budget:
                pct = min(d["spent_sgd"] / d["budget"], 1.0)
                color = "🟢" if pct < 0.7 else "🟡" if pct < 0.9 else "🔴"
                status = " ⚠️ OVERSPENT!" if d["spent_sgd"] > d["budget"] else (
                         " ✅ EXACT!" if d["spent_sgd"] == d["budget"] else "")
                budget_str = f"${d['spent_sgd']:.0f} / ${d['budget']:.0f} budget"
            else:
                pct = 0
                color = "⚪"
                status = " (no budget set)"
                budget_str = f"${d['spent_sgd']:.0f} spent"
            person_parts = [f"{n}: ${v['sgd']:.0f}"
                           for n, v in d["by_user"].items() if v["sgd"] > 0]
            if d["spent_inr"] > 0:
                person_parts += [f"₹{d['spent_inr']:.0f} INR"]
            breakdown = f" — {' | '.join(person_parts)}" if person_parts else ""
            st.markdown(f"{color} **{d['icon']} {cat}** — {budget_str}{status}{breakdown}")
            if has_budget:
                st.progress(pct)

    # --- INCOME TAB ---
    with tab3:
        st.markdown(f"### 💚 Income — {MONTH_NAMES[fm-1]} {fy}")
        with st.expander("➕ Add Income"):
            all_users = get_all_users()
            user_names = [u["name"] for u in all_users]
            col1, col2 = st.columns(2)
            with col1:
                inc_amount = st.number_input("Amount", min_value=0.01,
                                            step=100.0, key="new_inc_amt")
                inc_currency = st.selectbox("Currency", ["SGD", "INR"],
                                           key="new_inc_cur")
                if inc_currency == "SGD" and inc_amount > 50000:
                    st.caption(f"💡 ${inc_amount:.0f} SGD — that's a large SGD amount. If this is ₹{inc_amount:.0f}, switch to INR")
                elif inc_currency == "INR" and inc_amount < 100:
                    st.caption(f"💡 ₹{inc_amount:.2f} — if this is ${inc_amount:.2f} SGD, switch currency to SGD")
            with col2:
                inc_type = st.selectbox("Type", list(itype_options.keys()),
                                       key="new_inc_type")
                inc_date = st.date_input("Date", value=date.today(),
                                        key="new_inc_date")
            inc_earner = st.selectbox(
                "Earned by", user_names,
                index=user_names.index(user["name"])
                if user["name"] in user_names else 0,
                key="new_inc_earner")
            inc_desc = st.text_input("Description",
                                    placeholder="e.g. May 2026 Salary",
                                    key="new_inc_desc")
            if st.button("➕ Add Income", type="primary", key="add_inc_btn"):
                if inc_desc and inc_amount > 0:
                    earner = next((u for u in all_users
                                  if u["name"] == inc_earner), None)
                    earner_id = earner["id"] if earner else user["id"]
                    add_income_db(earner_id, itype_options[inc_type]["id"],
                                 inc_amount, inc_currency, inc_desc, inc_date)
                    st.success(f"✅ Income recorded for {inc_earner}!")
                    st.rerun()
                else:
                    st.error("Please fill all fields!")

        income_list = get_income(fm, fy)
        if income_list:
            for inc in income_list:
                symbol = "$" if inc["currency"] == "SGD" else "₹"
                col1, col2, col3 = st.columns([3, 1, 0.5])
                with col1:
                    st.markdown(f"""<div class='income-item'>
                        <strong>{inc['income_types']['icon']} {inc['description']}</strong><br>
                        <small>{inc['income_types']['name']} • 👤 {inc['users']['name']} • {inc['date']}</small>
                    </div>""", unsafe_allow_html=True)
                with col2:
                    st.markdown(
                        f"<div style='text-align:right;padding-top:14px;"
                        f"font-weight:bold;color:#00b894;'>"
                        f"{symbol}{inc['amount']:.2f}</div>",
                        unsafe_allow_html=True)
                with col3:
                    if st.button("🗑️", key=f"delinc_{inc['id']}"):
                        delete_income_db(inc["id"], inc["amount"], inc["currency"])
                        st.rerun()
        else:
            st.info(f"No income recorded for {MONTH_NAMES[fm-1]} {fy}.")

    # --- EXPENSES TAB ---
    with tab4:
        st.markdown(f"### 📋 Expenses — {MONTH_NAMES[fm-1]} {fy}")
        with st.expander("➕ Add Expense Manually"):
            all_users = get_all_users()
            user_names = [u["name"] for u in all_users]
            col1, col2 = st.columns(2)
            with col1:
                exp_amount = st.number_input("Amount", min_value=0.01,
                                            step=0.50, key="new_exp_amt")
                exp_currency = st.selectbox("Currency", ["SGD", "INR"],
                                           key="new_exp_cur")
                # Warn if amount looks wrong for the selected currency
                if exp_currency == "SGD" and exp_amount > 500:
                    st.caption(f"💡 SGD {exp_amount:.0f} — if this is actually ₹{exp_amount:.0f}, switch currency to INR")
                elif exp_currency == "INR" and exp_amount < 10:
                    st.caption(f"💡 ₹{exp_amount:.2f} — if this is actually ${exp_amount:.2f} SGD, switch currency to SGD")
            with col2:
                exp_cat = st.selectbox("Category", list(cat_options.keys()),
                                      key="new_exp_cat")
                exp_date = st.date_input("Date", value=date.today(),
                                        key="new_exp_date")
            exp_spender = st.selectbox(
                "Spent by", user_names,
                index=user_names.index(user["name"])
                if user["name"] in user_names else 0,
                key="new_exp_spender")
            exp_desc = st.text_input("Description",
                                    placeholder="e.g. Lunch at hawker",
                                    key="new_exp_desc")
            if st.button("➕ Add Expense", type="primary", key="add_exp_btn"):
                if exp_desc and exp_amount > 0:
                    spender = next((u for u in all_users
                                   if u["name"] == exp_spender), None)
                    spender_id = spender["id"] if spender else user["id"]
                    add_expense_db(spender_id, cat_options[exp_cat]["id"],
                                  exp_amount, exp_desc, exp_currency, exp_date)
                    st.success(f"✅ Added under {exp_spender}!")
                    st.rerun()
                else:
                    st.error("Please fill all fields!")

        expenses = get_expenses(fm, fy)
        if expenses:
            for exp in expenses:
                symbol = "$" if exp.get("currency", "SGD") == "SGD" else "₹"
                with st.expander(
                    f"{exp['categories']['icon']} {symbol}{exp['amount']:.2f} — "
                    f"{exp['description']} | 👤 {exp['users']['name']} ({exp['date']})"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        edit_amount = st.number_input(
                            "Amount", value=float(exp["amount"]),
                            min_value=0.01, key=f"ea_{exp['id']}")
                        edit_currency = st.selectbox(
                            "Currency", ["SGD", "INR"],
                            index=0 if exp.get("currency", "SGD") == "SGD" else 1,
                            key=f"ec_{exp['id']}")
                    with col2:
                        edit_cat = st.selectbox(
                            "Category", list(cat_options.keys()),
                            index=list(cat_options.keys()).index(
                                exp["categories"]["name"])
                            if exp["categories"]["name"] in cat_options else 0,
                            key=f"ecat_{exp['id']}")
                        edit_date = st.date_input(
                            "Date",
                            value=datetime.strptime(exp["date"], "%Y-%m-%d").date(),
                            key=f"ed_{exp['id']}")
                    edit_desc = st.text_input(
                        "Description", value=exp["description"],
                        key=f"edesc_{exp['id']}")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("💾 Save", key=f"save_{exp['id']}"):
                            update_expense_db(
                                exp["id"], exp["amount"],
                                exp.get("currency", "SGD"),
                                edit_amount, edit_currency, edit_desc,
                                cat_options[edit_cat]["id"], edit_date,
                                old_cat_id=exp["category_id"])  # enables merchant rule saving
                            st.success("✅ Updated!")
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"del_{exp['id']}"):
                            delete_expense_db(exp["id"], exp["amount"],
                                            exp.get("currency", "SGD"))
                            st.success("🗑️ Deleted!")
                            st.rerun()
        else:
            st.info(f"No expenses for {MONTH_NAMES[fm-1]} {fy}.")

    # --- IMPORT TAB ---
    with tab5:
        st.markdown("### 🏦 Import Bank Statement")
        st.info(
            "🔒 **Privacy:** File processed locally on your machine. "
            "Only date/amount/description sent to AI. "
            "Account numbers & personal details auto-removed.")

        col1, col2 = st.columns(2)
        with col1:
            import_currency = st.selectbox(
                "Statement Currency", ["SGD", "INR"], key="import_cur")
        with col2:
            st.caption("✅ Works with DBS, OCBC, HDFC, SBI, any bank!")

        uploaded_file = st.file_uploader(
            "Upload Statement",
            type=["pdf", "csv", "xlsx", "xls", "png", "jpg", "jpeg"],
            key="statement_upload")

        if uploaded_file and st.button("🔍 Extract Transactions", type="primary"):
            with st.spinner("Reading file locally..."):
                raw_text, error = extract_text_from_file(uploaded_file)
            if error:
                st.error(f"Could not read file: {error}")
            elif not raw_text or len(raw_text.strip()) < 50:
                st.error("Could not extract enough text. Try a different format.")
            else:
                with st.spinner("Removing sensitive data..."):
                    clean_text = strip_sensitive_data(raw_text)
                with st.spinner("AI reading transactions... (~30 seconds)"):
                    transactions, error = parse_statement_with_claude(
                        clean_text, import_currency)
                if error:
                    st.error(f"Could not parse: {error}")
                elif not transactions:
                    st.error("No transactions found.")
                else:
                    st.session_state.import_preview = transactions
                    st.session_state.import_filename = uploaded_file.name
                    st.success(
                        f"✅ Found {len(transactions)} transactions! Review below.")

        if st.session_state.import_preview:
            transactions = st.session_state.import_preview
            # Filter out CC bill payments / inter-account transfers (type="skip")
            skipped_auto = [t for t in transactions if t.get("type") == "skip"]
            # Also filter out zero or negative amounts — these are parse errors
            invalid_amount = [t for t in transactions
                              if t.get("type") != "skip" and float(t.get("amount", 0)) <= 0]
            expenses_preview = [t for t in transactions
                                 if t.get("type") == "expense" and float(t.get("amount", 0)) > 0]
            income_preview   = [t for t in transactions
                                 if t.get("type") == "income"  and float(t.get("amount", 0)) > 0]
            if skipped_auto:
                skip_msgs = []
                if skipped_auto:
                    skip_msgs.append(f"{len(skipped_auto)} credit card bill payment(s)/transfer(s)")
                if invalid_amount:
                    skip_msgs.append(f"{len(invalid_amount)} zero/negative amount(s)")
                if skip_msgs:
                    st.info(f"ℹ️ Auto-skipped: {', '.join(skip_msgs)}. GIRO payments to real payees (tax, utilities, insurance) are kept.")
            symbol = "$" if import_currency == "SGD" else "₹"

            st.markdown(f"### Review {len(transactions)} Transactions")
            st.caption("✅ New categories will be auto-created with smart icons!")
            selected = []

            if income_preview:
                st.markdown("#### 💚 Income")
                for i, txn in enumerate(income_preview):
                    col1, col2, col3, col4 = st.columns([0.5, 2.5, 1, 1.5])
                    with col1:
                        checked = st.checkbox("", value=True, key=f"imp_inc_{i}")
                    with col2:
                        st.caption(txn.get("description", ""))
                    with col3:
                        st.caption(f"**{symbol}{txn.get('amount',0):.2f}**")
                    with col4:
                        st.caption(txn.get("date", ""))
                    if checked:
                        selected.append(("income", txn))

            if expenses_preview:
                st.markdown("#### 💸 Expenses")
                # Pre-run semantic match + load hashes for preview
                preview_cat_names = list({
                    txn.get("suggested_category", "Others").strip()
                    for txn in expenses_preview
                })
                with st.spinner("🧠 Resolving categories..."):
                    preview_semantic_map = semantic_category_match(
                        preview_cat_names, fresh_categories)
                preview_hashes = get_imported_hashes()

                for i, txn in enumerate(expenses_preview):
                    col1, col2, col3, col4 = st.columns([0.5, 2, 1, 1.5])
                    with col1:
                        checked = st.checkbox("", value=True, key=f"imp_exp_{i}")
                    with col2:
                        st.caption(txn.get("description", ""))
                    with col3:
                        st.caption(f"**{symbol}{txn.get('amount',0):.2f}**")
                    with col4:
                        raw_sug  = txn.get("suggested_category", "Others").strip()
                        desc     = txn.get("description", "")
                        txn_date_str = txn.get("date", str(date.today()))
                        try:
                            _d = datetime.strptime(txn_date_str, "%Y-%m-%d").date()
                        except Exception:
                            _d = date.today()
                        _hash = make_txn_hash(desc, txn.get("amount", 0),
                                              _d, import_currency)
                        is_dup = _hash in preview_hashes
                        if is_dup:
                            st.caption(f"🔁 Already imported — will be skipped")
                        else:
                            rule_match = apply_merchant_rules(desc, get_merchant_rules())
                            if rule_match:
                                cat_label = f"🧠 {rule_match['icon']} {rule_match['name']}"
                            elif preview_semantic_map.get(raw_sug):
                                resolved = preview_semantic_map[raw_sug]
                                cat_label = f"✅ {resolved['icon']} {resolved['name']}"
                            else:
                                cat_label = f"🆕 {raw_sug}"
                            st.caption(f"{txn_date_str} • {cat_label}")
                    if checked:
                        selected.append(("expense", txn))

            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"✅ Import {len(selected)}", type="primary"):
                    imported = 0
                    skipped = 0
                    new_cats = set()
                    fresh_categories = get_categories()

                    # Step 1: Load saved merchant rules + already-imported hashes
                    merchant_rules    = get_merchant_rules()
                    imported_hashes   = get_imported_hashes()
                    duplicate_count   = 0

                    # Step 2: Collect unique suggested category names for semantic matching
                    suggested_cat_names = list({
                        txn.get("suggested_category", "Others").strip()
                        for t, txn in selected if t == "expense"
                        and txn.get("suggested_category", "").strip()
                    })

                    # Step 3: Semantic match suggested names → existing categories (one Claude call)
                    with st.spinner("🧠 Matching categories..."):
                        semantic_map = semantic_category_match(suggested_cat_names, fresh_categories)

                    # Step 4: Import — priority order per transaction:
                    #   1. Merchant rule (user's past correction — highest trust)
                    #   2. Semantic category match (Claude reasoning on category names)
                    #   3. String substring match (fast fallback)
                    #   4. Create new category (last resort)
                    for txn_type, txn in selected:
                        try:
                            txn_date = datetime.strptime(txn["date"], "%Y-%m-%d").date()

                            if txn_type == "income":
                                # Duplicate check
                                txn_hash = make_txn_hash(
                                    txn["description"], txn["amount"],
                                    txn_date, import_currency)
                                if txn_hash in imported_hashes:
                                    duplicate_count += 1
                                    continue
                                itype = income_types[0]
                                add_income_db(
                                    user["id"], itype["id"],
                                    txn["amount"], import_currency,
                                    txn["description"], txn_date)
                                save_import_hash(txn_hash)
                                imported_hashes.add(txn_hash)
                                imported += 1
                            else:
                                cat_name = txn.get("suggested_category", "Others").strip()
                                desc     = txn.get("description", "")

                                # Priority 1: merchant rule — user previously corrected this merchant
                                matched_cat = apply_merchant_rules(desc, merchant_rules)

                                # Priority 2: semantic category name match
                                if not matched_cat:
                                    matched_cat = semantic_map.get(cat_name)

                                # Priority 3: string substring match
                                if not matched_cat:
                                    matched_cat = next(
                                        (c for c in fresh_categories
                                        if cat_name.lower() in c["name"].lower()
                                        or c["name"].lower() in cat_name.lower()),
                                        None
                                    )

                                # Priority 4: create new category
                                if not matched_cat:
                                    matched_cat = get_or_create_category(cat_name)
                                    fresh_categories = get_categories()
                                    semantic_map = semantic_category_match(
                                        suggested_cat_names, fresh_categories)
                                    if matched_cat and matched_cat.get("id"):
                                        new_cats.add(
                                            f"{matched_cat.get('icon','📦')} {cat_name}")

                                if matched_cat and matched_cat.get("id"):
                                    # Duplicate check
                                    txn_hash = make_txn_hash(
                                        txn["description"], txn["amount"],
                                        txn_date, import_currency)
                                    if txn_hash in imported_hashes:
                                        duplicate_count += 1
                                    else:
                                        add_expense_db(
                                            user["id"], matched_cat["id"],
                                            txn["amount"], txn["description"],
                                            import_currency, txn_date)
                                        save_import_hash(txn_hash)
                                        imported_hashes.add(txn_hash)
                                        imported += 1
                                else:
                                    skipped += 1
                                    st.warning(f"Skipped (no category): {txn.get('description','')}")

                        except Exception as e:
                            skipped += 1
                            st.warning(f"Skipped: {txn.get('description','')} — {e}")

                    try:
                        supabase.table("import_log").insert({
                            "user_id": user["id"],
                            "filename": st.session_state.import_filename,
                            "imported_count": imported
                        }).execute()
                    except:
                        pass

                    msg = f"🎉 Imported {imported} transactions!"
                    if skipped:       msg += f" ({skipped} skipped)"
                    if duplicate_count: msg += f" · {duplicate_count} duplicate(s) skipped — already in your records"
                    st.success(msg)
                    if new_cats:
                        st.info(f"✨ Created {len(new_cats)} new categories: {', '.join(new_cats)}")

                    # Auto-switch filter to the month of imported transactions
                    if selected:
                        try:
                            first_date = datetime.strptime(
                                selected[0][1]["date"], "%Y-%m-%d").date()
                            st.session_state.filter_month = first_date.month
                            st.session_state.filter_year = first_date.year
                        except:
                            pass

                    st.session_state.import_preview = None
                    st.rerun()

            with col2:
                if st.button("❌ Cancel"):
                    st.session_state.import_preview = None
                    st.rerun()

    # --- BUDGETS TAB ---
    with tab6:
        st.markdown("### 🎯 Category Budgets")
        with st.expander("➕ Add New Category"):
            col1, col2 = st.columns(2)
            with col1:
                new_cat_name = st.text_input("Name", placeholder="e.g. Gym",
                                            key="new_cat_name")
                new_cat_icon = st.text_input("Icon", placeholder="e.g. 💪",
                                            key="new_cat_icon")
            with col2:
                new_cat_sgd = st.number_input("SGD Budget", min_value=0.0,
                                             step=50.0, key="new_cat_sgd")
                new_cat_inr = st.number_input("INR Budget", min_value=0.0,
                                             step=500.0, key="new_cat_inr")
            if st.button("➕ Add Category", type="primary", key="add_cat_btn"):
                if new_cat_name:
                    supabase.table("categories").insert({
                        "name": new_cat_name,
                        "icon": new_cat_icon or "📦",
                        "budget": new_cat_sgd,
                        "budget_inr": new_cat_inr,
                        "is_active": True
                    }).execute()
                    st.success("✅ Added!")
                    st.rerun()

        for cat in categories:
            with st.expander(f"{cat['icon']} {cat['name']}"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    edit_name = st.text_input("Name", value=cat["name"],
                                             key=f"cn_{cat['id']}")
                    edit_icon = st.text_input("Icon", value=cat["icon"],
                                             key=f"ci_{cat['id']}")
                with col2:
                    edit_sgd = st.number_input(
                        "SGD Budget", value=float(cat["budget"]),
                        min_value=0.0, step=50.0, key=f"cs_{cat['id']}")
                with col3:
                    edit_inr = st.number_input(
                        "INR Budget", value=float(cat.get("budget_inr", 0)),
                        min_value=0.0, step=500.0, key=f"ci2_{cat['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Save", key=f"savec_{cat['id']}"):
                        supabase.table("categories").update({
                            "name": edit_name, "icon": edit_icon,
                            "budget": edit_sgd, "budget_inr": edit_inr
                        }).eq("id", cat["id"]).execute()
                        st.success("✅ Saved!")
                        st.rerun()
                with col2:
                    if st.button("🗑️ Delete", key=f"delc_{cat['id']}"):
                        supabase.table("categories").update(
                            {"is_active": False}).eq("id", cat["id"]).execute()
                        st.success("🗑️ Deleted!")
                        st.rerun()

    # --- SETTINGS TAB ---
    with tab7:
        st.markdown("### ⚙️ Settings")

        st.markdown("#### 💱 Currency Settings")
        col1, col2 = st.columns([2, 3])
        with col1:
            new_rate = st.number_input(
                "INR → SGD rate (1 INR = ? SGD)",
                value=float(st.session_state.inr_to_sgd_rate),
                min_value=0.001, max_value=1.0,
                step=0.001, format="%.4f",
                key="rate_input",
                help="e.g. if 1 SGD = 62 INR, enter 0.0161")
            if st.button("💾 Save Rate", key="save_rate"):
                st.session_state.inr_to_sgd_rate = new_rate
                st.success(f"✅ Rate saved: 1 INR = {new_rate:.4f} SGD  (1 SGD ≈ {1/new_rate:.1f} INR)")
        with col2:
            st.markdown(f"""
            <div style='background:#f0f4ff;border-radius:10px;padding:12px;margin-top:8px;font-size:0.85rem;'>
            <b>Current rate:</b> 1 INR = {st.session_state.inr_to_sgd_rate:.4f} SGD<br>
            <b>Equivalent:</b> 1 SGD ≈ {1/st.session_state.inr_to_sgd_rate:.1f} INR<br>
            <br>Toggle <b>"Show all in SGD"</b> in the filter bar to see all amounts unified.
            </div>""", unsafe_allow_html=True)
        st.markdown("---")

        st.markdown("#### 👤 Family Members")
        users_list = supabase.table("users").select("*").execute().data

        with st.expander("➕ Add Family Member"):
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Name", key="new_user_name")
            with col2:
                new_pin = st.text_input("PIN (4 digits)", max_chars=4,
                                       key="new_user_pin")
            if st.button("➕ Add Member", type="primary", key="add_user_btn"):
                if new_name and len(new_pin) == 4:
                    supabase.table("users").insert(
                        {"name": new_name, "pin": new_pin}).execute()
                    st.success("✅ Added!")
                    st.rerun()
                else:
                    st.error("Name and 4-digit PIN required!")

        for u in users_list:
            with st.expander(f"👤 {u['name']}"):
                col1, col2 = st.columns(2)
                with col1:
                    edit_uname = st.text_input("Name", value=u["name"],
                                              key=f"un_{u['id']}")
                with col2:
                    edit_upin = st.text_input("PIN", value=u["pin"],
                                             max_chars=4, key=f"up_{u['id']}")
                if st.button("💾 Save", key=f"saveu_{u['id']}"):
                    supabase.table("users").update(
                        {"name": edit_uname, "pin": edit_upin}
                    ).eq("id", u["id"]).execute()
                    st.success("✅ Saved!")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### 🧠 Merchant Memory")
        st.caption("These rules were saved when you corrected a category on an expense. They take highest priority during import.")
        saved_rules = get_merchant_rules()
        if not saved_rules:
            st.info("No merchant rules yet. Correct a category on any expense to create one.")
        else:
            for rule in saved_rules:
                cat = rule.get("categories", {})
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.caption(f"**{rule['merchant_pattern']}**")
                with col2:
                    st.caption(f"→ {cat.get('icon','📦')} {cat.get('name','Unknown')}")
                with col3:
                    if st.button("🗑️", key=f"del_rule_{rule['id']}"):
                        try:
                            supabase.table("merchant_rules").delete().eq(
                                "id", rule["id"]).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        st.markdown("#### 🗑️ Clear Chat")
        if st.button("🗑️ Clear Chat History"):
            st.session_state.messages = []
            st.success("✅ Cleared!")
            st.rerun()

        st.markdown("---")
        st.markdown("#### 🚨 Clear All Data")
        st.warning("⚠️ This will permanently delete ALL expenses, income, and reset the balance to zero. Use only for testing.")
        if "confirm_clear_all" not in st.session_state:
            st.session_state.confirm_clear_all = False

        if not st.session_state.confirm_clear_all:
            if st.button("🗑️ Clear All Data", type="secondary"):
                st.session_state.confirm_clear_all = True
                st.rerun()
        else:
            st.error("⚠️ Are you sure? This cannot be undone.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Yes, delete everything", type="primary"):
                    try:
                        # Soft-delete all expenses
                        supabase.table("expenses").update({"is_deleted": True}).eq("is_deleted", False).execute()
                        # Soft-delete all income
                        supabase.table("income").update({"is_deleted": True}).eq("is_deleted", False).execute()
                        # Reset balance to zero
                        balance = get_balance()
                        supabase.table("balance").update({"sgd_amount": 0, "inr_amount": 0}).eq("id", balance["id"]).execute()
                        st.session_state.confirm_clear_all = False
                        st.session_state.messages = []
                        st.success("✅ All data cleared!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            with col2:
                if st.button("❌ Cancel"):
                    st.session_state.confirm_clear_all = False
                    st.rerun()

# --- RUN ---
if not st.session_state.logged_in:
    show_login()
else:
    show_app()