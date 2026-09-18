# ZARA: Autonomous Personal AI Engineering & Research Agent

> **ZARA** is a production-grade personal AI engineering and research agent operating on an 8-stage state-machine loop with continuous self-learning, sandboxed process execution, provider-independent LLM brain architecture, typed tool registry, macOS developer tools, and local female TTS voice feedback.

---

## 1. Architecture & The Core Loop

Unlike open-ended prompts that assume success, ZARA operates on a strictly verified 8-stage state machine where each step must satisfy checkable criteria before proceeding:

```
┌─────────────┐
│  PERCEIVE   │  Read task, inspect workspace, query persistent memory log
└──────┬──────┘
       ▼
┌─────────────┐
│    PLAN     │  Decompose into smallest verifiable steps with explicit success conditions
└──────┬──────┘
       ▼
┌─────────────┐
│     ACT     │  Execute ONE step via typed tools (code, terminal, test, etc.)
└──────┬──────┘
       ▼
┌─────────────┐
│   VERIFY    │  Validate real signals (tests pass, exit code 0, AST syntax checks)
└──────┬──────┘
       ▼
   pass? ──no──► DIAGNOSE & RETRY (traceback parser -> hypothesis -> targeted patch, max 5)
       │yes
       ▼
┌─────────────┐
│   REFLECT   │  Synthesize concise 1-3 line lesson (approach, result, lesson)
└──────┬──────┘
       ▼
┌─────────────┐
│   PERSIST   │  Append to memory/zara_log.md & episodic memory store
└──────┬──────┘
       ▼
   more steps? ──yes──► back to ACT
       │no
       ▼
┌─────────────┐
│   REPORT    │  Report verified summary & auditory update via female TTS (Samantha)
└─────────────┘
```

---

## 2. Implemented Subsystems (Phases 0–24)

| Subsystem | Components | Description |
|---|---|---|
| **AI Brain Layer** | `brain/` | Provider-independent architecture (`LLMProvider`) supporting **Google Gemini**, **Anthropic Claude**, **OpenAI GPT**, **Local Ollama**, and an offline **Mock** provider with automatic failover and token tracking. |
| **Typed Tool Registry** | `tools/` | Schema-validated tool interface with risk levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), input validation, timeouts, and JSONL audit logging. |
| **Autonomous Coding** | `modules/coding.py` | Multi-file reader/writer, AST syntax validation, unified diff generator, and symbol extraction. |
| **Intelligent Debugger** | `modules/debugging.py` | Traceback parser (file, line, exception type), test reproducer generator, hypothesis builder, and targeted patcher. |
| **Verifiable Evidence** | `modules/verification.py` | Evidence collector storing SHA-256 output hashes, exit codes, and timestamps for every check. |
| **Layered Sandbox** | `modules/execution.py` | `Request -> Policy -> Permission -> Sandbox -> Execution -> Audit`. Regex interceptor for destructive commands, Docker container isolation (`--network none`), memory/CPU limits. |
| **Hierarchical Memory** | `modules/memory.py`, `modules/memory_extractor.py` | Phase 14 Advanced Memory: 12 structured memory categories, 5 scopes (Global, User, Project, Task, Session), strict cross-project isolation, hybrid vector + lexical retrieval, deduplication, conflict resolution, secret scrubbing, and temporal decay. |
| **Self-Improvement** | `modules/self_improvement.py` | Evaluates completed tasks and proposes prompt, workflow, or tool refinements to human review queue. |
| **Voice Interface** | `modules/voice.py` | Zero-dependency native macOS female TTS (`say -v Samantha`) with speech interruption, sanitization, and STT microphone adapter. |
| **Conversational Mode** | `core/conversation.py` | Multi-turn conversational REPL (`./zara.py chat`) retaining task context across prompts. |
| **macOS Automation** | `tools/macos_control.py` | Native desktop notifications (`osascript`), clipboard read/write (`pbcopy`/`pbpaste`), screenshot capture (`screencapture`). |
| **Vision Analysis** | `modules/vision.py` | Image and screenshot analysis for terminal errors, UI interfaces, and visual assets. |
| **Web Research** | `modules/research.py` | Query &rarr; Search &rarr; Retrieve &rarr; Extract &rarr; Synthesize &rarr; Cite with verified facts and source separation. |
| **Controlled Git** | `modules/git_tools.py` | Status, diff, branch, commit, log, and pull request bundle preparation. |
| **Blender 3D** | `modules/blender.py` | Standalone Python script generator for 3D meshes, materials, lighting, cameras, and headless rendering. |
| **Authorized Security Lab** | `modules/security.py` | Scope-gated defensive port scanner and HTTP security header auditor enforcing `config/security_scope.json`. |
| **Job Application Drafter**| `modules/job_hunter.py` | Tailored application packet and cover letter drafter outputting to `queue/job_applications/` with `pending_human_approval`. |
| **Desktop GUI** | `gui/app.py` | Native dark-themed desktop interface displaying conversation, live state pipeline, memory, and checkpoints. |
| **Command Center UI** | `ui/server.py`, `ui/static/` | Phase 13 visual command center dashboard with FastAPI backend, WebSockets event streaming, multimodal world model inspector, task DAG, screen perception feed, and subsystem control. |
| **Observability & Audit** | `core/observability.py` | Structured JSONL audit log (`logs/audit.jsonl`) with automatic secret scrubbing. |
| **Crash Recovery** | `core/recovery.py` | Checkpoints task context to `checkpoints/` after every verified step, enabling safe resume from last verified step. |

