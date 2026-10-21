"""Local QR login; credential values never reach stdout, chat, or tool results."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp

from bili_api import BiliAPI, BiliError, UA, private_json

PASSPORT = "https://passport.bilibili.com"
COOKIE_NAMES = {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3", "buvid4"}


def login_cookies(response_cookies, payload):
    """Support web polling's Set-Cookie/callback URL and legacy cookie_info."""
    cookies = {k: str(getattr(v, "value", v)) for k, v in response_cookies.items() if k in COOKIE_NAMES}
    for item in (payload.get("cookie_info") or {}).get("cookies", []):
        if item.get("name") in COOKIE_NAMES:
            cookies.setdefault(item["name"], str(item["value"]))
    url = urlparse(str(payload.get("url") or ""))
    if url.scheme == "https" and (url.hostname or "").endswith(".bilibili.com"):
        for k, values in parse_qs(url.query).items():
            if k in COOKIE_NAMES and len(values) == 1:
                cookies.setdefault(k, values[0])
    if not all(cookies.get(k) for k in ("SESSDATA", "bili_jct", "DedeUserID")):
        raise BiliError("QR confirmation did not supply usable credentials")
    return cookies


async def get_json(session, endpoint, params=None):
    async with session.get(PASSPORT + endpoint, params=params, allow_redirects=False) as response:
        if response.status != 200:
            raise BiliError(f"login HTTP {response.status}")
        raw = bytearray()
        async for chunk in response.content.iter_chunked(8192):
            raw.extend(chunk)
            if len(raw) > 256_000:
                raise BiliError("login response too large")
        result = json.loads(raw)
        if result.get("code") != 0:
            raise BiliError("login API rejected request")
        return result.get("data") or {}, response.cookies


async def login(state_dir, timeout=240, open_image=True):
    import qrcode
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    qr_path = state / "login-qr.png"
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20), trust_env=True,
        cookie_jar=aiohttp.DummyCookieJar(), headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
    ) as session:
        data, _ = await get_json(session, "/x/passport-login/web/qrcode/generate")
        key, url = data["qrcode_key"], data["url"]
        parsed = urlparse(url)
        # Bilibili currently returns account.bilibili.com for QR scans; keep a
        # strict host allowlist rather than trusting any bilibili subdomain.
        if parsed.scheme != "https" or parsed.hostname not in {
            "passport.bilibili.com", "account.bilibili.com",
        }:
            raise BiliError("unexpected QR destination")
        qrcode.make(url).save(qr_path)
        os.chmod(qr_path, 0o600)
        print(f"请用B站手机App扫码：{qr_path.resolve()}", flush=True)
        if open_image and os.name == "nt":
            os.startfile(qr_path)  # type: ignore[attr-defined]
        deadline = time.monotonic() + min(600, max(30, timeout))
        try:
            while time.monotonic() < deadline:
                poll, cookies = await get_json(session, "/x/passport-login/web/qrcode/poll", {"qrcode_key": key})
                code = poll.get("code")
                if code == 0:
                    values = login_cookies(cookies, poll)
                    # Validate before replacing a previously working credential file.
                    headers = {"User-Agent": UA, "Cookie": "; ".join(f"{k}={v}" for k, v in values.items())}
                    async with session.get("https://api.bilibili.com/x/web-interface/nav", headers=headers,
                                           allow_redirects=False) as check:
                        nav = await check.json()
                        if check.status != 200 or nav.get("code") != 0 or not (nav.get("data") or {}).get("isLogin"):
                            raise BiliError("login confirmation failed nav verification")
                    private_json(state / "cookies.json", {"cookies": values, "refresh_token": poll.get("refresh_token"), "updated_at": time.time()})
                    print("登录已验证，凭证已保存到本地运行目录。", flush=True)
                    return
                if code == 86038:
                    raise BiliError("QR expired; rerun local login")
                if code not in {86101, 86090}:
                    raise BiliError("unexpected QR polling state")
                await asyncio.sleep(2)
            raise BiliError("QR login timed out")
        finally:
            qr_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    try:
        asyncio.run(login(args.state_dir, args.timeout, not args.no_open))
    except Exception as exc:
        # No traceback: HTTP objects may contain credential-bearing callback URLs.
        print(f"登录未完成：{type(exc).__name__}。请检查本地网络或重新扫码。", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
