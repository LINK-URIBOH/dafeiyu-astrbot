"""Read-only live verification; output status/schema only, never balances or secrets."""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path

from .domain import PROVIDERS, ZONE, stamp
from .engine import Engine
from .providers import Adapters
from .store import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--secrets', required=True)
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    root = Path(args.state_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    store = Store(root / 'probe.sqlite3')
    engine = Engine(store, Adapters(store, args.secrets), {}, None, lambda:False)
    await engine.capture()
    summary, verified = {}, {}
    for provider in PROVIDERS:
        state = store.state(provider)
        summary[provider] = {k:state[k] for k in ('status','reason','billing_complete','billing_error','used_verified') if k in state}
        summary[provider]['has_snapshot'] = store.latest(provider) is not None
        if provider == 'siliconflow': summary[provider]['wallet_mapping_verified'] = bool(state.get('verified_mapping'))
        if provider == 'bailian': summary[provider]['recognized_product_codes'] = state.get('recognized_product_codes', [])
        verified[provider] = {k:state[k] for k in ('verified_mapping','used_verified','recognized_product_codes') if k in state}
    path = root / 'verified-state.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle: json.dump(verified, handle)
    path.chmod(0o600)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__': asyncio.run(main())
