"""SQLite operational store. File-backed by default; set FLOWPAY_DB_PATH."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("FLOWPAY_DB_PATH", "/data/flowpayai.sqlite3"))
if not str(DB_PATH).startswith("/data"):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS shopping_sessions(
          session_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_executions(
          execution_id TEXT PRIMARY KEY, session_id TEXT, query TEXT NOT NULL,
          status TEXT, product_count INTEGER DEFAULT 0, started_at TEXT NOT NULL,
          completed_at TEXT, error TEXT, result_json TEXT);
        CREATE TABLE IF NOT EXISTS products(
          product_id TEXT PRIMARY KEY, name TEXT, price REAL, currency TEXT,
          retailer TEXT, url TEXT, decision_status TEXT, payload_json TEXT,
          first_seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS carts(
          cart_id TEXT PRIMARY KEY, session_id TEXT, currency TEXT, status TEXT,
          total REAL DEFAULT 0, updated_at TEXT NOT NULL, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS checkout_intents(
          checkout_id TEXT PRIMARY KEY, cart_id TEXT, amount TEXT, currency TEXT,
          status TEXT, created_at TEXT NOT NULL, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS payment_orders(
          paypal_order_id TEXT PRIMARY KEY, checkout_id TEXT, amount TEXT,
          currency TEXT, status TEXT, created_at TEXT NOT NULL, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS payment_events(
          event_id TEXT PRIMARY KEY, paypal_order_id TEXT, event_type TEXT,
          status TEXT, created_at TEXT NOT NULL, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS payment_methods(
          method_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
          vault_id_ciphertext TEXT NOT NULL, vault_id_hash TEXT NOT NULL UNIQUE,
          provider TEXT NOT NULL DEFAULT 'paypal', status TEXT NOT NULL DEFAULT 'ACTIVE',
          created_at TEXT NOT NULL, payload_json TEXT);
        CREATE INDEX IF NOT EXISTS ix_payment_methods_buyer
          ON payment_methods(buyer_id, status);
        CREATE TABLE IF NOT EXISTS vault_order_intents(
          paypal_order_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
          paypal_customer_id TEXT, save_requested INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS vault_customers(
          paypal_customer_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS webhook_events(
          event_id TEXT PRIMARY KEY, event_type TEXT, verified INTEGER NOT NULL DEFAULT 0,
          processing_status TEXT, received_at TEXT NOT NULL, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS audit_events(
          event_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, event_type TEXT NOT NULL,
          entity_type TEXT, entity_id TEXT, actor TEXT, execution_id TEXT,
          severity TEXT DEFAULT 'INFO', details_json TEXT,
          previous_hash TEXT, event_hash TEXT);
        CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_events(occurred_at);
        CREATE INDEX IF NOT EXISTS ix_workflow_started ON workflow_executions(started_at);
        CREATE INDEX IF NOT EXISTS ix_payment_created ON payment_orders(created_at);
        """)


def audit(
    event_type,
    entity_type=None,
    entity_id=None,
    actor="system",
    execution_id=None,
    severity="INFO",
    details=None,
):
    import hashlib

    event_id = str(uuid.uuid4())
    now = utcnow()
    with connect() as c:
        prev = c.execute(
            "SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        previous_hash = prev["event_hash"] if prev else ""
        body = json.dumps(details or {}, sort_keys=True, default=str)
        digest = hashlib.sha256(
            f"{previous_hash}|{event_id}|{now}|{event_type}|{body}".encode()
        ).hexdigest()
        c.execute(
            """INSERT INTO audit_events
          (event_id,occurred_at,event_type,entity_type,entity_id,actor,execution_id,severity,details_json,previous_hash,event_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                now,
                event_type,
                entity_type,
                entity_id,
                actor,
                execution_id,
                severity,
                body,
                previous_hash,
                digest,
            ),
        )
    return event_id


def record_workflow(query, result, session_id=None):
    execution_id = str(uuid.uuid4())
    now = utcnow()
    products = result.get("products") or []
    status = result.get("status", "completed")
    with connect() as c:
        c.execute(
            """INSERT INTO workflow_executions
          (execution_id,session_id,query,status,product_count,started_at,completed_at,error,result_json)
          VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                execution_id,
                session_id,
                query,
                status,
                len(products),
                now,
                utcnow(),
                json.dumps(result.get("errors") or [], default=str),
                json.dumps(result, default=str),
            ),
        )
        for p in products:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("product_id") or uuid.uuid4())
            c.execute(
                """INSERT INTO products(product_id,name,price,currency,retailer,url,decision_status,payload_json,first_seen_at)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
              name=excluded.name,price=excluded.price,currency=excluded.currency,
              retailer=excluded.retailer,url=excluded.url,decision_status=excluded.decision_status,payload_json=excluded.payload_json""",
                (
                    pid,
                    p.get("name"),
                    p.get("price"),
                    p.get("currency"),
                    p.get("source") or p.get("retailer"),
                    p.get("url"),
                    p.get("decision_status"),
                    json.dumps(p, default=str),
                    now,
                ),
            )
    audit(
        "workflow.completed",
        "workflow",
        execution_id,
        execution_id=execution_id,
        severity="ERROR" if result.get("errors") else "INFO",
        details={"query": query, "status": status, "product_count": len(products)},
    )
    return execution_id


