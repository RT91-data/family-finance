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
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
for key, default in [
    ("logged_in", False), ("user", None), ("messages", []),
    ("import_preview", None), ("import_filename", None)
]:
    if key not in st.session_state:
        st.session_state[key] = default

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

def update_expense_db(expense_id, old_amount, old_currency, new_amount, new_currency, new_desc, new_cat_id, new_date):
    restore_balance(old_amount, old_currency)
    supabase.table("expenses").update({
        "amount": float(new_amount), "currency": new_currency,
        "description": new_desc, "category_id": new_cat_id,
        "date": str(new_date)
    }).eq("id", expense_id).execute()
    deduct_balance(float(new_amount), new_currency)

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

def get_user_spending():
    expenses = get_expenses()
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

def get_alerts():
    alerts = []
    for cat, d in get_monthly_summary().items():
        if d["budget"] > 0:
            pct = d["spent_sgd"] / d["budget"] * 100
            if pct > 100:
                alerts.append(f"🔴 {d['icon']} {cat}: Overspent by ${d['spent_sgd']-d['budget']:.2f} SGD!")
            elif pct >= 90:
                alerts.append(f"🟡 {d['icon']} {cat}: {pct:.0f}% of SGD budget used!")
        if d["budget_inr"] > 0 and d["spent_inr"] > d["budget_inr"]:
            alerts.append(f"🔴 {d['icon']} {cat}: Overspent by ₹{d['spent_inr']-d['budget_inr']:.2f} INR!")
    return alerts

