from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
PROVIDERS = ('deepseek', 'bailian', 'siliconflow')
LABELS = {'deepseek': 'DeepSeek', 'bailian': '百炼', 'siliconflow': '硅基流动'}
ALIASES = {**{p: p for p in PROVIDERS}, 'ds': 'deepseek', '百炼': 'bailian', '硅基流动': 'siliconflow', 'sf': 'siliconflow'}
BOUNDARY_TOLERANCE = 300


def money(value) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError('missing monetary value')
    try:
        result = Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        raise ValueError('invalid monetary value') from None
    if not result.is_finite():
        raise ValueError('non-finite monetary value')
    return result


def amount(value) -> str:
    return format(money(value), 'f')


def display(value) -> str:
    return '不可获取' if value is None else f'￥{money(value):.4f}'


def stamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZONE)
    return int(value.timestamp())


def local(value: int | float) -> datetime:
    return datetime.fromtimestamp(value, ZONE)


def latest_end(now: datetime) -> datetime:
    now = now.astimezone(ZONE)
    end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    return end if now >= end else end - timedelta(days=1)


def date_end(text: str) -> int:
    return stamp(datetime.strptime(text, '%Y-%m-%d').replace(hour=22, tzinfo=ZONE))


def parse_time(value: str) -> int:
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return stamp(value)


def months_for(start: int, end: int) -> list[str]:
    a, b = local(start), local(end - 1)
    cursor = a.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = []
    while cursor <= b:
        result.append(cursor.strftime('%Y-%m'))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def identity(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def balance_cost(start, end, adjustment: Decimal):
    if not start or not end:
        return None, '缺少22点有效边界快照；未伪造历史余额'
    if start['account'] != end['account'] or start['currency'] != end['currency']:
        return None, '账户凭据或币种变化，需要重新建立基线'
    if start['currency'] != 'CNY':
        return None, '非人民币账户，不进行汇率换算'
    if start.get('used') is not None and end.get('used') is not None:
        value = money(end['used']) - money(start['used'])
        method = '累计消费差'
    elif start.get('balance') is not None and end.get('balance') is not None:
        value = money(start['balance']) + adjustment - money(end['balance'])
        method = '余额差计算；资金变化需登记'
    else:
        return None, '未取得同口径余额或累计消费字段'
    if value < 0:
        return None, '余额增加或累计消费回退，请核对充值、退款及额度调整'
    return amount(value), method


def bill_total(rows: list[dict], start: int, end: int):
    total = Decimal(0)
    ambiguous = False
    for row in rows:
        a, b = row.get('start'), row.get('end')
        if a is None or b is None or b < a:
            ambiguous = True
            continue
        overlaps = start <= a < end if a == b else a < end and b > start
        if not overlaps:
            continue
        if a < start or b > end or row.get('currency') != 'CNY':
            ambiguous = True
            continue
        total += money(row['cost'])
    return (None, '存在无法精确归属22点窗口的账单，不进行比例分摊') if ambiguous else (amount(total), '已出账应付费用，含未结清；暂计')
