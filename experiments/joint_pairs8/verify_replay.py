"""Replay the frozen forty retrieval contexts with the cached local encoder."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNTIME = REPO/'experiments/generative40/runtime'


def load(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-dir', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(REPO/'src'), str(RUNTIME/'method')]
    from candidate_entry import JointCandidateRetriever
    from rag_app.grounding import prepare_evidence
    from rag_ingest.temporal import load_temporal_catalog
    from selection_adapter import canonical, messages_for_selection
    import torch

    torch.set_num_threads(4)
    lock = load(HERE/'candidate_lock.json')
    for name, expected in lock['inputs_sha256_lf'].items():
        actual = (REPO/name).read_bytes().replace(b'\r\n', b'\n')
        if sha256(actual).hexdigest() != expected:
            raise ValueError('Frozen input fingerprint differs: ' + name)
    protocol = load(HERE/'generation_protocol.json')
    if sha256((RUNTIME/'generation_prompt.txt').read_bytes()).hexdigest() != protocol['prompt_sha256']:
        raise ValueError('Generation prompt does not match the frozen protocol')
    catalog = load_temporal_catalog(RUNTIME/'temporal_catalog.json')
    requests = load(HERE/'model_inputs40.json')['requests']
    old_requests = load(RUNTIME/'model_inputs40.json')['requests']
    inventory = load(HERE/'evidence_inventory40.json')['rows']
    assert len(requests) == len({r['id'] for r in requests}) == 40
    candidate = JointCandidateRetriever(args.experiment_dir, args.cache_dir)
    distance_delta = 0.0
    for frozen, old, item in zip(requests, old_requests, inventory, strict=True):
        assert frozen['id'] == old['id'] == item['id']
        payload, previous = (json.loads(r['messages'][1]['content']) for r in (frozen, old))
        question = payload['question']
        assert question == previous['question']
        expected = payload['evidence']
        assert len(expected) == 8 and [r['evidence_id'] for r in expected] == list(range(1, 9))
        assert [r['chunk_id'] for r in expected] == item['chunk_ids']
        assert [r['chunk_id'] for r in expected[:5]] == [r['chunk_id'] for r in previous['evidence'][:5]]
        assert sha256(canonical(expected)).hexdigest() == item['evidence_sha256']
        assert messages_for_selection(question, expected) == frozen['messages']
        assert sha256(canonical(frozen['messages'])).hexdigest() == item['selection_messages_sha256']
        actual = prepare_evidence(candidate.retrieve(question), catalog)
        for a, b in zip(actual, expected, strict=True):
            assert a.keys() == b.keys()
            assert all(a[k] == b[k] for k in a if k != 'distance'), frozen['id']
            distance_delta = max(distance_delta, abs(a['distance'] - b['distance']))
    assert distance_delta < 1e-5
    print(f'40 contexts and 320 evidence blocks verified. Maximum distance difference: {distance_delta:.3g}.')


if __name__ == '__main__':
    main()