def get_or_create_category(cat_name):
    """Get existing category or auto-create new one during import."""
    categories = get_categories()

    # Try to find existing match
    matched = next(
        (c for c in categories if cat_name.lower() in c["name"].lower()
         or c["name"].lower() in cat_name.lower()),
        None
    )
    if matched:
        return matched

    # Smart icon map — covers Singapore + India merchants
    icon_map = {
        # Food & Dining
        "food": "🍜", "dining": "🍜", "restaurant": "🍜", "cafe": "☕",
        "coffee": "☕", "starbucks": "☕", "toast box": "☕", "ya kun": "☕",
        "hawker": "🍜", "kopitiam": "🍜", "foodcourt": "🍜",
        "mcdonalds": "🍔", "mcdonald": "🍔", "burger": "🍔", "kfc": "🍗",
        "pizza": "🍕", "dominos": "🍕", "subway": "🥪",
        "foodpanda": "🍕", "deliveroo": "🍕", "grabfood": "🍕",
        "swiggy": "🍕", "zomato": "🍕",
        # Grocery & Supermarket
        "ntuc": "🛒", "fairprice": "🛒", "cold storage": "🛒",
        "giant": "🛒", "sheng siong": "🛒", "don don donki": "🛒",
        "big basket": "🛒", "grofers": "🛒", "blinkit": "🛒",
        "grocery": "🛒", "supermarket": "🛒", "market": "🛒",
        # Transport
        "grab": "🚗", "gojek": "🚗", "taxi": "🚗", "phv": "🚗",
        "comfort": "🚗", "delgro": "🚗", "cabcharge": "🚗",
        "ola": "🚗", "uber": "🚗", "rapido": "🚗",
        "mrt": "🚇", "bus": "🚌", "train": "🚇", "metro": "🚇",
        "ezlink": "🚇", "transit": "🚇", "smrt": "🚇",
        "petrol": "⛽", "shell": "⛽", "caltex": "⛽", "sinopec": "⛽",
        "parking": "🅿️",
        # Online Shopping
        "shopee": "🛍️", "lazada": "🛍️", "amazon": "📦",
        "taobao": "📦", "alibaba": "📦", "zalora": "👗",
        "flipkart": "📦", "myntra": "👗", "ajio": "👗",
        "meesho": "🛍️", "snapdeal": "📦",
        "online": "🛒", "ecommerce": "💻", "delivery": "🚚",
        # Shopping
        "shopping": "🛍️", "clothes": "👗", "fashion": "👗",
        "uniqlo": "👕", "zara": "👗", "hm": "👗", "cotton on": "👕",
        "watsons": "💄", "guardian": "💄", "sasa": "💄",
        "ikea": "🏠", "courts": "📺", "harvey norman": "📺",
        "popular": "📚", "kinokuniya": "📚", "books": "📚",
        # Bills & Utilities
        "bills": "💡", "utilities": "💡", "sp group": "💡",
        "city gas": "💡", "power": "💡", "electricity": "💡",
        "singtel": "📱", "starhub": "📱", "m1": "📱",
        "circles": "📱", "redone": "📱", "gomo": "📱",
        "airtel": "📱", "jio": "📱", "bsnl": "📱", "vodafone": "📱",
        "phone": "📱", "mobile": "📱", "internet": "🌐",
        "broadband": "🌐", "wifi": "🌐",
        "water": "💧", "pub": "💧",
        # Health & Medical
        "health": "💊", "medical": "🏥", "pharmacy": "💊",
        "dental": "🦷", "doctor": "🏥", "clinic": "🏥",
        "hospital": "🏥", "polyclinic": "🏥", "sgh": "🏥",
        "ttsh": "🏥", "nuh": "🏥", "kk": "🏥",
        "apollo": "🏥", "fortis": "🏥", "max": "🏥",
        "unity pharmacy": "💊", "guardian pharmacy": "💊",
        # Entertainment
        "entertainment": "🎬", "netflix": "🎬", "spotify": "🎵",
        "disney": "🎬", "youtube": "🎬", "amazon prime": "🎬",
        "hotstar": "🎬", "zee5": "🎬", "sonyliv": "🎬",
        "movies": "🎬", "cinema": "🎬", "cathay": "🎬",
        "gv": "🎬", "shaw": "🎬", "golden village": "🎬",
        "games": "🎮", "steam": "🎮", "playstation": "🎮",
        "karaoke": "🎤", "ktv": "🎤",
        # Education
        "education": "📚", "school": "🏫", "tuition": "📚",
        "course": "📚", "udemy": "💻", "coursera": "💻",
        "skillsfuture": "📚", "learning": "📚",
        # Travel
        "travel": "✈️", "hotel": "🏨", "flight": "✈️",
        "airbnb": "🏠", "agoda": "🏨", "booking": "🏨",
        "singapore airlines": "✈️", "sia": "✈️", "scoot": "✈️",
        "airasia": "✈️", "indigo": "✈️", "air india": "✈️",
        # Fitness & Beauty
        "gym": "💪", "fitness": "💪", "yoga": "🧘",
        "anytime fitness": "💪", "true fitness": "💪",
        "hair": "💇", "salon": "💇", "spa": "💆",
        "nail": "💅", "beauty": "💄",
        # Housing & Home
        "rent": "🏠", "mortgage": "🏠", "housing": "🏠",
        "hdb": "🏠", "condo": "🏠", "property": "🏠",
        "renovation": "🔨", "plumber": "🔧", "electrician": "🔧",
        # Insurance & Finance
        "insurance": "🛡️", "prudential": "🛡️", "aia": "🛡️",
        "ntuc income": "🛡️", "great eastern": "🛡️",
        "lic": "🛡️", "hdfc life": "🛡️", "sbi life": "🛡️",
        "cpf": "💰", "medisave": "💊", "investment": "📈",
        "stocks": "📈", "mutual fund": "📈", "fd": "💰",
        # Kids & Family
        "kids": "👶", "baby": "👶", "childcare": "👶",
        "toys": "🧸", "toysrus": "🧸", "kiddy palace": "🧸",
        # Pets
        "pet": "🐾", "vet": "🐾", "dog": "🐕", "cat": "🐈",
        # Religion & Charity
        "temple": "🙏", "church": "🙏", "mosque": "🙏",
        "donation": "🙏", "charity": "🙏", "zakat": "🙏",
        # Misc
        "atm": "🏧", "cash": "💵", "transfer": "💸",
        "casino": "🎰", "genting": "🎰", "rws": "🎰",
        "alcohol": "🍺", "wine": "🍷", "beer": "🍺",
    }

    icon = "📦"
    for keyword, emoji in icon_map.items():
        if keyword in cat_name.lower():
            icon = emoji
            break

    # Create new category
    result = supabase.table("categories").insert({
        "name": cat_name,
        "icon": icon,
        "budget": 0,
        "budget_inr": 0,
        "is_active": True
    }).execute()

    if result.data:
        return result.data[0]
    return {"id": None, "name": cat_name, "icon": icon}

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
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD]', text)
    text = re.sub(r'Account\s*(?:No|Number|#)[:\s]*[\d\-X*]+',
                 'Account [REMOVED]', text, flags=re.IGNORECASE)
    text = re.sub(r'Card\s*(?:No|Number|#)[:\s]*[\d\-X*]+',
                 'Card [REMOVED]', text, flags=re.IGNORECASE)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                 '[EMAIL]', text)
    text = re.sub(r'\b[689]\d{7}\b', '[PHONE]', text)
    text = re.sub(r'\b[A-Z]\d{7}[A-Z]\b', '[NRIC]', text)
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
- description: clean merchant/payee name only
- suggested_category: be specific and descriptive, use the actual merchant type
- currency is {currency} ({symbol})

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

