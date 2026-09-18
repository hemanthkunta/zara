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

# Ensure runtime directories exist
for directory in (MEMORY_DIR, JOB_QUEUE_DIR, CONFIG_DIR, LOGS_DIR, CHECKPOINTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Risk Levels for Human Confirmation System
class RiskLevel(str, Enum):
    LOW = "LOW"            # Read-only operations, safe inspects
    MEDIUM = "MEDIUM"      # Normal workspace file changes & test runs
    HIGH = "HIGH"          # Destructive ops, system-level execution, git push
    CRITICAL = "CRITICAL"  # Operations requiring explicit double-confirmation or outside default scope

# Loop & Safety parameters
MAX_DIAGNOSE_RETRIES = int(os.getenv("ZARA_MAX_RETRIES", "5"))
COMMAND_TIMEOUT_SECONDS = int(os.getenv("ZARA_CMD_TIMEOUT", "60"))
SANDBOX_DOCKER_IMAGE = os.getenv("ZARA_DOCKER_IMAGE", "python:3.11-slim")
SANDBOX_MEMORY_LIMIT = os.getenv("ZARA_SANDBOX_MEM", "512m")
SANDBOX_CPU_LIMIT = os.getenv("ZARA_SANDBOX_CPU", "1.0")

# Voice Parameters
ENABLE_VOICE = os.getenv("ZARA_ENABLE_VOICE", "true").lower() in ("true", "1", "yes")
VOICE_NAME = os.getenv("ZARA_VOICE_NAME", "Samantha")  # Default macOS female voice
VOICE_RATE = int(os.getenv("ZARA_VOICE_RATE", "190"))

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
