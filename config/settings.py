"""
Configuration settings for the ZARA Autonomous Agent.
"""
from pathlib import Path
import os
from enum import Enum

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_FILE = MEMORY_DIR / "zara_log.md"
QUEUE_DIR = BASE_DIR / "queue"
JOB_QUEUE_DIR = QUEUE_DIR / "job_applications"
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"
SECURITY_SCOPE_FILE = CONFIG_DIR / "security_scope.json"
AUDIT_LOG_FILE = LOGS_DIR / "audit.jsonl"
SYSTEM_LOG_FILE = LOGS_DIR / "zara.log"
SCREENSHOTS_DIR = LOGS_DIR / "screenshots"
PROJECTS_DIR = BASE_DIR / "projects"
SCHEDULES_DIR = BASE_DIR / "schedules"
SCHEDULES_FILE = CONFIG_DIR / "schedules.json"
EVENTS_LOG_FILE = LOGS_DIR / "events.jsonl"

# Ensure runtime directories exist
for directory in (MEMORY_DIR, JOB_QUEUE_DIR, CONFIG_DIR, LOGS_DIR, CHECKPOINTS_DIR, SCREENSHOTS_DIR, PROJECTS_DIR, SCHEDULES_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Risk Levels for Human Confirmation System
# Risk Levels for Human Confirmation System
class RiskLevel(str, Enum):
    LOW = "LOW"            # Read-only operations, safe inspects
    MEDIUM = "MEDIUM"      # Normal workspace file changes & test runs
    HIGH = "HIGH"          # Destructive ops, system-level execution, git push
    CRITICAL = "CRITICAL"  # Operations requiring explicit double-confirmation or outside default scope

# Failure Types for Fine-Grained Error Classification
class FailureType(str, Enum):
    TIMEOUT = "timeout"
    COMMAND_FAILURE = "command_failure"
    TOOL_VALIDATION_FAILURE = "tool_validation_failure"
    PLANNER_FAILURE = "planner_failure"
    VERIFICATION_FAILURE = "verification_failure"
    PERMISSION_FAILURE = "permission_failure"
    DEPENDENCY_FAILURE = "dependency_failure"
    UNEXPECTED_EXCEPTION = "unexpected_exception"

# Loop & Safety parameters
MAX_STEPS = int(os.getenv("ZARA_MAX_STEPS", "20"))
MAX_RETRIES_PER_STEP = int(os.getenv("ZARA_MAX_RETRIES_PER_STEP", "2"))
MAX_TOTAL_RETRIES = int(os.getenv("ZARA_MAX_TOTAL_RETRIES", "5"))
MAX_DIAGNOSE_RETRIES = MAX_TOTAL_RETRIES
MAX_EXECUTION_TIME_SECONDS = int(os.getenv("ZARA_MAX_EXECUTION_TIME", "300"))
COMMAND_TIMEOUT_SECONDS = int(os.getenv("ZARA_CMD_TIMEOUT", "60"))
SANDBOX_DOCKER_IMAGE = os.getenv("ZARA_DOCKER_IMAGE", "python:3.11-slim")
SANDBOX_MEMORY_LIMIT = os.getenv("ZARA_SANDBOX_MEM", "512m")
SANDBOX_CPU_LIMIT = os.getenv("ZARA_SANDBOX_CPU", "1.0")

# Research & Browser Budget Parameters
MAX_RESEARCH_QUERIES = int(os.getenv("ZARA_MAX_RESEARCH_QUERIES", "8"))
MAX_SOURCES = int(os.getenv("ZARA_MAX_SOURCES", "10"))
MAX_PAGES = int(os.getenv("ZARA_MAX_PAGES", "10"))
MAX_RESEARCH_TIME_SECONDS = int(os.getenv("ZARA_MAX_RESEARCH_TIME_SECONDS", "120"))

# Computer Interaction & Screenshot Parameters
MAX_SCREENSHOT_AGE_HOURS = int(os.getenv("ZARA_MAX_SCREENSHOT_AGE_HOURS", "24"))
MAX_SCREENSHOTS_KEPT = int(os.getenv("ZARA_MAX_SCREENSHOTS_KEPT", "20"))
MAX_GUI_RETRIES = int(os.getenv("ZARA_MAX_GUI_RETRIES", "3"))
DEFAULT_DISPLAY_ID = int(os.getenv("ZARA_DEFAULT_DISPLAY_ID", "1"))

# Voice Parameters
ENABLE_VOICE = os.getenv("ZARA_ENABLE_VOICE", "true").lower() in ("true", "1", "yes")
VOICE_NAME = os.getenv("ZARA_VOICE_NAME", "Samantha")  # Default macOS female voice
VOICE_RATE = int(os.getenv("ZARA_VOICE_RATE", "190"))
WAKE_WORD = os.getenv("ZARA_WAKE_WORD", "ZARA")
MAX_RECORDING_SECONDS = int(os.getenv("ZARA_MAX_RECORDING_SECONDS", "15"))
VOICE_SILENCE_TIMEOUT = float(os.getenv("ZARA_VOICE_SILENCE_TIMEOUT", "1.5"))
TTS_ENABLED = os.getenv("ZARA_ENABLE_TTS", "true").lower() in ("true", "1", "yes")
STT_PROVIDER = os.getenv("ZARA_STT_PROVIDER", "local")  # local, mock, remote
TTS_PROVIDER = os.getenv("ZARA_TTS_PROVIDER", "macos")  # macos, mock, elevenlabs
VOICE_LANGUAGE = os.getenv("ZARA_VOICE_LANGUAGE", "en-US")
MAX_VOICE_SUMMARY_LENGTH = int(os.getenv("ZARA_MAX_VOICE_SUMMARY_LENGTH", "200"))
VOICE_TEMP_DIR = LOGS_DIR / "voice"
VOICE_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# LLM Brain Configuration
DEFAULT_LLM_PROVIDER = os.getenv("ZARA_LLM_PROVIDER", "auto") # auto, gemini, anthropic, openai, ollama, mock
DEFAULT_MODEL_GEMINI = os.getenv("ZARA_MODEL_GEMINI", "gemini-2.5-flash")
DEFAULT_MODEL_ANTHROPIC = os.getenv("ZARA_MODEL_ANTHROPIC", "claude-3-5-sonnet-20241022")
DEFAULT_MODEL_OPENAI = os.getenv("ZARA_MODEL_OPENAI", "gpt-4o")
DEFAULT_MODEL_OLLAMA = os.getenv("ZARA_MODEL_OLLAMA", "llama3.1")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Blocked destructive commands regex
BLOCKED_COMMAND_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-rf)\s+/",
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-rf)\s+~",
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-rf)\s+\*",
    r"\bdrop\s+database\b",
    r"\bdrop\s+table\b",
    r"\btruncate\s+table\b",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bmkfs\b",
    r":\(\)\{\s*:\|:&\s*\};:",  # fork bomb
]

