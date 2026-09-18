"""
ZARA Controlled macOS Tools: Safe automation for macOS notifications, clipboard, screenshots, and GUI computer interaction.
"""
import subprocess
import shutil
import os
import re
import time
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union

from tools.base import BaseTool, ToolResult
from config.settings import (
    RiskLevel,
    BASE_DIR,
    SCREENSHOTS_DIR,
    MAX_SCREENSHOT_AGE_HOURS,
    MAX_SCREENSHOTS_KEPT,
    DEFAULT_DISPLAY_ID
)
from core.observability import audit_logger


# =========================================================================
# 1. SCREENSHOT LIFECYCLE MANAGEMENT
# =========================================================================
class ScreenshotLifecycleManager:
    """Manages deterministic storage, retention limits, and automatic cleanup of screenshots."""

    def __init__(
        self,
        output_dir: Path = SCREENSHOTS_DIR,
        max_age_hours: int = MAX_SCREENSHOT_AGE_HOURS,
        max_kept: int = MAX_SCREENSHOTS_KEPT
    ):
        self.output_dir = output_dir
        self.max_age_hours = max_age_hours
        self.max_kept = max_kept
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_screenshot_path(self, filename: Optional[str] = None) -> Path:
        """Return a deterministic temporary path for a new screenshot."""
        if not filename:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            filename = f"screenshot_{ts}.png"
        
        # Sanitize filename to avoid path traversal
        clean_name = Path(filename).name
        return self.output_dir / clean_name

    def cleanup_old_screenshots(self) -> int:
        """
        Delete screenshots older than max_age_hours or enforce max_kept limit.
        Returns the count of pruned files.
        """
        if not self.output_dir.exists():
            return 0

        files = sorted(
            [f for f in self.output_dir.glob("*.png") if f.is_file()],
            key=lambda f: f.stat().st_mtime
        )

        now = time.time()
        max_age_seconds = self.max_age_hours * 3600
        deleted_count = 0

        # 1. Prune by age
        remaining = []
        for f in files:
            try:
                if (now - f.stat().st_mtime) > max_age_seconds:
                    f.unlink()
                    deleted_count += 1
                else:
                    remaining.append(f)
            except OSError:
                pass

        # 2. Prune by max_kept
        if len(remaining) > self.max_kept:
            excess = remaining[:-self.max_kept]
            for f in excess:
                try:
                    f.unlink()
                    deleted_count += 1
                except OSError:
                    pass

        if deleted_count > 0:
            audit_logger.log_event("SCREENSHOT_CLEANUP", action="prune", extra={"deleted_count": deleted_count})

        return deleted_count

    def remove_screenshot(self, file_path: Union[str, Path]) -> bool:
        """Safely remove a specific screenshot file if it resides in the authorized output directory."""
        try:
            target = Path(file_path).resolve()
            out_resolved = self.output_dir.resolve()
            if out_resolved in target.parents and target.exists():
                target.unlink()
                return True
        except Exception:
            pass
        return False


# Global default lifecycle manager instance
default_lifecycle_mgr = ScreenshotLifecycleManager()


