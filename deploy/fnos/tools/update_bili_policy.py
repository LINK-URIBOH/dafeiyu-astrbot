"""Update ONLY the existing Bilibili job's access policy. Never initialize jobs."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote

OLD_POLICY = '遇到登录要求、验证码或页面限制立即结束，不关闭登录浮层、不重试。'
NEW_POLICY = ('普通登录按钮、右上角非阻挡登录推荐不点击、不关闭，继续读取公开内容；'
              '真正阻挡内容的登录墙、验证码或访问限制立即结束，不关闭、不绕过、不重试。')


def revised_note(note):
    if NEW_POLICY in note:
        return note
    if note.count(OLD_POLICY) != 1:
        raise ValueError('Task note has changed; inspect before updating')
    return note.replace(OLD_POLICY, NEW_POLICY)


def invariants(job):
    payload = job.get('payload') or {}
    return ({k: job.get(k) for k in ('job_id', 'name', 'job_type', 'cron_expression', 'timezone',
                                    'enabled', 'run_once', 'persistent')},
            {k: v for k, v in payload.items() if k not in ('note', 'run_at')})


def update(api, backup_dir):
    jobs = api.request('GET', '/cron/jobs')
    matches = [j for j in jobs if j.get('name') == '大肥鱼每日浏览B站']
    if len(matches) != 1:
        raise ValueError('Expected one existing Bilibili job')
    job = matches[0]
    note = revised_note(job['note'])
    if note == job['note']:
        return False
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = backup_dir / 'bili-job-before.json'
    with backup.open('x', encoding='utf-8') as f:
        backup.chmod(0o600)
        json.dump(job, f, ensure_ascii=False, indent=2)
    api.request('PATCH', '/cron/jobs/' + quote(job['job_id'], safe=''), {'note': note})
    after = next(j for j in api.request('GET', '/cron/jobs') if j['job_id'] == job['job_id'])
    if after['note'] != note or invariants(after) != invariants(job):
        raise RuntimeError('Updated task did not preserve its policy invariants; inspect backup')
    return True


if __name__ == '__main__':
    from api_client import Dashboard
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', required=True)
    args = parser.parse_args()
    print('Bilibili note updated' if update(Dashboard(), args.backup_dir) else 'Policy already current')
