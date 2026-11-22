"""Real Chromium, synthetic local HTML, no Internet or model calls."""
import asyncio
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_use import Browser
from browser_use.dom.views import DEFAULT_INCLUDE_ATTRIBUTES
from access_guard import OBSERVE_ACCESS
from server import blocked_access


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'<html><body>fixture</body></html>')

    def log_message(self, *args):
        pass


TIP = '''<div class="header-avatar-unlogin-wrap"><div class="login-panel-popover"
    style="position:absolute;left:65vw;top:77px;width:359px;height:235px">
    登录后你可以 免费看高清视频 <div>立即登录</div>{extra}</div></div>'''
CONTENT = '<main><h1>综合热门</h1><a href="/video/BV1Test123456">公开视频标题</a><span>UP主</span></main>'


class DomTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dom_matrix(self):
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        fixtures = [
            ('public', CONTENT, False),
            ('ordinary_header_button', '<header><button>立即登录</button></header>' + CONTENT, False),
            ('observed_bili_tip', TIP.format(extra='') + CONTENT, False),
            ('masked_tip', TIP.format(extra='') + CONTENT + '<div class="mask" style="position:fixed;inset:0"></div>', True),
            ('unknown_mask', TIP.format(extra='') + CONTENT + '<div style="position:fixed;inset:0;z-index:9999"></div>', True),
            ('tip_without_public_content', TIP.format(extra=''), True),
            ('central_login', CONTENT + '<div role="dialog" style="position:fixed;top:30%;left:30%">扫码登录<input type="password"></div>', True),
            ('login_only', '<main>请先登录后查看</main>', True),
            ('restricted', CONTENT + '<div>访问受限</div>', True),
            ('captcha_text', CONTENT + '<div>安全验证 请输入验证码</div>', True),
            ('captcha_without_text', CONTENT + '<div class="captcha" style="width:300px;height:100px"></div>', True),
            ('captcha_iframe', CONTENT + '<iframe src="about:blank#captcha" style="width:300px;height:100px"></iframe>', True),
            ('password_without_text', CONTENT + '<input type="password">', True),
            ('otp_without_text', CONTENT + '<input autocomplete="one-time-code">', True),
            ('qr_without_text', CONTENT + '<div class="login"><canvas></canvas></div>', True),
            ('hidden_login', CONTENT + '<div style="display:none">扫码登录</div>', False),
            ('hidden_captcha', CONTENT + '<div class="captcha" style="display:none;width:300px;height:100px"></div>', False),
            ('form_in_tip', TIP.format(extra='<input type="password">') + CONTENT, True),
            ('qr_in_tip', TIP.format(extra='<canvas></canvas>') + CONTENT, True),
            ('challenge_in_tip', TIP.format(extra='验证码') + CONTENT, True),
            ('modal_parent', '<div role="dialog">' + TIP.format(extra='') + '</div>' + CONTENT, True),
            ('oversized_tip', TIP.format(extra='').replace('height:235px', 'height:650px') + CONTENT, True),
        ]
        with tempfile.TemporaryDirectory() as profile:
            browser = Browser(executable_path='/usr/bin/chromium', headless=True,
                              user_data_dir=profile, enable_default_extensions=False,
                              chromium_sandbox=False,
                              args=['--host-resolver-rules=MAP www.bilibili.com 127.0.0.1'])
            try:
                await browser.start()
                page = await browser.get_current_page()
                await page.goto(f'http://www.bilibili.com:{http.server_port}/')
                await asyncio.sleep(0.5)
                for name, html, expected in fixtures:
                    with self.subTest(name=name):
                        await page.evaluate('(html) => { document.body.innerHTML = html; }', html)
                        observed = json.loads(await page.evaluate(OBSERVE_ACCESS))
                        actual = observed['challenge'] or blocked_access(observed['text'])
                        self.assertEqual(actual, expected, observed)
                        if name == 'public':
                            state = await browser.get_browser_state_summary(include_screenshot=False, cached=False)
                            serialized = state.dom_state.llm_representation([*DEFAULT_INCLUDE_ATTRIBUTES, 'href'])
                            self.assertIn('/video/BV1Test123456', serialized)
                # Exemption is tied to the observed official host, not arbitrary lookalike HTML.
                await page.goto(f'http://127.0.0.1:{http.server_port}/')
                await asyncio.sleep(0.5)
                await page.evaluate('(html) => { document.body.innerHTML = html; }', TIP.format(extra='') + CONTENT)
                observed = json.loads(await page.evaluate(OBSERVE_ACCESS))
                self.assertTrue(blocked_access(observed['text']))
                print('DOM matrix: 23 cases verified')
            finally:
                await browser.kill()
                http.shutdown()
                http.server_close()


if __name__ == '__main__':
    unittest.main()
