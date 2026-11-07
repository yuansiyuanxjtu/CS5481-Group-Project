"""Run the frozen full40 candidate only after the user explicitly approves its scope.

The delivered approval template is false. This launcher never changes that approval.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--app-src', required=True, type=Path)
    parser.add_argument('--trial-root', required=True, type=Path)
    parser.add_argument('--approval-file', required=True, type=Path)
    args = parser.parse_args()
    runtime, app_src = args.runtime.resolve(), args.app_src.resolve()
    sys.path[:0] = [str(runtime), str(app_src)]
    import controller80 as controller
    approval = json.loads(args.approval_file.read_bytes())
    trial_id = approval.get('trial_id', '')
    controller.validate_authorization(runtime, trial_id, approval)
    if approval.get('launcher_sha256') != sha256(Path(__file__).read_bytes()).hexdigest():
        raise controller.TrialBlocked('Approval is not bound to this launcher version.')
    controller.initialize(runtime, app_src)
    # Credential loading is deliberately after every approval/version gate.
    from dataclasses import replace
    from rag_app.config import Settings
    import httpx
    cfg = replace(Settings.from_env(), timeout=120, top_k=8,
                  collection='fixed_150_overlap_30', arm='enhanced', max_distance=None)
    if not cfg.api_key:
        raise controller.TrialBlocked('Configure provider credentials locally.')
    run, anchors, _, _, _ = controller.run_trial(
        runtime, app_src, args.trial_root.resolve(), trial_id, 'run.json', cfg,
        lambda: httpx.AsyncHTTPTransport(retries=0), authorization=approval)
    print(json.dumps({'trial_id': trial_id, 'provider_client_attempts': run['provider_client_attempts'],
                      'stopped': anchors['stopped'], 'scores': 'pending_C_and_B_review'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
