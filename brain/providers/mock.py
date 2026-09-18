"""
ZARA Mock LLM Provider: Deterministic, tool-aware LLM provider for offline testing and zero-key workflows.
Generates structured tool calls complying with ZARA's registered tool schema.
"""
import json
import re
from typing import List, Dict, Any, Optional
from brain.base import LLMProvider, LLMMessage, LLMResponse, LLMUsage, Role

class MockLLMProvider(LLMProvider):
    def __init__(self, model_name: str = "zara-mock-v1"):
        super().__init__(model_name)

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        user_text = ""
        for m in reversed(messages):
            if m.role == Role.USER:
                user_text = m.content
                break

        # Check for planning requests
        user_lower = user_text.lower()
        if (
            "break this task" in user_lower
            or "available registered tools" in user_lower
            or "return json with 'steps'" in user_lower
            or "return only a valid json object with the following schema" in user_lower
        ):
            response_content = self._generate_mock_plan(user_text)
        elif "diagnose" in user_lower or "failure in step" in user_lower:
            response_content = self._generate_mock_diagnosis(user_text)
        elif "fibonacci" in user_lower and "code" in user_lower:
            response_content = self._generate_fibonacci_solution()
        else:
            response_content = (
                f"ZARA Reasoning Engine: Processed request '{user_text[:80]}'. "
                f"Ready to proceed with verifiable execution steps."
            )

        tokens = self.count_tokens(user_text) + self.count_tokens(response_content)
        usage = LLMUsage(
            prompt_tokens=self.count_tokens(user_text),
            completion_tokens=self.count_tokens(response_content),
            total_tokens=tokens,
            cost_usd=0.0
        )

        return LLMResponse(
            content=response_content,
            usage=usage,
            model=self.model_name,
            provider="mock"
        )

    def _generate_mock_plan(self, prompt: str) -> str:
        """Dynamically decompose natural-language engineering task into validated tool calls."""
        # Isolate the current task from prompt to avoid matching past lessons or template examples
        task_match = re.search(r'Task:\s*(.*?)(?:\n[A-Z][a-zA-Z\s]+:|$)', prompt, re.DOTALL)
        target_task = task_match.group(1).strip() if task_match else prompt
        task_lower = target_task.lower()

        steps = []

        # 1. Intentional syntax error task
        if "syntax error" in task_lower or "bad_syntax" in task_lower or "broken_syntax" in task_lower or "broken" in task_lower:
            filename = "broken_syntax.py"
            steps.append({
                "id": 1,
                "title": f"Create {filename} with intentional syntax error",
                "description": f"Write {filename} containing broken Python syntax",
                "tool": "write_file",
                "action_type": "tool",
                "target": filename,
                "arguments": {
                    "path": filename,
                    "content": "def broken_func(\n    print('Missing paren')\n",
                    "validate_syntax": False
                },
                "dependencies": [],
                "success_condition": f"File {filename} exists on disk"
            })
            steps.append({
                "id": 2,
                "title": f"Run {filename}",
                "description": f"Execute {filename} and trigger diagnosis/repair",
                "tool": "terminal_execute",
                "action_type": "tool",
                "target": f"python3 {filename}",
                "arguments": {
                    "command": f"python3 {filename}"
                },
                "dependencies": [1],
                "success_condition": "Output contains 'Fixed syntax successfully' and exit code is 0"
            })
            return json.dumps({"steps": steps}, indent=2)

        # 2. Multi-step dependent files task
        if "two file" in task_lower or "dependent" in task_lower or ("helper" in task_lower and "main" in task_lower):
            steps.append({
                "id": 1,
                "title": "Create helper.py module",
                "description": "Write helper module providing get_value function",
                "tool": "write_file",
                "action_type": "tool",
                "target": "helper.py",
                "arguments": {
                    "path": "helper.py",
                    "content": "def get_value():\n    return 42\n"
                },
                "dependencies": [],
                "success_condition": "File helper.py exists on disk"
            })
            steps.append({
                "id": 2,
                "title": "Create main_app.py consumer",
                "description": "Write main consumer script importing helper",
                "tool": "write_file",
                "action_type": "tool",
                "target": "main_app.py",
                "arguments": {
                    "path": "main_app.py",
                    "content": "from helper import get_value\nprint(f'Computed value: {get_value()}')\n"
                },
                "dependencies": [1],
                "success_condition": "File main_app.py exists on disk"
            })
            steps.append({
                "id": 3,
                "title": "Execute main_app.py",
                "description": "Run main application to verify integration",
                "tool": "terminal_execute",
                "action_type": "tool",
                "target": "python3 main_app.py",
                "arguments": {
                    "command": "python3 main_app.py"
                },
                "dependencies": [2],
                "success_condition": "Output contains 'Computed value: 42' and exit code is 0"
            })
            return json.dumps({"steps": steps}, indent=2)

        # 3. Read file tasks
        read_match = re.search(r'(?:read|examine|inspect|view|summarize)\s+(?:the\s+file\s+|file\s+)?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)', target_task, re.IGNORECASE)
        if read_match and not any(kw in task_lower for kw in ["create", "write", "make"]):
            filename = read_match.group(1)
            steps.append({
                "id": 1,
                "title": f"Read {filename}",
                "description": f"Read and inspect contents of {filename}",
                "tool": "read_file",
                "action_type": "tool",
                "target": filename,
                "arguments": {
                    "path": filename
                },
                "dependencies": [],
                "success_condition": f"File {filename} read successfully"
            })
            return json.dumps({"steps": steps}, indent=2)

        # 4. List directory / files
        if "list" in task_lower and ("file" in task_lower or "dir" in task_lower or "python" in task_lower or "repo" in task_lower):
            steps.append({
                "id": 1,
                "title": "List directory contents",
                "description": "Inspect files in workspace using list_dir",
                "tool": "list_dir",
                "action_type": "tool",
                "target": ".",
                "arguments": {
                    "path": "."
                },
                "dependencies": [],
                "success_condition": "Directory contents listed"
            })
            return json.dumps({"steps": steps}, indent=2)

        # 5. Create file and optionally run
        file_match = re.search(r'(?:create|write|make)\s+(?:a\s+file\s+called\s+|a\s+file\s+named\s+|a\s+file\s+)?([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+)', target_task, re.IGNORECASE)
        print_match = re.search(r'prints?\s+[\'"]([^\'"]+)[\'"]', target_task, re.IGNORECASE)

        if file_match:
            filename = file_match.group(1)
            msg = print_match.group(1) if print_match else "Hello from ZARA"
            
            # Step 1: Write file
            steps.append({
                "id": 1,
                "title": f"Create {filename}",
                "description": f"Write {filename} with print statement",
                "tool": "write_file",
                "action_type": "tool",
                "target": filename,
                "arguments": {
                    "path": filename,
                    "content": f'print("{msg}")\n'
                },
                "dependencies": [],
                "success_condition": f"File {filename} exists and content written"
            })

            # Step 2: If requested to run or execute
            if any(term in target_task.lower() for term in ["run", "execute", "verify", "output"]):
                cmd = f"python3 {filename}" if filename.endswith(".py") else f"./{filename}"
                steps.append({
                    "id": 2,
                    "title": f"Execute {filename}",
                    "description": f"Run {filename} and verify output matches '{msg}'",
                    "tool": "terminal_execute",
                    "action_type": "tool",
                    "target": cmd,
                    "arguments": {
                        "command": cmd
                    },
                    "dependencies": [1],
                    "success_condition": f"Output contains '{msg}' and exit code is 0"
                })

        elif "calculator" in target_task.lower():
            if "test" in target_task.lower() and not any(kw in target_task.lower() for kw in ["create a python calculator", "with add, subtract"]):
                steps.append({
                    "id": 1,
                    "title": "Create test_calculator.py",
                    "description": "Write test cases for calculator",
                    "tool": "write_file",
                    "action_type": "tool",
                    "target": "test_calculator.py",
                    "arguments": {
                        "path": "test_calculator.py",
                        "content": "import unittest\nfrom calculator import add, subtract, multiply, divide\n\nclass TestCalculator(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n    def test_subtract(self):\n        self.assertEqual(subtract(5, 2), 3)\n    def test_multiply(self):\n        self.assertEqual(multiply(3, 4), 12)\n    def test_divide(self):\n        self.assertEqual(divide(10, 2), 5)\n        with self.assertRaises(ValueError):\n            divide(1, 0)\n\nif __name__ == '__main__':\n    unittest.main()\n"
                    },
                    "dependencies": [],
                    "success_condition": "File test_calculator.py exists on disk"
                })
                steps.append({
                    "id": 2,
                    "title": "Execute test_calculator.py",
                    "description": "Run unit tests for calculator",
                    "tool": "terminal_execute",
                    "action_type": "tool",
                    "target": "python3 -m unittest test_calculator.py",
                    "arguments": {
                        "command": "python3 -m unittest test_calculator.py"
                    },
                    "dependencies": [1],
                    "success_condition": "Tests exit with return code 0"
                })
            elif "fix" in target_task.lower() or "failing" in target_task.lower():
                steps.append({
                    "id": 1,
                    "title": "Run test suite on calculator",
                    "description": "Execute test_calculator.py to identify failing test",
                    "tool": "terminal_execute",
                    "action_type": "tool",
                    "target": "python3 -m unittest test_calculator.py",
                    "arguments": {
                        "command": "python3 -m unittest test_calculator.py"
                    },
                    "dependencies": [],
                    "success_condition": "Tests exit with return code 0"
                })
            else:
                calc_code = (
                    "def add(a, b):\n    return a + b\n\n"
                    "def subtract(a, b):\n    return a - b\n\n"
                    "def multiply(a, b):\n    return a * b\n\n"
                    "def divide(a, b):\n    if b == 0:\n        raise ValueError('Cannot divide by zero')\n    return a / b\n"
                )
                steps.append({
                    "id": 1,
                    "title": "Create calculator.py",
                    "description": "Write calculator module with add, subtract, multiply, divide",
                    "tool": "write_file",
                    "action_type": "tool",
                    "target": "calculator.py",
                    "arguments": {
                        "path": "calculator.py",
                        "content": calc_code
                    },
                    "dependencies": [],
                    "success_condition": "File calculator.py exists on disk"
                })
                if any(kw in target_task.lower() for kw in ["test", "verify"]):
                    steps.append({
                        "id": 2,
                        "title": "Create test_calculator.py",
                        "description": "Write test cases for calculator",
                        "tool": "write_file",
                        "action_type": "tool",
                        "target": "test_calculator.py",
                        "arguments": {
                            "path": "test_calculator.py",
                            "content": "import unittest\nfrom calculator import add, subtract, multiply, divide\n\nclass TestCalculator(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n    def test_subtract(self):\n        self.assertEqual(subtract(5, 2), 3)\n    def test_multiply(self):\n        self.assertEqual(multiply(3, 4), 12)\n    def test_divide(self):\n        self.assertEqual(divide(10, 2), 5)\n\nif __name__ == '__main__':\n    unittest.main()\n"
                        },
                        "dependencies": [1],
                        "success_condition": "File test_calculator.py exists on disk"
                    })
                    steps.append({
                        "id": 3,
                        "title": "Run unit tests",
                        "description": "Execute test_calculator.py",
                        "tool": "terminal_execute",
                        "action_type": "tool",
                        "target": "python3 -m unittest test_calculator.py",
                        "arguments": {
                            "command": "python3 -m unittest test_calculator.py"
                        },
                        "dependencies": [2],
                        "success_condition": "Tests exit with return code 0"
                    })

        elif any(kw in target_task.lower() for kw in ["research", "summarize the important changes", "compare several", "find documentation"]):
            steps.append({
                "id": 1,
                "title": "Search web for authoritative technical documentation",
                "description": f"Query search engine for topic: {target_task[:50]}",
                "tool": "web_search",
                "action_type": "tool",
                "target": "web_search",
                "arguments": {
                    "query": target_task[:60],
                    "max_results": 3
                },
                "dependencies": [],
                "success_condition": "Search returns structured results with URLs and titles"
            })
            steps.append({
                "id": 2,
                "title": "Open primary documentation page",
                "description": "Fetch official documentation page and extract markdown content",
                "tool": "browser_open",
                "action_type": "tool",
                "target": "browser_open",
                "arguments": {
                    "url": "https://docs.python.org/3.14/whatsnew/3.14.html",
                    "max_length": 6000
                },
                "dependencies": [1],
                "success_condition": "Page content extracted with HTTP status 200"
            })
            steps.append({
                "id": 3,
                "title": "Extract evidence on language and runtime features",
                "description": "Extract targeted technical evidence addressing research query",
                "tool": "extract_content",
                "action_type": "tool",
                "target": "extract_content",
                "arguments": {
                    "url": "https://docs.python.org/3.14/whatsnew/3.14.html",
                    "target_topic": "Python 3.14 features",
                    "source_id": "source_01"
                },
                "dependencies": [2],
                "success_condition": "Evidence excerpts extracted and linked to source_id"
            })

        elif re.search(r'\btests?\b', target_task.lower()) and ("run" in target_task.lower() or "existing" in target_task.lower()):
            steps.append({
                "id": 1,
                "title": "Run test suite",
                "description": "Discover and execute tests",
                "tool": "run_tests",
                "action_type": "tool",
                "target": "tests",
                "arguments": {
                    "test_path": "tests"
                },
                "dependencies": [],
                "success_condition": "Test runner exits with code 0"
            })

        else:
            # General fallback: inspect workspace with list_dir
            steps.append({
                "id": 1,
                "title": "Inspect workspace environment",
                "description": "List files in workspace before acting",
                "tool": "list_dir",
                "action_type": "tool",
                "target": ".",
                "arguments": {
                    "path": "."
                },
                "dependencies": [],
                "success_condition": "Directory listing obtained"
            })

        return json.dumps({"steps": steps}, indent=2)

    def _generate_mock_diagnosis(self, prompt: str) -> str:
        prompt_lower = prompt.lower()
        if "syntaxerror" in prompt_lower or "broken_func" in prompt_lower or "broken_syntax" in prompt_lower:
            return json.dumps({
                "failure_type": "syntax_error",
                "root_cause_category": "syntax_error",
                "hypothesis": "Python script contains syntax error with unclosed parenthesis.",
                "root_cause": "SyntaxError: '(' was never closed",
                "affected_file": "broken_syntax.py",
                "affected_line": 1,
                "explanation": "Unclosed parenthesis in function header.",
                "recommended_action": "Add closing parenthesis to function signature",
                "confidence": 0.99,
                "corrected_tool": None,
                "corrected_arguments": None,
                "proposed_fix": {
                    "action": "fix_syntax",
                    "file": "broken_syntax.py",
                    "new_content": "def broken_func():\n    print('Fixed syntax successfully')\n\nif __name__ == '__main__':\n    broken_func()\n"
                }
            }, indent=2)
        elif "multiply" in prompt_lower or ("assertionerror" in prompt_lower and "calculator" in prompt_lower):
            return json.dumps({
                "failure_type": "assertion_failure",
                "root_cause_category": "code_logic",
                "hypothesis": "Function multiply in calculator.py performs addition instead of multiplication.",
                "root_cause": "multiply implementation has incorrect operator (+ instead of *)",
                "affected_file": "calculator.py",
                "affected_line": 8,
                "explanation": "Test expected 3 * 4 == 12, but multiply returned 7.",
                "recommended_action": "Change '+' to '*' in multiply function",
                "confidence": 0.98,
                "corrected_tool": None,
                "corrected_arguments": None,
                "proposed_fix": {
                    "action": "fix_implementation_logic",
                    "file": "calculator.py",
                    "patch": {
                        "old": "def multiply(a, b):\n    return a + b",
                        "new": "def multiply(a, b):\n    return a * b"
                    }
                }
            }, indent=2)
        elif "zerodivisionerror" in prompt_lower or "runtime" in prompt_lower:
            return json.dumps({
                "failure_type": "runtime_error",
                "root_cause_category": "code_logic",
                "hypothesis": "Division by zero encountered in runtime execution.",
                "root_cause": "Denominator is 0 without zero-check guard",
                "affected_file": "runtime_bug.py",
                "affected_line": 2,
                "explanation": "Code attempted division by zero.",
                "recommended_action": "Guard against zero divisor",
                "confidence": 0.95,
                "corrected_tool": None,
                "corrected_arguments": None,
                "proposed_fix": {
                    "action": "fix_runtime_error",
                    "file": "runtime_bug.py",
                    "patch": {
                        "old": "return x / 0",
                        "new": "return x / 1"
                    }
                }
            }, indent=2)
        elif "wrong_module" in prompt_lower or "importerror" in prompt_lower or "modulenotfounderror" in prompt_lower:
            return json.dumps({
                "failure_type": "import_error",
                "root_cause_category": "dependency",
                "hypothesis": "Local module import specifies incorrect module name.",
                "root_cause": "Import statement refers to non-existent module wrong_module",
                "affected_file": "consumer.py",
                "affected_line": 1,
                "explanation": "File attempted to import from wrong_module instead of calculator.",
                "recommended_action": "Update import statement to import from calculator",
                "confidence": 0.99,
                "corrected_tool": None,
                "corrected_arguments": None,
                "proposed_fix": {
                    "action": "fix_import",
                    "file": "consumer.py",
                    "patch": {
                        "old": "from wrong_module import add",
                        "new": "from calculator import add"
                    }
                }
            }, indent=2)
        elif "command not found" in prompt_lower:
            category = "command"
            hypothesis = "Command is invalid or binary not found in PATH."
            fix = {"action": "fix_command"}
        elif "assertionerror" in prompt_lower:
            category = "code_logic"
            hypothesis = "Assertion error: function implementation returned unexpected result."
            fix = {"action": "patch_code"}
        else:
            category = "tool_arguments"
            hypothesis = "Execution output did not satisfy success condition."
            fix = {"action": "adjust_arguments"}

        return json.dumps({
            "root_cause_category": category,
            "hypothesis": hypothesis,
            "corrected_tool": None,
            "corrected_arguments": None,
            "proposed_fix": fix
        }, indent=2)

    def _generate_fibonacci_solution(self) -> str:
        return json.dumps({
            "code": "def fibonacci(n: int) -> int:\n    if n <= 0:\n        return 0\n    elif n == 1:\n        return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n",
            "test": "import unittest\nfrom fibonacci import fibonacci\n\nclass TestFib(unittest.TestCase):\n    def test_fib(self):\n        self.assertEqual(fibonacci(0), 0)\n        self.assertEqual(fibonacci(1), 1)\n        self.assertEqual(fibonacci(7), 13)\n\nif __name__ == '__main__':\n    unittest.main()\n"
        }, indent=2)
