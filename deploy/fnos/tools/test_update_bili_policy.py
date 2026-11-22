import copy
import tempfile
import unittest
from pathlib import Path
from update_bili_policy import NEW_POLICY, OLD_POLICY, revised_note, update


class FakeAPI:
    def __init__(self):
        self.job = dict(job_id='synthetic', name='大肥鱼每日浏览B站', note='before;' + OLD_POLICY + 'after',
                        payload=dict(note='before;' + OLD_POLICY + 'after', session='test-private',
                                     provider_id='test-model', persona_id='test-persona', origin='api'),
                        cron_expression='30 20 * * *', timezone='Asia/Shanghai', enabled=True)
        self.patches = []

    def request(self, method, path, payload=None):
        if method == 'GET':
            return [copy.deepcopy(self.job)]
        self.patches.append(copy.deepcopy(payload))
        self.job['note'] = payload['note']
        self.job['payload']['note'] = payload['note']


class PolicyTests(unittest.TestCase):
    def test_exact_replacement_preserves_other_instructions(self):
        self.assertEqual(revised_note('before;' + OLD_POLICY + 'after'), 'before;' + NEW_POLICY + 'after')

    def test_unknown_or_duplicate_policy_requires_review(self):
        for note in ('custom task', OLD_POLICY + OLD_POLICY):
            with self.assertRaises(ValueError): revised_note(note)

    def test_only_note_patch_and_idempotent(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(update(api, root))
            self.assertFalse(update(api, root))
            self.assertEqual(api.patches, [{'note': 'before;' + NEW_POLICY + 'after'}])
            self.assertTrue((Path(root) / 'bili-job-before.json').is_file())

    def test_changed_recipient_is_detected(self):
        api = FakeAPI()
        original = api.request
        def request(method, path, payload=None):
            result = original(method, path, payload)
            if method == 'PATCH': api.job['payload']['session'] = 'unexpected'
            return result
        api.request = request
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError): update(api, root)


if __name__ == '__main__':
    unittest.main()
