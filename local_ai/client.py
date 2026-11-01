"""Small Ollama native HTTP adapter; no SDK, redirects, proxies or retries."""

import http.client
import json
import socket
from urllib.parse import urlsplit

from .config import Config, LabError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class OllamaClient:
    def __init__(self, config: Config):
        self.config = config

    def request(self, path, body=None):
        u = urlsplit(self.config.base_url)
        # A literal loopback address is required by Config, so no DNS/proxy route.
        connection = http.client.HTTPConnection(u.hostname, u.port,
                                                timeout=self.config.timeout_seconds)
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            connection.request("GET" if body is None else "POST", path, payload,
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise LabError("Ollama 响应超过 2 MiB，已停止")
            if response.status != 200:
                hint = "；请用 ollama pull 下载配置中的模型" if response.status == 404 else ""
                raise LabError(f"Ollama HTTP {response.status}{hint}；检查 Ollama 服务日志")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("error"):
                raise LabError("Ollama 返回了错误或非对象响应")
            return data
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            raise LabError("无法连接本机 Ollama 或请求超时；检查服务/端口，首次加载可增加 timeout_seconds") from exc
        except (ValueError, UnicodeError) as exc:
            raise LabError("Ollama 返回的不是有效 JSON") from exc
        finally:
            connection.close()

    def preflight(self):
        version = self.request("/api/version")
        info = self.request("/api/show", {"model": self.config.model})
        if info.get("remote_host") or info.get("remote_model"):
            raise LabError("检测到远程模型，拒绝发送任务")
        capabilities = info.get("capabilities", [])
        if not isinstance(capabilities, list) or "tools" not in capabilities:
            raise LabError("模型未声明 tools 能力；请更新 Ollama 或切换推荐模型")
        return {"ollama_version": version.get("version"), "model": self.config.model,
                "capabilities": capabilities, "details": info.get("details", {})}

    def chat(self, messages, tools):
        return self.request("/api/chat", {
            "model": self.config.model, "messages": messages, "tools": tools,
            "stream": False, "think": self.config.think, "keep_alive": "5m",
            "options": {"num_ctx": self.config.num_ctx, "num_predict": self.config.num_predict,
                        "temperature": 0},
        })
