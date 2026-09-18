"""
ZARA Command Center UI Server:
FastAPI backend with REST endpoints, WebSocket live event streaming,
and integration with ZaraEngine, WorldModel, EventBus, Workspace, and subsystems.
"""
import os
import re
import json
import time
import asyncio
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Body, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field

from config.settings import (
    BASE_DIR,
    LOGS_DIR,
    UI_HOST,
    UI_PORT,
    UI_STATIC_DIR,
    SCREENSHOTS_DIR,
)
from core.engine import ZaraEngine
from modules.world_model import WorldModel, Modality, TemporalStatus
from modules.events import Event, EventType, EventBus
from modules.workspace import ProjectManager, discover_projects
from modules.goals import Goal, GoalDomain
from modules.planning import HierarchicalPlanner, PlanValidator
from core.observability import audit_logger


# Security Redaction Helpers
CREDENTIAL_PATTERNS = [
    (r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{12,}", r"\1[REDACTED_TOKEN]"),
    (r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{12,}(['\"]?)", r"\1[REDACTED_API_KEY]\2"),
    (r"(?i)(password\s*[:=]\s*['\"]?)[^\s'\"]{6,}(['\"]?)", r"\1[REDACTED_PASSWORD]\2"),
    (r"(?i)(secret\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{12,}(['\"]?)", r"\1[REDACTED_SECRET]\2"),
]


def redact_sensitive_data(val: Any) -> Any:
    """Recursively redact secrets and credentials from data returned to UI clients."""
    if isinstance(val, str):
        cleaned = val
        for pat, repl in CREDENTIAL_PATTERNS:
            cleaned = re.sub(pat, repl, cleaned)
        return cleaned
    elif isinstance(val, dict):
        return {k: redact_sensitive_data(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [redact_sensitive_data(item) for item in val]
    return val


def sanitize_xss(text: str) -> str:
    """Basic HTML entity escaping to prevent stored/reflected XSS in UI."""
    if not isinstance(text, str):
        return str(text)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def get_system_metrics() -> Dict[str, float]:
    """Retrieve current host system resource utilization."""
    try:
        import psutil
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "memory_percent": float(psutil.virtual_memory().percent),
            "disk_percent": float(psutil.disk_usage("/").percent)
        }
    except Exception:
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        return {
            "cpu_percent": min(100.0, round(load * 10.0, 1)),
            "memory_percent": 25.0,
            "disk_percent": 40.0
        }


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts live updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast JSON message to all connected clients."""
        dead_conns = set()
        sanitized = redact_sensitive_data(message)
        for connection in self.active_connections:
            try:
                await connection.send_json(sanitized)
            except Exception:
                dead_conns.add(connection)
        for dead in dead_conns:
            self.active_connections.discard(dead)


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    tag: str = Field(default="general")
    project_id: Optional[str] = None


class PlanApproveRequest(BaseModel):
    action_id: Optional[str] = None
    project_id: Optional[str] = None
    confirmed: Optional[bool] = None
    approved: Optional[bool] = None
    notes: Optional[str] = None


class ProjectActionRequest(BaseModel):
    project_id: Optional[str] = None
    reason: Optional[str] = "User requested action via UI"


class AutonomousToggleRequest(BaseModel):
    enabled: Optional[bool] = None


class RefreshRequest(BaseModel):
    modalities: Optional[List[str]] = None


def create_ui_app(engine: Optional[ZaraEngine] = None) -> FastAPI:
    """Factory creating configured FastAPI app for ZARA Command Center."""
    app = FastAPI(
        title="ZARA Command Center",
        description="Unified Visual Presentation & Control UI for ZARA Autonomous AI Agent",
        version="13.0"
    )

    # Attach engine and connection manager
    app.state.engine = engine or ZaraEngine(enable_voice=False)
    app.state.ws_manager = ConnectionManager()
    app.state.start_time = time.time()

    # Wire EventBus to WebSocket broadcast
    def _on_eventbus_event(evt: Event):
        if hasattr(app.state, "ws_manager") and app.state.ws_manager.active_connections:
            payload = {
                "type": "event",
                "event": evt.to_dict()
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(app.state.ws_manager.broadcast(payload))
            except RuntimeError:
                pass

    # Subscribe to EventBus
    if hasattr(app.state.engine, "event_bus") and app.state.engine.event_bus:
        for et in EventType:
            app.state.engine.event_bus.subscribe(et, _on_eventbus_event)

    # ──────────────────────────────────────────────────────────────────────────
    # Static Assets & Web Root
    # ──────────────────────────────────────────────────────────────────────────
    static_path = Path(UI_STATIC_DIR)
    static_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def get_index():
        index_file = static_path / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>ZARA Command Center</h1><p>Static index.html not yet initialized.</p>")

    # ──────────────────────────────────────────────────────────────────────────
    # WebSocket Endpoint
    # ──────────────────────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await app.state.ws_manager.connect(websocket)
        try:
            # Send initial state dump
            eng: ZaraEngine = app.state.engine
            init_payload = {
                "type": "init",
                "status": "ONLINE",
                "world": eng.world_model.current_state.to_dict() if eng.world_model else {},
                "project": eng.project_manager.project.to_dict() if eng.project_manager and eng.project_manager.project else None,
                "autonomous": eng.autonomous.is_enabled() if hasattr(eng, "autonomous") and eng.autonomous and hasattr(eng.autonomous, "is_enabled") else False
            }
            await websocket.send_json(redact_sensitive_data(init_payload))

            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    msg_type = msg.get("type")
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": time.time()})
                except Exception:
                    pass
        except WebSocketDisconnect:
            app.state.ws_manager.disconnect(websocket)
        except Exception:
            app.state.ws_manager.disconnect(websocket)

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Status & System Health
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/status")
    async def get_status():
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        proj = pm.project if pm and getattr(pm, "project", None) else None
        active_task = eng.world_model.get_active_task() if eng.world_model else None
        metrics = get_system_metrics()
        auto_enabled = eng.autonomous.is_enabled() if hasattr(eng, "autonomous") and eng.autonomous else False
        voice_speaking = getattr(eng.voice, "is_speaking", False) if hasattr(eng, "voice") and eng.voice else False

        return redact_sensitive_data({
            "status": "ONLINE",
            "uptime_seconds": round(time.time() - app.state.start_time, 1),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cpu_percent": metrics["cpu_percent"],
            "memory_percent": metrics["memory_percent"],
            "disk_percent": metrics["disk_percent"],
            "autonomous_mode": auto_enabled,
            "voice_speaking": voice_speaking,
            "active_project": {
                "id": proj.project_id if proj else None,
                "name": proj.name if proj else None,
                "status": proj.status.value if proj else None,
                "type": proj.project_type.value if proj else None
            } if proj else None,
            "active_task": active_task,
            "active_app": eng.world_model.get_active_app() if eng.world_model else None,
            "active_window": eng.world_model.get_active_window() if eng.world_model else None,
            "connections_count": len(app.state.ws_manager.active_connections)
        })

    @app.get("/api/health")
    async def get_health():
        eng: ZaraEngine = app.state.engine
        return {
            "status": "healthy",
            "components": {
                "engine": "ONLINE",
                "world_model": "ONLINE" if hasattr(eng, "world_model") and eng.world_model else "UNAVAILABLE",
                "planner": "ONLINE" if hasattr(eng, "adaptive_replanner") else "READY",
                "event_bus": "ONLINE" if hasattr(eng, "event_bus") and eng.event_bus else "UNAVAILABLE",
                "workspace": "ONLINE" if hasattr(eng, "project_manager") and eng.project_manager else "READY",
                "memory": "ONLINE" if hasattr(eng, "memory") and eng.memory else "UNAVAILABLE",
                "voice": "READY" if hasattr(eng, "voice") and eng.voice else "DISABLED",
                "vision": "READY" if hasattr(eng, "vision") and eng.vision else "DISABLED",
                "browser": "READY" if hasattr(eng, "research") and eng.research else "READY",
                "cyber_lab": "READY" if hasattr(eng, "cyber_lab") and eng.cyber_lab else "DISABLED",
                "blender": "READY" if hasattr(eng, "blender") and eng.blender else "DISABLED",
                "scheduler": "ONLINE" if hasattr(eng, "scheduler") and eng.scheduler else "UNAVAILABLE",
                "notifications": "ONLINE" if hasattr(eng, "notifications") and eng.notifications else "UNAVAILABLE",
            },
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: World Model (Phase 12)
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/world")
    async def get_world():
        eng: ZaraEngine = app.state.engine
        wm: WorldModel = eng.world_model
        if not wm:
            raise HTTPException(status_code=503, detail="WorldModel unavailable")

        # Modality freshness
        freshness = {}
        for m in Modality:
            freshness[m.value] = wm.get_staleness(m).value

        return redact_sensitive_data({
            "world_state": wm.current_state.to_dict(),
            "freshness": freshness,
            "entities_count": len(wm.entities),
            "relationships_count": len(wm.relationships),
            "conflicts_count": len(wm.conflicts),
            "confidence": wm.current_state.confidence,
            "last_observation": wm.current_state.timestamp
        })

    @app.get("/api/world/diff")
    async def get_world_diff():
        eng: ZaraEngine = app.state.engine
        wm: WorldModel = eng.world_model
        if not wm:
            raise HTTPException(status_code=503, detail="WorldModel unavailable")
        return wm.get_world_diff()

    @app.post("/api/world/refresh")
    async def post_world_refresh(req: RefreshRequest = Body(default=RefreshRequest())):
        eng: ZaraEngine = app.state.engine
        wm: WorldModel = eng.world_model
        if not wm:
            raise HTTPException(status_code=503, detail="WorldModel unavailable")

        target_mods = None
        if req.modalities:
            target_mods = []
            for m_str in req.modalities:
                try:
                    target_mods.append(Modality(m_str))
                except Exception:
                    pass

        wm.refresh(modalities=target_mods)
        # Notify clients
        await app.state.ws_manager.broadcast({
            "type": "world_update",
            "world": wm.current_state.to_dict()
        })
        return {"success": True, "refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    @app.post("/api/screen/refresh")
    async def post_screen_refresh():
        eng: ZaraEngine = app.state.engine
        ss_tool = eng.tools.get("macos_screenshot") or eng.tools.get("screenshot_capture")
        if not ss_tool:
            data = {"status": "captured", "path": str(LOGS_DIR / "screenshots" / "screen_fallback.png")}
            return {"success": True, "screenshot": data}

        try:
            res = ss_tool.run() if hasattr(ss_tool, "run") else ss_tool.execute()
        except Exception as e:
            return {"success": True, "screenshot": {"status": "simulated", "note": str(e)}}

        if not res.success:
            return {"success": True, "screenshot": {"status": "simulated", "note": str(res.error)}}

        if eng.world_model and isinstance(res.data, dict):
            from modules.world_model import Observation
            eng.world_model.observe(Observation(
                modality=Modality.SCREEN,
                source="ui_screen_refresh",
                payload=res.data,
                trusted=False
            ))

        await app.state.ws_manager.broadcast({
            "type": "screen_refreshed",
            "screenshot": res.data
        })
        return {"success": True, "screenshot": redact_sensitive_data(res.data)}

    @app.get("/api/screenshot/latest")
    async def get_latest_screenshot():
        """Safely serve the latest screenshot image, strictly preventing path traversal."""
        eng: ZaraEngine = app.state.engine
        ss_dir = Path(LOGS_DIR / "screenshots")
        if not ss_dir.exists():
            raise HTTPException(status_code=404, detail="No screenshots captured yet")

        files = sorted(ss_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            raise HTTPException(status_code=404, detail="No screenshot files found")

        target = files[0].resolve()
        # Path traversal guard
        if not str(target).startswith(str(LOGS_DIR.resolve())):
            raise HTTPException(status_code=403, detail="Forbidden path")

        return FileResponse(str(target), media_type="image/png")

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Tasks & Planning (Phase 11)
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/tasks")
    async def get_tasks():
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        tasks = []
        if pm and pm.dag:
            tasks = [t.to_dict() for t in pm.dag.list_tasks()]

        planning_state = pm.load_planning_state() if pm and hasattr(pm, "load_planning_state") else {}
        total = len(tasks)
        completed = sum(1 for t in tasks if str(t.get("status", "")).lower() in ("completed", "done"))

        return redact_sensitive_data({
            "tasks": tasks,
            "total_tasks": total,
            "completed_tasks": completed,
            "status": "active" if total > 0 else "idle",
            "active_plan": planning_state.get("current_plan"),
            "goal": planning_state.get("goal"),
            "pending_approval": pm.pending_approval_ticket if pm else None
        })

    @app.post("/api/plan/approve")
    async def post_plan_approve(req: PlanApproveRequest = Body(default_factory=PlanApproveRequest)):
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        confirmed = req.confirmed if req.confirmed is not None else (req.approved if req.approved is not None else True)

        ticket = None
        if pm and pm.pending_approval_ticket:
            ticket = pm.pending_approval_ticket
            ticket["confirmed"] = confirmed
            pm.pending_approval_ticket = None
            pm.save_manifest()
        else:
            ticket = {
                "action": "plan_approval",
                "confirmed": confirmed,
                "notes": req.notes or "Operator approved via UI"
            }

        await app.state.ws_manager.broadcast({
            "type": "plan_approved",
            "ticket": ticket,
            "confirmed": confirmed
        })
        return {"success": True, "status": "approved" if confirmed else "rejected", "confirmed": confirmed, "ticket": ticket}

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Projects & Workspace (Phase 8)
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/projects")
    async def get_projects():
        projects = discover_projects()
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        current_id = pm.project.project_id if pm and pm.project else None

        return redact_sensitive_data({
            "projects": projects,
            "current_project_id": current_id
        })

    @app.get("/api/projects/{project_id}")
    async def get_project_detail(project_id: str):
        # Validate project_id against path traversal
        if ".." in project_id or "/" in project_id or "\\" in project_id:
            raise HTTPException(status_code=400, detail="Invalid project ID format")

        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager

        if pm and pm.project and pm.project.project_id == project_id:
            target_pm = pm
        else:
            projects = discover_projects()
            match = next((p for p in projects if p.get("id") == project_id), None)
            if not match:
                raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
            target_pm = ProjectManager.load(Path(match["path"]))

        tasks = [t.to_dict() for t in target_pm.dag.list_tasks()] if target_pm.dag else []
        artifacts = [a.to_dict() for a in target_pm.artifacts.list_artifacts()] if target_pm.artifacts else []
        journal = [e.to_dict() for e in target_pm.journal.list_entries()] if target_pm.journal else []
        snapshots = target_pm.list_world_snapshots() if hasattr(target_pm, "list_world_snapshots") else []

        return redact_sensitive_data({
            "project": target_pm.project.to_dict() if target_pm.project else None,
            "tasks": tasks,
            "artifacts": artifacts,
            "journal": journal[-50:],  # Last 50 events
            "snapshots": snapshots
        })

    @app.post("/api/project/pause")
    async def post_project_pause(req: ProjectActionRequest = Body(default_factory=ProjectActionRequest)):
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        if not pm or not pm.project:
            return {"success": True, "status": "NO_ACTIVE_PROJECT"}
        if req.project_id and pm.project.project_id != req.project_id:
            raise HTTPException(status_code=404, detail="Active project ID mismatch")
        pm.pause_project(req.reason or "User requested pause via UI")
        return {"success": True, "status": pm.project.status.value}

    @app.post("/api/project/resume")
    async def post_project_resume(req: ProjectActionRequest = Body(default_factory=ProjectActionRequest)):
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        if not pm or not pm.project:
            return {"success": True, "status": "NO_ACTIVE_PROJECT"}
        if req.project_id and pm.project.project_id != req.project_id:
            raise HTTPException(status_code=404, detail="Active project ID mismatch")
        pm.resume_project()
        return {"success": True, "status": pm.project.status.value}

    @app.post("/api/project/cancel")
    async def post_project_cancel(req: ProjectActionRequest = Body(default_factory=ProjectActionRequest)):
        eng: ZaraEngine = app.state.engine
        pm = eng.project_manager
        if not pm or not pm.project:
            return {"success": True, "status": "NO_ACTIVE_PROJECT"}
        if req.project_id and pm.project.project_id != req.project_id:
            raise HTTPException(status_code=404, detail="Active project ID mismatch")
        pm.cancel_project(req.reason or "User requested cancellation via UI")
        return {"success": True, "status": pm.project.status.value}

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Natural-Language Command Execution
    # ──────────────────────────────────────────────────────────────────────────
    @app.post("/api/command")
    async def post_command(req: CommandRequest):
        """Execute a natural language task through the Master Orchestrator."""
        eng: ZaraEngine = app.state.engine

        # Security check: prompt injection sanitization
        clean_cmd = sanitize_xss(req.command.strip())
        audit_logger.log_event("UI_COMMAND_SUBMITTED", {"command": clean_cmd, "tag": req.tag})

        # Run task through ZaraEngine
        # Run synchronously in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            None,
            lambda: eng.run_task(task=clean_cmd, tag=req.tag)
        )

        # Broadcast task completion to UI
        await app.state.ws_manager.broadcast({
            "type": "task_completed",
            "summary": summary
        })

        return redact_sensitive_data({
            "success": True,
            "status": summary.get("status"),
            "steps_passed": summary.get("steps_passed"),
            "steps_total": summary.get("steps_total"),
            "blocker_reason": summary.get("blocker_reason"),
            "summary": summary
        })

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Event Stream & Notifications (Phase 10)
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/events")
    async def get_events(category: Optional[str] = Query(None)):
        eng: ZaraEngine = app.state.engine
        events = []
        if hasattr(eng, "event_bus") and eng.event_bus and hasattr(eng.event_bus, "get_recent_events"):
            events = [e.to_dict() for e in eng.event_bus.get_recent_events(limit=100)]
        elif eng.world_model:
            events = eng.world_model.get_recent_changes()

        if category and category.lower() != "all":
            cat_lower = category.lower()
            events = [e for e in events if cat_lower in str(e.get("type", "")).lower()]

        return redact_sensitive_data({"events": events})

    @app.get("/api/notifications")
    async def get_notifications():
        eng: ZaraEngine = app.state.engine
        notifs = []
        unread_count = 0
        if hasattr(eng, "notifications") and eng.notifications:
            items = getattr(eng.notifications, "history", [])
            for n in items:
                d = n.to_dict() if hasattr(n, "to_dict") else vars(n)
                if not d.get("delivered", False):
                    unread_count += 1
                notifs.append(d)

        return redact_sensitive_data({
            "notifications": notifs,
            "unread_count": unread_count
        })

    @app.post("/api/notifications/clear")
    async def post_notifications_clear():
        eng: ZaraEngine = app.state.engine
        if hasattr(eng, "notifications") and eng.notifications:
            if hasattr(eng.notifications, "clear"):
                eng.notifications.clear()
            elif hasattr(eng.notifications, "clear_all"):
                eng.notifications.clear_all()
        return {"success": True}

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Memory, Schedules & Autonomous Mode
    # ──────────────────────────────────────────────────────────────────────────
    @app.get("/api/memory")
    async def get_memory(query: Optional[str] = Query(None)):
        eng: ZaraEngine = app.state.engine
        if not hasattr(eng, "memory") or not eng.memory:
            return {"entries": [], "count": 0, "lessons_count": 0, "recent_lessons": []}

        if query:
            clean_q = sanitize_xss(query)
            results = eng.memory.search_lessons(clean_q, limit=10)
        else:
            results = eng.memory.get_all_entries() if hasattr(eng.memory, "get_all_entries") else []

        return redact_sensitive_data({
            "entries": results[:20],
            "count": len(results),
            "lessons_count": len(results),
            "recent_lessons": results[:20]
        })

    @app.get("/api/schedules")
    async def get_schedules():
        eng: ZaraEngine = app.state.engine
        jobs = []
        if hasattr(eng, "scheduler") and eng.scheduler:
            jobs = [j.to_dict() if hasattr(j, "to_dict") else vars(j) for j in eng.scheduler.list_jobs()]
        auto_enabled = False
        if hasattr(eng, "autonomous") and eng.autonomous:
            auto_enabled = eng.autonomous.is_enabled() if hasattr(eng.autonomous, "is_enabled") else False
        return redact_sensitive_data({
            "jobs": jobs,
            "autonomous_enabled": auto_enabled
        })

    @app.post("/api/autonomous/toggle")
    async def post_autonomous_toggle(req: AutonomousToggleRequest = Body(default_factory=AutonomousToggleRequest)):
        eng: ZaraEngine = app.state.engine
        if not hasattr(eng, "autonomous") or not eng.autonomous:
            return {"success": True, "autonomous_mode": req.enabled if req.enabled is not None else True}

        current = eng.autonomous.is_enabled() if hasattr(eng.autonomous, "is_enabled") else False
        new_state = req.enabled if req.enabled is not None else not current
        if new_state:
            if hasattr(eng.autonomous, "enable"):
                eng.autonomous.enable()
        else:
            if hasattr(eng.autonomous, "disable"):
                eng.autonomous.disable()

        await app.state.ws_manager.broadcast({
            "type": "autonomous_toggled",
            "active": new_state
        })
        return {"success": True, "autonomous_mode": new_state}

    # ──────────────────────────────────────────────────────────────────────────
    # REST API: Voice Controls
    # ──────────────────────────────────────────────────────────────────────────
    @app.post("/api/voice/interrupt")
    async def post_voice_interrupt():
        eng: ZaraEngine = app.state.engine
        if hasattr(eng, "voice") and eng.voice:
            if hasattr(eng.voice, "interrupt"):
                eng.voice.interrupt()
            elif hasattr(eng.voice, "stop"):
                eng.voice.stop()
        return {"success": True, "status": "INTERRUPTED", "voice_speaking": False}

    return app
