"""Explicit entry for the frozen, offline-validated joint_pairs8 experiment."""
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO/'experiments/retrieval_candidates'))
from joint_context import JointContextRetriever


class JointCandidateRetriever:
    def __init__(self, experiment_dir, cache_dir):
        lock = json.loads((HERE/'candidate_lock.json').read_bytes())
        if lock['candidate'] != 'joint_pairs8':
            raise ValueError('Expected the frozen joint_pairs8 candidate')
        for name, expected in lock['code_sha256_lf'].items():
            contents = (REPO/name).read_bytes().replace(b'\r\n', b'\n')
            if sha256(contents).hexdigest() != expected:
                raise ValueError('Candidate code differs from the frozen version: ' + name)
        self.engine = JointContextRetriever(experiment_dir, cache_dir)
        self.engine.share_encoder_and_collection()
        self.last_trace = []

    def retrieve(self, question, top_k=8, *, collection='fixed_150_overlap_30', arm='enhanced'):
        if not isinstance(question, str) or not question.strip():
            raise ValueError('Question must be a nonempty string')
        if (top_k, collection, arm) != (8, 'fixed_150_overlap_30', 'enhanced'):
            raise ValueError('Candidate requires enhanced fixed_150_overlap_30 and top_k=8')
        choices, vector, traces = self.engine.proposals(question)
        ids = choices['joint_pairs8']
        if len(ids) != 8 or len(set(ids)) != 8 or ids[:5] != choices['closure8'][:5]:
            raise ValueError('Candidate violated the frozen budget or prefix')
        self.last_trace = traces['joint_pairs8']
        return self.engine.materialize(ids, vector)