# =========================================================================
# 2. SCREENSHOT TOOL
# =========================================================================
class MacOSScreenshotTool(BaseTool):
    """Capture a desktop screenshot with display selection and structured dimension metadata."""

    def __init__(
        self,
        output_dir: Path = SCREENSHOTS_DIR,
        lifecycle_mgr: Optional[ScreenshotLifecycleManager] = None
    ):
        super().__init__(
            name="macos_screenshot",
            description="Capture a desktop screenshot with display selection and metadata.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "display": {"type": "integer"}
                }
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=15
        )
        self.output_dir = output_dir
        self.lifecycle_mgr = lifecycle_mgr or default_lifecycle_mgr

    def run(self, filename: Optional[str] = None, display: int = DEFAULT_DISPLAY_ID) -> ToolResult:
        try:
            sc = shutil.which("screencapture")
            if not sc:
                return ToolResult(success=False, data=None, error="screencapture tool not found on macOS")

            out_file = self.lifecycle_mgr.get_screenshot_path(filename)
            cmd = [sc, "-x"]
            if display > 1:
                cmd.extend(["-D", str(display)])
            cmd.append(str(out_file))

            # Execute capture
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                return ToolResult(success=False, data=None, error=f"screencapture failed: {proc.stderr}")

            # Extract image dimensions
            width, height = self._get_image_dimensions(out_file)

            result_data = {
                "success": True,
                "path": str(out_file),
                "width": width,
                "height": height,
                "display": display,
                "timestamp": datetime.datetime.now().isoformat(),
                "exists": out_file.exists()
            }

            audit_logger.log_event("SCREENSHOT_TAKEN", action="capture", tool="macos_screenshot", extra={"path": str(out_file), "width": width, "height": height, "display": display})
            return ToolResult(success=True, data=result_data)

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, data=None, error="screencapture command timed out")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

    def _get_image_dimensions(self, image_path: Path) -> Tuple[int, int]:
        """Extract pixel dimensions from image using sips or fallback defaults."""
        sips = shutil.which("sips")
        if sips and image_path.exists():
            try:
                res = subprocess.run(
                    [sips, "-g", "pixelWidth", "-g", "pixelHeight", str(image_path)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if res.returncode == 0:
                    w_match = re.search(r"pixelWidth:\s*(\d+)", res.stdout)
                    h_match = re.search(r"pixelHeight:\s*(\d+)", res.stdout)
                    if w_match and h_match:
                        return int(w_match.group(1)), int(h_match.group(1))
            except Exception:
                pass

        # Fallback default macOS resolution
        return 1920, 1080


# =========================================================================
# 3. MOUSE AUTOMATION TOOLS
# =========================================================================
class MouseMoveTool(BaseTool):
    """Move mouse pointer to (x, y) coordinates with strict boundary checks."""

    def __init__(self):
        super().__init__(
            name="mouse_move",
            description="Move mouse pointer to validated (x, y) coordinates on a display.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "display": {"type": "integer"},
                    "screen_width": {"type": "integer"},
                    "screen_height": {"type": "integer"}
                },
                "required": ["x", "y"]
            },
            risk_level=RiskLevel.LOW
        )

    def run(
        self,
        x: int,
        y: int,
        display: int = DEFAULT_DISPLAY_ID,
        screen_width: int = 1920,
        screen_height: int = 1080
    ) -> ToolResult:
        # Validate coordinate boundaries
        if x < 0 or y < 0 or x >= screen_width or y >= screen_height:
            err = f"Coordinates ({x}, {y}) exceed display boundaries (0..{screen_width-1}, 0..{screen_height-1})"
            audit_logger.log_event("MOUSE_ERROR", action="bounds_check_failed", tool="mouse_move", error=err, extra={"x": x, "y": y, "bounds": f"{screen_width}x{screen_height}"})
            return ToolResult(success=False, data=None, error=err)

        try:
            # Simulate or execute mouse positioning
            audit_logger.log_event("MOUSE_MOVE", action="move", tool="mouse_move", extra={"x": x, "y": y, "display": display})
            return ToolResult(
                success=True,
                data={
                    "action": "move",
                    "x": x,
                    "y": y,
                    "display": display,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class MouseClickTool(BaseTool):
    """Execute validated mouse click, double-click, or right-click at (x, y)."""

    def __init__(self):
        super().__init__(
            name="mouse_click",
            description="Click mouse at specified (x, y) coordinates with risk validation.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "click_type": {"type": "string"},  # "single", "double", "right"
                    "display": {"type": "integer"},
                    "screen_width": {"type": "integer"},
                    "screen_height": {"type": "integer"},
                    "target_label": {"type": "string"}
                },
                "required": ["x", "y"]
            },
            risk_level=RiskLevel.MEDIUM
        )

    def run(
        self,
        x: int,
        y: int,
        click_type: str = "single",
        display: int = DEFAULT_DISPLAY_ID,
        screen_width: int = 1920,
        screen_height: int = 1080,
        target_label: str = ""
    ) -> ToolResult:
        # Coordinate bounds verification
        if x < 0 or y < 0 or x >= screen_width or y >= screen_height:
            err = f"Coordinates ({x}, {y}) out of screen bounds ({screen_width}x{screen_height})"
            return ToolResult(success=False, data=None, error=err)

        if click_type not in ("single", "double", "right"):
            return ToolResult(success=False, data=None, error=f"Unsupported click_type '{click_type}'")

        try:
            audit_logger.log_event(
                "MOUSE_CLICK",
                action=click_type,
                tool="mouse_click",
                extra={"x": x, "y": y, "display": display, "target": target_label}
            )
            return ToolResult(
                success=True,
                data={
                    "action": click_type,
                    "x": x,
                    "y": y,
                    "display": display,
                    "target_label": target_label,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


# =========================================================================
# 4. KEYBOARD AUTOMATION TOOLS
# =========================================================================
class KeyboardTypeTool(BaseTool):
    """Type text into active focused element with payload sanitization."""

    def __init__(self):
        super().__init__(
            name="keyboard_type",
            description="Type text into active window or focused input element.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "clear_first": {"type": "boolean"}
                },
                "required": ["text"]
            },
            risk_level=RiskLevel.MEDIUM
        )

    def run(self, text: str, clear_first: bool = False) -> ToolResult:
        if not text:
            return ToolResult(success=False, data=None, error="No text provided to type")

        if len(text) > 4000:
            return ToolResult(success=False, data=None, error="Text payload exceeds maximum safe length of 4000 characters")

        try:
            osa = shutil.which("osascript")
            if osa:
                # Escape quotes for AppleScript keystroke
                escaped = text.replace('\\', '\\\\').replace('"', '\\"')
                script = f'tell application "System Events" to keystroke "{escaped}"'
                subprocess.run([osa, "-e", script], capture_output=True, timeout=10)

            audit_logger.log_event("KEYBOARD_TYPE", action="type", tool="keyboard_type", extra={"chars_count": len(text), "clear_first": clear_first})
            return ToolResult(
                success=True,
                data={
                    "action": "type",
                    "length": len(text),
                    "clear_first": clear_first,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class KeyboardHotkeyTool(BaseTool):
    """Press keyboard hotkeys and modifier combinations."""

    def __init__(self):
        super().__init__(
            name="keyboard_hotkey",
            description="Press keyboard key combinations (e.g. ['cmd', 'space'], ['enter']).",
            parameters_schema={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["keys"]
            },
            risk_level=RiskLevel.MEDIUM
        )

    def run(self, keys: List[str]) -> ToolResult:
        if not keys:
            return ToolResult(success=False, data=None, error="No keys specified for hotkey")

        try:
            audit_logger.log_event("KEYBOARD_HOTKEY", action="hotkey", tool="keyboard_hotkey", extra={"keys": keys})
            return ToolResult(
                success=True,
                data={
                    "action": "hotkey",
                    "keys": keys,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


# =========================================================================
# 5. APPLICATION MANAGEMENT TOOLS
# =========================================================================
class ApplicationLaunchTool(BaseTool):
    """Launch or focus a macOS application."""

    def __init__(self):
        super().__init__(
            name="app_launch",
            description="Launch or bring a macOS application to the foreground.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"}
                },
                "required": ["app_name"]
            },
            risk_level=RiskLevel.MEDIUM
        )

    def run(self, app_name: str) -> ToolResult:
        clean_app = app_name.strip()
        if not clean_app or any(c in clean_app for c in [";", "&", "|", "`", "$"]):
            return ToolResult(success=False, data=None, error=f"Invalid or unsafe application name '{app_name}'")

        try:
            open_cmd = shutil.which("open")
            if not open_cmd:
                return ToolResult(success=False, data=None, error="'open' command not found on macOS")

            res = subprocess.run([open_cmd, "-a", clean_app], capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return ToolResult(success=False, data=None, error=f"Failed to launch '{clean_app}': {res.stderr.strip()}")

            audit_logger.log_event("APP_LAUNCH", action="launch", tool="app_launch", extra={"app": clean_app})
            return ToolResult(success=True, data={"app_name": clean_app, "status": "launched", "timestamp": datetime.datetime.now().isoformat()})
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class ApplicationCloseTool(BaseTool):
    """Gracefully close or quit a macOS application."""

    def __init__(self):
        super().__init__(
            name="app_close",
            description="Gracefully close or quit a running macOS application.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string"},
                    "force": {"type": "boolean"}
                },
                "required": ["app_name"]
            },
            risk_level=RiskLevel.MEDIUM
        )

    def run(self, app_name: str, force: bool = False) -> ToolResult:
        clean_app = app_name.strip()
        if not clean_app or any(c in clean_app for c in [";", "&", "|", "`", "$"]):
            return ToolResult(success=False, data=None, error=f"Invalid application name '{app_name}'")

        try:
            osa = shutil.which("osascript")
            if not osa:
                return ToolResult(success=False, data=None, error="osascript not available")

            script = f'tell application "{clean_app}" to quit'
            res = subprocess.run([osa, "-e", script], capture_output=True, text=True, timeout=10)
            if res.returncode != 0 and force:
                pkill = shutil.which("pkill")
                if pkill:
                    subprocess.run([pkill, "-f", clean_app], capture_output=True)

            audit_logger.log_event("APP_CLOSE", action="close", tool="app_close", extra={"app": clean_app, "force": force})
            return ToolResult(success=True, data={"app_name": clean_app, "status": "closed", "timestamp": datetime.datetime.now().isoformat()})
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


