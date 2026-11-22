"""Cumulative net balance change and full Shanghai-calendar-week averages.

Equal-length contiguous natural weeks telescope: their average is the net
change between the first and last Monday boundaries divided by week count.
Only those two endpoints are needed; this never estimates model usage/cost.
"""
from datetime import timedelta
from .domain import BOUNDARY_TOLERANCE,amount,identity,local,money,stamp

def monday(moment):
    day=local(moment).replace(hour=0,minute=0,second=0,microsecond=0)
    return stamp(day-timedelta(days=day.weekday()))

def basis(provider, sample):
    return (sample.get('account'),sample.get('currency'),
            sample.get('verified_mapping') if provider=='siliconflow' else None)

def value(provider, sample):
    return money(sample.get('cash' if provider=='bailian' else 'balance'))

def valid(provider, sample, expected):
    try:
        return bool(sample.get('account')) and sample.get('currency')=='CNY' and basis(provider,sample)==expected and value(provider,sample).is_finite()
    except (ValueError,TypeError):return False

def summarize(store,provider,closing,stop):
    result={'cumulative_change':None,'cumulative_start':None,'weekly_change':None,
            'week_count':0,'weekly_start':None,'weekly_end':monday(stop),'reason':''}
    if not closing or not valid(provider,closing,basis(provider,closing)):
        result['reason']='缺少同口径期末余额';return result
    expected=basis(provider,closing)
    key='balance_baseline_v1:'+provider+':'+identity('|'.join(str(x) for x in expected))
    cached=store.meta(key)
    if cached:
        import json
        first=json.loads(cached)
    else:
        first=next((x for x in store.samples(provider,closing['observed']) if valid(provider,x,expected)),None)
        if first:first=store.remember_baseline(key,first)
    if not first or first['observed']>closing['observed']:
        result['reason']='缺少本账户统计起点';return result
    result.update(cumulative_change=amount(value(provider,closing)-value(provider,first)),cumulative_start=first['observed'])
    week_end=monday(stop)
    week_key=key+':first_monday'
    cached=store.meta(week_key)
    if cached:
        import json
        weekly=json.loads(cached)
    else:
        week_start=monday(first['observed'])
        if first['observed']-week_start>BOUNDARY_TOLERANCE:week_start+=7*86400
        weekly=None
        for boundary in range(week_start,week_end,7*86400):
            sample=next((x for x in store.samples(provider,closing['observed'],near=boundary) if valid(provider,x,expected)),None)
            if sample:
                weekly=store.remember_baseline(week_key,{'boundary':boundary,'sample':sample});break
    if not weekly or weekly['boundary']>=week_end:
        result['reason']='暂无可计算的完整自然周';return result
    end=next((x for x in store.samples(provider,closing['observed'],near=week_end) if valid(provider,x,expected)),None)
    if not end:
        result['reason']='缺少最近已结束自然周的周一零点采样';return result
    count=(week_end-weekly['boundary'])//(7*86400)
    change=(value(provider,end)-value(provider,weekly['sample']))/count
    result.update(weekly_change=amount(change),week_count=count,weekly_start=weekly['boundary'])
    return result
