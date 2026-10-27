import json
from api_client import BASE, Dashboard

evidence = json.loads((BASE / 'incoming/bili-verified.json').read_text())
if not evidence.get('verified'):
    raise RuntimeError('Bilibili public-page evidence has not passed verification')
state = json.loads((BASE / 'incoming/setup-state.json').read_text())
api = Dashboard()
job = api.request('PATCH', '/cron/jobs/' + state['bili_job_id'], {'enabled': True})
print(json.dumps({'name': job['name'], 'enabled': job['enabled'], 'timezone': job['timezone'], 'next_run_time': job['next_run_time']}, ensure_ascii=False))
