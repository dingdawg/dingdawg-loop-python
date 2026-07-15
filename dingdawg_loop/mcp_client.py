"""
Lightweight MCP stdio client — stdlib only, zero external deps.

Spawns `npx dingdawg-loop` as a subprocess, exchanges JSON-RPC 2.0
messages over stdin/stdout, returns parsed dicts.

Handles:
  - Connection timeout (5s default)
  - Governance unreachable → fail-closed
  - Subprocess cleanup on every code path
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from typing import Any, Dict, Optional


# ── tunables ──────────────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT = 5.0   # seconds to wait for MCP response
_NPX_CMD = os.environ.get("DINGDAWG_NPX_CMD", "npx")
_LOOP_PKG = os.environ.get("DINGDAWG_LOOP_PKG", "dingdawg-loop")


# ── internal helpers ──────────────────────────────────────────────────────────

def _make_rpc(method: str, params: Dict[str, Any]) -> str:
    """Encode a JSON-RPC 2.0 request as a newline-terminated string."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    return json.dumps(payload) + "\n"


def _read_line(proc: subprocess.Popen, timeout: float) -> Optional[str]:
    """
    Read one line from proc.stdout with a hard timeout.
    Returns None if the timeout fires or the process exits before responding.
    """
    result: list = [None]
    error: list = [None]

    def _reader():
        try:
            result[0] = proc.stdout.readline()
        except Exception as exc:  # noqa: BLE001
            error[0] = exc

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        # Timed out — process still blocked on read
        return None
    if error[0]:
        return None
    return result[0]


def _call_mcp(method: str, params: Dict[str, Any], timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    Spawn `npx dingdawg-loop`, send one JSON-RPC call, return the result dict.

    Raises McpCallError on any failure so callers can implement fail-closed
    behaviour without catching generic exceptions.
    """
    cmd = [_NPX_CMD, "--yes", _LOOP_PKG]
    proc: Optional[subprocess.Popen] = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        message = _make_rpc(method, params)
        proc.stdin.write(message)
        proc.stdin.flush()

        raw = _read_line(proc, timeout)

        if raw is None:
            raise McpCallError(
                f"MCP timeout after {timeout}s waiting for response to '{method}'"
            )

        raw = raw.strip()
        if not raw:
            raise McpCallError("MCP returned empty response")

        envelope = json.loads(raw)

        if "error" in envelope:
            err = envelope["error"]
            raise McpCallError(
                f"MCP error {err.get('code', '?')}: {err.get('message', str(err))}"
            )

        return envelope.get("result", {})

    except McpCallError:
        raise
    except json.JSONDecodeError as exc:
        raise McpCallError(f"MCP returned non-JSON: {exc}") from exc
    except FileNotFoundError:
        raise McpCallError(
            f"'{_NPX_CMD}' not found — is Node.js installed? "
            "Run: npm install -g dingdawg-loop"
        )
    except Exception as exc:  # noqa: BLE001
        raise McpCallError(f"MCP subprocess error: {exc}") from exc
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                proc.kill()


# ── public API ────────────────────────────────────────────────────────────────

class McpCallError(RuntimeError):
    """Raised when the MCP subprocess call fails for any reason."""


def mcp_register_loop(
    agent_id: str,
    cron: str,
    action_type: str,
    risk_tier: str,
    description: str,
    verifier: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Call dingdawg-loop::register_loop over MCP stdio."""
    return _call_mcp(
        method="register_loop",
        params={
            "agent_id": agent_id,
            "cron": cron,
            "action_type": action_type,
            "risk_tier": risk_tier,
            "description": description,
            "verifier": verifier,
        },
        timeout=timeout,
    )


def mcp_execute_loop(
    loop_id: str,
    notes: str = "",
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Call dingdawg-loop::execute_loop over MCP stdio."""
    return _call_mcp(
        method="execute_loop",
        params={"loop_id": loop_id, "notes": notes},
        timeout=timeout,
    )


def mcp_list_loops(
    agent_id: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Call dingdawg-loop::list_loops over MCP stdio."""
    params: Dict[str, Any] = {}
    if agent_id is not None:
        params["agent_id"] = agent_id
    return _call_mcp(method="list_loops", params=params, timeout=timeout)


def mcp_govern(
    agent_id: str,
    action_type: str,
    description: str,
    risk_tier: str = "medium",
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Call dingdawg-governance::govern over MCP stdio (via dingdawg-loop bridge)."""
    return _call_mcp(
        method="govern",
        params={
            "agent_id": agent_id,
            "action_type": action_type,
            "description": description,
            "risk_tier": risk_tier,
        },
        timeout=timeout,
    )
