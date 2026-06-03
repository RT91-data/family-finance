# 💰 Family Finance Tracker

A full-stack AI-powered personal finance app built with **Streamlit**, **Claude AI (Anthropic)**, and **Supabase**. Designed for families managing a shared money pool across two currencies — SGD and INR.

> Built as a portfolio project during a deliberate career transition into AI Engineering. Demonstrates real-world use of LLM tool use, agentic loops, multi-currency data modelling, and production-grade patterns like sensitive data scrubbing and automated testing.

---

## ✨ Features

### 💬 AI Chat Assistant
- Natural language expense and income recording — just type like you're texting
- Claude uses **tool use (function calling)** to decide what action to take and executes it directly
- Understands relationship words: *"my husband paid rent"*, *"he bought groceries"*, *"by her"* all resolve to the correct family member automatically
- Agentic loop: for edit/delete operations, Claude first searches for the record, gets the ID, then updates — no manual ID lookup needed
- Chat context respects the global month filter — summaries always refer to the selected month

### 📊 Dashboard
- Monthly income vs expense metrics per currency
- **Per-person grouped bar chart** — see each family member's income and spending side by side
- **Donut chart** — income vs expense split with pinned colours (never flips)
- **Stacked category chart** — each category bar is broken down by person, budget ceiling shown in grey
- Budget progress bars with 🟢/🟡/🔴 status and per-person breakdown

### 💚 Income Tab
- Add income manually with earner, type, date, currency
- View all income entries for the selected month with delete option

### 📋 Expenses Tab
- Add expenses manually with spender, category, date, currency
- Inline edit and delete for every expense
- All entries filtered by the global month/year selector

### 🏦 Import Bank Statement
- Upload PDF, CSV, Excel, or image (PNG/JPG) bank/credit card statements
- Claude extracts all transactions automatically
- **Sensitive data scrubbed locally** before anything is sent to the AI: card numbers, account numbers, NRIC, email, phone all replaced with placeholders
- **Credit card bill payments auto-skipped** ("PAYMENT THANK YOU", "CREDIT CARD PAYMENT", "MINIMUM PAYMENT", inter-account transfers) — avoids double counting since individual transactions are already captured
- **GIRO payments to real payees are kept** — tax (IRAS), insurance premiums, utilities, loan repayments, subscriptions via GIRO are genuine expenses and are imported normally. Only GIRO payments *to a credit card company* are skipped
- Review and selectively import transactions
- New categories auto-created with smart icon matching (100+ merchant keywords mapped)

### 🎯 Budgets Tab
- Set SGD and INR budgets per category
- Add, edit, rename, or delete categories with custom icons

### ⚙️ Settings
- Add/edit family members
- **Exchange rate setting** — set 1 INR = ? SGD, used for unified reporting
- **Clear all data** — two-step confirmation, soft-deletes all expenses and income (for testing/reset)

### 🔀 Unified Currency View
- Toggle "Show all in SGD" in the filter bar
- Converts all INR amounts to SGD using your set exchange rate
- Every chart, card, and budget bar reflects the unified total
- Balance cards, per-person charts, and category breakdowns all update instantly

### 📅 Global Date Filter
- Month + year selector at the top of the app
- All tabs (Dashboard, Income, Expenses) respect the filter simultaneously
- After importing a statement, the filter auto-jumps to that statement's month

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| AI | Anthropic Claude (`claude-sonnet-4-20250514`) |
| Database | Supabase (PostgreSQL) |
| Charts | Plotly (`graph_objects` + `express`) |
| PDF parsing | pdfplumber |
| OCR (images) | pytesseract + Pillow |
| Data | pandas |
| Auth (basic) | Click-to-login (PIN stored but not required for demo) |

---

## 🗄️ Database Schema (Supabase)

Create the following tables in your Supabase project:

