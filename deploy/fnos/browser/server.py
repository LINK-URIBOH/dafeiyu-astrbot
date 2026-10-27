#!/usr/bin/env python
"""Linux BrowserMCP: AstrBot -> project Docker network -> Chromium.

Only read actions are exposed. No desktop, phone or SSH reverse proxy is used.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from browser_use import Agent, Browser, ChatDeepSeek, Tools
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

HERE = Path(__file__).resolve().parent

HOST = os.environ.get("BROWSER_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("BROWSER_MCP_PORT", "8010"))
SSE_PATH = os.environ.get("BROWSER_MCP_SSE_PATH", "/Browser")
MESSAGE_PATH = os.environ.get("BROWSER_MCP_MESSAGE_PATH", "/Browser/messages/")

MODEL = os.environ.get("BROWSER_MODEL", "deepseek-flash")
HEADLESS = os.environ.get("BROWSER_HEADLESS", "1").lower() not in {"0", "false", "no"}
MAX_STEPS_DEFAULT = int(os.environ.get("BROWSER_MAX_STEPS", "8"))
TASK_TIMEOUT = int(os.environ.get("BROWSER_TASK_TIMEOUT", "180"))

CHROME_PATH = os.environ.get(
    "BROWSER_CHROME_PATH", "/usr/bin/chromium"
)
PROFILE_DIR = Path(
    os.environ.get("BROWSER_PROFILE_DIR", "/data/profile")
)
ALLOWLIST_FILE = HERE / "browser_allowlist.txt"

READ_ONLY_POLICY = """你是大肥鱼的只读网页助手。必须遵守：
1. 只允许浏览、搜索、读取、提取信息。
2. 禁止登录、注册、支付、下单、购买、充值、发帖、评论、点赞、投币、收藏、私信、删除、修改账户设置。
3. 如果任务要求上述写操作，直接拒绝并在最终结果里说明。
4. 不要下载或执行任何文件。
5. 优先读取公开页面，遇到验证码、登录要求或访问限制立即停止，不关闭登录浮层，不重试。
6. 浏览 B 站时最多选三条内容；区分页面标题/简介与实际看过的内容，只报告可核对的信息。没有核实视频完整链接的条目不推荐。
7. 完成后用中文简短汇报，附上关键链接。
"""

READ_ACTIONS = {'done', 'search', 'navigate', 'go_back', 'wait', 'switch', 'close',
                'extract', 'search_page', 'find_elements', 'scroll', 'find_text'}
ACCESS_MARKERS = ('请先登录', '登录后查看', '扫码登录', '短信登录', '密码登录', '账号密码登录',
                  '登录后你可以', '登录后即可', '立即登录', '请登录', '扫描二维码',
                  '验证码', '安全验证', '访问受限', '风控验证', 'verify you are human', 'captcha')

def blocked_access(text: str) -> bool:
    text = text.lower()
    return any(marker in text for marker in ACCESS_MARKERS)

def reported_login_wall(text: str) -> bool:
    for negative in ('未出现登录', '没有登录浮层', '未遇到登录', '无登录弹窗', '未弹出登录', '没有登录弹窗'):
        text = text.replace(negative, '')
    return any(marker in text.lower() for marker in ('登录浮层', '登录弹窗', '登录面板', '登录框', 'login modal', 'login popup', 'login wall'))

class ReadOnlyAgent(Agent):
    """Guard browser-use 0.13.11 before its model can choose the next action."""
    blocked_reason: str | None = None

    async def _get_next_action(self, browser_state_summary):
        dom = browser_state_summary.dom_state
        text = dom.llm_representation() if dom else ''
        if blocked_access(text):
            self.blocked_reason = '公开页面出现登录要求、验证码或访问限制，已立即停止；本次不提供未核实的推荐。'
            raise RuntimeError(self.blocked_reason)
        result = await super()._get_next_action(browser_state_summary)
        output = self.state.last_model_output
        if output and reported_login_wall(output.model_dump_json()):
            self.blocked_reason = '浏览器检测到登录浮层，已停止；本次不提供推荐，也不关闭浮层或重试。'
            raise RuntimeError(self.blocked_reason)
        return result


class ChatDeepSeekNoThinking(ChatDeepSeek):
    """deepseek-flash 默认开思考，会拒绝 browser-use 的 tool_choice。

    browser-use 的适配器只在模型名含 deepseek-v4 时才发送 thinking 参数；
    这里强制它发送 thinking=disabled，让 deepseek-flash 能走 function calling。
    """

    def _supports_thinking(self) -> bool:
        return True


mcp = MCPServer(
    "BrowserMCP",
    instructions="只读浏览器助手：在独立 Chrome 中浏览、搜索、提取网页信息。",
)
_task_lock = asyncio.Lock()

def cleanup_stale_profile_locks() -> None:
    # The dedicated container has no browser at server startup. Chromium stores
    # its old container hostname in these symlinks, which survive recreation.
    for proc in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            command = proc.read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b'chromium' in command and b'--user-data-dir' in command:
            raise RuntimeError('An existing Chromium process owns the browser profile')
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        path = PROFILE_DIR / name
        if path.is_symlink():
            path.unlink()


def _load_allowlist() -> list[str] | None:
    if not ALLOWLIST_FILE.exists():
        return None
    domains = []
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            domains.append(line)
    return domains or None


@mcp.tool()
async def browser_task(task: str, max_steps: int = MAX_STEPS_DEFAULT) -> str:
    """在 Linux 容器内的独立 Chromium 中执行一个只读网页任务。

    Args:
        task: 中文任务描述，例如“打开 B 站搜索某个主题，返回前三条视频标题和链接”。
        max_steps: 最大执行步数，默认及上限均为 8。

    Returns:
        任务的最终结果（中文文本）；失败或超时返回错误说明。
    """
    if not task or not task.strip():
        return "任务描述为空。"
    if len(task) > 2000:
        return "任务描述过长（上限 2000 字）。"
    steps = max(1, min(int(max_steps), 8))

    async with _task_lock:
        try:
            return await asyncio.wait_for(
                _run_task(task.strip(), steps), timeout=TASK_TIMEOUT
            )
        except asyncio.TimeoutError:
            return f"任务超时（{TASK_TIMEOUT} 秒），已中止。"
        except Exception as exc:
            return f"浏览器任务失败：{type(exc).__name__}。请查看服务日志中的脱敏诊断。"


async def _run_task(task: str, max_steps: int) -> str:
    browser = Browser(
        executable_path=CHROME_PATH,
        headless=HEADLESS,
        user_data_dir=str(PROFILE_DIR),
        enable_default_extensions=False,
        chromium_sandbox=False,
        allowed_domains=_load_allowlist(),
    )
    try:
        tools = Tools()
        tools.registry.registry.actions = {name: action for name, action in tools.registry.registry.actions.items() if name in READ_ACTIONS}
        agent = ReadOnlyAgent(
            task=READ_ONLY_POLICY + "\n\n任务：" + task,
            llm=ChatDeepSeekNoThinking(model=MODEL),
            browser=browser,
            tools=tools,
            use_vision=False,
            use_judge=False,
            enable_signal_handler=False,
            max_failures=1,
            max_actions_per_step=1,
            enable_planning=False,
            final_response_after_failure=False,
            step_timeout=60,
        )
        result = await agent.run(max_steps=max_steps)
        if agent.blocked_reason:
            return agent.blocked_reason
        final = result.final_result()
        return final or "任务执行完毕，但没有返回文本结果。"
    finally:
        try:
            await browser.kill()
        except Exception:
            pass


@mcp.tool()
async def browser_health() -> str:
    """检查 Browser Use 服务是否就绪（不执行网页任务，不消耗模型 token）。"""
    allow = _load_allowlist()
    return (
        f"ok; model={MODEL}; headless={HEADLESS}; profile={PROFILE_DIR}; "
        f"allowlist={len(allow) if allow else 'off'}; chrome={CHROME_PATH}"
    )


if __name__ == "__main__":
    cleanup_stale_profile_locks()
    print(f"BrowserMCP listening on {HOST}:{PORT} (sse={SSE_PATH})", flush=True)
    mcp.run(transport="sse", host=HOST, port=PORT, sse_path=SSE_PATH,
            message_path=MESSAGE_PATH,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
