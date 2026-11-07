"""Authorization gates using synthetic MockTransport only; no real approval/key."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / 'runtime'
APP_SRC = Path(os.environ.get('B_TEST_APP_SRC', HERE.parents[1] / 'src')).resolve()
sys.path[:0] = [str(RUNTIME), str(APP_SRC)]
import controller80 as controller
from rag_app.config import Settings
import httpx
import run_authorized_full40 as launcher


def approval(root):
    return {'approved': True, 'user_statement': 'SYNTHETIC UNIT TEST ONLY; NOT REAL EXECUTION APPROVAL',
            'trial_id': 'synthetic_paid_metadata', 'max_provider_attempts': 80,
            'authorized_trial_root': str(Path(root).resolve()),
            'runtime_manifest_sha256': controller.digest(RUNTIME / 'runtime_manifest.json'),
            'launcher_sha256': sha256((HERE / 'run_authorized_full40.py').read_bytes()).hexdigest()}


def settings():
    return Settings(api_key='SYNTHETIC_TEST_KEY_ONLY', timeout=120, top_k=8,
                    collection='fixed_150_overlap_30', arm='enhanced')


class SyntheticProvider:
    def __init__(self):
        self.dispatches = 0

    def handler(self, request):
        self.dispatches += 1
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

    def transport(self, **kwargs):
        return httpx.MockTransport(self.handler)


@contextmanager
def workspace_folder():
    parent = Path.cwd() / 'tmp'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as name:
        yield Path(name).resolve()


class LauncherTests(unittest.TestCase):
    def arguments(self, folder, root):
        return ['launcher', '--runtime', str(RUNTIME), '--app-src', str(APP_SRC),
                '--trial-root', str(root), '--approval-file', str(folder / 'approval.json')]

    def check_bad_record(self, changes):
        with workspace_folder() as folder:
            root = folder / 'trials'
            record = {**approval(root), **changes}
            (folder / 'approval.json').write_text(json.dumps(record), encoding='utf-8')
            with (patch.object(sys, 'argv', self.arguments(folder, root)),
                  patch.object(Settings, 'from_env') as credentials,
                  patch('httpx.AsyncHTTPTransport') as transport,
                  patch.object(controller, 'initialize') as initialize,
                  self.assertRaises(controller.TrialBlocked)):
                launcher.main()
            credentials.assert_not_called()
            transport.assert_not_called()
            initialize.assert_not_called()
            self.assertFalse(root.exists())

    def test_unapproved_record_blocks_before_credentials(self):
        self.check_bad_record({'approved': False})

    def test_wrong_runtime_blocks_before_credentials(self):
        self.check_bad_record({'runtime_manifest_sha256': 'changed'})

    def test_empty_approval_statement_blocks_before_credentials(self):
        self.check_bad_record({'user_statement': ''})

    def test_changed_launcher_blocks_before_credentials(self):
        self.check_bad_record({'launcher_sha256': 'changed'})

    def test_missing_or_invalid_authorized_root_blocks_before_credentials(self):
        for value in (None, '', [], 'relative/path'):
            with self.subTest(value=value):
                self.check_bad_record({'authorized_trial_root': value})

    def test_different_approved_root_blocks_launcher_before_credentials_or_files(self):
        with workspace_folder() as folder:
            self.check_bad_record({'authorized_trial_root': str(folder / 'other')})

    def test_same_approved_root_is_accepted_by_launcher(self):
        with workspace_folder() as folder:
            root = folder / 'trials'
            record = approval(root)
            (folder / 'approval.json').write_text(json.dumps(record), encoding='utf-8')
            provider = SyntheticProvider()
            with (patch.object(sys, 'argv', self.arguments(folder, root)),
                  patch.object(Settings, 'from_env', return_value=settings()) as credentials,
                  patch('httpx.AsyncHTTPTransport', side_effect=provider.transport)):
                launcher.main()
            credentials.assert_called_once()
            self.assertEqual(provider.dispatches, 80)
            self.assertTrue((root / record['trial_id'] / 'TRIAL_STARTED.json').is_file())
            # Reusing these exact approval bytes with another output root was
            # the original replay defect. Reject before credential/transport work.
            different = folder / 'replayed_elsewhere'
            with (patch.object(sys, 'argv', self.arguments(folder, different)),
                  patch.object(Settings, 'from_env') as credentials,
                  patch('httpx.AsyncHTTPTransport') as transport,
                  self.assertRaises(controller.TrialBlocked)):
                launcher.main()
            credentials.assert_not_called()
            transport.assert_not_called()
            self.assertEqual(provider.dispatches, 80)
            self.assertFalse(different.exists())

    def test_relative_requested_root_resolves_before_launcher_dispatch(self):
        with workspace_folder() as folder:
            root = folder / 'trials'
            (folder / 'approval.json').write_text(json.dumps(approval(root)), encoding='utf-8')
            relative = os.path.relpath(root, Path.cwd())
            record = approval(root)
            self.assertEqual(controller.validate_authorization(
                RUNTIME, record['trial_id'], record, relative), root)
            with (patch.object(sys, 'argv', self.arguments(folder, relative)),
                  patch.object(Settings, 'from_env', return_value=settings()),
                  patch.object(controller, 'run_trial', return_value=(
                      {'provider_client_attempts': 0}, {'stopped': False}, None, None, None)) as run):
                launcher.main()
            self.assertEqual(run.call_args.args[2], root.resolve())
            self.assertFalse(root.exists())

    def test_synthetic_80_call_mode_has_truthful_checkpoints(self):
        with workspace_folder() as root:
            provider = SyntheticProvider()
            record = approval(root)
            with (patch.object(Settings, 'from_env', side_effect=AssertionError('No credentials')),
                  patch('httpx.AsyncHTTPTransport', side_effect=AssertionError('No real transport'))):
                run, _, _, _, _ = controller.run_trial(
                    RUNTIME, APP_SRC, root, record['trial_id'], 'run.json', settings(),
                    provider.transport, authorization=record)
            self.assertEqual(provider.dispatches, 80)
            self.assertEqual(run['provider_client_attempts'], 80)
            self.assertEqual(run['execution_mode'], 'paid')
            self.assertNotIn('real_model_calls_asserted_by_offline_entry', run)
            for file in (root / record['trial_id']).glob('run.checkpoint*.json'):
                checkpoint = json.loads(file.read_bytes())
                self.assertEqual(checkpoint['execution_mode'], 'paid')
                self.assertNotIn('real_model_calls_asserted_by_offline_entry', checkpoint)

    def test_direct_authorized_different_root_is_blocked_before_any_side_effect(self):
        with workspace_folder() as folder:
            approved, requested = folder / 'approved', folder / 'different'
            record = approval(approved)
            factory = Mock(side_effect=AssertionError('No provider dispatch'))
            with (patch.object(Settings, 'from_env') as credentials,
                  patch.object(controller, 'initialize') as initialize,
                  self.assertRaises(controller.TrialBlocked)):
                controller.run_trial(RUNTIME, APP_SRC, requested, record['trial_id'],
                                     'run.json', settings(), factory, authorization=record)
            credentials.assert_not_called()
            initialize.assert_not_called()
            factory.assert_not_called()
            self.assertFalse(approved.exists())
            self.assertFalse(requested.exists())

    def test_direct_missing_root_is_blocked(self):
        with workspace_folder() as folder:
            record = approval(folder)
            del record['authorized_trial_root']
            factory = Mock(side_effect=AssertionError('No transport'))
            with self.assertRaises(controller.TrialBlocked):
                controller.run_trial(RUNTIME, APP_SRC, folder, record['trial_id'], 'run.json',
                                     settings(), factory, authorization=record)
            factory.assert_not_called()
            self.assertFalse((folder / record['trial_id']).exists())

    def test_symlink_alias_normalizes_and_same_root_replays_stay_blocked(self):
        with workspace_folder() as folder:
            root, alias = folder / 'actual', folder / 'alias'
            root.mkdir()
            try:
                alias.symlink_to(root, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f'Symlink creation unavailable on this platform: {type(error).__name__}')
            record = approval(root)
            self.assertEqual(controller.validate_authorization(RUNTIME, record['trial_id'], record, alias), root)
            provider = SyntheticProvider()
            controller.run_trial(RUNTIME, APP_SRC, alias, record['trial_id'], 'run.json', settings(),
                                 provider.transport, authorization=record)
            self.assertEqual(provider.dispatches, 80)
            original = (root / record['trial_id'] / 'run.json').read_bytes()
            for requested, output in ((root, 'run.json'), (alias, 'changed.json')):
                factory = Mock(side_effect=AssertionError('Replay must not dispatch'))
                with self.assertRaises(controller.TrialBlocked):
                    controller.run_trial(RUNTIME, APP_SRC, requested, record['trial_id'], output,
                                         settings(), factory, authorization=record)
                factory.assert_not_called()
            self.assertEqual((root / record['trial_id'] / 'run.json').read_bytes(), original)
            # An approval cannot itself store a mutable symlink alias.
            with self.assertRaises(controller.TrialBlocked):
                controller.validate_authorization(RUNTIME, record['trial_id'],
                                                  {**record, 'authorized_trial_root': str(alias)}, root)

    def test_separately_authorized_new_root_is_accepted(self):
        with workspace_folder() as folder:
            provider = SyntheticProvider()
            for root in (folder / 'first', folder / 'second'):
                record = approval(root)
                run, _, _, _, _ = controller.run_trial(
                    RUNTIME, APP_SRC, root, record['trial_id'], 'run.json', settings(),
                    provider.transport, authorization=record)
                self.assertEqual(run['provider_client_attempts'], 80)
            self.assertEqual(provider.dispatches, 160)

    def test_historical_fingerprints_and_current_unapproved_template(self):
        history = HERE / 'history/runtime_v1'
        historical = json.loads((history / 'runtime_manifest.json').read_bytes())
        old_template = json.loads((history / 'authorization.example.json').read_bytes())
        provenance = json.loads((HERE.parents[1] / 'docs/experiments/generative40/freeze_provenance.json').read_bytes())
        old_manifest_hash = controller.digest(history / 'runtime_manifest.json')
        self.assertEqual(old_manifest_hash, provenance['runtime_manifest_sha256'])
        self.assertEqual(old_manifest_hash, old_template['runtime_manifest_sha256'])
        self.assertEqual(controller.digest(history / 'run_authorized_full40.py.txt'), old_template['launcher_sha256'])
        for row in historical['files']:
            path = history / 'controller80.py.txt' if row['path'] == 'controller80.py' else RUNTIME / row['path']
            self.assertEqual(controller.digest(path), row['sha256'])
        current = json.loads((HERE / 'authorization.example.json').read_bytes())
        self.assertIs(current['approved'], False)
        self.assertIsNone(current['authorized_trial_root'])
        self.assertEqual(current['runtime_manifest_sha256'], controller.digest(RUNTIME / 'runtime_manifest.json'))
        self.assertEqual(current['launcher_sha256'], controller.digest(HERE / 'run_authorized_full40.py'))


if __name__ == '__main__':
    unittest.main()
