"""
dingdawg-loop
=============
Governed scheduling for Python agents — 2-line integration with
CrewAI, LangGraph, and any custom agent framework.

Quick start::

    from dingdawg_loop import schedule_governed

    schedule_governed(
        agent_id="compliance-scanner",
        cron="0 9 * * *",
        verifier="neurosymbolic",
    )

Prerequisite: Node.js >= 18 + npm install -g dingdawg-loop
"""

from .core import (
    GovernanceGate,
    execute_governed,
    list_loops,
    schedule_governed,
)

__all__ = [
    "schedule_governed",
    "execute_governed",
    "list_loops",
    "GovernanceGate",
]

__version__ = "1.0.0"
__author__ = "ISG / DingDawg"
__license__ = "MIT"
