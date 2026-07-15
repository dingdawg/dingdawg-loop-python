"""
dingdawg_loop.core
==================
Primary public interface for the DingDawg Loop Protocol (DDLP) Python wrapper.

All functions return plain dicts — easy to log, serialize, and audit.
No external dependencies; stdlib only (subprocess, json, threading).

Prerequisites
-------------
Node.js >= 18 and the dingdawg-loop npm package must be installed:

    npm install -g dingdawg-loop
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from .mcp_client import (
    McpCallError,
    mcp_execute_loop,
    mcp_govern,
    mcp_list_loops,
    mcp_register_loop,
)

# ── in-process loop registry (lightweight cache) ────────────────────────────
_LOOP_REGISTRY: Dict[str, Dict[str, Any]] = {}


# ── GovernanceGate ───────────────────────────────────────────────────────────

class GovernanceGate:
    """
    Wraps the dingdawg-governance MCP server for Python agents.

    Usage::

        gate = GovernanceGate()
        receipt = gate.govern(
            agent_id="my-agent",
            action_type="send_email",
            description="Send weekly summary to stakeholders",
            risk_tier="medium",
        )
        if receipt["decision"] == "allow":
            send_email(...)
    """

    def __init__(self, fail_closed: bool = True, timeout: float = 5.0) -> None:
        """
        Args:
            fail_closed: If True (default), treat governance errors as 'deny'.
                         If False, treat errors as 'allow' (fail-open — not recommended).
            timeout: Seconds to wait for the MCP response.
        """
        self.fail_closed = fail_closed
        self.timeout = timeout

    def govern(
        self,
        agent_id: str,
        action_type: str,
        description: str,
        risk_tier: str = "medium",
    ) -> Dict[str, Any]:
        """
        Run a governance check against the dingdawg-governance MCP server.

        Args:
            agent_id:    Unique identifier for the calling agent.
            action_type: Category of the action (e.g. "generate_report").
            description: Human-readable description of what the agent will do.
            risk_tier:   One of "low" | "medium" | "high" | "critical".

        Returns:
            A plain dict with at minimum::

                {
                    "decision":    "allow" | "deny" | "review",
                    "receipt_id":  "<uuid>",
                    "risk_score":  <int 0-100>,
                    "explanation": {...},
                }

            On governance unreachable with fail_closed=True::

                {
                    "decision":   "deny",
                    "receipt_id": "<uuid>",
                    "risk_score": -1,
                    "explanation": {"error": "<reason>", "fail_closed": True},
                }
        """
        try:
            result = mcp_govern(
                agent_id=agent_id,
                action_type=action_type,
                description=description,
                risk_tier=risk_tier,
                timeout=self.timeout,
            )
            # Normalise: ensure required keys exist
            return {
                "decision": result.get("decision", "review"),
                "receipt_id": result.get("receipt_id", str(uuid.uuid4())),
                "risk_score": result.get("risk_score", 50),
                "explanation": result.get("explanation", {}),
            }
        except McpCallError as exc:
            decision = "deny" if self.fail_closed else "allow"
            return {
                "decision": decision,
                "receipt_id": str(uuid.uuid4()),
                "risk_score": -1,
                "explanation": {
                    "error": str(exc),
                    "fail_closed": self.fail_closed,
                },
            }


# ── schedule_governed ────────────────────────────────────────────────────────

def schedule_governed(
    agent_id: str,
    cron: str,
    action_type: str = "scheduled_execution",
    risk_tier: str = "low",
    description: str = "",
    verifier: str = "neurosymbolic",
    on_execute: Optional[Callable[..., Any]] = None,
    fail_closed: bool = True,
) -> Dict[str, Any]:
    """
    Register a governed scheduled loop with the DingDawg Loop Protocol.

    The governance check runs *before* each execution. If governance
    denies the action, ``on_execute`` is never called.

    Args:
        agent_id:    Unique agent identifier (e.g. "compliance-scanner").
        cron:        Standard cron expression (e.g. "0 9 * * *").
        action_type: What the agent does (e.g. "generate_report").
        risk_tier:   "low" | "medium" | "high" | "critical".
        description: Human-readable description of what the agent will do.
        verifier:    "neurosymbolic" (default) | "local".
        on_execute:  Optional callback — invoked when governance allows execution.
                     Receives ``loop_id`` as a keyword argument.
        fail_closed: If governance is unreachable, skip execution (default True).

    Returns:
        On success::

            {"loop_id": "<uuid>", "status": "registered", "schedule": "<cron>"}

        On MCP failure with fail_closed=True::

            {"loop_id": None, "status": "error_skipped", "reason": "<msg>"}

    Example::

        from dingdawg_loop import schedule_governed

        schedule_governed(
            agent_id="compliance-scanner",
            cron="0 9 * * *",
            verifier="neurosymbolic",
        )
    """
    if not agent_id:
        raise ValueError("agent_id must be a non-empty string")
    if not cron:
        raise ValueError("cron must be a non-empty cron expression")

    _valid_risk = {"low", "medium", "high", "critical"}
    if risk_tier not in _valid_risk:
        raise ValueError(f"risk_tier must be one of {sorted(_valid_risk)}, got '{risk_tier}'")

    _valid_verifiers = {"neurosymbolic", "local"}
    if verifier not in _valid_verifiers:
        raise ValueError(f"verifier must be one of {sorted(_valid_verifiers)}, got '{verifier}'")

    try:
        result = mcp_register_loop(
            agent_id=agent_id,
            cron=cron,
            action_type=action_type,
            risk_tier=risk_tier,
            description=description or f"Governed scheduled loop for agent '{agent_id}'",
            verifier=verifier,
        )
        loop_id = result.get("loop_id", str(uuid.uuid4()))
        entry: Dict[str, Any] = {
            "loop_id": loop_id,
            "status": "registered",
            "schedule": cron,
            "agent_id": agent_id,
            "action_type": action_type,
            "risk_tier": risk_tier,
            "verifier": verifier,
            "on_execute": on_execute,
            "fail_closed": fail_closed,
        }
        _LOOP_REGISTRY[loop_id] = entry
        return {
            "loop_id": loop_id,
            "status": "registered",
            "schedule": cron,
        }
    except McpCallError as exc:
        if fail_closed:
            return {
                "loop_id": None,
                "status": "error_skipped",
                "reason": str(exc),
            }
        raise


# ── execute_governed ─────────────────────────────────────────────────────────

def execute_governed(loop_id: str, notes: str = "") -> Dict[str, Any]:
    """
    Manually trigger a governed loop execution.

    The governance gate runs first. A 'deny' decision means the
    registered ``on_execute`` callback is never called.

    Args:
        loop_id: The loop identifier returned by :func:`schedule_governed`.
        notes:   Optional human-readable context for this execution.

    Returns:
        On allowed execution::

            {
                "outcome":    "executed",
                "receipt_id": "<uuid>",
                "risk_score": <int>,
            }

        On governance denial::

            {
                "outcome":    "denied",
                "receipt_id": "<uuid>",
                "risk_score": <int>,
            }

        On review queue::

            {
                "outcome":    "review_queued",
                "receipt_id": "<uuid>",
                "risk_score": <int>,
            }

        On any error (fail-closed)::

            {
                "outcome": "error_skipped",
                "reason":  "<message>",
            }

    Example::

        from dingdawg_loop import execute_governed

        result = execute_governed("loop-abc123", notes="Manual compliance run")
        print(result["outcome"])   # "executed" | "denied" | "review_queued" | "error_skipped"
    """
    if not loop_id:
        return {"outcome": "error_skipped", "reason": "loop_id must be a non-empty string"}

    # Resolve fail_closed from local registry; default True
    registry_entry = _LOOP_REGISTRY.get(loop_id, {})
    fail_closed: bool = registry_entry.get("fail_closed", True)
    on_execute: Optional[Callable[..., Any]] = registry_entry.get("on_execute")

    try:
        result = mcp_execute_loop(loop_id=loop_id, notes=notes)
    except McpCallError as exc:
        return {"outcome": "error_skipped", "reason": str(exc)}

    decision = result.get("decision", result.get("outcome", "deny"))
    receipt_id = result.get("receipt_id", str(uuid.uuid4()))
    risk_score = result.get("risk_score", -1)

    if decision == "allow":
        # Governance approved — invoke callback if registered
        if on_execute is not None:
            try:
                on_execute(loop_id=loop_id)
            except Exception as exc:  # noqa: BLE001
                # Callback failure never silently swallows the receipt
                return {
                    "outcome": "error_skipped",
                    "receipt_id": receipt_id,
                    "risk_score": risk_score,
                    "reason": f"on_execute callback raised: {exc}",
                }
        return {
            "outcome": "executed",
            "receipt_id": receipt_id,
            "risk_score": risk_score,
        }

    if decision == "review":
        return {
            "outcome": "review_queued",
            "receipt_id": receipt_id,
            "risk_score": risk_score,
        }

    # decision == "deny" or anything unrecognised
    return {
        "outcome": "denied",
        "receipt_id": receipt_id,
        "risk_score": risk_score,
    }


# ── list_loops ────────────────────────────────────────────────────────────────

def list_loops(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all registered governed loops, optionally filtered by agent.

    Args:
        agent_id: Optional filter. Pass None to list all loops.

    Returns:
        A list of loop dicts, each containing at minimum::

            {
                "loop_id":    "<uuid>",
                "agent_id":   "<str>",
                "cron":       "<str>",
                "risk_tier":  "<str>",
                "verifier":   "<str>",
                "status":     "<str>",
            }

        Falls back to the in-process registry if the MCP call fails.

    Example::

        from dingdawg_loop import list_loops

        for loop in list_loops(agent_id="compliance-scanner"):
            print(loop["loop_id"], loop["cron"])
    """
    try:
        result = mcp_list_loops(agent_id=agent_id)
        loops: List[Dict[str, Any]] = result.get("loops", [])
        return loops
    except McpCallError:
        # Degrade gracefully: return in-process registry
        entries = list(_LOOP_REGISTRY.values())
        if agent_id is not None:
            entries = [e for e in entries if e.get("agent_id") == agent_id]
        # Strip non-serialisable on_execute callable before returning
        return [
            {k: v for k, v in e.items() if k != "on_execute"}
            for e in entries
        ]