# Phase 10: Proactive Autonomy & Scheduling Parameters
AUTONOMOUS_MODE = os.getenv("ZARA_AUTONOMOUS_MODE", "false").lower() in ("true", "1", "yes")
QUIET_HOURS_START = os.getenv("ZARA_QUIET_HOURS_START", "23:00")
QUIET_HOURS_END = os.getenv("ZARA_QUIET_HOURS_END", "07:00")
MAX_AUTONOMOUS_RUNS_PER_DAY = int(os.getenv("ZARA_MAX_AUTONOMOUS_RUNS", "50"))
MAX_AUTONOMOUS_TOOL_CALLS_PER_DAY = int(os.getenv("ZARA_MAX_AUTONOMOUS_TOOL_CALLS", "100"))
MAX_AUTONOMOUS_RUNTIME_SECONDS_PER_DAY = int(os.getenv("ZARA_MAX_AUTONOMOUS_RUNTIME", "3600"))
MAX_TRIGGER_CHAIN_DEPTH = int(os.getenv("ZARA_MAX_TRIGGER_CHAIN_DEPTH", "5"))
TRIGGER_COOLDOWN_SECONDS = int(os.getenv("ZARA_TRIGGER_COOLDOWN", "60"))

# Phase 11: Advanced Goal Understanding, Planning & Adaptive Reasoning
MAX_PLAN_REVISIONS = int(os.getenv("ZARA_MAX_PLAN_REVISIONS", "5"))
MAX_REPLAN_DEPTH = int(os.getenv("ZARA_MAX_REPLAN_DEPTH", "3"))
MAX_ADAPTIVE_RETRIES = int(os.getenv("ZARA_MAX_ADAPTIVE_RETRIES", "3"))
PLANNING_DIR = LOGS_DIR / "planning"
PLANNING_DIR.mkdir(parents=True, exist_ok=True)
DECISIONS_LOG_FILE = LOGS_DIR / "decisions.jsonl"
MAX_CONTEXT_HISTORY_TOKENS = int(os.getenv("ZARA_MAX_CONTEXT_HISTORY_TOKENS", "4000"))

