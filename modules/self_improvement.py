"""
ZARA Self-Improvement Module: Evaluates task history and proposes improvements to workflows, prompts, and strategies.
Safety Rule: Never autonomously modifies safety policies, permissions, or security scopes.
"""
from pathlib import Path
import json
import datetime
from typing import List, Dict, Any, Optional
from modules.memory import MemoryStore
from core.state import TaskContext

PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "queue" / "improvement_proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

class SelfImprovementEvaluator:
    def __init__(self, memory_store: Optional[MemoryStore] = None):
        self.memory = memory_store or MemoryStore()

    def evaluate_task(self, context: TaskContext) -> Optional[Dict[str, Any]]:
        """
        Analyze the task run. If retries were high or failures occurred,
        generate a structured improvement proposal requiring user approval.
        """
        proposal = None
        if len(context.diagnoses) >= 2 or not context.is_completed:
            proposal = {
                "id": f"prop-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "task": context.task,
                "category": "workflow_refinement",
                "observations": [f"Attempt {d.attempt}: {d.failure_reason[:150]}" for d in context.diagnoses],
                "proposed_action": (
                    f"Refine pre-planning verification criteria for {context.tag}. "
                    f"Ensure required dependencies and file structures are asserted before code generation."
                ),
                "requires_user_approval": True,
                "status": "pending_approval"
            }
            proposal_file = PROPOSALS_DIR / f"{proposal['id']}.json"
            proposal_file.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

        return proposal

    def list_proposals(self) -> List[Dict[str, Any]]:
        proposals = []
        for file in sorted(PROPOSALS_DIR.glob("prop-*.json")):
            try:
                proposals.append(json.loads(file.read_text(encoding="utf-8")))
            except Exception:
                pass
        return proposals