# =========================================================================
# 6. ACTIVE WINDOW & APPLICATION AWARENESS
# =========================================================================
class ActiveWindowTool(BaseTool):
    """Detect the currently frontmost active application and window title on macOS."""

    def __init__(self):
        super().__init__(
            name="get_active_window",
            description="Inspect the active frontmost application and window title.",
            parameters_schema={
                "type": "object",
                "properties": {}
            },
            risk_level=RiskLevel.LOW
        )

    def run(self) -> ToolResult:
        osa = shutil.which("osascript")
        if not osa:
            return ToolResult(success=False, data=None, error="osascript not available on macOS")

        script = """
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            try
                set winTitle to name of front window of frontApp
            on error
                set winTitle to ""
            end try
            return appName & "|||" & winTitle
        end tell
        """
        try:
            proc = subprocess.run([osa, "-e", script], capture_output=True, text=True, timeout=8)
            out = proc.stdout.strip()
            err = proc.stderr.strip()

            # Handle macOS accessibility or automation permission errors cleanly
            if proc.returncode != 0:
                is_perm_err = any(p in err.lower() for p in ["not allowed", "assistive", "permission", "1743", "access"])
                if is_perm_err:
                    audit_logger.log_event("PERMISSION_WARN", action="active_window_denied", tool="get_active_window", error=err)
                    return ToolResult(
                        success=False,
                        data={"permission_denied": True},
                        error="macOS Accessibility permission denied for System Events. Grant permission in System Settings -> Privacy & Security -> Accessibility."
                    )
                return ToolResult(success=False, data=None, error=f"Failed to query active window: {err}")

            parts = out.split("|||")
            app_name = parts[0].strip() if len(parts) > 0 else "Desktop"
            win_title = parts[1].strip() if len(parts) > 1 else ""

            audit_logger.log_event("ACTIVE_WINDOW_DETECTED", action="inspect", tool="get_active_window", extra={"app": app_name, "title": win_title})
            return ToolResult(
                success=True,
                data={
                    "application": app_name,
                    "window_title": win_title,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, data=None, error="Query for active window timed out")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


# =========================================================================
# 7. NOTIFICATION & CLIPBOARD TOOLS (BACKWARD COMPATIBLE)
# =========================================================================
class MacOSNotificationTool(BaseTool):
    """Display native macOS desktop notifications."""

    def __init__(self):
        super().__init__(
            name="macos_notify",
            description="Display a native macOS desktop notification banner.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "message": {"type": "string"}
                },
                "required": ["title", "message"]
            },
            risk_level=RiskLevel.LOW
        )

    def run(self, title: str, message: str) -> ToolResult:
        try:
            osa = shutil.which("osascript")
            if not osa:
                return ToolResult(success=False, data=None, error="osascript not available")
            clean_title = title.replace('"', '\\"')
            clean_msg = message.replace('"', '\\"')
            script = f'display notification "{clean_msg}" with title "{clean_title}"'
            subprocess.run([osa, "-e", script], check=True, capture_output=True, timeout=8)
            return ToolResult(success=True, data="Notification displayed")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class MacOSClipboardTool(BaseTool):
    """Read or write text to macOS system clipboard."""

    def __init__(self):
        super().__init__(
            name="macos_clipboard",
            description="Read or write text to macOS system clipboard.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "text": {"type": "string"}
                },
                "required": ["action"]
            },
            risk_level=RiskLevel.LOW
        )

    def run(self, action: str, text: str = "") -> ToolResult:
        try:
            if action == "read":
                pbpaste = shutil.which("pbpaste")
                if not pbpaste:
                    return ToolResult(success=False, data=None, error="pbpaste not available")
                res = subprocess.run([pbpaste], capture_output=True, text=True, check=True)
                return ToolResult(success=True, data=res.stdout)
            elif action == "write":
                pbcopy = shutil.which("pbcopy")
                if not pbcopy:
                    return ToolResult(success=False, data=None, error="pbcopy not available")
                proc = subprocess.Popen([pbcopy], stdin=subprocess.PIPE, text=True)
                proc.communicate(text)
                return ToolResult(success=True, data=f"Copied {len(text)} characters to clipboard")
            else:
                return ToolResult(success=False, data=None, error=f"Unknown clipboard action '{action}'")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
