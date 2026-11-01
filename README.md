# 1 实验：RTX 5090 本地 AI 自动化

第一个可运行原型：**本地大模型 → 提议工具调用 → Python 校验/执行 → 回传结果 → 下一步**。
目标显卡为 RTX 5090 32GB；Windows 原生和 Linux 分别提供安装路线，不要求已经配置 Python、Ollama 或 CUDA。

第一版可计算、列出实验目录、读文本、创建文本报告。默认写入只预览；加 `--apply` 后仍须逐次确认。
Python 工具是项目预先写好的函数，不是执行模型随意生成的 Python 代码。

## 先看验证状态

- 已在开发环境 Linux / Python 3.12.14 通过 34 项离线测试，包括真实本机 HTTP 连接到模拟 Ollama 服务、工具回传和文件边界测试。
- 离线演示可完成「读取采购数据 → 计算 997 元 → 预览/创建报告」。模拟响应不代表大模型已验证。
- **尚未在你的 RTX 5090 上验证**模型下载/加载、真实 tool calling 稳定性、显存占用、速度和驱动兼容性。真实验收使用 `doctor`、`smoke`、`ollama ps`。
- 仓库附 Windows/Linux、Python 3.11/3.12 的 GitHub Actions；云端结果以 PR Checks 为准，详见 [验证记录](docs/VALIDATION.md)。

## 选择的模型与框架

截至 2026-11-01 核对官方资料，Ollama 明确列出 RTX 5090（计算能力 12.0）支持。

| 用途 | Ollama 标签 | 官方模型文件大小 | 本项目设置 |
| --- | --- | --- | --- |
| 默认，发挥 32GB 显存 | `qwen3.5:27b-q4_K_M` | 约 17GB | 8192 上下文，关闭思考输出 |
| 较小的排障/入门备选 | `qwen3:14b-q4_K_M` | 约 9.3GB | 相同配置，可直接替换 model |

两者均声明 tools 能力。**模型文件大小不等于总显存占用**：还需要运行时缓冲、KV cache，以及桌面占用。
27B Q4 + 8K 是针对 32GB 显存的起始配置建议，不是已测得的适配保证。显存紧张先降上下文至 4096，
同时把 `num_predict` 改为 1024，或改用 14B。不要直接使用模型标称的 256K 上下文。
模型标签可能更新；用 `ollama list` 记录 ID，用 `doctor` 记录 Ollama 版本。

| 框架 | 这次的取舍 |
| --- | --- |
| Ollama | 默认。Windows 原生/Linux 安装、本地 HTTP API 和 tools 协议适合第一个项目。客户端不需要 PyTorch。 |
| llama.cpp | 后续需要 GGUF、推理参数和底层服务控制时考虑；本项目暂未实现其接口适配。 |
| vLLM | 后续评估并发服务时再考虑；官方 GPU 路线依赖 Linux/CUDA/PyTorch，Windows 需 WSL 等额外环境。 |

硬件起点：32GB 系统内存可先尝试，建议 64GB；SSD 预留约 60GB 给两个量化模型、下载和环境。
这些是容量规划建议。此客户端仅使用 Python 标准库，性能主要取决于 Ollama、模型和驱动。
详细来源和选择依据见 [模型与框架](docs/MODELS.md)。

## 从零安装：Windows

使用 RTX 5090 所在的 Windows 机器；建议 Windows 11。第一版选原生 Windows，不需要 Docker/WSL。

