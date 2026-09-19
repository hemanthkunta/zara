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
| **Self-Improvement & Learning** | `modules/evaluation.py`, `modules/self_improvement.py` | Phase 17 Self-Improvement, Evaluation & Adaptive Optimization: Multi-dimensional evaluation (Correctness, Quality, Efficiency, Reliability, Safety, Satisfaction), strategy library with automated validation, regression-guarded improvement proposals, controlled A/B experiments, atomic rollback, and critical safety file blocklist. |
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
| **Crash Recovery** | `core/recovery.py` | Checkpoints task context to `checkpoints/` after every verified step, enabling safe resume from last verified step with 5-tier classification (`SAFE_RESUME`, `RETRY`, `REQUIRES_VERIFICATION`, `REQUIRES_APPROVAL`, `MANUAL_INTERVENTION`). |
| **Unified Health & Lifecycle** | `core/lifecycle.py`, `core/health.py` | Phase 18 Production Lifecycle & Health: 8-stage state-machine startup/shutdown, non-invasive active probes across all 16 subsystems (`GlobalHealthService`). |
| **Environment Doctor** | `core/doctor.py` | Phase 18 Environment Diagnostics: Deep validation of runtime (Python 3.10+), Git, SQLite, AI provider keys, optional tools (Blender, Nmap), and port availability without leaking secrets. |
| **Atomic Persistence & Backup**| `core/persistence.py`, `core/backup.py` | Phase 18 Hardening & Disaster Recovery: Fsync atomic writes, corruption quarantine, SHA-256 integrity, compressed `.tar.gz` archives with path traversal protection. |
| **Configuration Validator** | `config/validator.py` | Phase 18 Configuration Integrity: Type & range bounds enforcement, safe sanitization, and immutable safety blocklist verification. |

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

### Multi-Agent & Workstream Orchestration (Phase 15)
```bash
# View summary of worker pools, active locks & success rate
./zara.py workers status

# List all registered workers across projects
./zara.py workers list

# Filter workers by status or project
./zara.py workers list --status running --project project-alpha

# Inspect active resource locks (Filesystem, GUI, Ports, etc.)
./zara.py workers locks

# Inspect details and budgets of a specific worker
./zara.py workers inspect wkr_12345678

# Pause, resume, or cancel a worker
./zara.py workers pause wkr_12345678
./zara.py workers resume wkr_12345678
./zara.py workers cancel wkr_12345678
```

### AI Model Router & Provider Failover (Phase 16)
```bash
# View active provider, model, latency, and router metrics
./zara.py models status

# List all registered AI models, capabilities, and availability
./zara.py models list

# Filter models by provider
./zara.py models list --provider google

# Inspect operational health, average latency, and error counts
./zara.py models health

# View task-to-model routing table and decision rationale
./zara.py models routing

# Inspect circuit breaker states (HEALTHY, DEGRADED, OPEN, HALF_OPEN)
./zara.py models circuit-breakers

# Discover available models from environment/SDKs
./zara.py models discover

# Run operational test ping on a provider
./zara.py models test mock
```

### Self-Improvement, Evaluation & Learning (Phase 17)
```bash
# View learning status, evaluation counts, strategies, proposals, experiments
./zara.py learning status

# View aggregate learning and subsystem evaluation statistics
./zara.py learning stats

# List synthesized lessons learned from task executions
./zara.py learning lessons

# List strategy library with validation metrics and version counts
./zara.py learning strategies

# View improvement proposals (filterable by status or risk tier)
./zara.py learning proposals
./zara.py learning proposals --status proposed --risk medium

# List active and completed controlled experiments (A/B testing)
./zara.py learning experiments

# Inspect recent multi-dimensional task evaluations
./zara.py learning evaluations --recent 10

# Inspect specific evaluation, proposal, strategy, or experiment
./zara.py learning inspect eval-12345678

# Review and approve/reject an improvement proposal
./zara.py learning approve prop-12345678
./zara.py learning reject prop-12345678 --reason "Safety risk"

# List and propose candidates
./zara.py learning propose

# Validate an improvement proposal in sandbox
./zara.py learning validate prop-12345678

# Inspect model router learning observations
./zara.py learning models

# Inspect specialist worker learning observations
./zara.py learning workers

# Evaluate a task across 6 objective dimensions
./zara.py learning evaluate "Implement database indexing"

# Atomically roll back a deployed improvement version or experiment
./zara.py learning rollback prop-12345678
```

