# 验证记录与本机验收

日期：2026-11-01。开发环境 Linux，Python 3.12.14。该环境没有 Ollama 可执行文件；没有在此使用 RTX 5090 推理。

## 已执行

```bash
python3 -m unittest discover -s tests -v
```

结果：34 项测试通过，0 失败，0 跳过（开发环境）。范围：

- 真实 loopback HTTP socket 上的模拟 Ollama 服务，验证 UTF-8 请求、工具 Schema、assistant/tool 消息往返。
- 404/500/重定向/无效 JSON/响应超限/超时处理，远程模型别名和不支持工具的模型拒绝。
- 模拟模型的完整读取→计算→批准新建流程，验证结果实际落盘为 997；预览不产生报告文件。
- 路径越界、Windows 路径/保留名/ADS、符号链接、硬链接、FIFO、模拟 reparse 属性、UTF-8 与大小限制。
- 非交互批准拒绝、批准后目标变化、审计失败、参数过滤、调用预算与终止行为。

这些 HTTP 测试不是连接真实 Ollama 的结果。Windows 原生执行和 GitHub Actions 状态以实际 CI 输出为准。
软件包安装（可选 `pip install -e .`）和实际模型速度不属于上述测试结果。

另已实际执行 README 的虚拟环境创建、空 requirements 安装、CLI init、demo 预览、
TTY 中 demo --apply 的精确批准，并读取落盘报告确认总价为 997。
`compileall` 和 `git diff --cached --check` 通过；真实 Ollama 的 doctor/smoke 尚未在开发环境运行。

## 你电脑上的分级验收

Windows 把下方 `python` 替换为 `.\.venv\Scripts\python.exe`；Linux 激活虚拟环境。

| 步骤 | 命令 | 通过标准 |
| --- | --- | --- |
| 1. 硬件 | `nvidia-smi` | 正确列出 RTX 5090、显存和驱动版本 |
| 2. 离线测试 | `python -m unittest discover -s tests -v` | 无失败；记录实际 skipped 数，不隐藏 OS 差异 |
| 3. 离线演示 | `python -m local_ai init` 后 `python -m local_ai demo` | 算出 997；只预览且不创建报告 |
| 4. 服务/模型 | `python -m local_ai doctor` | 版本输出，模型声明 tools，无 remote 字段拒绝 |
| 5. 真实工具往返 | `python -m local_ai smoke` | 输出 PASS，实际 calculate 返回 56088，模型继续回答 |
| 6. GPU 驻留 | smoke 后立即 `ollama ps` 与 `nvidia-smi` | 核对模型 PROCESSOR 和显存；优先达到 100% GPU |
| 7. 真实文件任务 | README 中 run 命令，先预览后 --apply | 实际读 sample.json、算出997、经确认新建报告；不得覆盖 |
| 8. 拒绝操作 | 在 --apply 确认提示处回车 | 非零退出，任务停止，无新报告 |

`doctor` 不执行推理，可能显示 running_models=[]；这不代表模型无法使用 GPU。运行 smoke 后再看驻留。
`smoke` 不自动批准文件写入；其成功检查工具执行的数值而非仅搜索模型回答中的数字。
CLI 的成功退出代表调用循环正常结束，不保证模型满足所有自然语言要求，最终仍需查看工具记录和产物。

## 结果记录模板

不要把私人机器名/账号、实际任务输入或原始审计日志提交到公共仓库。

| 项目 | 本机填写 |
| --- | --- |
| OS / Python | 待测 |
| NVIDIA 驱动 / 显卡可用显存 | 待测 |
| Ollama 版本 / 模型标签及 ID | 待测 |
| num_ctx / num_predict | 默认 8192 / 2048 |
| 离线测试结果/跳过项 | 待测 |
| smoke 多次成功次数 | 待测 |
| ollama ps PROCESSOR | 待测 |
| 热启动生成 token/s / 端到端耗时 | 待测 |
| 文件预览/批准/拒绝 | 待测 |

## 排障顺序

1. `nvidia-smi` 失败：先修驱动，不要依靠更换 Python 包解决。Windows/Linux 的驱动安装步骤不同。
2. 本机 HTTP 不通：确认托盘程序或 Linux 服务运行，端口与配置一致；不要同时运行两份 ollama serve。
3. 模型 404：对照 `ollama list` 和 config 的完整名称，先 pull。网络受限时完成官方模型下载再验收。
4. API 不识别模型/think/tools：更新官方 Ollama，换 `qwen3:14b-q4_K_M` 对照；不要删除执行器的参数校验来“修复”。
5. 显存不足：先 `ollama stop` 停止不使用的已加载模型，关闭其他 GPU 应用；然后降上下文至4096、输出至1024或换14B。
6. CPU/GPU 混合驻留：这是卸载到内存的迹象，能运行不代表充分使用5090。以 ollama ps 和驱动日志确认原因。
7. 工具调用次数耗尽/截断：缩小任务、保持 think=false，合理调整输出预算；不要无上限重试。
8. 拒绝链接/junction：移动到普通本地目录，避免 OneDrive/同步盘/网络盘重解析路径；不要关闭保护绕过。
9. 文件已存在：手动换输出名。初始化不会恢复被人工修改的 sample.json；要恢复样例，先备份并手动移走旧文件再 init。
