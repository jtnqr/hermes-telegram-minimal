import sys
import unittest
from pathlib import Path

# Add plugin root to sys.path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from __init__ import clean_telegram_content, format_telegram_verbose_tool


class TestFormatting(unittest.TestCase):
    def test_clean_telegram_content_emojis(self):
        raw = "✨ Success! Here is some 🚀 data and 💡 ideas."
        cleaned = clean_telegram_content(raw)
        self.assertIn("[+]", cleaned)
        self.assertIn("[i]", cleaned)
        self.assertNotIn("✨", cleaned)
        self.assertNotIn("🚀", cleaned)

    def test_clean_telegram_content_latex_math(self):
        raw = r"Formula: \omega = 2\pi f and \Delta x \rightarrow 0"
        cleaned = clean_telegram_content(raw)
        self.assertIn("ω", cleaned)
        self.assertIn("Δ", cleaned)
        self.assertIn("→", cleaned)
        self.assertNotIn(r"\omega", cleaned)

    def test_clean_telegram_content_code_fence_preservation(self):
        code_block = "```python\n# Do not touch emojis here: 🚀\nx = 1\n```"
        raw = f"Intro 🚀\n{code_block}\nOutro ✨"
        cleaned = clean_telegram_content(raw)
        self.assertIn("```python\n# Do not touch emojis here: 🚀\nx = 1\n```", cleaned)
        self.assertTrue("[+]" in cleaned or "[i]" in cleaned)

    def test_clean_telegram_content_multi_backtick_normalization(self):
        raw = "With backticks (`` `[~]` ``) and ``foo``"
        cleaned = clean_telegram_content(raw)
        self.assertIn("`[~]`", cleaned)
        self.assertIn("`foo`", cleaned)
        self.assertNotIn("``", cleaned)

    def test_clean_telegram_content_preserves_code_block_order(self):
        raw = """1. First:
```bash
echo first
```
2. Second:
```bash
echo second
```
3. Third:
```bash
echo third
```"""
        cleaned = clean_telegram_content(raw)
        pos_first = cleaned.find("echo first")
        pos_second = cleaned.find("echo second")
        pos_third = cleaned.find("echo third")
        self.assertTrue(pos_first < pos_second < pos_third, "Code block order was corrupted!")

    def test_format_patch_short(self):
        args = {
            "path": "src/main.py",
            "old_string": "x = 1\ny = 2",
            "new_string": "x = 10\ny = 20",
        }
        result = format_telegram_verbose_tool("patch", args)
        self.assertIn("**patch** `src/main.py`", result)
        self.assertIn("```diff", result)
        self.assertIn("- x = 1", result)
        self.assertIn("+ x = 10", result)

    def test_format_patch_overflow(self):
        old_lines = [f"old_line_{i}" for i in range(40)]
        new_lines = [f"new_line_{i}" for i in range(40)]
        args = {
            "path": "huge_file.py",
            "old_string": "\n".join(old_lines),
            "new_string": "\n".join(new_lines),
        }
        result = format_telegram_verbose_tool("patch", args)
        self.assertIn("**patch** `huge_file.py`", result)
        self.assertIn("- ... (15 more lines)", result)
        self.assertIn("+ ... (15 more lines)", result)

    def test_format_execute_code_short(self):
        args = {
            "code": "import os\nprint(os.getpid())\n",
        }
        result = format_telegram_verbose_tool("execute_code", args)
        self.assertIn("**execute_code**", result)
        self.assertIn("```python", result)
        self.assertIn("print(os.getpid())", result)

    def test_format_execute_code_overflow(self):
        code = "\n".join([f"var_{i} = {i}" for i in range(60)])
        args = {"code": code}
        result = format_telegram_verbose_tool("execute_code", args)
        self.assertIn("**execute_code**", result)
        self.assertIn("# ... (25 more lines)", result)

    def test_format_terminal_short(self):
        args = {"command": "git status --short"}
        result = format_telegram_verbose_tool("terminal", args)
        self.assertIn("**terminal**", result)
        self.assertIn("```sh", result)
        self.assertIn("git status --short", result)


if __name__ == "__main__":
    unittest.main()
