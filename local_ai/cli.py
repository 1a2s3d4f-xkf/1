import argparse
import json
import sys
from pathlib import Path

from .agent import run_agent
from .client import OllamaClient
from .config import Config, LabError
from .demo import DEMO_PROMPT, SAMPLE, DemoClient
from .safety import Workspace, visible
from .tools import Audit, ToolRunner


def confirm(path):
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"确认以上内容后，输入 WRITE {path} 才会创建（其他输入拒绝）：")
        return answer == f"WRITE {path}"
    except EOFError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="RTX 5090 本地 AI 自动化实验；默认只预览模型写入")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="创建独立工作区和 sample.json，不覆盖已有文件")
    sub.add_parser("doctor", help="检查本机 Ollama/模型和已加载模型，输出版本")
    sub.add_parser("smoke", help="真实模型必须调用 calculate 才能通过")
    for command in ("run", "demo"):
        child = sub.add_parser(command, help="执行真实任务" if command == "run" else "离线模拟模型演示")
        child.add_argument("--apply", action="store_true", help="允许逐次交互批准创建文件")
        if command == "run":
            child.add_argument("prompt")
    args = parser.parse_args(argv)
    try:
        config = Config.load(args.config)
        # Fixed sibling directories: the model cannot choose its root or audit path.
        base = args.config.absolute().parent
        if args.command == "doctor":
            client = OllamaClient(config)
            report = client.preflight()
            report["running_models"] = client.request("/api/ps").get("models", [])
            print(visible(json.dumps(report, ensure_ascii=False, indent=2)))
            print("仅证明服务可用；请在推理后用 ollama ps 和 nvidia-smi 核实 GPU。")
            return 0
        workspace = Workspace(base / "workspace", config.max_file_bytes)
        if args.command == "init":
            sample = workspace.path("sample.json")
            if sample.exists():
                print("sample.json 已存在，保持原内容。")
            else:
                workspace.create("sample.json", json.dumps(SAMPLE, ensure_ascii=False, indent=2) + "\n")
                print("已创建 workspace/sample.json，示例总价应为 997 元。")
            return 0
        runner = ToolRunner(workspace, Audit(base / ".local-ai"),
                            apply=getattr(args, "apply", False), confirm=confirm)
        if args.command == "demo":
            print("[离线演示] 使用固定模拟响应，不代表模型或 GPU 已通过验证。")
            client, prompt = DemoClient(), DEMO_PROMPT
        else:
            client = OllamaClient(config)
            print(visible(json.dumps(client.preflight(), ensure_ascii=False)))
            prompt = ("必须调用 calculate 工具计算 123*456，然后用中文回答结果。不要读写文件。"
                      if args.command == "smoke" else args.prompt)
        result = run_agent(client, runner, prompt, config)
        print("\n" + visible(result.text))
        if args.command == "demo":
            if (len(runner.events) != 3
                    or any(not x["result"].get("ok") for x in runner.events)):
                raise LabError("离线演示未完成：检查 sample.json 或使用新的输出文件名")
        if args.command == "smoke":
            if not any(e["tool"] == "calculate" and e["result"].get("value") == 56088 for e in runner.events):
                raise LabError("真实模型未完成指定工具调用，smoke 未通过")
            print("[PASS] 真实模型发出 calculate 调用，Python 返回 56088，模型完成后续回答。")
        for index, metric in enumerate(result.metrics, 1):
            duration, count = metric.get("eval_duration"), metric.get("eval_count")
            if type(duration) in {int, float} and duration > 0 and type(count) is int:
                print(f"[性能] 第 {index} 轮生成速度 {count / (duration / 1e9):.1f} token/s（不含加载/提示处理）")
        return 0
    except (LabError, OSError, ValueError, KeyError, TypeError) as exc:
        print(visible(f"错误：{exc}"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断；此前创建的文件仍保留，请检查工作区。", file=sys.stderr)
        return 130