1. 从 [NVIDIA 官方驱动页](https://www.nvidia.com/Download/index.aspx) 安装与你的系统、RTX 5090 匹配的驱动，按安装器要求重启。
   不要把框架文档中的通用最低版本当作 5090 可用驱动。
2. 从 [Python 官网](https://www.python.org/downloads/windows/) 安装 Python 3.11 或更新版本，建议 3.12+；启用 Python Launcher/PATH。
3. 从 [Git 官网](https://git-scm.com/downloads/win) 安装 Git；从 [Ollama 官网](https://ollama.com/download/windows) 安装 Ollama。
4. 重新打开 PowerShell，执行：

```powershell
nvidia-smi
py -3 --version
git --version
ollama --version
```

`nvidia-smi` 应列出 RTX 5090 和约 32GB 显存。若任何命令找不到，先完成对应安装/PATH 设置。

退出托盘中的 Ollama，设置仅本地运行，然后从开始菜单重新打开 Ollama：

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_NO_CLOUD", "1", "User")
```

获取本 PR 的代码（合并后可省略 `-b feat/local-ai-5090`）：

```powershell
git clone -b feat/local-ai-5090 https://github.com/1a2s3d4f-xkf/1.git local-ai-5090
cd local-ai-5090
py -3 -m venv .venv
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m local_ai init
.\.venv\Scripts\python.exe -m local_ai demo
```

这里直接使用虚拟环境解释器，无须修改 PowerShell 执行策略。依赖文件为空是有意设计：运行和测试均无第三方 Python 依赖。

下载并验证真实模型：

```powershell
ollama pull qwen3.5:27b-q4_K_M
.\.venv\Scripts\python.exe -m local_ai doctor
.\.venv\Scripts\python.exe -m local_ai smoke
ollama ps
nvidia-smi
```

模型下载需联网；下载成功并关闭云功能后，日常推理使用本机服务，不需要云 API Key。
如果尚未安装完 Ollama，也可先运行前面的离线测试和 demo。

## 从零安装：Linux

以下系统包命令针对 **Ubuntu 24.04**；其他发行版使用各自的包管理器，不要照搬 `apt`。

1. 通过发行版「附加驱动」或 NVIDIA 官方安装指南安装支持 RTX 5090 的驱动，必要时重启。
   Secure Boot 开启时，按发行版提示完成驱动模块签名/注册。确认 `nvidia-smi` 正常。
2. 安装 Python/Git/curl，然后安装官方 Ollama：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl
python3 --version
nvidia-smi
curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
less /tmp/ollama-install.sh
sh /tmp/ollama-install.sh
```

如果安装器创建了 systemd 服务，执行 `sudo systemctl edit ollama`，加入：

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NO_CLOUD=1"
```

保存后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama --version
```

若没有 systemd，在单独终端运行并保持该终端打开：

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 ollama serve
```

只启动一种服务方式，避免端口冲突。随后在另一个终端：

```bash
git clone -b feat/local-ai-5090 https://github.com/1a2s3d4f-xkf/1.git local-ai-5090
cd local-ai-5090
python3 -m venv .venv
source .venv/bin/activate
cp config.example.json config.json
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m local_ai init
python -m local_ai demo
ollama pull qwen3.5:27b-q4_K_M
python -m local_ai doctor
python -m local_ai smoke
ollama ps
nvidia-smi
```

本项目不要求手动安装 CUDA Toolkit 或 PyTorch。驱动与 Ollama 负责 GPU 推理。
macOS 可以研究代码/离线演示，但不能作为 RTX 5090 的同一硬件验收环境；本轮未提供 macOS GPU 路线。

## 第一个真实任务

下面的 `python`：Linux 指已激活虚拟环境的解释器；Windows 替换为 `.\.venv\Scripts\python.exe`。
从项目根目录运行。

```bash
python -m local_ai run "读取 sample.json，调用 calculate 计算每项金额和总价，创建 report.md，并说明实际是否写入成功。"
```

默认预览：应显示读取、计算和写入预览，**不会创建 report.md**。模型可能偏离指令，以工具日志为准。
批准真实创建：

```bash
python -m local_ai run --apply "读取 sample.json，调用 calculate 计算总价，并创建 report.md。"
```

终端将显示完整待写内容，输入 **`WRITE report.md`** 才会创建。其他输入/EOF 都拒绝并停止任务；
重定向或管道输入不能批准。程序没有 `--yes` 模式。重复运行遇到已有文件会报错，可手动换一个输出文件名。
路径始终相对于 `config.json` 所在目录的 `workspace/`，不是整个电脑。

完全离线演示的真实写入使用 `python -m local_ai demo --apply`，确认字符串是 `WRITE demo-report.md`。
默认样例总价：`399*1 + 299*2 = 997`。

更小模型备选：执行 `ollama pull qwen3:14b-q4_K_M`，在 `config.json` 将 `model` 改为该标签，再执行 `doctor` 和 `smoke`。
本项目读取 JSON 配置，不读取 `.env`。不要在配置里添加 API Key。

## 工具和项目结构

| 工具 | 实际执行的 Python 逻辑 | 边界 |
| --- | --- | --- |
| `calculate` | AST 白名单计算四则运算 | 无 eval/exec，禁止函数调用/幂运算，数值限制 ±1e12 |
| `list_files` | 列出一个目录 | 不递归，最多扫描 200 项，只列可用的文件/目录 |
| `read_text` | 读取 UTF-8 文本 | 默认 8KiB；仅 .txt/.md/.json/.csv |
| `write_text` | 独占创建新文本文件 | 默认预览；逐次批准；禁止覆盖、删除、自动创建父目录 |

| 文件 | 作用 |
| --- | --- |
| `local_ai/client.py` | 本机 Ollama API、连接超时、响应上限、远程模型检测 |
| `local_ai/agent.py` | 顺序工具循环，最多 6 轮模型请求/12 次工具调用 |
| `local_ai/tools.py` | 工具注册表、参数校验、确认和审计日志 |
| `local_ai/safety.py` | 路径、链接、文件大小、类型和终端字符防护 |
| `local_ai/demo.py` | 明确标识为模拟模型的离线演示 |
| `local_ai/cli.py` | init / doctor / smoke / demo / run 命令 |
| `config.example.json` | 本地配置模板；工作区和审计位置不能由模型更改 |
| `tests/` | 安全回归和模拟 HTTP 集成测试，不下载模型 |
| `docs/` | 模型依据、安全边界、验证记录和故障排查 |

审计写入 `.local-ai/audit.jsonl`，只记录时间、run_id、已知工具名、状态和参数摘要哈希，不保存原始输入/输出。
日志和实验数据均被 `.gitignore` 排除。终端可能展示模型/文件内容，请勿在实验目录放入真实密码或个人资料。
它是**应用层约束原型，不是操作系统安全沙箱**；重要局限见 [安全说明](docs/SECURITY.md)。

## 遇到问题

- 服务连接失败：检查 Ollama 是否运行，配置是否为 `http://127.0.0.1:11434`，不要填云端 URL。
- 提示模型不存在：`ollama list` 核对标签，重新 `ollama pull` 配置中的标签。
- `smoke` 失败：更新 Ollama、保持 `think: false`，再试 14B。不得把普通文字回答当作成功调用工具。
- 首次加载超时：可将 `timeout_seconds` 调至 300；模型加载/生成速度尚无本机保证。
- 显存不足或 CPU 卸载：关闭其他 GPU 程序，降低上下文/模型尺寸，推理后看 `ollama ps` 的 PROCESSOR。
- 根目录含链接/junction：把项目放入普通本地目录，例如 `C:\ai\local-ai-5090` 或 `~/local-ai-5090`。

更多情况见 [本机验收与排障](docs/VALIDATION.md)。后续扩展先增加只读截图/页面观察，再设计受控鼠标键盘动作；
不应直接把 unrestricted shell、浏览器登录或整个用户目录交给模型。
