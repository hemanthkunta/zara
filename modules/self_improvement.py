"""
ZARA Self-Improvement Module: Evaluates task history and proposes improvements to workflows, prompts, and strategies.
Safety Rule: Never autonomously modifies safety policies, permissions, or security scopes.
Maintains backward compatibility with Phase 1 while delegating to Phase 17 EvaluationManager.
"""
from pathlib import Path
import json
import datetime
from typing import List, Dict, Any, Optional

from modules.memory import MemoryStore
from core.state import TaskContext
from modules.evaluation import EvaluationManager, ChangeType, ProposalRisk

PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "queue" / "improvement_proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


class SelfImprovementEvaluator:
    def __init__(self, memory_store: Optional[MemoryStore] = None, evaluation_manager: Optional[EvaluationManager] = None):
        self.memory = memory_store or MemoryStore()
        self.evaluation_manager = evaluation_manager or EvaluationManager(memory_store=self.memory)

    def evaluate_task(self, context: TaskContext) -> Optional[Dict[str, Any]]:
        """
        Analyze the task run via EvaluationManager. If retries were high or failures occurred,
        generate a structured improvement proposal requiring user approval.
        """
        # Run full Phase 17 multi-dimensional evaluation
        eval_result = self.evaluation_manager.evaluate_task_execution(context)

        proposal = None
        if len(context.diagnoses) >= 2 or not context.is_completed:
            prop_obj = self.evaluation_manager.create_proposal(
                title=f"Refine pre-planning verification criteria for {context.tag}",
                description=f"Task '{context.task}' encountered {len(context.diagnoses)} diagnoses. Ensure required dependencies and assertions are checked before code generation.",
                affected_component=f"modules/{context.tag}.py",
                change_type=ChangeType.PLANNING_HEURISTIC,
                risk=ProposalRisk.MEDIUM,
                source_evidence={"diagnoses": [d.to_dict() for d in context.diagnoses], "evaluation_id": eval_result.evaluation_id},
                expected_benefit="Reduce diagnostic retries and prevent repeated runtime failures.",
            )

            # Also write to legacy queue directory for backward-compatible inspections
            proposal = {
                "id": prop_obj.proposal_id,
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
