"""Dados, autenticação e permissões do FinanCorp.

Use DATABASE_URL (PostgreSQL) em produção. SQLite continua disponível para uso local.
Cada cadastro cria um espaço financeiro privado, isolado por workspace_id.
"""
import hashlib
import hmac
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import pandas as pd

DB = os.path.join(os.path.dirname(__file__), "financorp.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ROLES = {"admin": {"ver", "editar", "relatorios", "usuarios"},
         "financeiro": {"ver", "editar", "relatorios"}, "leitor": {"ver"}}


def _postgres():
    return bool(DATABASE_URL)


@contextmanager
def conn():
    if _postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Instale as dependências do requirements.txt.") from exc
        c = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
    else:
        c = sqlite3.connect(DB, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _sql(query):
    return query.replace("?", "%s") if _postgres() else query


def _rows(query, params=()):
    with conn() as c:
        cur = c.execute(_sql(query), params)
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def _df(query, params=(), dates=None):
    df = pd.DataFrame(_rows(query, params))
    if dates:
        for col in dates:
            if col in df:
                df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def can(role, perm):
    return perm in ROLES.get(role, set())


def _hash(pw, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 310_000).hex()
    return f"{salt}${digest}"


def _check(pw, stored):
    try:
        salt, expected = stored.split("$", 1)
        for rounds in (310_000, 100_000):
            actual = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), rounds).hex()
            if hmac.compare_digest(actual, expected):
                return rounds
        return 0
    except (AttributeError, ValueError):
        return 0


def login(username, pw):
    rows = _rows("SELECT id, username, name, role, workspace_id, pw FROM users WHERE username=?",
                 (username.strip(),))
    user = rows[0] if rows else None
    rounds = _check(pw, user["pw"]) if user else 0
    if user and rounds:
        if rounds < 310_000:
            with conn() as c:
                c.execute(_sql("UPDATE users SET pw=? WHERE id=?"),
                          (_hash(pw), user["id"]))
        user.pop("pw", None)
        return user
    return None


def register_workspace(username, name, workspace_name, pw):
    """Create a private workspace and its first administrator."""
    username = username.strip()
    name = name.strip()
    workspace_name = workspace_name.strip()
    if len(username) < 3 or len(name) < 2 or len(workspace_name) < 2:
        raise ValueError("Preencha os campos com pelo menos 2 caracteres (login: 3).")
    if len(pw) < 10:
        raise ValueError("Use uma senha com pelo menos 10 caracteres.")
    with conn() as c:
        cur = c.execute(_sql("INSERT INTO workspaces(name) VALUES(?)"), (workspace_name,))
        if _postgres():
            workspace_id = cur.fetchone()["id"]
        else:
            workspace_id = cur.lastrowid
        c.execute(_sql("INSERT INTO users(username,name,role,pw,workspace_id) "
                       "VALUES(?,?,?,?,?)"),
                  (username, name, "admin", _hash(pw), workspace_id))
    return login(username, pw)


def users(workspace_id):
    return _df("SELECT id, username, name, role FROM users WHERE workspace_id=? ORDER BY name",
               (workspace_id,))


def add_user(username, name, role, pw, workspace_id):
    with conn() as c:
        c.execute(_sql("INSERT INTO users(username,name,role,pw,workspace_id) "
                       "VALUES(?,?,?,?,?)"),
                  (username.strip(), name.strip(), role, _hash(pw), workspace_id))


def set_role(user_id, role, workspace_id):
    with conn() as c:
        c.execute(_sql("UPDATE users SET role=? WHERE id=? AND workspace_id=?"),
                  (role, user_id, workspace_id))


def categories(tipo=None, workspace_id=1):
    query = "SELECT id,name,type FROM categories WHERE workspace_id=?"
    params = [workspace_id]
    if tipo:
        query += " AND type=?"
        params.append(tipo)
    query += " ORDER BY name"
    return _df(query, params)


def add_category(name, tipo, workspace_id):
    with conn() as c:
        c.execute(_sql("INSERT INTO categories(name,type,workspace_id) VALUES(?,?,?)"),
                  (name.strip(), tipo, workspace_id))


def transactions(workspace_id=1):
    df = _df("SELECT t.id,t.description,t.type,t.category_id,t.amount,t.due_date,"
             "t.paid_date,t.party,c.name AS categoria FROM transactions t "
             "JOIN categories c ON c.id=t.category_id WHERE t.workspace_id=?",
             (workspace_id,), dates=("due_date", "paid_date"))
    if df.empty:
        for col in ("id", "description", "type", "category_id", "amount", "party", "categoria"):
            df[col] = pd.Series(dtype="object")
        for col in ("due_date", "paid_date"):
            df[col] = pd.Series(dtype="datetime64[ns]")
        df["status"] = pd.Series(dtype="object")
        return df
    today = pd.Timestamp(date.today())
    df["status"] = "Pendente"
    df.loc[df.due_date < today, "status"] = "Atrasado"
    df.loc[df.paid_date.notna(), "status"] = "Pago"
    return df


def add_transaction(desc, tipo, cat_id, amount, due, paid, party, workspace_id=1):
    with conn() as c:
        c.execute(_sql("INSERT INTO transactions(description,type,category_id,amount,due_date,"
                       "paid_date,party,workspace_id) VALUES(?,?,?,?,?,?,?,?)"),
                  (desc.strip(), tipo, cat_id, amount, str(due),
                   str(paid) if paid else None, party.strip(), workspace_id))


def mark_paid(tx_id, workspace_id, when=None):
    with conn() as c:
        c.execute(_sql("UPDATE transactions SET paid_date=? WHERE id=? AND workspace_id=?"),
                  (str(when or date.today()), tx_id, workspace_id))


