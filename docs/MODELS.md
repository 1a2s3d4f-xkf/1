# 模型与框架选择依据

资料核对日期：2026-11-01。这里的适配判断是依据官方规格所作的工程选择，尚无此用户机器的实测数据。

## 为什么选这一组合

Ollama 的硬件支持页明确列出 RTX 5090，计算能力 12.0。使用官方当前安装包和匹配该卡的 NVIDIA 驱动，
避免旧版推理框架不认识 Blackwell 的问题。Windows 原生路径可以减少首个项目的环境配置步骤。

默认 `qwen3.5:27b-q4_K_M`：官方条目标注约 17GB、Q4_K_M、tools/vision/thinking。此次只使用文本和 tools，
没有接入图像、鼠标键盘。27B Q4 给 32GB 卡留下运行时余量，但 8K 上下文、桌面占用、版本和后端都影响实际显存。
`qwen3:14b-q4_K_M` 约 9.3GB，作为更轻的工具调用备选。我们没有声称二者哪个速度更快或成功率更高。

不默认使用 BF16 大模型或超长上下文，也不假设 32GB 可以容纳任意 32B/70B 模型。
模型的“文件大小”、运行时“驻留内存”和显卡“剩余显存”是不同量。

客户端使用 Ollama 原生 `/api/chat`，请求 `stream: false` 并传递 `tools` JSON Schema；
每次把原 assistant 消息和 `role=tool, tool_name=...` 结果回传。执行器严格顺序运行，不并行修改文件。
调用前用 `/api/show` 检查 tools 能力和 remote_host/remote_model，拒绝检测到的远程模型。
这不能替代对本机 Ollama 服务的信任；使用官方服务并设置 `OLLAMA_NO_CLOUD=1`。

llama.cpp 提供更底层的 GGUF 推理与服务能力，适合后续调参；vLLM 官方 GPU 安装有 Linux 和 CUDA/PyTorch 兼容要求，
更适合作为后续独立环境评估。当前只有 Ollama 适配器，不会自动切换其他框架。

## 官方来源

| 主题 | 来源 |
| --- | --- |
| Ollama GPU/RTX 5090 支持 | https://docs.ollama.com/gpu |
| 默认模型、量化和文件体积 | https://ollama.com/library/qwen3.5:27b-q4_K_M |
| 备选模型、量化和文件体积 | https://ollama.com/library/qwen3:14b-q4_K_M |
| 工具调用与结果回传 | https://docs.ollama.com/capabilities/tool-calling |
| chat 参数、think 和统计 | https://docs.ollama.com/api/chat |
| 模型详情与能力查询 | https://docs.ollama.com/api-reference/show-model-details |
| remote_host / remote_model 字段定义 | https://github.com/ollama/ollama/blob/main/api/types.go （ShowResponse） |
| GPU 驻留、关闭云功能、上下文配置 | https://docs.ollama.com/faq |
| Windows / Linux 安装 | https://docs.ollama.com/windows 、 https://docs.ollama.com/linux |
| llama.cpp | https://github.com/ggml-org/llama.cpp |
| vLLM GPU 环境与 Windows 限制 | https://docs.vllm.ai/en/latest/getting_started/installation/gpu/ |

## 可复现的本机记录

模型标签不是不可变版本。安装成功后人工记录：OS、Python 版本、NVIDIA 驱动、Ollama 版本、
`ollama list` 中模型 ID、config.json、`ollama ps` 的上下文和 PROCESSOR。
首次运行包括模型加载，不宜与热启动速度直接比较。CLI 显示 API 返回的生成 token/s，
它不包括加载和输入处理时间，也不等于完整任务延迟。真实可靠性至少用多次 smoke 和多次完整任务分别观察。
