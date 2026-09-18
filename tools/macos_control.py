"""
ZARA Controlled macOS Tools: Safe automation for macOS notifications, clipboard, screenshots, and processes.
"""
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel, BASE_DIR

class MacOSNotificationTool(BaseTool):
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
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run([osa, "-e", script], check=True, capture_output=True)
            return ToolResult(success=True, data="Notification displayed")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

class MacOSClipboardTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="macos_clipboard",
            description="Read or write text to macOS system clipboard.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},  # "read" or "write"
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

class MacOSScreenshotTool(BaseTool):
    def __init__(self, output_dir: Path = BASE_DIR / "logs" / "screenshots"):
        super().__init__(
            name="macos_screenshot",
            description="Capture a desktop screenshot and save to workspace.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"}
                },
                "required": ["filename"]
            },
            risk_level=RiskLevel.MEDIUM
        )
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, filename: str = "screenshot.png") -> ToolResult:
        try:
            sc = shutil.which("screencapture")
            if not sc:
                return ToolResult(success=False, data=None, error="screencapture tool not found on macOS")
            out_file = self.output_dir / filename
            subprocess.run([sc, "-x", str(out_file)], check=True, timeout=10)
            return ToolResult(success=True, data={"path": str(out_file), "exists": out_file.exists()})
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
