"""
Unit tests for ZARA Tool Registry and Typed Tool Interface.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from tools.registry import ToolRegistry
from tools.filesystem import ReadFileTool, WriteFileTool, PatchFileTool, ListDirTool
from tools.terminal import TerminalExecutionTool
from config.settings import RiskLevel

class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_tools_test_")
        self.workspace = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tool_input_validation(self):
        reg = ToolRegistry()
        reg.register(WriteFileTool(self.workspace))

        # Missing required parameter 'content'
        res = reg.execute("write_file", {"path": "test.txt"})
        self.assertFalse(res.success)
        self.assertIn("Missing required parameter", res.error)

        # Wrong type parameter
        res = reg.execute("write_file", {"path": 12345, "content": "hello"})
        self.assertFalse(res.success)
        self.assertIn("must be a string", res.error)

    def test_filesystem_tools(self):
        reg = ToolRegistry()
        reg.register(WriteFileTool(self.workspace))
        reg.register(ReadFileTool(self.workspace))
        reg.register(PatchFileTool(self.workspace))
        reg.register(ListDirTool(self.workspace))

        # 1. Write file
        w_res = reg.execute("write_file", {"path": "hello.py", "content": "msg = 'ZARA'\n"})
        self.assertTrue(w_res.success)

        # 2. Read file
        r_res = reg.execute("read_file", {"path": "hello.py"})
        self.assertTrue(r_res.success)
        self.assertEqual(r_res.data, "msg = 'ZARA'\n")

        # 3. Patch file
        p_res = reg.execute("patch_file", {"path": "hello.py", "old_str": "ZARA", "new_str": "ZARA-AGENT"})
        self.assertTrue(p_res.success)

        r_res2 = reg.execute("read_file", {"path": "hello.py"})
        self.assertEqual(r_res2.data, "msg = 'ZARA-AGENT'\n")

        # 4. List directory
        l_res = reg.execute("list_dir", {"path": "."})
        self.assertTrue(l_res.success)
        self.assertIn("hello.py", l_res.data)

    def test_path_traversal_refusal(self):
        reg = ToolRegistry()
        reg.register(ReadFileTool(self.workspace))
        reg.register(WriteFileTool(self.workspace))

        # Path traversal read
        res = reg.execute("read_file", {"path": "../../../etc/passwd"})
        self.assertFalse(res.success)
        self.assertIn("Path traversal detected", res.error)

        # Path traversal write
        res2 = reg.execute("write_file", {"path": "../secret.txt", "content": "data"})
        self.assertFalse(res2.success)
        self.assertIn("Path traversal detected", res2.error)

    def test_permission_gate(self):
        # Set max auto risk to LOW
        reg = ToolRegistry(max_auto_risk=RiskLevel.LOW, confirm_callback=lambda tool, args: False)
        # Register terminal execute tool (MEDIUM risk)
        reg.register(TerminalExecutionTool(self.workspace))

        res = reg.execute("terminal_execute", {"command": "echo test"})
        self.assertFalse(res.success)
        self.assertIn("Permission denied", res.error)

if __name__ == "__main__":
    unittest.main()