### System Health, Doctor & Backups (Phase 18)
```bash
# Check aggregate health of all 16 subsystems
./zara.py health
./zara.py health --json

# Run deep environment diagnostics and dependency audits
./zara.py doctor
./zara.py doctor --json

# Create atomic compressed system backup (.tar.gz)
./zara.py backup
./zara.py backup --list

# Safely restore from a verified backup archive
./zara.py restore backups/zara_backup_20260918_203000.tar.gz
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
- **Secret Scrubbing**: API keys, auth tokens, and passwords are automatically redacted from logs, events, and memory entries.
- **Model Router Safety**: Tool-call safety ensures models propose actions without executing them; circuit breakers isolate failing providers, with strict offline mock fallback.
- **Self-Improvement Safety Principle**: ZARA must NEVER autonomously rewrite its safety policies, authorization, confirmation gates, or secret redaction. Improvements attempting to modify critical system files (`modules/cyber_lab.py`, `config/security_scope.json`, `tools/registry.py`, `core/observability.py`) are strictly prohibited and permanently rejected (`CRITICAL_SYSTEM_MODIFICATION_PROHIBITED`). All code modifications must pass the full test suite before deployment and maintain instant atomic rollback capability.
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
│   ├── validator.py             # Configuration validation & blocklist enforcement (Phase 18)
│   └── security_scope.json      # Pre-approved security scope list
├── core/
│   ├── engine.py                # 8-stage state machine execution engine
│   ├── lifecycle.py             # Deterministic startup, states & graceful shutdown (Phase 18)
│   ├── health.py                # Unified health service across all 16 subsystems (Phase 18)
│   ├── doctor.py                # Deep environment diagnostics & dependency audits (Phase 18)
│   ├── backup.py                # Atomic backup (.tar.gz) & verified restore (Phase 18)
│   ├── persistence.py           # Atomic writes, corruption quarantine & checksums (Phase 18)
│   ├── conversation.py          # Multi-turn conversational session manager
│   ├── prompts.py               # Master looping system prompts & templates
│   ├── state.py                 # State models & dataclasses
│   ├── recovery.py              # Task checkpointing & classified crash recovery (Phase 18)
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
│   ├── evaluation.py            # Self-improvement, task evaluation & learning pipeline (Phase 17)
│   ├── model_router.py          # AI model router, capability discovery & circuit breakers (Phase 16)
│   ├── resource_locking.py      # Granular resource lock manager (Phase 15)
│   ├── workers.py               # Delegated worker profiles & workstream orchestrator (Phase 15)
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
├── ui/                          # Unified Command Center & Control UI (Phase 13/14/15/16/17)
├── learning/                    # Self-improvement & learning storage (Phase 17)
│   ├── strategies.json          # Validated and candidate execution strategies
│   ├── evaluations/             # Multi-dimensional task evaluations
│   ├── experiments/             # A/B & shadow experiment records
│   └── improvements/            # Versioned deployments for atomic rollback
├── memory/
│   ├── zara_log.md              # Human-readable append-only lessons
│   ├── episodes.jsonl           # Structured episodic memory
│   ├── preferences.json         # User preferences store
│   └── vectors.db               # SQLite hybrid vector & structured memory index
├── backups/                     # Compressed .tar.gz system backups (Phase 18)
├── queue/
│   ├── job_applications/        # Human-in-the-loop review queue
│   ├── improvement_proposals/   # Self-improvement proposals queue
│   └── task_queue.json          # Multi-task orchestrator status store
├── logs/
│   ├── audit.jsonl              # Structured audit log
│   ├── zara.log                 # System log
│   └── workers/                 # Worker execution logs & JSON state (Phase 15)
├── checkpoints/                 # Task recovery state checkpoints
└── tests/
    ├── test_zara_core.py        # Core loop and integration tests
    ├── test_llm_brain.py        # Brain providers and router tests
    ├── test_tool_registry.py    # Tool validation, traversal & permission tests
    ├── test_specialized_modules.py # Git, Blender, Research, Recovery, Security tests
    ├── test_memory_advanced.py  # Phase 14 memory CRUD, decay & conflicts
    ├── test_memory_scoping.py   # Phase 14 scoping, isolation & privacy
    ├── test_memory_integration.py # Phase 14 full-system integration tests
    ├── test_workers_core.py     # Phase 15 worker state, types, budgets & lifecycles
    ├── test_resource_locking.py # Phase 15 granular resource manager & contention
    ├── test_parallel_orchestration.py # Phase 15 parallel DAG execution, UI & CLI
    ├── test_model_router_core.py # Phase 16 model router, providers, retry & fallback
    ├── test_model_health_and_circuit.py # Phase 16 provider health tracking & circuit breaker
    ├── test_model_integration.py # Phase 16 worker routing, engine & UI integration
    ├── test_evaluation_core.py  # Phase 17 evaluation dimensions, criteria & learning candidates
    ├── test_learning_strategies.py # Phase 17 strategy library, planner integration & subsystems
    ├── test_improvement_experiments.py # Phase 17 proposals, safety guards, experiments & rollback
    ├── test_final_integration_lifecycle.py # Phase 18 deterministic lifecycle, config & atomic persistence
    ├── test_final_health_doctor.py # Phase 18 health service, doctor diagnostics, backups & recovery
    └── test_final_end_to_end_scenarios.py # Phase 18 end-to-end scenarios A-G, hardening & invariants
```
