"""One read-only BSS operation in an isolated venv; secrets arrive on stdin only."""
import json
import logging
import sys

logging.disable(logging.CRITICAL)

def main():
    from alibabacloud_bssopenapi20171214.client import Client
    from alibabacloud_bssopenapi20171214 import models
    from alibabacloud_tea_openapi.models import Config
    from alibabacloud_tea_util.models import RuntimeOptions
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError()
    data = json.loads(raw)
    cfg = data['credentials']
    client = Client(Config(access_key_id=cfg['access_key_id'],access_key_secret=cfg['access_key_secret'],
                          endpoint='business.aliyuncs.com',region_id='cn-hangzhou'))
    runtime = RuntimeOptions(connect_timeout=8000, read_timeout=20000, autoretry=False)
    if data['operation'] == 'balance':
        result = client.query_account_balance_with_options(runtime)
    elif data['operation'] == 'bills':
        result = client.query_bill_with_options(models.QueryBillRequest(**data['parameters']), runtime)
    else:
        raise ValueError()
    print(json.dumps(result.body.to_map()))

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"Success":false,"Code":"READ_FAILED"}')
