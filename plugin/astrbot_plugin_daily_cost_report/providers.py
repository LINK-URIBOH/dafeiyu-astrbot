from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

import aiohttp

from .domain import amount, identity, money, months_for, parse_time

DEEPSEEK_URL = 'https://api.deepseek.com/user/balance'
SILICONFLOW_URL = 'https://cloud.siliconflow.cn/walletd-server/api/v1/subject/profile/peek'


class SourceError(Exception):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(code)  # Never embed upstream response text or credentials.


def load_secrets(path):
    path = Path(path)
    if not path.exists():
        return {}
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise SourceError('permissions', '费用凭据文件必须仅所属用户可读（600）')
    try:
        result = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError):
        raise SourceError('configuration', '费用凭据文件格式错误') from None


async def http_json(url, headers):
    # URLs are constants, not user-configurable; redirects never carry credentials.
    if url not in (DEEPSEEK_URL, SILICONFLOW_URL):
        raise SourceError('configuration', '拒绝向未授权地址发送凭据')
    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=8)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url, headers=headers, allow_redirects=False) as response:
                if response.status in (401, 403):
                    raise SourceError('authentication', '凭据或登录态失效，请更新受限文件')
                if response.status != 200:
                    raise SourceError('http', '费用接口不可用（HTTP ' + str(response.status) + '）')
                raw = await response.content.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise SourceError('schema', '费用响应超出大小限制')
                return json.loads(raw)
    except SourceError:
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError):
        raise SourceError('network', '费用查询超时或网络不可用') from None
    except (ValueError, UnicodeError):
        raise SourceError('schema', '费用接口未返回有效 JSON') from None


def normalize_bills(items, product_codes=()):
    selected, recognized = {}, set()
    for item in items:
        code = str(item.get('ProductCode', ''))
        name = str(item.get('ProductName', ''))
        if code not in product_codes and not any(s in name.lower() for s in ('百炼', 'model studio')):
            continue
        recognized.add(code)
        kind = item.get('Item')
        if kind not in ('PayAsYouGoBill', 'Refund', 'Adjustment'):
            continue
        rid = str(item.get('RecordID') or '')
        if not rid:
            raise SourceError('schema', '百炼账单缺少稳定记录编号，不能安全去重')
        sub = str(item.get('SubOrderId') or '')
        currency = str(item.get('Currency') or '')
        if currency != 'CNY':
            raise SourceError('currency', '百炼账单币种不是人民币')
        value = money(item.get('PretaxAmount'))
        if kind == 'Refund' and value > 0:
            value = -value
        try:
            start, end = parse_time(item['UsageStartTime']), parse_time(item['UsageEndTime'])
        except (KeyError, ValueError, TypeError):
            start = end = None
        row = {'id': '|'.join((rid, sub, code, str(kind))), 'start': start, 'end': end,
               'cost': amount(value), 'currency': currency}
        if row['id'] in selected and selected[row['id']] != row:
            raise SourceError('schema', '百炼同一账单编号返回不同内容，暂不汇总')
        selected[row['id']] = row
    return list(selected.values()), recognized


