"""
Phase 2A track 5 — operational alerts.

Single sink for safety-critical events (risk rejection, kill-switch state
change, exchange drift, execution errors). The sink is fire-and-forget HTTP
POST: it must never raise into the trading engine, and must never block the
hot path for more than ALERT_TIMEOUT_SECONDS.

Configuration (all optional)
----------------------------
ALERT_WEBHOOK_URL          generic POST endpoint that receives the JSON body.
ALERT_TELEGRAM_BOT_TOKEN   when set, sends a chat message via Telegram Bot API.
ALERT_TELEGRAM_CHAT_ID     destination chat id (required with TOKEN).
ALERT_MIN_LEVEL            INFO | WARN | ERROR (default: WARN — filters chatter).
ALERT_TIMEOUT_SECONDS      per-call HTTP timeout (default: 3s).

Public API
----------
* `send_alert(level, category, message, **extra)` — non-blocking emit.
* `register_alerter(fn)` — append an extra sink (used by tests).
* `flush()` — wait for the in-flight queue (used by tests).

Hooks installed by the engine call `send_alert(...)` directly; no global side
effects on import.
"""
from __future__ import annotations

import json
import os
import threading
import time
from queue import Queue, Empty
from typing import Any, Callable, Dict, List, Optional


_LEVELS = {"INFO": 10, "WARN": 20, "ERROR": 30}

_extra_sinks: List[Callable[[Dict[str, Any]], None]] = []
_queue: "Queue[Dict[str, Any]]" = Queue(maxsize=256)
_worker_started = False
_worker_lock = threading.Lock()


def register_alerter(fn: Callable[[Dict[str, Any]], None]) -> None:
    """Append an extra sink callable. Used by tests."""
    _extra_sinks.append(fn)


def _min_level() -> int:
    raw = (os.getenv("ALERT_MIN_LEVEL") or "WARN").upper().strip()
    return _LEVELS.get(raw, 20)


def _timeout() -> float:
    try:
        return float(os.getenv("ALERT_TIMEOUT_SECONDS", "3"))
    except ValueError:
        return 3.0


def _post(url: str, payload: Dict[str, Any]) -> None:
    """Synchronous POST; errors swallowed (alerter must never crash callers)."""
    try:
        import requests  # local import — alerts are optional path.

        requests.post(url, json=payload, timeout=_timeout())
    except Exception:
        return


def _telegram_send(text: str) -> None:
    token = (os.getenv("ALERT_TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("ALERT_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        return
    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000]},
            timeout=_timeout(),
        )
    except Exception:
        return


def _format_telegram(payload: Dict[str, Any]) -> str:
    return (
        f"[{payload.get('level')}] {payload.get('category')} — "
        f"{payload.get('message')}\n"
        f"{json.dumps(payload.get('extra') or {}, default=str)[:1000]}"
    )


def _dispatch(payload: Dict[str, Any]) -> None:
    """Send to every configured sink. Each sink isolated."""
    url = (os.getenv("ALERT_WEBHOOK_URL") or "").strip()
    if url:
        _post(url, payload)
    if (os.getenv("ALERT_TELEGRAM_BOT_TOKEN") or "").strip():
        _telegram_send(_format_telegram(payload))
    for fn in list(_extra_sinks):
        try:
            fn(payload)
        except Exception:
            continue


def _worker_loop() -> None:
    while True:
        try:
            item = _queue.get(timeout=1.0)
        except Empty:
            continue
        if item is None:  # sentinel; not used today but cheap to keep.
            return
        try:
            _dispatch(item)
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, name="phase2a-alerter", daemon=True)
        t.start()
        _worker_started = True


def send_alert(
    level: str,
    category: str,
    message: str,
    *,
    sync: bool = False,
    **extra: Any,
) -> None:
    """
    Fire-and-forget alert. Never raises. Drops on full queue.

    `sync=True` bypasses the worker thread (used by tests for determinism).
    """
    lvl = (level or "WARN").upper()
    if _LEVELS.get(lvl, 20) < _min_level():
        return
    payload = {
        "level": lvl,
        "category": str(category)[:64],
        "message": str(message)[:2000],
        "extra": {k: v for k, v in extra.items() if v is not None},
        "ts": time.time(),
    }
    if sync:
        _dispatch(payload)
        return
    _ensure_worker()
    try:
        _queue.put_nowait(payload)
    except Exception:
        # Queue full — drop. Engine must keep trading.
        pass


def flush(timeout: float = 5.0) -> None:
    """Block until queue drains (best-effort)."""
    try:
        _queue.join()
    except Exception:
        return
