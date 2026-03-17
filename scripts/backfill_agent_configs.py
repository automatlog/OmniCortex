"""
Backfill agent YAML config snapshots for all existing agents.

Usage:
  source .venv/bin/activate
  python scripts/backfill_agent_configs.py
"""

from core.agent_manager import get_all_agents
from core.agent_config import sync_agent_config


def main() -> None:
    agents = get_all_agents()
    print(f"Found {len(agents)} agents")
    for agent in agents:
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            continue
        try:
            sync_agent_config(agent_id, event_type="sync")
            print(f"[OK] {agent_id}")
        except Exception as exc:
            print(f"[FAIL] {agent_id}: {exc}")


if __name__ == "__main__":
    main()

