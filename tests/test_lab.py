import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_ai.agent import run_agent
from local_ai.cli import confirm, main
from local_ai.config import Config, LabError
from local_ai.demo import DemoClient, SAMPLE
from local_ai.safety import Workspace, checked_stat, visible
from local_ai.tools import Audit, ToolRunner, calculate


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve system temp aliases before passing a user-selected root.
        self.base = Path(self.temp.name).resolve()
        self.workspace = Workspace(self.base / "workspace")
        self.audit = Audit(self.base / "state")
        self.runner = ToolRunner(self.workspace, self.audit, output=lambda _: None)


class SafetyTests(Fixture):
    def test_normal_unicode_roundtrip_and_no_overwrite(self):
        self.workspace.create("hello.md", "中文内容\n")
        self.assertEqual(self.workspace.read("hello.md"), "中文内容\n")
        with self.assertRaises(LabError):
            self.workspace.create("hello.md", "覆盖")
        self.assertEqual(self.workspace.read("hello.md"), "中文内容\n")

    def test_cross_platform_path_attacks(self):
        paths = ["../secret.txt", "/etc/passwd", "C:/secret.txt", "C:secret.txt",
                 "..\\secret.txt", "\\\\host\\share.txt", "a//x.txt", "a/./x.txt",
                 ".env", ".git/config", "NUL.txt", "con.txt", "LPT1.json", "COM9.md",
                 "file.txt:secret", "file.txt.", "file.txt ", "file\x00.txt", "file.py",
                 "file.exe", "a/../../b.txt"]
        for name in paths:
            with self.subTest(name=name), self.assertRaises(LabError):
                self.workspace.path(name)

    def test_parent_must_exist_and_nested_valid(self):
        with self.assertRaises(LabError):
            self.workspace.create("nested/a.txt", "hi")
        (self.workspace.root / "nested").mkdir()
        self.workspace.create("nested/a.txt", "hi")
        self.assertEqual(self.workspace.read("nested/a.txt"), "hi")

    def test_size_limit_and_binary(self):
        with self.assertRaises(LabError):
            self.workspace.create("big.txt", "中" * 3000)
        (self.workspace.root / "big.txt").write_bytes(b"a" * 8193)
        (self.workspace.root / "binary.txt").write_bytes(b"\xff")
        for name in ("big.txt", "binary.txt"):
            with self.assertRaises(LabError):
                self.workspace.read(name)

    def test_symlink_file_directory_and_root_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        link = self.workspace.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
            (self.workspace.root / "file.txt").symlink_to(outside / "secret.txt")
        except OSError:
            self.skipTest("OS does not permit symlinks for this user")
        for name in ("link/secret.txt", "file.txt"):
            with self.assertRaises(LabError):
                self.workspace.read(name)
        with self.assertRaises(LabError):
            Workspace(link)
        self.assertEqual(self.workspace.list(), [])

    def test_hardlink_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_text("secret")
        try:
            os.link(outside, self.workspace.root / "hard.txt")
        except OSError:
            self.skipTest("Hardlinks unavailable")
        with self.assertRaises(LabError):
            self.workspace.read("hard.txt")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.workspace.root / "fifo.txt")
        with self.assertRaises(LabError):
            self.workspace.read("fifo.txt")

    def test_windows_reparse_attribute(self):
        fake = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=fake), self.assertRaises(LabError):
            checked_stat(Path("junction"))

    def test_terminal_control_escape(self):
        self.assertEqual(visible("ok\x1b[2J\r\u202e"), "ok\\u001b[2J\\u000d\\u202e")