---

## 3. Quickstart & CLI Commands

### Conversational Mode (Default)
Start an interactive chat session with ZARA:
```bash
./zara.py chat
# or simply:
./zara.py
```

### Run an Autonomous Engineering Task
```bash
./zara.py run "Create a FastAPI application with tests" --tag api
```

### Launch the Desktop GUI
```bash
./zara.py gui
```

### Launch Unified Command Center & Control UI (Web / Browser)
```bash
# Launch server and open browser
./zara.py ui --open

# Custom port
./zara.py ui --port 9000

# Inspect UI server status
./zara.py ui status
```

### List Registered Tools and Risk Levels
```bash
./zara.py tools
```

### Inspect, Search, and Manage Long-Term Memory (Phase 14)
```bash
# Read all entries / search lessons
./zara.py memory

# Search memory with query and filters
./zara.py memory "unit test verification" --type INSTRUCTION --scope GLOBAL

# Subsystem statistics (breakdowns by category and scope)
./zara.py memory --stats

# View detected contradictions and conflicts
./zara.py memory --conflicts

# View most recent memories
./zara.py memory --recent 10

# Export project or global memories to JSON
./zara.py memory --export memory_backup.json
```

### Inspect Task Recovery Checkpoints
```bash
./zara.py recover
```

### Test Voice Synthesis (Female Voice)
```bash
./zara.py voice-test
```

### Run Comprehensive Test Suite
```bash
./zara.py test
```

---

## 4. Safety Guardrails & Policies

- **Strict Scope Verification**: Security auditing is restricted to pre-approved hosts in `config/security_scope.json` (`localhost`, `127.0.0.1`). Any external target triggers a `ScopeViolationError`.
- **Destructive Command Interception**: Commands containing `rm -rf /`, `DROP TABLE`, `git push --force`, or fork bombs are blocked by the safety interceptor.
- **Draft-Only Job Hunter**: Job applications are enqueued to `queue/job_applications/` for manual human approval. Automated submission is prohibited.
- **Secret Scrubbing**: API keys, auth tokens, and passwords are automatically redacted from logs and memory entries.
- **Bounded Retries**: Maximum 5 diagnostic attempts per step before escalating to human input.

