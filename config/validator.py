"""
ZARA Configuration Validator & Hardening Module (Phase 18).
Validates settings types, bounds, security constraints, and provides sanitized configuration snapshots.
"""
from pathlib import Path
from typing import Dict, Any, List, Tuple, Set, Optional
from dataclasses import dataclass, field
import os

from config.settings import (
    BASE_DIR, CONFIG_DIR, LOGS_DIR, MEMORY_DIR, CHECKPOINTS_DIR, BACKUPS_DIR,
    MAX_STEPS, MAX_RETRIES_PER_STEP, MAX_TOTAL_RETRIES, MAX_EXECUTION_TIME_SECONDS,
    COMMAND_TIMEOUT_SECONDS, UI_PORT, UI_HOST, MAX_PARALLEL_WORKERS,
    WORKER_LOCK_TIMEOUT_SECONDS, MODEL_REQUEST_TIMEOUT,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    STRATEGY_MIN_EVIDENCE_THRESHOLD, STRATEGY_VALIDATION_SUCCESS_RATE,
    CRITICAL_FILES_BLOCKLIST, SECURITY_SCOPE_FILE
)
from core.observability import audit_logger


@dataclass
class ConfigValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sanitized_config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "sanitized_config": self.sanitized_config
        }


class ConfigValidator:
    """Validates runtime configuration bounds, security constraints, and sanity."""

    REQUIRED_CRITICAL_FILES = {
        "modules/cyber_lab.py",
        "config/security_scope.json",
        "tools/registry.py",
        "core/observability.py",
        "modules/security.py",
        "config/settings.py",
    }

    @classmethod
    def validate(cls, config_overrides: Optional[Dict[str, Any]] = None, overrides: Optional[Dict[str, Any]] = None) -> ConfigValidationResult:
        """Validate all active configuration settings against acceptable security and operational bounds."""
        errors: List[str] = []
        warnings: List[str] = []

        eff_overrides = {}
        if config_overrides: eff_overrides.update(config_overrides)
        if overrides: eff_overrides.update(overrides)

        cfg = cls._gather_config(eff_overrides)

        # 1. Integer bounds validation
        int_bounds: Dict[str, Tuple[int, int]] = {
            "MAX_STEPS": (1, 100),
            "MAX_RETRIES_PER_STEP": (0, 10),
            "MAX_TOTAL_RETRIES": (1, 50),
            "MAX_EXECUTION_TIME_SECONDS": (10, 7200),
            "COMMAND_TIMEOUT_SECONDS": (5, 600),
            "UI_PORT": (1024, 65535),
            "MAX_PARALLEL_WORKERS": (1, 32),
            "CIRCUIT_BREAKER_FAILURE_THRESHOLD": (1, 20),
            "STRATEGY_MIN_EVIDENCE_THRESHOLD": (1, 50),
        }

        for key, (min_v, max_v) in int_bounds.items():
            val = cfg.get(key)
            if val is None or not isinstance(val, int):
                errors.append(f"Invalid type for {key}: expected integer, got {type(val).__name__}")
            elif val < min_v or val > max_v:
                errors.append(f"{key} value {val} out of bounds [{min_v}, {max_v}]")

        # 2. Float bounds validation
        float_bounds: Dict[str, Tuple[float, float]] = {
            "WORKER_LOCK_TIMEOUT_SECONDS": (1.0, 300.0),
            "MODEL_REQUEST_TIMEOUT": (1.0, 600.0),
            "CIRCUIT_BREAKER_COOLDOWN_SECONDS": (1.0, 3600.0),
            "STRATEGY_VALIDATION_SUCCESS_RATE": (0.1, 1.0),
        }

        for key, (min_v, max_v) in float_bounds.items():
            val = cfg.get(key)
            if val is None or not isinstance(val, (int, float)):
                errors.append(f"Invalid type for {key}: expected float, got {type(val).__name__}")
            elif float(val) < min_v or float(val) > max_v:
                errors.append(f"{key} value {val} out of bounds [{min_v}, {max_v}]")

        # 3. Security Blocklist validation
        blocklist = cfg.get("CRITICAL_FILES_BLOCKLIST")
        if not isinstance(blocklist, (set, list)):
            errors.append("CRITICAL_FILES_BLOCKLIST must be a set or list")
        else:
            missing = cls.REQUIRED_CRITICAL_FILES - set(blocklist)
            if missing:
                errors.append(f"CRITICAL_FILES_BLOCKLIST is missing required critical files: {missing}")

        # 4. Security Scope File validation
        scope_file = Path(cfg.get("SECURITY_SCOPE_FILE", SECURITY_SCOPE_FILE))
        if not scope_file.exists():
            warnings.append(f"Security scope file not found at {scope_file}")

        # 5. UI Host validation
        host = cfg.get("UI_HOST", "127.0.0.1")
        if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            warnings.append(f"UI_HOST set to non-standard address: {host}")
        if host == "0.0.0.0":
            warnings.append("UI_HOST bound to 0.0.0.0 (publicly accessible if network allows)")

        # 6. Sanitize configuration for audit and display (strip any sensitive env keys)
        sanitized = cls._sanitize_config(cfg)

        is_valid = len(errors) == 0
        return ConfigValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            sanitized_config=sanitized
        )

    @classmethod
    def _gather_config(cls, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = {
            "MAX_STEPS": MAX_STEPS,
            "MAX_RETRIES_PER_STEP": MAX_RETRIES_PER_STEP,
            "MAX_TOTAL_RETRIES": MAX_TOTAL_RETRIES,
            "MAX_EXECUTION_TIME_SECONDS": MAX_EXECUTION_TIME_SECONDS,
            "COMMAND_TIMEOUT_SECONDS": COMMAND_TIMEOUT_SECONDS,
            "UI_PORT": UI_PORT,
            "UI_HOST": UI_HOST,
            "MAX_PARALLEL_WORKERS": MAX_PARALLEL_WORKERS,
            "WORKER_LOCK_TIMEOUT_SECONDS": WORKER_LOCK_TIMEOUT_SECONDS,
            "MODEL_REQUEST_TIMEOUT": MODEL_REQUEST_TIMEOUT,
            "CIRCUIT_BREAKER_FAILURE_THRESHOLD": CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            "CIRCUIT_BREAKER_COOLDOWN_SECONDS": CIRCUIT_BREAKER_COOLDOWN_SECONDS,
            "STRATEGY_MIN_EVIDENCE_THRESHOLD": STRATEGY_MIN_EVIDENCE_THRESHOLD,
            "STRATEGY_VALIDATION_SUCCESS_RATE": STRATEGY_VALIDATION_SUCCESS_RATE,
            "CRITICAL_FILES_BLOCKLIST": set(CRITICAL_FILES_BLOCKLIST),
            "SECURITY_SCOPE_FILE": str(SECURITY_SCOPE_FILE),
        }
        if overrides:
            cfg.update(overrides)
        return cfg

    @classmethod
    def _sanitize_config(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Produce safe display dictionary without secrets."""
        sanitized = {}
        for k, v in cfg.items():
            if any(secret_term in k.lower() for secret_term in ("key", "secret", "token", "password", "auth")):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, set):
                sanitized[k] = sorted(list(v))
            else:
                sanitized[k] = v
        return sanitized