def rows(sql, params=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def save_payment_order(
    order_id,
    checkout_id=None,
    amount=None,
    currency=None,
    status="CREATED",
    payload=None,
):
    with connect() as c:
        c.execute(
            """INSERT INTO payment_orders VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(paypal_order_id) DO UPDATE SET status=excluded.status,payload_json=excluded.payload_json""",
            (
                order_id,
                checkout_id,
                str(amount or ""),
                currency,
                status,
                utcnow(),
                json.dumps(payload or {}, default=str),
            ),
        )
    audit(
        "payment.order_saved",
        "payment_order",
        order_id,
        details={"status": status, "amount": amount, "currency": currency},
    )


def record_webhook(event_id, event_type, verified, payload):
    """Claim a verified webhook once; failed deliveries may be retried."""
    with connect() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO webhook_events
               (event_id,event_type,verified,processing_status,received_at,payload_json)
               VALUES(?,?,?,?,?,?)""",
            (
                event_id,
                event_type,
                int(bool(verified)),
                "processing",
                utcnow(),
                json.dumps(payload or {}, default=str),
            ),
        )
        inserted = cur.rowcount == 1
        if not inserted:
            existing = c.execute(
                "SELECT processing_status FROM webhook_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if existing and existing["processing_status"] == "failed":
                c.execute(
                    """UPDATE webhook_events
                       SET processing_status='processing', received_at=?, payload_json=?
                       WHERE event_id=?""",
                    (utcnow(), json.dumps(payload or {}, default=str), event_id),
                )
                inserted = True
    if inserted:
        audit(
            "paypal.webhook_received",
            "webhook",
            event_id,
            severity="INFO" if verified else "WARNING",
            details={"event_type": event_type, "verified": bool(verified)},
        )
    return inserted


def mark_webhook_status(event_id, processing_status):
    if processing_status not in {"processed", "failed"}:
        raise ValueError("processing_status must be 'processed' or 'failed'")
    with connect() as c:
        c.execute(
            "UPDATE webhook_events SET processing_status=? WHERE event_id=?",
            (processing_status, event_id),
        )


def save_cart(cart, session_id=None):
    cart_id = cart.get("cart_id") or str(uuid.uuid4())
    items = cart.get("items") or []
    total = sum(float(item.get("line_total") or 0) for item in items)
    with connect() as c:
        c.execute(
            """INSERT INTO carts(cart_id,session_id,currency,status,total,updated_at,payload_json)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(cart_id) DO UPDATE SET
          currency=excluded.currency,status=excluded.status,total=excluded.total,
          updated_at=excluded.updated_at,payload_json=excluded.payload_json""",
            (
                cart_id,
                session_id,
                cart.get("currency"),
                "active",
                total,
                utcnow(),
                json.dumps(cart, default=str),
            ),
        )
    audit(
        "cart.saved",
        "cart",
        cart_id,
        details={
            "line_count": len(items),
            "total": total,
            "currency": cart.get("currency"),
        },
    )
    return cart_id


def save_checkout(details, cart):
    checkout_id = str(
        details.get("checkout_intent_id") or details.get("checkout_id") or uuid.uuid4()
    )
    amount = details.get("amount") or details.get("total") or ""
    currency = details.get("currency") or cart.get("currency")
    with connect() as c:
        c.execute(
            """INSERT INTO checkout_intents(checkout_id,cart_id,amount,currency,status,created_at,payload_json)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(checkout_id) DO UPDATE SET
          status=excluded.status,payload_json=excluded.payload_json""",
            (
                checkout_id,
                cart.get("cart_id"),
                str(amount),
                currency,
                "confirmed",
                utcnow(),
                json.dumps(details, default=str),
            ),
        )
    audit(
        "checkout.confirmed",
        "checkout",
        checkout_id,
        details={
            "cart_id": cart.get("cart_id"),
            "amount": amount,
            "currency": currency,
        },
    )
    return checkout_id


def update_payment_status(order_id, status, payload=None):
    with connect() as c:
        c.execute(
            "UPDATE payment_orders SET status=?, payload_json=? WHERE paypal_order_id=?",
            (status, json.dumps(payload or {}, default=str), order_id),
        )
    audit(
        "payment.status_updated",
        "payment_order",
        order_id,
        severity="WARNING" if status in {"DENIED", "FAILED"} else "INFO",
        details={"status": status},
    )


def save_vault_order_intent(order_id, buyer_id):
    with connect() as c:
        c.execute(
            """INSERT OR REPLACE INTO vault_order_intents
               (paypal_order_id,buyer_id,save_requested,created_at)
               VALUES(?,?,1,?)""",
            (order_id, buyer_id, utcnow()),
        )
    audit(
        "paypal.vault_opt_in_order_created",
        "payment_order",
        order_id,
        details={"buyer_id": buyer_id},
    )


def save_vault_customer(paypal_customer_id, buyer_id):
    if not paypal_customer_id or not buyer_id:
        return
    with connect() as c:
        c.execute(
            """INSERT INTO vault_customers(paypal_customer_id,buyer_id,created_at)
               VALUES(?,?,?) ON CONFLICT(paypal_customer_id) DO NOTHING""",
            (paypal_customer_id, buyer_id, utcnow()),
        )


def get_buyer_for_paypal_customer(paypal_customer_id):
    with connect() as c:
        row = c.execute(
            "SELECT buyer_id FROM vault_customers WHERE paypal_customer_id=?",
            (paypal_customer_id,),
        ).fetchone()
    return row["buyer_id"] if row else None


def get_vault_order_intent(order_id):
    with connect() as c:
        row = c.execute(
            "SELECT * FROM vault_order_intents WHERE paypal_order_id=?",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def save_payment_method(
    method_id, buyer_id, vault_id_ciphertext, vault_id_hash, payload=None
):
    with connect() as c:
        c.execute(
            """INSERT INTO payment_methods
               (method_id,buyer_id,vault_id_ciphertext,vault_id_hash,
                provider,status,created_at,payload_json)
               VALUES(?,?,?,?, 'paypal','ACTIVE',?,?)
               ON CONFLICT(vault_id_hash) DO NOTHING""",
            (
                method_id,
                buyer_id,
                vault_id_ciphertext,
                vault_id_hash,
                utcnow(),
                json.dumps(payload or {}, default=str),
            ),
        )
    audit(
        "paypal.vault_payment_method_saved",
        "payment_method",
        method_id,
        details={"buyer_id": buyer_id, "provider": "paypal"},
    )
    return method_id


def list_payment_methods(buyer_id):
    with connect() as c:
        result = c.execute(
            """SELECT method_id, provider, status, created_at
               FROM payment_methods
               WHERE buyer_id=? AND status='ACTIVE'
               ORDER BY created_at DESC""",
            (buyer_id,),
        ).fetchall()
    return [dict(row) for row in result]


def get_payment_method(method_id, buyer_id):
    with connect() as c:
        row = c.execute(
            """SELECT * FROM payment_methods
               WHERE method_id=? AND buyer_id=? AND status='ACTIVE'""",
            (method_id, buyer_id),
        ).fetchone()
    return dict(row) if row else None


def set_payment_method_status_by_hash(vault_id_hash, status):
    with connect() as c:
        row = c.execute(
            "SELECT method_id FROM payment_methods WHERE vault_id_hash=?",
            (vault_id_hash,),
        ).fetchone()
        if not row:
            return False
        c.execute(
            "UPDATE payment_methods SET status=? WHERE vault_id_hash=?",
            (status, vault_id_hash),
        )
    audit(
        "paypal.vault_payment_method_status_changed",
        "payment_method",
        row["method_id"],
        details={"status": status},
    )
    return True


def delete_payment_method_local(method_id, buyer_id):
    with connect() as c:
        row = c.execute(
            """SELECT method_id FROM payment_methods
               WHERE method_id=? AND buyer_id=? AND status='ACTIVE'""",
            (method_id, buyer_id),
        ).fetchone()
        if not row:
            return False
        c.execute(
            "UPDATE payment_methods SET status='DELETED' WHERE method_id=?",
            (method_id,),
        )
    audit(
        "paypal.vault_payment_method_deleted",
        "payment_method",
        method_id,
        details={"buyer_id": buyer_id},
    )
    return True


def has_vault_opt_in_for_buyer(buyer_id):
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM vault_order_intents WHERE buyer_id=? LIMIT 1",
            (buyer_id,),
        ).fetchone()
    return row is not None
