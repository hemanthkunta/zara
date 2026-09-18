"""
ZARA Phase 14: Memory Extractor.
Extracts candidate memories from task results, user feedback, and explicit user statements.
Enforces privacy screening, secret rejection, and source-based confidence scoring.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple

from modules.memory import (
    MemoryItem,
    MemoryType,
    MemoryScope,
    MemorySource,
    PrivacyLevel,
    contains_secret,
    scrub_text,
)


class MemoryExtractor:
    """Extracts structured memories from task results, user prompts, and feedback."""

    # Patterns indicating explicit instruction to store or remember
    REMEMBER_PATTERNS = [
        r"(?:please\s+)?remember\s+(?:that\s+)?(.+)",
        r"(?:please\s+)?keep\s+in\s+mind\s+(?:that\s+)?(.+)",
        r"(?:please\s+)?note\s+(?:that\s+)?(.+)",
        r"(?:my\s+)?preference\s+is\s+(?:to\s+)?(.+)",
        r"i\s+(?:always\s+)?prefer\s+(.+)",
        r"always\s+(?:use\s+|do\s+|run\s+)?(.+)",
        r"never\s+(?:use\s+|do\s+|run\s+)?(.+)",
    ]

    # Patterns indicating explicit instruction NOT to store
    DO_NOT_STORE_PATTERNS = [
        r"don'?t\s+remember",
        r"do\s+not\s+remember",
        r"don'?t\s+save",
        r"do\s+not\s+save",
        r"don'?t\s+store",
        r"do\s+not\s+store",
        r"off\s+the\s+record",
        r"forget\s+this",
        r"private\s+mode",
    ]

    # Patterns indicating instruction to forget something
    FORGET_PATTERNS = [
        r"forget\s+(?:about\s+)?(.+)",
        r"remove\s+(?:the\s+)?memory\s+(?:about\s+)?(.+)",
        r"delete\s+(?:the\s+)?memory\s+(?:about\s+)?(.+)",
    ]

    def __init__(self):
        pass

    def extract_from_user_input(
        self,
        user_input: str,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[List[MemoryItem], Optional[Dict[str, Any]]]:
        """
        Analyze user input for explicit memory commands or statements.
        Returns (list_of_memory_candidates, optional_directive_action_dict).
        Directive action can be {'action': 'forget', 'target': '...'} or {'action': 'do_not_store'}.
        """
        text = user_input.strip()
        if not text:
            return [], None

        # 1. Check for 'do not store' directive
        for pat in self.DO_NOT_STORE_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return [], {"action": "do_not_store", "reason": "User requested off-the-record / do not store"}

        # 2. Check for 'forget' directive
        for pat in self.FORGET_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                target = m.group(1).strip()
                return [], {"action": "forget", "target": target}

        # 3. Check for secrets - if input contains high entropy API keys/passwords, reject storing as memory
        if contains_secret(text):
            return [], {"action": "rejected_secret", "reason": "Input contains secret/credentials"}

        candidates: List[MemoryItem] = []

        # 4. Check for explicit remember / preference patterns
        for pat in self.REMEMBER_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                extracted_content = m.group(1).strip()
                # Clean punctuation at end
                extracted_content = re.sub(r"[.!?]+$", "", extracted_content)
                if len(extracted_content) < 3:
                    continue

                # Determine type
                m_type = MemoryType.PREFERENCE
                tags = ["user_directive"]
                if "never" in text.lower() or "always" in text.lower():
                    m_type = MemoryType.INSTRUCTION
                    tags.append("rule")
                elif "prefer" in text.lower():
                    m_type = MemoryType.PREFERENCE
                    tags.append("preference")
                else:
                    m_type = MemoryType.FACT
                    tags.append("fact")

                scope = MemoryScope.PROJECT if project_id else MemoryScope.USER

                item = MemoryItem(
                    type=m_type,
                    content=extracted_content,
                    scope=scope,
                    confidence=0.98,
                    importance=0.9,
                    source=MemorySource.USER_STATED,
                    project_id=project_id,
                    task_id=task_id,
                    tags=tags,
                    metadata={"raw_input": scrub_text(text)},
                )
                candidates.append(item)
                break  # Matched one remember pattern

        return candidates, None

    def extract_from_task_result(
        self,
        task_id: str,
        goal: str,
        result: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> List[MemoryItem]:
        """
        Extract patterns, experiences, and decisions from a completed task execution result.
        """
        candidates: List[MemoryItem] = []
        status = result.get("status", "unknown")
        error = result.get("error")
        summary = result.get("summary", "")
        artifacts = result.get("artifacts", [])
        tool_results = result.get("tool_results", [])

        # 1. Error pattern extraction
        if status in ("failed", "error") or error:
            err_msg = str(error or summary or "Unknown failure")
            if not contains_secret(err_msg):
                clean_err = scrub_text(err_msg)
                item = MemoryItem(
                    type=MemoryType.ERROR_PATTERN,
                    content=f"Task '{goal}' failed with error: {clean_err[:300]}",
                    scope=MemoryScope.PROJECT if project_id else MemoryScope.TASK,
                    confidence=0.88,
                    importance=0.85,
                    source=MemorySource.TASK_RESULT,
                    project_id=project_id,
                    task_id=task_id,
                    tags=["error_pattern", "failure", status],
                    metadata={"error": clean_err[:200], "goal": goal[:100]},
                )
                candidates.append(item)

        # 2. Success pattern extraction
        elif status in ("completed", "success", "done"):
            success_desc = summary or f"Task '{goal}' completed successfully."
            if not contains_secret(success_desc):
                clean_desc = scrub_text(success_desc)
                item = MemoryItem(
                    type=MemoryType.SUCCESS_PATTERN,
                    content=f"Successful execution pattern for '{goal}': {clean_desc[:300]}",
                    scope=MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL,
                    confidence=0.85,
                    importance=0.75,
                    source=MemorySource.TASK_RESULT,
                    project_id=project_id,
                    task_id=task_id,
                    tags=["success_pattern", "completed"],
                    metadata={"goal": goal[:100], "artifact_count": len(artifacts)},
                )
                candidates.append(item)

        # 3. Key decisions or architecture experiences if present in result metadata
        decisions = result.get("decisions") or []
        for dec in decisions:
            if isinstance(dec, str) and dec.strip() and not contains_secret(dec):
                item = MemoryItem(
                    type=MemoryType.DECISION,
                    content=f"Architectural decision in '{goal}': {dec.strip()}",
                    scope=MemoryScope.PROJECT if project_id else MemoryScope.USER,
                    confidence=0.90,
                    importance=0.80,
                    source=MemorySource.TASK_RESULT,
                    project_id=project_id,
                    task_id=task_id,
                    tags=["decision", "architecture"],
                )
                candidates.append(item)

        # 4. Project context if artifacts or project structures were generated
        if project_id and artifacts:
            art_names = [Path(a).name if isinstance(a, str) else str(a) for a in artifacts[:5]]
            item = MemoryItem(
                type=MemoryType.PROJECT_CONTEXT,
                content=f"Project {project_id} produced artifacts: {', '.join(art_names)} for goal '{goal}'",
                scope=MemoryScope.PROJECT,
                confidence=0.92,
                importance=0.70,
                source=MemorySource.TASK_RESULT,
                project_id=project_id,
                task_id=task_id,
                tags=["project_context", "artifacts"],
            )
            candidates.append(item)

        return candidates

    def extract_from_feedback(
        self,
        feedback_text: str,
        rating: Optional[float] = None,
        context_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[MemoryItem]:
        """
        Extract user feedback memory item.
        """
        text = feedback_text.strip()
        if not text or contains_secret(text):
            return []

        clean_text = scrub_text(text)
        importance = 0.85
        if rating is not None:
            if rating < 0.5:
                importance = 0.92  # High importance on negative feedback to avoid repeating mistakes

        item = MemoryItem(
            type=MemoryType.USER_FEEDBACK,
            content=f"User feedback: {clean_text}",
            scope=MemoryScope.PROJECT if project_id else MemoryScope.USER,
            confidence=0.95,
            importance=importance,
            source=MemorySource.USER_STATED,
            project_id=project_id,
            task_id=context_id,
            tags=["feedback", "rating_" + str(rating) if rating is not None else "unrated"],
            metadata={"rating": rating, "context_id": context_id},
        )
        return [item]
