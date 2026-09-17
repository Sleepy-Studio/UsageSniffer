"""Cursor editor parser (defensive): ~/.config/Cursor/User state.vscdb files.

Caveats (verified 2026): per-bubble inputTokens/outputTokens read as zero
on current builds; promptTokenBreakdown is a context snapshot, not billing.
Only usageData {costInCents, amount} per composer is a trustworthy signal,
and even that is a summary. Everything token-wise is char-estimated and
flagged as such (started=0 messages carry on; totals may be 0).

Strategy: copy each state.vscdb (+wal+shm) to temp, read ItemTable /
cursorDiskKV keys for composer headers + bubble bodies, count messages,
estimate tokens at ~4 chars/token, surface costInCents when present.
Returns [] when no Cursor data exists.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from ..models import SessionRecord


def _copy_db(src: Path) -> Path | None:
    try:
        tmp = Path(tempfile.mkdtemp(prefix="usagesniffer-cursor-"))
        for ext in ("", "-wal", "-shm"):
            side = src.parent / (src.name + ext) if ext else src
            if side.exists():
                shutil.copy2(side, tmp / (src.name + ext))
        return tmp / src.name
    except OSError:
        return None


def _read_kv(db: Path) -> dict:
    out: dict = {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        kv_tables = [t for t in ("ItemTable", "cursorDiskKV") if t in tables]
        for t in kv_tables:
            try:
                cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
                if "key" not in cols or "value" not in cols:
                    continue
                for k, v in con.execute(f"SELECT key, value FROM {t}"):
                    out.setdefault(str(k), v)
            except sqlite3.Error:
                continue
    finally:
        con.close()
    return out


def _parse_composer(cid: str, kv: dict) -> SessionRecord:
    rec = SessionRecord(session_id=cid, agent="cursor")
    body_keys = [k for k in kv if k.startswith("bubbleId:") and k.endswith(":" + cid)]
    if not body_keys and "composerData:" + cid in kv:
        pass
    chars_in = chars_out = 0
    for k in body_keys:
        try:
            b = json.loads(kv[k]) if isinstance(kv[k], str) else kv[k]
        except (json.JSONDecodeError, TypeError):
            continue
        txt = b.get("text", "") if isinstance(b, dict) else str(b)
        btype = b.get("type") if isinstance(b, dict) else None
        rec.n_messages += 1
        if btype == 1:
            chars_in += len(str(txt))
        else:
            chars_out += len(str(txt))
    meta_raw = kv.get("composerData:" + cid, "")
    try:
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) and meta_raw else {}
    except json.JSONDecodeError:
        meta = {}
    if isinstance(meta, dict):
        usage = meta.get("usageData", {}) or {}
        if isinstance(usage, dict) and usage.get("costInCents"):
            try:
                rec.buckets["other"] += int(float(usage["costInCents"]))
            except (TypeError, ValueError):
                pass
        rec.model = str(meta.get("model", meta.get("modelName", "")))
    # Char-estimated tokens (NOT billing).
    rec.input_tokens = chars_in // 4
    rec.output_tokens = chars_out // 4
    rec.buckets["user"] += chars_in // 4
    rec.buckets["assistant_text"] += chars_out // 4
    return rec


def scan(root: Path | None = None) -> list[SessionRecord]:
    root = root or (Path.home() / ".config" / "Cursor" / "User")
    out: list[SessionRecord] = []
    if not root.exists():
        # legacy fallback
        alt = Path.home() / ".cursor"
        if not alt.exists():
            return out
    dbs = sorted((root / "workspaceStorage").glob("*/state.vscdb")) if (root / "workspaceStorage").exists() else []
    gdbs = [root / "globalStorage" / "state.vscdb"]
    targets = [d for d in gdbs + dbs if d.exists()]
    if not targets:
        return out
    kv: dict = {}
    for db in targets:
        tmp = _copy_db(db)
        if not tmp:
            continue
        try:
            kv.update(_read_kv(tmp))
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)
    if not kv:
        return out
    cids: set[str] = set()
    for k in kv:
        if k.startswith("composerData:"):
            cids.add(k.split(":", 1)[1])
        if k.startswith("bubbleId:"):
            parts = k.split(":")
            if len(parts) >= 3:
                cids.add(parts[-1])
    for cid in sorted(cids):
        try:
            rec = _parse_composer(cid, kv)
            if rec.n_messages:
                out.append(rec)
        except Exception:
            continue
    return out