def delete_transaction(tx_id, workspace_id):
    with conn() as c:
        c.execute(_sql("DELETE FROM transactions WHERE id=? AND workspace_id=?"),
                  (tx_id, workspace_id))


def init():
    """Create schema and migrate the existing local demo data once."""
    identity = "SERIAL PRIMARY KEY" if _postgres() else "INTEGER PRIMARY KEY"
    with conn() as c:
        c.execute(f"CREATE TABLE IF NOT EXISTS workspaces(id {identity}, name TEXT NOT NULL)")
        c.execute(f"CREATE TABLE IF NOT EXISTS users(id {identity}, username TEXT UNIQUE NOT NULL, "
                  "name TEXT NOT NULL, role TEXT NOT NULL, pw TEXT NOT NULL, workspace_id INTEGER)")
        c.execute(f"CREATE TABLE IF NOT EXISTS categories(id {identity}, name TEXT NOT NULL, "
                  "type TEXT NOT NULL, workspace_id INTEGER)")
        c.execute(f"CREATE TABLE IF NOT EXISTS transactions(id {identity}, description TEXT NOT NULL, "
                  "type TEXT NOT NULL, category_id INTEGER REFERENCES categories(id), "
                  "amount REAL NOT NULL, due_date TEXT NOT NULL, paid_date TEXT, party TEXT, "
                  "workspace_id INTEGER)")
        # Existing SQLite databases predate workspaces. Add tenant columns without losing data.
        for table in ("users", "categories", "transactions"):
            cols = [row["name"] if isinstance(row, sqlite3.Row) else row["column_name"]
                    for row in c.execute(_sql(f"PRAGMA table_info({table})") if not _postgres()
                                          else "SELECT column_name FROM information_schema.columns "
                                               "WHERE table_name=?", (table,) if _postgres() else ())]
            if "workspace_id" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id INTEGER")
        if not _postgres():
            c.execute("INSERT INTO workspaces(id,name) VALUES(1,?) "
                      "ON CONFLICT(id) DO NOTHING", ("FinanCorp Demo",))
            for table in ("users", "categories", "transactions"):
                c.execute(f"UPDATE {table} SET workspace_id=1 WHERE workspace_id IS NULL")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_workspace_name "
                  "ON categories(workspace_id,name)")
    if not _postgres() and os.getenv("FINANCORP_DEMO") == "1" \
            and not _rows("SELECT id FROM users LIMIT 1"):
        seed()


def seed():
    """Local-only fictional demonstration data; production starts empty."""
    with conn() as c:
        c.execute(_sql("INSERT INTO workspaces(id,name) VALUES(1,?) ON CONFLICT(id) DO NOTHING"),
                  ("FinanCorp Demonstração",))
    add_user("admin", "Admin demonstração", "admin", "admin123", 1)
    add_user("julia", "Julia (Financeiro)", "financeiro", "fin123", 1)
    add_user("leitor", "Leitor demonstração", "leitor", "leitor123", 1)

    cats = {"Vendas": "receita", "Serviços": "receita", "Consultoria": "receita",
            "Salários": "despesa", "Aluguel": "despesa", "Impostos": "despesa",
            "Marketing": "despesa", "Software": "despesa", "Fornecedores": "despesa",
            "Viagens": "despesa"}
    for name, tipo in cats.items():
        add_category(name, tipo, 1)
    ids = {row["name"]: row["id"] for row in _rows(
        "SELECT id,name FROM categories WHERE workspace_id=?", (1,))}
    rng = random.Random(42)
    today = date.today()
    clients = ["Alfa Tech", "Beta Ltda", "Grupo Orion", "Nova Era SA", "Delta Foods"]
    vendors = ["Cloud Corp", "Papelaria Central", "Agência Pixel", "Logística Rápida"]

    def add(desc, tipo, cat, value, due, party):
        paid = None
        if due <= today - timedelta(days=2) and rng.random() < 0.93:
            paid = min(due + timedelta(days=rng.randint(0, 3)), today)
        add_transaction(desc, tipo, ids[cat], round(value, 2), due, paid, party, 1)

    base = today.replace(day=1)
    for month_offset in range(-11, 2):
        idx = base.year * 12 + base.month - 1 + month_offset
        month = date(idx // 12, idx % 12 + 1, 1)
        growth = 1 + 0.025 * (month_offset + 11)
        revenue = 0
        for cat, span in (("Vendas", (7000, 15000)), ("Serviços", (3000, 8000)),
                          ("Consultoria", (4000, 9000))):
            for _ in range(rng.randint(2, 3)):
                value = rng.uniform(*span) * growth
                revenue += value
                client = rng.choice(clients)
                add(f"{cat} - {client}", "receita", cat, value,
                    month.replace(day=rng.randint(3, 27)), client)
        add("Folha de pagamento", "despesa", "Salários",
            38000 * (1 + 0.01 * (month_offset + 11)), month.replace(day=5), "RH")
        add("Aluguel do escritório", "despesa", "Aluguel", 9500,
            month.replace(day=10), "Imobiliária Prime")
        add("Licenças SaaS", "despesa", "Software", 2800,
            month.replace(day=12), "Cloud Corp")
        add("Impostos do mês", "despesa", "Impostos", revenue * 0.12,
            month.replace(day=20), "Receita Federal")
        for cat, span in (("Marketing", (1500, 5000)), ("Fornecedores", (4000, 12000)),
                          ("Viagens", (500, 3000))):
            vendor = rng.choice(vendors)
            add(f"{cat} - {vendor}", "despesa", cat, rng.uniform(*span),
                month.replace(day=rng.randint(4, 26)), vendor)