class ToolTests(Fixture):
    def test_calculator_and_code_rejection(self):
        self.assertEqual(calculate("399 + 299 * 2"), 997)
        self.assertEqual(calculate("-(3 + 2) / 2"), -2.5)
        for expr in ["__import__('os').system('echo BAD')", "2**1000000", "[1]", "True",
                     "1/0", "1e309", "10**10", "abs(1)", "1e12*2", "x.y", "1+" * 150]:
            with self.subTest(expr=expr), self.assertRaises(LabError):
                calculate(expr)

    def test_unknown_tools_and_arguments(self):
        for name, args in [("shell", {"command": "anything"}),
                           ("calculate", {"expression": "1+1", "code": "evil"}),
                           ("calculate", {"expression": 123}), ("read_text", {})]:
            self.assertFalse(self.runner.dispatch(name, args)["ok"])

    def test_default_is_preview(self):
        result = self.runner.dispatch("write_text", {"path": "report.md", "content": "test"})
        self.assertEqual(result["status"], "preview")
        self.assertFalse((self.workspace.root / "report.md").exists())

    def test_apply_still_requires_approval(self):
        self.runner.apply = True
        result = self.runner.dispatch("write_text", {"path": "report.md", "content": "test"})
        self.assertEqual(result["status"], "denied")
        self.assertFalse((self.workspace.root / "report.md").exists())

    def test_approved_write_and_audit_redaction(self):
        self.runner.apply, self.runner.confirm = True, lambda _: True
        result = self.runner.dispatch("write_text", {"path": "report.md", "content": "PRIVATE-TEXT"})
        self.assertTrue(result["created"])
        audit = self.audit.path.read_text()
        self.assertNotIn("PRIVATE-TEXT", audit)
        self.assertNotIn("report.md", audit)
        records = [json.loads(line) for line in audit.splitlines()]
        self.assertEqual([r["status"] for r in records], ["started", "created"])

    def test_recheck_after_approval(self):
        def race(_):
            self.workspace.create("report.md", "existing")
            return True
        self.runner.apply, self.runner.confirm = True, race
        result = self.runner.dispatch("write_text", {"path": "report.md", "content": "new"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.workspace.read("report.md"), "existing")

    def test_audit_failure_prevents_write(self):
        self.runner.apply, self.runner.confirm = True, lambda _: True
        with patch.object(self.audit, "record", side_effect=LabError("unavailable")):
            with self.assertRaises(LabError):
                self.runner.dispatch("write_text", {"path": "report.md", "content": "new"})
        self.assertFalse((self.workspace.root / "report.md").exists())

    def test_piped_yes_does_not_approve(self):
        with patch("sys.stdin", io.StringIO("WRITE report.md\n")):
            self.assertFalse(confirm("report.md"))


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def chat(self, messages, tools):
        self.messages = list(messages)
        return next(self.responses)


def response(calls=None, content="done", **kwargs):
    return {"done": True, "message": {"role": "assistant", "content": content,
                                      "tool_calls": [] if calls is None else calls}, **kwargs}


def call(name="calculate", **args):
    return {"function": {"name": name, "arguments": args}}


class AgentTests(Fixture):
    def test_full_offline_flow_uses_tool_results(self):
        self.workspace.create("sample.json", json.dumps(SAMPLE, ensure_ascii=False))
        self.runner.apply, self.runner.confirm = True, lambda _: True
        result = run_agent(DemoClient(), self.runner, "demo", Config())
        self.assertIn("未调用真实模型", result.text)
        self.assertIn("997", self.workspace.read("demo-report.md"))
        self.assertEqual([e["tool"] for e in self.runner.events], ["read_text", "calculate", "write_text"])

    def test_multi_call_and_tool_name_protocol(self):
        client = ScriptedClient([response([call(expression="1+1"), call(expression="2+2")]), response()])
        run_agent(client, self.runner, "math", Config())
        results = [m for m in client.messages if m["role"] == "tool"]
        self.assertEqual([m["tool_name"] for m in results], ["calculate", "calculate"])
        self.assertEqual([json.loads(m["content"])["value"] for m in results], [2, 4])

    def test_malformed_batch_has_no_partial_execution(self):
        client = ScriptedClient([response([call(expression="1+1"), {"function": {"name": "bad"}}])])
        with self.assertRaises(LabError):
            run_agent(client, self.runner, "x", Config())
        self.assertEqual(self.runner.events, [])

    def test_budget_prevents_whole_batch(self):
        client = ScriptedClient([response([call(expression="1+1"), call(expression="2+2")])])
        with self.assertRaises(LabError):
            run_agent(client, self.runner, "x", replace(Config(), max_tool_calls=1))
        self.assertEqual(self.runner.events, [])

    def test_loop_limit(self):
        client = ScriptedClient([response([call(expression="1+1")])] * 2)
        with self.assertRaisesRegex(LabError, "最大模型轮数"):
            run_agent(client, self.runner, "x", replace(Config(), max_steps=2))

    def test_incomplete_and_truncated_response_do_not_execute(self):
        for extra in ({"done": False}, {"done_reason": "length"}, {"prompt_eval_count": 7000}):
            client = ScriptedClient([response([call(expression="1+1")], **extra)])
            with self.assertRaises(LabError):
                run_agent(client, self.runner, "x", Config())
        self.assertEqual(self.runner.events, [])

    def test_denial_stops_remaining_calls(self):
        self.runner.apply = True
        client = ScriptedClient([response([call("write_text", path="a.txt", content="x"),
                                           call(expression="1+1")])])
        with self.assertRaisesRegex(LabError, "拒绝"):
            run_agent(client, self.runner, "x", Config())
        self.assertEqual(len(self.runner.events), 1)

    def test_history_limit(self):
        with self.assertRaisesRegex(LabError, "字节预算"):
            run_agent(ScriptedClient([]), self.runner, "大" * 12000, Config())


class ConfigCliTests(Fixture):
    def test_config_validation(self):
        bad = [{"base_url": url} for url in ["https://example.com", "http://localhost:11434",
               "http://127.0.0.1:11434/evil", "http://u@127.0.0.1:11434", "http://0.0.0.0:11434",
               "http://127.0.0.1:0", "http://[::1]:11434/?x=1"]]
        bad += [{"model": "qwen-cloud"}, {"max_steps": True}, {"max_steps": 0}, {"think": "false"}]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(LabError):
                Config(**args)
        Config(base_url="http://[::1]:11434")

    def test_init_demo_cli_and_custom_config_directory(self):
        config = self.base / "config.json"
        config.write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--config", str(config), "init"]), 0)
            self.assertEqual(main(["--config", str(config), "init"]), 0)
            self.assertEqual(main(["--config", str(config), "demo"]), 0)
        self.assertFalse((self.base / "workspace/demo-report.md").exists())

    def test_missing_and_unknown_config_fail(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--config", str(self.base / "missing.json"), "init"]), 1)
        path = self.base / "bad.json"
        path.write_text('{"modle": "typo"}')
        with self.assertRaises(LabError):
            Config.load(path)


if __name__ == "__main__":
    unittest.main()
