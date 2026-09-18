# ZARA: Autonomous Engineering & Research Agent

> **ZARA** is an autonomous engineering and research agent operating on a strict, verifiable state-machine loop with continuous self-learning, sandboxed execution, safety interceptors, and local female TTS voice feedback.

---

## The Core State Machine Loop

Unlike open-ended prompts that assume success, ZARA operates on an 8-stage cycle where progress is strictly verified by real signals (tests, exit codes, output matching) before advancing:

```
┌─────────────┐
│  PERCEIVE   │  Read task, current repo state, query memory log for past lessons
└──────┬──────┘
       ▼
┌─────────────┐
│    PLAN     │  Break into smallest verifiable steps; state success condition per step
└──────┬──────┘
       ▼
┌─────────────┐
│     ACT     │  Execute ONE step (write code / run command / call tool)
└──────┬──────┘
       ▼
┌─────────────┐
│   VERIFY    │  Run real check (pytest, lint, exit code); compare actual vs expected
└──────┬──────┘
       ▼
   pass? ──no──► DIAGNOSE & RETRY (root cause hypothesis → targeted fix; max 5 retries)
       │yes
       ▼
┌─────────────┐
│   REFLECT   │  Synthesize concise 1-3 line lesson (approach, result, lesson)
└──────┬──────┘
       ▼
┌─────────────┐
│   PERSIST   │  Append to memory/zara_log.md (versioned self-learning store)
└──────┬──────┘
       ▼
   more steps? ──yes──► back to ACT
       │no
       ▼
┌─────────────┐
│   REPORT    │  Report verified summary & audio status update via female TTS
└─────────────┘
```

---

## Architectural Modules

| Module | Location | Purpose & Autonomy |
|---|---|---|
| **Core Engine** | `core/engine.py` | 8-stage state machine orchestrating Perceive &rarr; Plan &rarr; Act &rarr; Verify &rarr; Diagnose &rarr; Reflect &rarr; Persist. |
| **Master Prompts** | `core/prompts.py` | The master looping system prompt, stage templates, and operational guardrails. |
| **Coding** | `modules/coding.py` | Workspace-constrained file reader, writer, AST syntax validator, and targeted patcher. |
| **Debugging** | `modules/debugging.py` | Error parsing, traceback diagnosis, hypothesis formation, and targeted fix proposal. |
| **Execution** | `modules/execution.py` | Safe process execution engine with destructive command safety filters and Docker isolation. |
| **Self-Learning Memory** | `modules/memory.py` | Append-only store (`memory/zara_log.md`) with keyword relevance querying before planning. |
| **Voice Interface** | `modules/voice.py` | Offline macOS native female voice (`Samantha`) + fallback to ElevenLabs / pyttsx3. |
| **Security Testing** | `modules/security.py` | Scope-gated security testing strictly enforcing `config/security_scope.json` with user confirmation. |
| **Job Hunter** | `modules/job_hunter.py` | Job application drafter outputting to `queue/job_applications/` for manual human review (never auto-submits). |
| **Orchestrator** | `modules/orchestrator.py` | Multi-task queue manager tracking `pending`, `running`, `done`, and `blocked` tasks. |

---

## Hard Rules & Safety Guardrails

- **Zero Unverified Approvals**: Never mark a step "done" because code "looks right". A step only passes when verified by concrete output or exit code 0.
- **Destructive Command Interception**: Blocks commands matching patterns like `rm -rf /`, `DROP TABLE`, `git push --force`, or fork bombs.
- **Security Scope Enforcement**: Security scans can only target hosts listed in `config/security_scope.json` (`localhost`, `127.0.0.1`). Unauthorized targets trigger immediate exceptions.
- **Human-in-the-Loop Job Applications**: To comply with platform Terms of Service, job applications are drafted into `queue/job_applications/` and require explicit human review.
- **Bounded Diagnostic Retries**: Max 5 attempts per step before gracefully halting and escalating to human guidance.

---

## Quickstart

### 1. Test Voice Synthesis
```bash
./zara.py voice-test
```

### 2. Search or Read Memory Log
```bash
# Read all memory entries
./zara.py memory

# Search memory for past lessons on a topic
./zara.py memory "unit test verification"
```

### 3. Run an Autonomous Task
```bash
./zara.py run "echo 'ZARA autonomous loop active' > status.txt" --tag test
```

### 4. Run Core Verification Tests
```bash
pytest -v tests/
```
