"""
ZARA Unified Lifecycle Management Module (Phase 18).
Coordinates deterministic application lifecycle:
STARTUP -> CONFIG_VALIDATION -> DEPENDENCY_VALIDATION -> SUBSYSTEM_INIT -> HEALTH_CHECK -> READY -> RUNNING -> SHUTDOWN.
Ensures comprehensive resource cleanup across repeated startup/shutdown cycles.
"""
import time
import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass, field

from config.validator import ConfigValidator
from core.doctor import EnvironmentDoctor
from core.health import GlobalHealthService, SubsystemStatus
from core.persistence import cleanup_temp_files
from core.observability import audit_logger


class LifecycleState(str, Enum):
    STARTUP = "STARTUP"
    CONFIG_VALIDATION = "CONFIG_VALIDATION"
    DEPENDENCY_VALIDATION = "DEPENDENCY_VALIDATION"
    SUBSYSTEM_INIT = "SUBSYSTEM_INIT"
    HEALTH_CHECK = "HEALTH_CHECK"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    TERMINATED = "TERMINATED"


@dataclass
class LifecycleStatus:
    state: LifecycleState
    uptime_seconds: float = 0.0
    started_at: Optional[str] = None
    last_health_status: Optional[str] = None
    warnings: list = field(default_factory=list)


class ZaraLifecycleManager:
    """Orchestrates deterministic startup, health checks, execution states, and teardown."""

    def __init__(self, engine: Optional[Any] = None):
        self.engine = engine
        self.state: LifecycleState = LifecycleState.STARTUP
        self._started_at_time: Optional[float] = None
        self._started_at_iso: Optional[str] = None
        self.warnings: list = []
        self.health_service = GlobalHealthService(engine=engine)

    def startup(self) -> bool:
        """Execute ordered startup sequence and transition to READY or DEGRADED."""
        self._started_at_time = time.time()
        self._started_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.state = LifecycleState.STARTUP
        audit_logger.log_event(event_type="lifecycle_startup_started", action="startup")

        # 1. Configuration Validation
        self.state = LifecycleState.CONFIG_VALIDATION
        cfg_res = ConfigValidator.validate()
        if not cfg_res.is_valid:
            self.warnings.extend(cfg_res.errors)
            audit_logger.log_event(
                event_type="lifecycle_config_failed",
                action="validate_config",
                error="; ".join(cfg_res.errors)
            )

        # 2. Dependency Diagnostics
        self.state = LifecycleState.DEPENDENCY_VALIDATION
        doc_rep = EnvironmentDoctor.run_diagnostics()
        if not doc_rep.can_run_core:
            self.warnings.append("Core environment dependencies missing")

        # 3. Subsystem Initialization Verification
        self.state = LifecycleState.SUBSYSTEM_INIT
        if self.engine:
            self.health_service.set_engine(self.engine)

        # 4. Clean up lingering temporary files
        if self.engine and hasattr(self.engine, "workspace_root"):
            cleanup_temp_files(self.engine.workspace_root / ".zara")
            cleanup_temp_files(self.engine.workspace_root)

        # 5. Global Health Check
        self.state = LifecycleState.HEALTH_CHECK
        health_rep = self.health_service.check_all()

        if health_rep.overall == SubsystemStatus.FAILED:
            self.state = LifecycleState.DEGRADED
            return False
        elif health_rep.overall == SubsystemStatus.DEGRADED:
            self.state = LifecycleState.DEGRADED
        else:
            self.state = LifecycleState.READY

        audit_logger.log_event(
            event_type="lifecycle_startup_completed",
            action="startup",
            extra={"final_state": self.state.value, "overall_health": health_rep.overall.value}
        )
        return True

    def shutdown(self) -> None:
        """Execute ordered, deterministic shutdown and release all subsystem resources."""
        self.state = LifecycleState.SHUTTING_DOWN
        audit_logger.log_event(event_type="lifecycle_shutdown_started", action="shutdown")

        eng = self.engine
        if eng:
            # Halt scheduler
            if hasattr(eng, "scheduler") and eng.scheduler:
                try:
                    if hasattr(eng.scheduler, "stop"):
                        eng.scheduler.stop()
                except Exception:
                    pass

            # Close multi-agent orchestrator & workers
            if hasattr(eng, "workstream_orchestrator") and eng.workstream_orchestrator:
                try:
                    eng.workstream_orchestrator.close()
                except Exception:
                    pass

            # Clear resource locks
            if hasattr(eng, "resource_manager") and eng.resource_manager:
                try:
                    eng.resource_manager.clear()
                except Exception:
                    pass

            # Close AI Model Router
            if hasattr(eng, "model_router") and eng.model_router:
                try:
                    eng.model_router.close()
                except Exception:
                    pass

            # Close Evaluation Manager
            if hasattr(eng, "evaluation_manager") and eng.evaluation_manager:
                try:
                    eng.evaluation_manager.close()
                except Exception:
                    pass

            # Close Memory Store connections
            if hasattr(eng, "memory") and eng.memory:
                try:
                    if hasattr(eng.memory, "close"):
                        eng.memory.close()
                except Exception:
                    pass

            # Close Research Engine sessions
            if hasattr(eng, "research") and eng.research:
                try:
                    if hasattr(eng.research, "close"):
                        eng.research.close()
                except Exception:
                    pass

            # Clean up temporary files
            if hasattr(eng, "workspace_root"):
                try:
                    cleanup_temp_files(eng.workspace_root / ".zara")
                except Exception:
                    pass

        self.state = LifecycleState.TERMINATED
        audit_logger.log_event(event_type="lifecycle_shutdown_completed", action="shutdown")

    def get_status(self) -> LifecycleStatus:
        uptime = (time.time() - self._started_at_time) if self._started_at_time else 0.0
        return LifecycleStatus(
            state=self.state,
            uptime_seconds=round(uptime, 2),
            started_at=self._started_at_iso,
            warnings=self.warnings
        )