```sql
-- Users
create table users (
  id serial primary key,
  name text not null,
  pin text default '0000'
);

-- Categories
create table categories (
  id serial primary key,
  name text not null,
  icon text default '📦',
  budget numeric default 0,
  budget_inr numeric default 0,
  is_active boolean default true
);

-- Income types
create table income_types (
  id serial primary key,
  name text not null,
  icon text default '💰',
  is_active boolean default true
);

-- Balance (single row)
create table balance (
  id serial primary key,
  sgd_amount numeric default 0,
  inr_amount numeric default 0,
  updated_at timestamptz default now()
);
insert into balance (sgd_amount, inr_amount) values (0, 0);

-- Expenses
create table expenses (
  id serial primary key,
  user_id integer references users(id),
  category_id integer references categories(id),
  amount numeric not null,
  currency text default 'SGD',
  description text,
  date date default current_date,
  is_deleted boolean default false,
  created_at timestamptz default now()
);

-- Income
create table income (
  id serial primary key,
  user_id integer references users(id),
  income_type_id integer references income_types(id),
  amount numeric not null,
  currency text default 'SGD',
  description text,
  date date default current_date,
  month integer,
  year integer,
  is_deleted boolean default false,
  created_at timestamptz default now()
);

-- Import log (optional)
create table import_log (
  id serial primary key,
  user_id integer references users(id),
  filename text,
  imported_count integer,
  created_at timestamptz default now()
);

-- Merchant memory — saves user corrections so future imports auto-categorise correctly
create table merchant_rules (
  id serial primary key,
  merchant_pattern text not null,
  category_id integer references categories(id),
  updated_at timestamptz default now()
);

-- Import deduplication — prevents importing the same transaction twice
create table import_hashes (
  id serial primary key,
  txn_hash text not null unique,
  created_at timestamptz default now()
);
```

Seed some starter data:
```sql
insert into income_types (name, icon) values
  ('Salary', '💰'), ('Bonus', '🎉'), ('Freelance', '💻'),
  ('Rental', '🏠'), ('Investment', '📈'), ('Other', '💵');

insert into categories (name, icon, budget, budget_inr) values
  ('Groceries', '🛒', 500, 5000),
  ('Transport', '🚗', 200, 0),
  ('Dining', '🍜', 300, 3000),
  ('Rent', '🏠', 3500, 0),
  ('Utilities', '💡', 200, 0),
  ('Entertainment', '🎬', 150, 0),
  ('Health', '💊', 100, 0),
  ('Shopping', '🛍️', 200, 0),
  ('Others', '📦', 0, 0);
```

---

## 🚀 Setup & Run

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/family-finance-tracker.git
cd family-finance-tracker
```

### 2. Install dependencies
```bash
pip install streamlit anthropic supabase python-dotenv pandas \
            plotly pdfplumber pytesseract pillow openpyxl
```

### 3. Install Tesseract (for image/OCR support)
- **Windows:** Download from https://github.com/UB-Mannheim/tesseract/wiki — install to `C:\Program Files\Tesseract-OCR\`
- **Mac:** `brew install tesseract`
- **Linux:** `sudo apt install tesseract-ocr`

### 4. Create `.env` file

Create a file named `.env` in the root of the project folder (same folder as `family_finance.py`):

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-public-key
ANTHROPIC_API_KEY=your-anthropic-api-key
```

**Where to get each value:**

| Variable | Where to find it |
|---|---|
| `SUPABASE_URL` | Supabase dashboard → your project → Settings → API → Project URL |
| `SUPABASE_KEY` | Supabase dashboard → your project → Settings → API → `anon` `public` key (NOT the service role key) |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys → Create Key |

> ⚠️ Never commit your `.env` file to GitHub. Add it to `.gitignore`:
> ```
> echo ".env" >> .gitignore
> ```

Also create a `.env.example` file (safe to commit — values are blank):
```env
SUPABASE_URL=
SUPABASE_KEY=
ANTHROPIC_API_KEY=
```

### 5. Update Tesseract path (Windows only)
In `family_finance.py`, line 17:
```python
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```
On Mac/Linux, remove this line — Tesseract is found automatically.

### 6. Run the app
```bash
streamlit run family_finance.py
```

---

## 🧪 Running Tests

```bash
python test_finance.py
```

**77 tests across 15 groups** — all pure logic, no Streamlit or live DB required:

| Group | What it tests |
|---|---|
| 1 | `get_monthly_summary` — per-user, per-category, SGD/INR split |
| 2 | `get_income_summary` — totals and per-user breakdown |
| 3 | `get_user_spending` — both members present even if only one has activity |
| 4 | `resolve_user` — direct name, case-insensitive, relationship words (husband/wife/him/her/he/she/by him/by her) |
| 5 | CC payment skip filtering — GIRO, autopay, bill payments excluded |
| 6 | Balance deduct/restore/add — SGD and INR, clamp at zero |
| 7 | Budget alerts — overspend (>100%) and near-limit (≥90%) |
| 8 | Sensitive data scrubbing — card, email, phone, NRIC |
| 9 | Mixed SGD+INR expenses tracked separately per user per category |
| 10 | `unified_summary` — INR→SGD conversion, INR fields zeroed out |
| 11 | `unified_income_summary` — handles member earning only in INR |
| 12 | `unified_user_spending` — per-person conversion accuracy |
| 13 | `to_sgd` helper — passthrough, conversion, zero, large amounts |
| 14 | Multi-currency balance ops — INR ops don't touch SGD |
| 15 | INR budget alerts — overspend fires, under-budget stays silent |

---

## 🏗️ Architecture