---

## 5. Directory Structure

```text
/Users/hemanthkunta/jarvis/
├── zara.py                      # Main executable launcher
├── cli.py                       # CLI parser & command dispatcher
├── README.md                    # Architecture and usage documentation
├── config/
│   ├── settings.py              # Configuration, model settings & risk tiers
│   └── security_scope.json      # Pre-approved security scope list
├── core/
│   ├── engine.py                # 8-stage state machine execution engine
│   ├── conversation.py          # Multi-turn conversational session manager
│   ├── prompts.py               # Master looping system prompts & templates
│   ├── state.py                 # State models & dataclasses
│   ├── recovery.py              # Task checkpointing & crash recovery
│   └── observability.py         # Structured JSONL audit logger & secret scrubber
├── brain/
│   ├── base.py                  # LLMProvider abstract base class
│   ├── router.py                # Provider router, fallback chain & structured JSON
│   └── providers/
│       ├── gemini.py            # Google Gemini adapter
│       ├── adapters.py          # Anthropic, OpenAI, and Ollama adapters
│       └── mock.py              # Deterministic offline provider for tests
├── tools/
│   ├── base.py                  # BaseTool and ToolResult abstractions
│   ├── registry.py              # Tool registry with permission gates
│   ├── filesystem.py            # Read, write, patch, list tools (with path traversal guards)
│   ├── terminal.py              # Sandboxed command and test runner tools
│   └── macos_control.py         # macOS notifications, clipboard, screenshots
├── modules/
│   ├── coding.py                # AST analysis, diff calculation & file operations
│   ├── debugging.py             # Traceback parsing, hypothesis builder & patcher
│   ├── execution.py             # Layered process runner (Request->Policy->Sandbox->Exec)
│   ├── verification.py          # Evidence recorder & syntax/command verifier
│   ├── memory.py                # Advanced long-term memory store (Phase 14)
│   ├── memory_extractor.py      # Automated pattern & preference extractor
│   ├── self_improvement.py      # Improvement proposal generator
│   ├── voice.py                 # Female TTS voice synthesizer & STT adapter
│   ├── vision.py                # Image & screenshot inspector
│   ├── research.py              # Web search, retrieval & citation synthesizer
│   ├── git_tools.py             # Controlled Git & PR preparation
│   ├── blender.py               # Blender 3D automation script synthesis
│   ├── security.py              # Authorized cybersecurity lab (port & header audit)
│   ├── job_hunter.py            # Job application drafter & review queue
│   └── orchestrator.py          # Multi-task queue state manager
├── gui/
│   └── app.py                   # Desktop GUI with state machine visualization
├── ui/                          # Unified Command Center & Control UI (Phase 13/14)
├── memory/
│   ├── zara_log.md              # Human-readable append-only lessons
│   ├── episodes.jsonl           # Structured episodic memory
│   ├── preferences.json         # User preferences store
│   └── vectors.db               # SQLite hybrid vector & structured memory index
├── queue/
│   ├── job_applications/        # Human-in-the-loop review queue
│   ├── improvement_proposals/   # Self-improvement proposals queue
│   └── task_queue.json          # Multi-task orchestrator status store
├── logs/
│   ├── audit.jsonl              # Structured audit log
│   └── zara.log                 # System log
├── checkpoints/                 # Task recovery state checkpoints
└── tests/
    ├── test_zara_core.py        # Core loop and integration tests
    ├── test_llm_brain.py        # Brain providers and router tests
    ├── test_tool_registry.py    # Tool validation, traversal & permission tests
    ├── test_specialized_modules.py # Git, Blender, Research, Recovery, Security tests
    ├── test_memory_advanced.py  # Phase 14 memory CRUD, decay & conflicts
    ├── test_memory_scoping.py   # Phase 14 scoping, isolation & privacy
    └── test_memory_integration.py # Phase 14 full-system integration tests
```
