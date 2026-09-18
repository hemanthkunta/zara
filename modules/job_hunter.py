"""
ZARA Job Hunter Module: Finds listings, drafts tailored applications, and queues for human approval.
Never auto-submits.
"""
from pathlib import Path
import json
import datetime
from typing import Dict, Any, List
from config.settings import JOB_QUEUE_DIR

class JobHunterModule:
    def __init__(self, queue_dir: Path = JOB_QUEUE_DIR):
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def draft_application(
        self,
        job_id: str,
        company: str,
        role: str,
        job_description: str,
        candidate_profile: Dict[str, Any]
    ) -> Path:
        """
        Drafts a tailored cover letter and application packet and stores it in the human approval queue.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company = "".join(c for c in company if c.isalnum() or c in ("-", "_")).lower()
        filename = f"draft_{safe_company}_{job_id}_{timestamp}.json"
        draft_path = self.queue_dir / filename

        tailored_cover_letter = (
            f"Dear Hiring Team at {company},\n\n"
            f"I am writing to express my strong enthusiasm for the {role} position. "
            f"With background in {candidate_profile.get('skills', 'software engineering and research')}, "
            f"I am excited about contributing to your team's initiatives.\n\n"
            f"Key Alignment:\n"
            f"- Technical Experience: {candidate_profile.get('summary', 'Hands-on system building and automation')}\n"
            f"- Problem Solving: Focus on verifiable milestones, test-driven execution, and rapid iteration.\n\n"
            f"Sincerely,\n"
            f"{candidate_profile.get('name', 'Candidate')}"
        )

        packet = {
            "status": "pending_human_approval",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "job_id": job_id,
            "company": company,
            "role": role,
            "job_description_snippet": job_description[:500],
            "tailored_cover_letter": tailored_cover_letter,
            "notes": "HUMAN REVIEW REQUIRED: Review before manual submission. Auto-submission is prohibited."
        }

        draft_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return draft_path

    def list_pending_applications(self) -> List[Dict[str, Any]]:
        results = []
        for file in sorted(self.queue_dir.glob("draft_*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                data["file_path"] = str(file)
                results.append(data)
            except Exception:
                pass
        return results
