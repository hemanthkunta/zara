"""
ZARA Conversational Session Manager: Multi-turn chat, task context retention, and follow-ups.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import datetime
from brain.router import LLMRouter
from brain.base import LLMMessage, Role
from core.engine import ZaraEngine

@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    task_id: Optional[str] = None

class ConversationalSession:
    def __init__(self, engine: ZaraEngine, router: Optional[LLMRouter] = None):
        self.engine = engine
        self.router = router or LLMRouter()
        self.history: List[ConversationTurn] = []
        self.active_context: Dict[str, Any] = {
            "current_project": None,
            "last_task": None,
            "last_summary": None
        }

    def process_user_input(self, user_text: str) -> str:
        """Process conversational user input, maintaining context and dispatching agent tasks."""
        self.history.append(ConversationTurn(role="user", content=user_text))

        # Check if the user is asking a question or requesting an engineering task
        is_direct_query = any(user_text.lower().startswith(q) for q in [
            "what is", "who are", "how do", "status", "help", "explain", "tell me"
        ]) and not any(verb in user_text.lower() for verb in ["create", "build", "write", "fix", "run", "test", "patch"])

        if is_direct_query:
            # Answer conversationally using LLM brain with session context
            system_prompt = (
                "You are ZARA, a personal engineering and research AI assistant. "
                "Be concise, clear, and professional. You have female persona. "
                f"Current context: {self.active_context}"
            )
            messages = [
                LLMMessage(role=Role(t.role), content=t.content) for t in self.history[-6:]
            ]
            response = self.router.generate(messages, system_prompt=system_prompt)
            assistant_reply = response.content
        else:
            # Dispatch to ZARA Autonomous 8-stage Engine
            self.engine.voice.speak(f"Starting autonomous task: {user_text[:50]}")
            summary = self.engine.run_task(user_text, tag="conversational")
            self.active_context["last_task"] = user_text
            self.active_context["last_summary"] = summary

            if summary["status"] == "COMPLETED":
                assistant_reply = (
                    f"I have completed your task: '{user_text}'. "
                    f"All {summary['steps_passed']} planned steps were verified successfully."
                )
            else:
                assistant_reply = (
                    f"I encountered a blocker during execution: {summary.get('blocker_reason')}. "
                    f"Human input or guidance is needed."
                )

        self.history.append(ConversationTurn(role="assistant", content=assistant_reply))
        self.engine.voice.speak(assistant_reply[:140])
        return assistant_reply

    def get_history(self) -> List[Dict[str, str]]:
        return [{"role": t.role, "content": t.content, "timestamp": t.timestamp} for t in self.history]