# Phase 12: Multimodal Perception & Unified World Model
WORLD_TTL_ACTIVE_APP = int(os.getenv("ZARA_WORLD_TTL_ACTIVE_APP", "10"))
WORLD_TTL_SCREEN = int(os.getenv("ZARA_WORLD_TTL_SCREEN", "15"))
WORLD_TTL_TERMINAL = int(os.getenv("ZARA_WORLD_TTL_TERMINAL", "30"))
WORLD_TTL_FILESYSTEM = int(os.getenv("ZARA_WORLD_TTL_FILESYSTEM", "60"))
WORLD_TTL_BROWSER = int(os.getenv("ZARA_WORLD_TTL_BROWSER", "120"))
WORLD_TTL_BLENDER = int(os.getenv("ZARA_WORLD_TTL_BLENDER", "60"))
WORLD_TTL_CYBER = int(os.getenv("ZARA_WORLD_TTL_CYBER", "60"))
WORLD_TTL_PROJECT = int(os.getenv("ZARA_WORLD_TTL_PROJECT", "30"))
WORLD_DIR = LOGS_DIR / "world"
WORLD_DIR.mkdir(parents=True, exist_ok=True)
WORLD_SNAPSHOTS_DIR = LOGS_DIR / "world_snapshots"
WORLD_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Phase 13: Unified Command Center & Control UI
UI_HOST = os.getenv("ZARA_UI_HOST", "127.0.0.1")
UI_PORT = int(os.getenv("ZARA_UI_PORT", "8420"))
UI_DIR = BASE_DIR / "ui"
UI_STATIC_DIR = UI_DIR / "static"
UI_STATIC_DIR.mkdir(parents=True, exist_ok=True)
UI_ENABLE_CORS = False

# Phase 15: Multi-Agent & Parallel Execution Parameters
MAX_PARALLEL_WORKERS = int(os.getenv("ZARA_MAX_PARALLEL_WORKERS", "4"))
MAX_WORKERS_PER_PROJECT = int(os.getenv("ZARA_MAX_WORKERS_PER_PROJECT", "4"))
MAX_PARALLEL_TOOL_CALLS = int(os.getenv("ZARA_MAX_PARALLEL_TOOL_CALLS", "8"))
MAX_PARALLEL_NETWORK_OPERATIONS = int(os.getenv("ZARA_MAX_PARALLEL_NETWORK_OPS", "4"))
MAX_PARALLEL_GUI_OPERATIONS = int(os.getenv("ZARA_MAX_PARALLEL_GUI_OPS", "1"))
WORKER_LOCK_TIMEOUT_SECONDS = float(os.getenv("ZARA_WORKER_LOCK_TIMEOUT", "30.0"))
WORKERS_DIR = LOGS_DIR / "workers"
WORKERS_DIR.mkdir(parents=True, exist_ok=True)

# Phase 16: AI Model Router, Provider Abstraction & Intelligent Failover
MODEL_ROUTER_ENABLED = os.getenv("ZARA_MODEL_ROUTER_ENABLED", "true").lower() in ("true", "1", "yes")
DEFAULT_MODEL = os.getenv("ZARA_DEFAULT_MODEL", "gemini-2.5-flash")
MODEL_REQUEST_TIMEOUT = float(os.getenv("ZARA_MODEL_REQUEST_TIMEOUT", "60.0"))
MAX_MODEL_RETRIES = int(os.getenv("ZARA_MAX_MODEL_RETRIES", "3"))
MAX_PROVIDER_FAILOVERS = int(os.getenv("ZARA_MAX_PROVIDER_FAILOVERS", "3"))
MODEL_HEALTH_TTL = float(os.getenv("ZARA_MODEL_HEALTH_TTL", "300.0"))
MODEL_SELECTION_MODE = os.getenv("ZARA_MODEL_SELECTION_MODE", "capability")
MAX_COST_PER_REQUEST = float(os.getenv("ZARA_MAX_COST_PER_REQUEST", "2.0"))
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("ZARA_CIRCUIT_BREAKER_THRESHOLD", "3"))
CIRCUIT_BREAKER_COOLDOWN_SECONDS = float(os.getenv("ZARA_CIRCUIT_BREAKER_COOLDOWN", "60.0"))
MODELS_DISCOVERY_CACHE_FILE = CONFIG_DIR / "models_cache.json"

