"""Approval gates and truthful paid-mode metadata, using synthetic MockTransport only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from hashlib import sha256

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / 'runtime'
APP_SRC = Path(os.environ.get('B_TEST_APP_SRC', HERE.parents[1] / 'src')).resolve()
sys.path[:0] = [str(RUNTIME), str(APP_SRC)]
import controller80 as controller
from rag_app.config import Settings
import httpx
import run_authorized_full40 as launcher


def approval():
    return {'approved': True, 'user_statement': 'SYNTHETIC UNIT TEST ONLY; NOT REAL EXECUTION APPROVAL',
            'trial_id': 'synthetic_paid_metadata', 'max_provider_attempts': 80,
            'runtime_manifest_sha256': controller.digest(RUNTIME / 'runtime_manifest.json'),
            'launcher_sha256': sha256((HERE / 'run_authorized_full40.py').read_bytes()).hexdigest()}


class LauncherTests(unittest.TestCase):
    def test_unapproved_record_blocks_before_credentials(self):
        self.check_bad_record({**approval(), 'approved': False})

    def test_wrong_runtime_blocks_before_credentials(self):
        self.check_bad_record({**approval(), 'runtime_manifest_sha256': 'changed'})

    def test_empty_approval_statement_blocks_before_credentials(self):
        self.check_bad_record({**approval(), 'user_statement': ''})

    def test_changed_launcher_blocks_before_credentials(self):
        self.check_bad_record({**approval(), 'launcher_sha256': 'changed'})

    def check_bad_record(self, record):
        workspace_tmp = Path.cwd() / 'tmp'
        workspace_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as name:
            folder = Path(name).resolve()
            self.assertTrue(folder.is_relative_to(workspace_tmp.resolve()))
            file = folder / 'approval.json'
            file.write_text(json.dumps(record), encoding='utf-8')
            args = ['launcher', '--runtime', str(RUNTIME), '--app-src', str(APP_SRC),
                    '--trial-root', str(folder / 'trials'), '--approval-file', str(file)]
            with (patch.object(sys, 'argv', args),
                  patch.object(Settings, 'from_env', side_effect=AssertionError('No credentials')),
                  self.assertRaises(controller.TrialBlocked)):
                launcher.main()
            self.assertFalse((folder / 'trials').exists())

    def test_synthetic_80_call_mode_has_truthful_checkpoints(self):
        count = 0
        def handler(request):
            nonlocal count
            count += 1
            user = json.loads(json.loads(request.content)['messages'][1]['content'])
            if 'source_units' in user:
                unit = user['source_units'][0]['unit_id']
                content = {'parts': [{'part_id': p['part_id'], 'supported': True, 'unit_ids': [unit]}
                                     for p in user['question_parts']]}
            else:
                ref = user['evidence_plan']['selected_units'][0]['evidence'][0]
                content = {'status': 'answered', 'claims': [{'text': 'Synthetic test claim only.', 'evidence': [ref]}]}
            return httpx.Response(200, json={'model': 'OFFLINE_STUB_ONLY',
                'choices': [{'message': {'content': json.dumps(content)}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}, request=request)
        workspace_tmp = Path.cwd() / 'tmp'
        workspace_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace_tmp) as name:
            folder = Path(name).resolve()
            self.assertTrue(folder.is_relative_to(workspace_tmp.resolve()))
            with patch.object(Settings, 'from_env', side_effect=AssertionError('No credentials')), \
                 patch('httpx.AsyncHTTPTransport', side_effect=AssertionError('No real transport')):
                run, _, _, _, _ = controller.run_trial(
                    RUNTIME, APP_SRC, folder, approval()['trial_id'], 'run.json',
                    Settings(api_key='SYNTHETIC_TEST_KEY_ONLY', timeout=120, top_k=8,
                             collection='fixed_150_overlap_30', arm='enhanced'),
                    lambda: httpx.MockTransport(handler), authorization=approval())
            self.assertEqual(count, 80)
            self.assertEqual(run['provider_client_attempts'], 80)
            self.assertEqual(run['execution_mode'], 'paid')
            self.assertNotIn('real_model_calls_asserted_by_offline_entry', run)
            for file in (folder / approval()['trial_id']).glob('run.checkpoint*.json'):
                checkpoint = json.loads(file.read_bytes())
                self.assertEqual(checkpoint['execution_mode'], 'paid')
                self.assertNotIn('real_model_calls_asserted_by_offline_entry', checkpoint)


if __name__ == '__main__':
    unittest.main()
