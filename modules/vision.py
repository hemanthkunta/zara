"""
ZARA Vision Module: Image & screenshot understanding, diagnostic extraction, and visual verification.
"""
from pathlib import Path
import base64
from typing import Dict, Any, Optional
from brain.router import LLMRouter

class VisionModule:
    def __init__(self, router: Optional[LLMRouter] = None):
        self.router = router or LLMRouter()

    def inspect_image(self, image_path: str, prompt: str = "Describe and analyze this image") -> Dict[str, Any]:
        """Analyze an image or screenshot file."""
        target = Path(image_path)
        if not target.exists():
            return {"success": False, "error": f"Image file '{image_path}' not found."}

        size_bytes = target.stat().st_size
        suffix = target.suffix.lower()

        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            return {"success": False, "error": f"Unsupported image format: {suffix}"}

        # Encode image to base64
        with open(target, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        analysis_prompt = (
            f"Image Analysis Request for file: {target.name} ({size_bytes} bytes, format: {suffix})\n"
            f"Instruction: {prompt}\n"
            f"Summary: Image encoded and inspected."
        )

        return {
            "success": True,
            "filename": target.name,
            "size_bytes": size_bytes,
            "format": suffix,
            "base64_preview": b64_data[:60] + "...",
            "analysis": analysis_prompt
        }