def resolve_user(name_hint, current_user_id):
    if not name_hint:
        return current_user_id, None
    all_users = get_all_users()
    matched = next(
        (u for u in all_users if name_hint.lower() in u["name"].lower()
         or u["name"].lower() in name_hint.lower()), None)
    if matched:
        return matched["id"], matched["name"]
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
        return (f"✅ Added: {symbol}{amount:.2f} for **{description}** → "
                f"{matched_cat['icon']} {matched_cat['name']} (👤 {spender_name})")

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
                         new_amount, new_currency, new_desc, new_cat_id, new_date)
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
        summary = get_monthly_summary()
        total_sgd_exp = sum(d["spent_sgd"] for d in summary.values())
        total_inr_exp = sum(d["spent_inr"] for d in summary.values())
        inc_sgd, inc_inr, by_user = get_income_summary()
        net_sgd = inc_sgd - total_sgd_exp
        result = f"📊 **{date.today().strftime('%B %Y')} Family Summary**\n"
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
        by_user = get_user_spending()
        inc_sgd, inc_inr, income_by_user = get_income_summary()
        result = f"👥 **{date.today().strftime('%B %Y')} — Who Earned & Spent**\n\n"
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
        expenses = get_expenses()[:tool_input.get("limit", 10)]
        if not expenses: return "No expenses this month!"
        result = "📋 **Recent Expenses:**\n"
        for exp in expenses:
            symbol = "$" if exp.get("currency", "SGD") == "SGD" else "₹"
            result += (f"• {exp['categories']['icon']} **{symbol}{exp['amount']:.2f}** "
                      f"— {exp['description']} (👤 {exp['users']['name']}, {exp['date']})\n")
        return result

    elif tool_name == "get_balance":
        b = get_balance()
        inc_sgd, inc_inr, _ = get_income_summary()
        summary = get_monthly_summary()
        exp_sgd = sum(d["spent_sgd"] for d in summary.values())
        return (f"💰 **Family Balance:**\n"
                f"🇸🇬 SGD: **${b['sgd_amount']:.2f}** available\n"
                f"🇮🇳 INR: **₹{b['inr_amount']:.2f}** available\n\n"
                f"This month: earned ${inc_sgd:.2f}, spent ${exp_sgd:.2f}, "
                f"saved ${inc_sgd-exp_sgd:.2f} SGD")

    elif tool_name == "get_alerts":
        alerts = get_alerts()
        return ("✅ All within budget! Great job!" if not alerts
                else "⚠️ **Budget Alerts:**\n" + "\n".join(alerts))

    elif tool_name == "get_insights":
        summary = get_monthly_summary()
        b = get_balance()
        inc_sgd, inc_inr, by_user = get_income_summary()
        user_spending = get_user_spending()
        data = f"Balance: SGD ${b['sgd_amount']:.2f}, INR ₹{b['inr_amount']:.2f}\n"
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
def run_agent(user_message, user_id, user_name):
    st.session_state.messages = [
        m for m in st.session_state.messages
        if isinstance(m.get("content"), str)
    ]
    st.session_state.messages.append({"role": "user", "content": user_message})

    system = f"""You are a warm, smart family finance assistant for a Singapore family.
Current user: {user_name}. Today: {date.today().strftime("%B %d, %Y")}.
Currencies: SGD ($) and INR (₹). Shared family pool — both incomes go into one pot.

Key rules:
- Spending mentioned → add_expense immediately, no questions asked
- Another person mentioned as spender → use spent_by field (e.g. "Amit paid rent" → spent_by="Amit")
- Income/salary mentioned → add_income immediately
- Another person mentioned as earner → use earned_by field
- Edit expense → find_expenses FIRST to get ID, then update_expense
- Delete expense → find_expenses FIRST to get ID, then delete_expense
- New category → add_category
- "who spent" or person comparison → get_spending_by_person
- Be warm, friendly, use emojis
- Always confirm what was recorded and under whose name"""

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
        <p style='color:#666;'>SGD & INR • Shared Family Tracker</p>
    </div>""", unsafe_allow_html=True)

    users = supabase.table("users").select("*").execute().data
    col1, col2 = st.columns(2)
    for i, u in enumerate(users):
        with (col1 if i % 2 == 0 else col2):
            if st.button(f"👤 {u['name']}", key=f"u_{u['id']}"):
                st.session_state.update({
                    "sel_id": u["id"],
                    "sel_name": u["name"],
                    "sel_pin": u["pin"]
                })
                st.rerun()

    if "sel_id" in st.session_state:
        st.markdown(f"### 🔐 PIN for {st.session_state.sel_name}")
        pin = st.text_input("", type="password", max_chars=4,
                           placeholder="4-digit PIN")
        if st.button("Login →", type="primary"):
            if pin == st.session_state.sel_pin:
                st.session_state.update({
                    "logged_in": True,
                    "user": {
                        "id": st.session_state.sel_id,
                        "name": st.session_state.sel_name
                    },
                    "messages": []
                })
                st.rerun()
            else:
                st.error("Wrong PIN!")

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
            for k in ["sel_id", "sel_name", "sel_pin"]:
                st.session_state.pop(k, None)
            st.rerun()

    # Fresh data
    balance = get_balance()
    categories = get_categories()
    cat_options = {c["name"]: c for c in categories}
    cat_map = {c["name"].lower(): c for c in categories}
    income_types = get_income_types()
    itype_options = {t["name"]: t for t in income_types}
    inc_sgd, inc_inr, income_by_user = get_income_summary()
    summary = get_monthly_summary()
    total_exp_sgd = sum(d["spent_sgd"] for d in summary.values())
    total_exp_inr = sum(d["spent_inr"] for d in summary.values())
    net_sgd = inc_sgd - total_exp_sgd
    net_inr = inc_inr - total_exp_inr
    user_spending = get_user_spending()
    alerts = get_alerts()

    # Balance cards
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""<div class='balance-card'>
            <div style='font-size:1.1rem;'>🇸🇬 SGD Balance</div>
            <div style='font-size:1.8rem;font-weight:bold;'>${balance['sgd_amount']:.2f}</div>
            <div style='font-size:0.75rem;opacity:0.9;'>💚 In: ${inc_sgd:.0f} | 💸 Out: ${total_exp_sgd:.0f}</div>
            <div style='font-size:0.8rem;'>{"✅" if net_sgd >= 0 else "⚠️"} Net: ${net_sgd:.0f}</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class='balance-card'>
            <div style='font-size:1.1rem;'>🇮🇳 INR Balance</div>
            <div style='font-size:1.8rem;font-weight:bold;'>₹{balance['inr_amount']:.2f}</div>
            <div style='font-size:0.75rem;opacity:0.9;'>💚 In: ₹{inc_inr:.0f} | 💸 Out: ₹{total_exp_inr:.0f}</div>
            <div style='font-size:0.8rem;'>{"✅" if net_inr >= 0 else "⚠️"} Net: ₹{net_inr:.0f}</div>
        </div>""", unsafe_allow_html=True)

    # Per person cards
    all_names = set(list(user_spending.keys()) + list(income_by_user.keys()))
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
        st.caption("💡 Try: 'Amit paid $3500 rent' or 'I got $5000 salary'")

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
                            run_agent(prompt, user["id"], user["name"])
                    st.rerun()

        if prompt := st.chat_input(
                "e.g. 'Amit paid $3500 rent' or 'I got $5000 salary'"):
            with messages_container:
                st.markdown(f'<div class="chat-user">{prompt}</div>',
                           unsafe_allow_html=True)
                with st.spinner("Thinking..."):
                    run_agent(prompt, user["id"], user["name"])
            st.rerun()

    # --- DASHBOARD TAB ---
    with tab2:
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

        if all_names:
            names = sorted(all_names)
            fig_person = go.Figure()
            fig_person.add_trace(go.Bar(
                name="💚 Earned", x=names,
                y=[income_by_user.get(n, {"sgd": 0})["sgd"] for n in names],
                marker_color="#00b894"))
            fig_person.add_trace(go.Bar(
                name="💸 Spent", x=names,
                y=[user_spending.get(n, {"sgd": 0})["sgd"] for n in names],
                marker_color="#6C63FF"))
            fig_person.update_layout(
                barmode="group", height=250,
                title="👥 SGD: Who Earned vs Spent",
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig_person, use_container_width=True)

        if inc_sgd > 0 or total_exp_sgd > 0:
            fig_pie = px.pie(
                values=[max(inc_sgd, 0.01), max(total_exp_sgd, 0.01)],
                names=["💚 Income", "💸 Expenses"],
                color_discrete_sequence=["#00b894", "#6C63FF"],
                title="SGD Income vs Expenses")
            fig_pie.update_layout(height=250, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_pie, use_container_width=True)

        sgd_data = [(cat, d["spent_sgd"], d["budget"])
                   for cat, d in summary.items() if d["budget"] > 0]
        if sgd_data:
            df = pd.DataFrame(sgd_data, columns=["Category", "Spent", "Budget"])
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Budget", x=df["Category"],
                               y=df["Budget"], marker_color="#e0e0e0"))
            fig.add_trace(go.Bar(name="Spent", x=df["Category"],
                               y=df["Spent"], marker_color="#6C63FF"))
            fig.update_layout(
                barmode="overlay", height=280,
                title="📊 SGD Budget vs Spent",
                margin=dict(l=0, r=0, t=30, b=0),
                xaxis_tickangle=-45,
                legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Budget Progress")
        for cat, d in summary.items():
            if d["budget"] > 0:
                pct = min(d["spent_sgd"] / d["budget"], 1.0)
                color = "🟢" if pct < 0.7 else "🟡" if pct < 0.9 else "🔴"
                if d["spent_sgd"] > d["budget"]:
                    status = " ⚠️ OVERSPENT!"
                elif d["spent_sgd"] == d["budget"]:
                    status = " ✅ EXACT!"
                else:
                    status = ""
                person_parts = [f"{n}: ${v['sgd']:.0f}"
                               for n, v in d["by_user"].items() if v["sgd"] > 0]
                breakdown = f" ({' | '.join(person_parts)})" if person_parts else ""
                st.markdown(
                    f"{color} **{d['icon']} {cat}** — "
                    f"${d['spent_sgd']:.0f}/${d['budget']:.0f}{status}{breakdown}")
                st.progress(pct)

    # --- INCOME TAB ---
    with tab3:
        st.markdown("### 💚 Income This Month")
        with st.expander("➕ Add Income"):
            all_users = get_all_users()
            user_names = [u["name"] for u in all_users]
            col1, col2 = st.columns(2)
            with col1:
                inc_amount = st.number_input("Amount", min_value=0.01,
                                            step=100.0, key="new_inc_amt")
                inc_currency = st.selectbox("Currency", ["SGD", "INR"],
                                           key="new_inc_cur")
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

        income_list = get_income()
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
            st.info("No income recorded this month. Add your salary above! 💚")

    # --- EXPENSES TAB ---
    with tab4:
        st.markdown("### 📋 This Month's Expenses")
        with st.expander("➕ Add Expense Manually"):
            all_users = get_all_users()
            user_names = [u["name"] for u in all_users]
            col1, col2 = st.columns(2)
            with col1:
                exp_amount = st.number_input("Amount", min_value=0.01,
                                            step=0.50, key="new_exp_amt")
                exp_currency = st.selectbox("Currency", ["SGD", "INR"],
                                           key="new_exp_cur")
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

        expenses = get_expenses()
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
                                cat_options[edit_cat]["id"], edit_date)
                            st.success("✅ Updated!")
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Delete", key=f"del_{exp['id']}"):
                            delete_expense_db(exp["id"], exp["amount"],
                                            exp.get("currency", "SGD"))
                            st.success("🗑️ Deleted!")
                            st.rerun()
        else:
            st.info("No expenses this month yet!")

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
            expenses_preview = [t for t in transactions if t.get("type") == "expense"]
            income_preview = [t for t in transactions if t.get("type") == "income"]
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
                for i, txn in enumerate(expenses_preview):
                    col1, col2, col3, col4 = st.columns([0.5, 2, 1, 1.5])
                    with col1:
                        checked = st.checkbox("", value=True, key=f"imp_exp_{i}")
                    with col2:
                        st.caption(txn.get("description", ""))
                    with col3:
                        st.caption(f"**{symbol}{txn.get('amount',0):.2f}**")
                    with col4:
                        cat_suggestion = txn.get('suggested_category', 'Others')
                        st.caption(f"{txn.get('date','')} • {cat_suggestion}")
                    if checked:
                        selected.append(("expense", txn))

            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"✅ Import {len(selected)}", type="primary"):
                    imported = 0
                    new_cats = set()
                    for txn_type, txn in selected:
                        try:
                            txn_date = datetime.strptime(
                                txn["date"], "%Y-%m-%d").date()
                            if txn_type == "income":
                                itype = income_types[0]
                                add_income_db(
                                    user["id"], itype["id"],
                                    txn["amount"], import_currency,
                                    txn["description"], txn_date)
                            else:
                                cat_name = txn.get("suggested_category", "Others")
                                # Auto-create category if needed
                                matched_cat = get_or_create_category(cat_name)
                                if matched_cat and matched_cat.get("id"):
                                    add_expense_db(
                                        user["id"], matched_cat["id"],
                                        txn["amount"], txn["description"],
                                        import_currency, txn_date)
                                    # Track new categories
                                    existing = [c["name"] for c in categories]
                                    if cat_name not in existing:
                                        new_cats.add(
                                            f"{matched_cat.get('icon','📦')} {cat_name}")
                            imported += 1
                        except Exception as e:
                            st.warning(
                                f"Skipped: {txn.get('description','')} — {e}")

                    supabase.table("import_log").insert({
                        "user_id": user["id"],
                        "filename": st.session_state.import_filename,
                        "imported_count": imported
                    }).execute()

                    st.success(f"🎉 Imported {imported} transactions!")
                    if new_cats:
                        st.info(
                            f"✨ Created {len(new_cats)} new categories: "
                            f"{', '.join(new_cats)}")
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

        st.markdown("#### 🗑️ Clear Chat")
        if st.button("🗑️ Clear Chat History"):
            st.session_state.messages = []
            st.success("✅ Cleared!")
            st.rerun()

# --- RUN ---
if not st.session_state.logged_in:
    show_login()
else:
    show_app()