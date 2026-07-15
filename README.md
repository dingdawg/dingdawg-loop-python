# dingdawg-loop

Governed scheduling for Python agents in 2 lines.
Works with CrewAI, LangGraph, AutoGen, and any custom agent framework.

```python
from dingdawg_loop import schedule_governed

schedule_governed(agent_id="compliance-scanner", cron="0 9 * * *", verifier="neurosymbolic")
```

Every execution runs through the DingDawg governance gate before anything fires.
Deny = nothing executes. No exceptions.

---

## Prerequisites

Node.js >= 18 and the DingDawg Loop MCP server:

```bash
npm install -g dingdawg-loop
```

Then install this package:

```bash
pip install dingdawg-loop
```

---

## Use cases

### 1 — Daily compliance report (CrewAI)

```python
from dingdawg_loop import schedule_governed, execute_governed
from crewai import Crew, Agent, Task

compliance_crew = Crew(agents=[...], tasks=[...])

def run_compliance(loop_id: str):
    compliance_crew.kickoff()

loop = schedule_governed(
    agent_id="compliance-scanner",
    cron="0 9 * * *",           # 09:00 every day
    action_type="generate_report",
    risk_tier="medium",
    description="Daily SOC-2 compliance scan and PDF report generation",
    verifier="neurosymbolic",
    on_execute=run_compliance,
)

print(loop)
# {"loop_id": "abc123", "status": "registered", "schedule": "0 9 * * *"}
```

### 2 — Recurring data sync (LangGraph)

```python
from dingdawg_loop import schedule_governed, execute_governed

loop = schedule_governed(
    agent_id="data-sync-agent",
    cron="*/15 * * * *",        # every 15 minutes
    action_type="data_sync",
    risk_tier="low",
    description="Sync CRM records to analytics warehouse",
    verifier="neurosymbolic",
)

# Manually trigger when needed (governance gate runs first)
result = execute_governed(loop["loop_id"], notes="Manual sync before board meeting")
print(result["outcome"])   # "executed" | "denied" | "review_queued" | "error_skipped"
```

### 3 — High-risk financial action with inline gate

```python
from dingdawg_loop import GovernanceGate

gate = GovernanceGate(fail_closed=True)

receipt = gate.govern(
    agent_id="finance-agent",
    action_type="wire_transfer",
    description="Transfer $42,000 to vendor account #8821",
    risk_tier="critical",
)

if receipt["decision"] == "allow":
    execute_wire_transfer(...)
else:
    notify_ops_team(receipt)
```

---

## API reference

### `schedule_governed(...) -> dict`

Register a governed loop. Returns `{"loop_id", "status", "schedule"}`.

| Param | Type | Default | Description |
|---|---|---|---|
| `agent_id` | str | required | Unique agent identifier |
| `cron` | str | required | Standard cron expression |
| `action_type` | str | `"scheduled_execution"` | What the agent does |
| `risk_tier` | str | `"low"` | `"low"` / `"medium"` / `"high"` / `"critical"` |
| `description` | str | `""` | Human-readable description |
| `verifier` | str | `"neurosymbolic"` | `"neurosymbolic"` or `"local"` |
| `on_execute` | callable | `None` | Callback fired on governance allow |
| `fail_closed` | bool | `True` | Skip execution if governance unreachable |

### `execute_governed(loop_id, notes="") -> dict`

Manually trigger a governed loop. Governance runs first.
Returns `{"outcome", "receipt_id", "risk_score"}`.

Possible outcomes: `"executed"` / `"denied"` / `"review_queued"` / `"error_skipped"`

### `list_loops(agent_id=None) -> list[dict]`

List registered loops. Optionally filter by `agent_id`.
Degrades gracefully to in-process registry if MCP is unreachable.

### `GovernanceGate`

Inline governance check for one-off actions outside of a scheduled loop.

```python
gate = GovernanceGate(fail_closed=True, timeout=5.0)
receipt = gate.govern(agent_id, action_type, description, risk_tier)
# receipt["decision"] == "allow" | "deny" | "review"
```

---

## Fail-closed behaviour

By default all functions are fail-closed: if the `npx dingdawg-loop` MCP
process is unreachable, times out, or returns an error, execution is
**skipped** and the function returns `{"outcome": "error_skipped", "reason": "..."}`.

To disable (not recommended for production):

```python
schedule_governed(..., fail_closed=False)
GovernanceGate(fail_closed=False)
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DINGDAWG_NPX_CMD` | `npx` | Override the npx binary path |
| `DINGDAWG_LOOP_PKG` | `dingdawg-loop` | Override the npm package name |

---

## Requirements

- Python >= 3.8
- Node.js >= 18
- `npm install -g dingdawg-loop`
- Zero Python dependencies (stdlib only)

---

## License

MIT — ISG / DingDawg