class Adapters:
    def __init__(self, store, secrets_file, environ=None, get_json=http_json, bss_factory=None):
        self.store = store
        self.secrets_file = secrets_file
        self.environ = os.environ if environ is None else environ
        self.get_json = get_json
        self.bss_factory = bss_factory

    async def collect(self, provider, now, start):
        if provider == 'deepseek' and self.environ.get('DEEPSEEK_API_KEY'):
            return await self.deepseek({})
        secrets = load_secrets(self.secrets_file)
        if provider == 'deepseek':
            return await self.deepseek(secrets)
        if provider == 'siliconflow':
            return await self.siliconflow(secrets)
        return await self.bailian(secrets, now, start)

    async def deepseek(self, secrets):
        key = self.environ.get('DEEPSEEK_API_KEY', '') or secrets.get('deepseek_api_key', '')
        if not key:
            raise SourceError('unconfigured', '未配置 DeepSeek API Key')
        data = await self.get_json(DEEPSEEK_URL, {'Authorization': 'Bearer ' + key.strip()})
        rows = [r for r in data.get('balance_infos', []) if r.get('currency') == 'CNY']
        if len(rows) != 1:
            raise SourceError('schema', '没有取得唯一的人民币余额记录')
        row = rows[0]
        return {'currency': 'CNY', 'account': identity(key.strip()), 'balance': amount(row.get('total_balance')),
                'cash': amount(row['topped_up_balance']) if row.get('topped_up_balance') is not None else None,
                'granted': amount(row['granted_balance']) if row.get('granted_balance') is not None else None}

    async def siliconflow(self, secrets):
        cfg = secrets.get('siliconflow', {})
        cookie, subject = str(cfg.get('cookie', '')).strip(), str(cfg.get('subject_id', '')).strip()
        if not cookie or not subject:
            raise SourceError('unconfigured', '未配置硅基流动 Cookie 和账户标识')
        if any(c in cookie + subject for c in ('\r', '\n')):
            raise SourceError('configuration', '登录态字段不能包含换行')
        if cfg.get('currency', 'CNY') != 'CNY':
            raise SourceError('currency', '仅接入硅基流动国内人民币账户')
        data = await self.get_json(SILICONFLOW_URL, {'Cookie': cookie, 'x-subject-id': subject,
            'Accept': 'application/json', 'Referer': 'https://cloud.siliconflow.cn/'})
        if data.get('code') not in (None, 0, 200, 20000) or data.get('status') is False:
            raise SourceError('authentication', '硅基流动钱包查询失败，请核对登录态')
        financial = data.get('data', {}).get('financialInfo')
        if not isinstance(financial, dict):
            raise SourceError('schema', '国内站钱包缺少 financialInfo，未将缺失字段当作零')
        scale = money(cfg.get('amount_scale'))
        if scale <= 0 or scale > 1:
            raise SourceError('configuration', '硅基流动金额比例必须在 (0,1]')
        balance_field = cfg.get('balance_field', 'balance')
        used_field = cfg.get('used_field', 'used')
        if balance_field not in ('balance', 'available') or used_field != 'used':
            raise SourceError('configuration', '不支持的钱包金额字段映射')
        balance = money(financial.get(balance_field)) * scale
        fingerprint = identity('|'.join((subject, amount(scale), balance_field, used_field)))
        previous = self.store.state('siliconflow')
        verified = previous.get('verified_mapping') == fingerprint
        used_verified = verified and previous.get('used_verified', False)
        if not verified:
            try:
                reference = money(cfg.get('reference_cash_balance_cny'))
            except ValueError:
                raise SourceError('verification', '需填写控制台现金余额，验证国内站金额单位') from None
            if abs(reference - balance) > Decimal('0.02'):
                raise SourceError('verification', '现金余额与控制台参考值不符，请核对字段、比例或更新参考值')
            if cfg.get('reference_cumulative_used_cny') not in ('', None):
                used_verified = abs(money(cfg['reference_cumulative_used_cny']) - money(financial.get(used_field)) * scale) <= Decimal('0.02')
                if not used_verified:
                    raise SourceError('verification', '累计消费与控制台参考值不符，暂不启用该字段')
        used = amount(money(financial.get(used_field)) * scale) if used_verified else None
        return {'currency': 'CNY', 'account': identity(subject), 'balance': amount(balance),
                'cash': amount(balance), 'used': used, 'verified_mapping': fingerprint,
                'used_verified': used_verified, 'balance_scope': '已核对现金口径；代金券未合并'}

    def _bss(self, cfg):
        if self.bss_factory:
            return self.bss_factory(cfg)
        if self.environ.get('DAFEIYU_COST_SDK_PYTHON'):
            return {'bridge_config': {k:cfg[k] for k in ('access_key_id','access_key_secret')}}
        try:
            from alibabacloud_bssopenapi20171214.client import Client
            from alibabacloud_tea_openapi.models import Config
        except ImportError:
            raise SourceError('dependency', '百炼费用官方 SDK 尚未安装') from None
        return Client(Config(access_key_id=cfg['access_key_id'], access_key_secret=cfg['access_key_secret'],
                             endpoint='business.aliyuncs.com', region_id='cn-hangzhou'))

    def _bss_query(self, client, operation, parameters):
        if self.bss_factory:
            result = client(operation, parameters)
        elif self.environ.get('DAFEIYU_COST_SDK_PYTHON'):
            payload = {'credentials':client['bridge_config'],'operation':operation,'parameters':parameters}
            process = subprocess.run([self.environ['DAFEIYU_COST_SDK_PYTHON'], str(Path(__file__).with_name('sdk_bridge.py'))],
                input=json.dumps(payload).encode(), capture_output=True, timeout=35)
            if process.returncode or len(process.stdout) > 2 * 1024 * 1024:
                raise SourceError('billing', '隔离费用 SDK 查询失败，未显示接口原文')
            result = json.loads(process.stdout)
        else:
            from alibabacloud_bssopenapi20171214 import models
            from alibabacloud_tea_util.models import RuntimeOptions
            runtime = RuntimeOptions(connect_timeout=8000, read_timeout=20000, autoretry=False)
            if operation == 'balance':
                result = client.query_account_balance_with_options(runtime).body.to_map()
            else:
                request = models.QueryBillRequest(**parameters)
                result = client.query_bill_with_options(request, runtime).body.to_map()
        if result.get('Success') is not True:
            raise SourceError('billing', '阿里云费用查询未成功，请核对 RAM 只读权限')
        return result.get('Data', {})

    async def bailian(self, secrets, now, start):
        cfg = secrets.get('bailian', {})
        if not cfg.get('access_key_id') or not cfg.get('access_key_secret'):
            raise SourceError('unconfigured', '未配置百炼 RAM 费用只读凭据')
        client = self._bss(cfg)
        try:
            balances = await asyncio.to_thread(self._bss_query, client, 'balance', {})
            currency = balances.get('Currency')
            if currency != 'CNY':
                raise SourceError('currency', '阿里云账户币种不是人民币')
            account = identity(cfg['access_key_id'])
            result = {'currency': 'CNY', 'account': account, 'cash': amount(balances.get('AvailableCashAmount')),
                      'available': amount(balances.get('AvailableAmount')), 'balance': None}
            recognized = set()
            known_codes = set(cfg.get('product_codes', [])) | set(self.store.state('bailian').get('recognized_product_codes', []))
            for cycle in months_for(start, now + 1):
                items, seen_pages = [], set()
                for page in range(1, 101):
                    data = await asyncio.to_thread(self._bss_query, client, 'bills',
                        {'billing_cycle': cycle, 'page_num': page, 'page_size': 300})
                    rows = data.get('Items', {}).get('Item', [])
                    total = int(data.get('TotalCount', 0))
                    if not isinstance(rows, list) or total < 0:
                        raise SourceError('schema', '百炼账单分页结构异常')
                    signature = identity(json.dumps(rows, sort_keys=True))
                    if rows and signature in seen_pages:
                        raise SourceError('pagination', '百炼账单分页重复，未保存不完整结果')
                    seen_pages.add(signature)
                    items.extend(rows)
                    if page * 300 >= total:
                        if len(items) < total:
                            raise SourceError('pagination', '百炼账单分页缺失')
                        break
                    if not rows:
                        raise SourceError('pagination', '百炼账单分页提前结束')
                else:
                    raise SourceError('pagination', '百炼账单超过分页上限')
                normalized, codes = normalize_bills(items, known_codes)
                recognized.update(codes)
                known_codes.update(codes)
                # Without a known product, an empty response cannot prove zero cost.
                if not known_codes:
                    raise SourceError('verification', '尚未识别百炼账单商品，请核对并填写 product_codes')
                self.store.replace_bills(account, cycle, normalized, now)
            result['recognized_product_codes'] = sorted(known_codes)
            result['billing_complete'] = True
            return result
        except SourceError as error:
            if 'result' in locals():
                result['billing_error'] = error.reason
                result['billing_complete'] = False
                return result
            raise
        except Exception:
            if 'result' in locals():
                result['billing_error'] = '百炼账单查询失败，请检查权限或重试；未用历史缓存冒充最新账单'
                result['billing_complete'] = False
                return result
            raise SourceError('billing', '阿里云余额查询失败，请核对凭据、权限及网络') from None