```
family_finance.py
│
├── Session State & Config
│   └── filter_month, filter_year, unified_currency, inr_to_sgd_rate
│
├── DB Helpers (Supabase)
│   ├── get_expenses / get_income / get_categories / get_income_types
│   ├── add_expense_db / add_income_db / update / delete (soft)
│   ├── get_balance / update_balance / deduct_balance / restore_balance
│   └── get_monthly_summary / get_income_summary / get_user_spending / get_alerts
│
├── Multi-Currency Helpers
│   ├── to_sgd(amount, currency, rate)
│   ├── unified_summary(summary, rate)
│   ├── unified_income_summary(inc_sgd, inc_inr, by_user, rate)
│   └── unified_user_spending(spending, rate)
│
├── Statement Import Pipeline
│   ├── extract_text_from_file()  — PDF/CSV/Excel/Image → raw text
│   ├── strip_sensitive_data()    — scrub PII before sending to AI
│   ├── parse_statement_with_claude() — Claude extracts transactions as JSON
│   └── get_or_create_category()  — smart icon matching, auto-creates new categories
│
├── AI Agent (Claude Tool Use)
│   ├── tools[]  — 15 tools: add/update/delete expense+income, categories, summaries, alerts
│   ├── resolve_user()  — name + relationship alias → user ID
│   ├── execute_tool()  — routes tool calls to DB operations
│   └── run_agent()     — agentic loop: keeps calling until stop_reason != tool_use
│
└── UI (Streamlit)
    ├── show_login()   — click-to-login, no PIN required
    └── show_app()
        ├── Global filter bar (month, year, unified toggle)
        ├── Balance cards + per-person summary cards
        └── Tabs: Chat | Dashboard | Income | Expenses | Import | Budgets | Settings
```

---

## 💡 Design Decisions

**Why Claude tool use instead of a simple form?**
Recording expenses via chat ("Grab ride $12") is faster than filling a form. Claude's tool use means it decides what to do and does it — add, edit, search, delete — without the user touching a dropdown.

**Why soft delete instead of hard delete?**
All deletions set `is_deleted = True` rather than removing rows. This preserves data integrity for balance recalculation and makes accidental deletions recoverable.

**Why session state for exchange rate instead of DB?**
The exchange rate fluctuates daily. Storing it in the DB would require a migration and a fetch on every page load. Session state is the right scope — set it when you open the app, use it for that session.

**Why `go.Pie` instead of `px.pie`?**
Plotly Express assigns colours by index, so "Expense" could end up green if income is absent. `go.Pie` with `marker_colors` pins the colours absolutely — green is always income, purple is always expense across every chart.

**Why `resolve_user` uses "other person" logic for relationship words?**
In a two-person family pool, "husband/wife/him/her" unambiguously means the person who is *not* currently logged in. The function resolves this by returning the first user whose ID differs from the current user's ID.

---

## 📁 Project Structure

```
family-finance-tracker/
├── family_finance.py    # Main app
├── test_finance.py      # 77 automated tests (no live DB needed)
├── .env                 # Your secrets (never commit this)
├── .env.example         # Template for others
└── README.md
```

`.env.example`:
```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-public-key
ANTHROPIC_API_KEY=your-anthropic-api-key
```

---

## 🔐 Privacy & Security

- Bank statement text is processed **locally** — only cleaned, PII-stripped transaction data (date, amount, description) is sent to the Anthropic API
- Card numbers, account numbers, NRIC, emails, and phone numbers are regex-replaced with placeholders before any AI call
- API keys stored in `.env`, never hardcoded
- Supabase RLS (Row Level Security) can be enabled for production use

---

## 🗺️ Potential Enhancements

- [ ] Monthly trend charts (last 6 months)
- [ ] Export to CSV/Excel
- [ ] Recurring expense detection
- [ ] Telegram/WhatsApp bot interface
- [ ] Deploy to Streamlit Cloud or Azure App Service
- [ ] PIN-based login for production use (PIN column already exists in DB)
- [ ] Multi-family / multi-pool support

---

## 👩‍💻 About This Project

This app was built as part of a deliberate career transition from **D365/X++ ERP consulting (14 years)** into **AI Engineering**. The goal was to build something real and useful — not a tutorial clone — using the AI tools I was learning.

Key learning areas demonstrated:
- **Anthropic Claude API** — tool use, agentic loops, structured JSON extraction, system prompt design
- **Prompt engineering** — few-shot examples, role framing, constraint specification
- **Production patterns** — sensitive data handling, soft deletes, error boundaries, automated testing
- **Full-stack integration** — Streamlit UI + Supabase PostgreSQL + Claude API working together

Built using: Claude API, Streamlit, Supabase, Python