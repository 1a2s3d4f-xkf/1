"""Deterministic fake model: proves orchestration, never claims GPU inference."""

import json

SAMPLE = {"items": [{"name": "键盘", "price": 399, "quantity": 1},
                    {"name": "鼠标", "price": 299, "quantity": 2}]}
DEMO_PROMPT = "读取 sample.json，用 calculate 计算总价，并创建 demo-report.md。"


class DemoClient:
    def __init__(self):
        self.step = 0

    def chat(self, messages, tools):
        self.step += 1
        if self.step == 1:
            name, args = "read_text", {"path": "sample.json"}
        else:
            result = json.loads(messages[-1]["content"])
            if not result.get("ok"):
                return {"done": True, "message": {"role": "assistant", "content": "演示停止：" + result["error"]}}
            if self.step == 2:
                items = json.loads(result["content"])["items"]
                expression = "+".join(f"{x['price']}*{x['quantity']}" for x in items)
                name, args = "calculate", {"expression": expression}
            elif self.step == 3:
                name, args = "write_text", {"path": "demo-report.md",
                                           "content": f"# 采购合计\n\n总价：{result['value']} 元。\n"}
            else:
                state = "已创建" if result.get("created") else "仅预览，未创建"
                return {"done": True, "message": {"role": "assistant", "content": f"{state} demo-report.md。此演示未调用真实模型。"}}
        return {"done": True, "message": {"role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}]}}
