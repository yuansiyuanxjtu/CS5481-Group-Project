"""Offline dual-source retrieval pilot for the existing 150/30 index."""
import argparse
from collections import Counter
from functools import cached_property, lru_cache
from hashlib import sha256
import json
from math import log
import os
from pathlib import Path
import re
from statistics import mean
import unicodedata

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.vector_store import open_collection
from rag_retrieval import DEFAULT_CACHE, DEFAULT_EXPERIMENT, Retriever
import torch

ARM = "enhanced"
COLLECTION = "fixed_150_overlap_30"
TOP_K = 5
CANDIDATES_PER_RANKER = 20
RRF_K = 20
STOP = set("a an the in of for to how what which does do did is are should its it on as and or by with under".split())


def tokens(text):
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if term not in STOP]


class CrossSourcePilot:
    def __init__(self, experiment_dir=DEFAULT_EXPERIMENT, cache_dir=DEFAULT_CACHE):
        self.baseline = Retriever(experiment_dir, cache_dir)
        self.folder = Path(experiment_dir) / ARM

    @cached_property
    def encoder(self):
        return MiniLMEncoder(str(self.baseline.cache_dir), offline=True)

    @cached_property
    def collection(self):
        context = json.loads((self.folder/"collection_context.json").read_text(encoding="utf-8"))
        return open_collection(self.folder/"chroma", COLLECTION, self.encoder.spec, context=context)

    @lru_cache(maxsize=5)
    def source(self, document_id):
        rows = self.collection.get(where={"document_id":document_id},
                                   include=["documents","metadatas","embeddings"])
        if len(rows["ids"]) < TOP_K:
            raise ValueError(f"Expected at least five indexed chunks for {document_id}")
        counts = [Counter(tokens(text)) for text in rows["documents"]]
        lengths = [sum(counter.values()) for counter in counts]
        frequencies = Counter(term for counter in counts for term in counter)
        return rows, counts, lengths, frequencies

    def rank_source(self, document_id, query):
        rows, counts, lengths, frequencies = self.source(document_id)
        ids = rows["ids"]
        count = len(ids)
        query_vector = self.encoder.encode([query], batch_size=1)[0]
        distances = 1 - np.clip(np.asarray(rows["embeddings"]) @ query_vector, -1, 1)
        dense = sorted(range(count), key=lambda i:(distances[i],ids[i]))
        average_length = mean(lengths)
        terms = set(tokens(query)) & frequencies.keys()
        weights = {term:log(1+(count-frequencies[term]+0.5)/(frequencies[term]+0.5))
                   for term in sorted(terms)}
        scores = []
        for counter, length in zip(counts,lengths,strict=True):
            normalizer = 1.2*(0.25+0.75*length/average_length)
            scores.append(sum(weight*counter[term]*2.2/(counter[term]+normalizer)
                              for term,weight in weights.items() if counter[term]))
        lexical = sorted((i for i in range(count) if scores[i] > 0),
                         key=lambda i:(-scores[i],ids[i]))
        fused = Counter()
        for ordering in (dense,lexical):
            for rank, index in enumerate(ordering[:CANDIDATES_PER_RANKER],1):
                fused[index] += 1/(RRF_K+rank)
        candidates = []
        for index in sorted(fused,key=lambda i:(-fused[i],distances[i],ids[i])):
            meta = rows["metadatas"][index]
            hit = {field:meta[field] for field in (
                "document_id","source_url","page_number","title","publication_date","regulatory_status",
            )}
            hit.update(chunk_id=ids[index],text=rows["documents"][index],distance=float(distances[index]))
            candidates.append((hit,fused[index]))
        return candidates

    def retrieve(self, question, routes=None):
        if routes is None:
            return self.baseline.retrieve(question, TOP_K, collection=COLLECTION, arm=ARM)
        if len(routes)!=2 or len({route["document_id"] for route in routes})!=2:
            raise ValueError("A routed query requires exactly two distinct source documents")
        left,right = [self.rank_source(route["document_id"],route["query"]) for route in routes]
        first_four = [hit for pair in zip(left[:2],right[:2],strict=True) for hit,_ in pair]
        fifth,_ = max((left[2],right[2]),key=lambda entry:entry[1])
        return [*first_four,fifth]


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC",text).split()).casefold()


def describe(hits, evidence):
    blocks = [{key:hit[key] for key in ("chunk_id","document_id","page_number","source_url")} for hit in hits]
    ranks = [next((i for i,hit in enumerate(hits,1)
                   if hit["document_id"]==label["document_id"] and hit["page_number"]==label["page_number"]
                   and normalize(label["excerpt"]) in normalize(hit["text"])),None)
             for label in evidence]
    return {"blocks":blocks,"excerpt_ranks":ranks,"complete":all(rank is not None for rank in ranks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions",type=Path,default=Path(__file__).with_name("dev_questions.jsonl"))
    parser.add_argument("--experiment-dir",type=Path,default=DEFAULT_EXPERIMENT)
    parser.add_argument("--cache-dir",type=Path,default=DEFAULT_CACHE)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    torch.set_num_threads(4)
    rows=[json.loads(line) for line in args.questions.read_bytes().splitlines()]
    pilot=CrossSourcePilot(args.experiment_dir,args.cache_dir)
    results=[]
    for row in rows:
        baseline=pilot.retrieve(row["question"])
        candidate=pilot.retrieve(row["question"],row["routes"])
        for hits in (baseline,candidate):
            assert len(hits)==len({hit["chunk_id"] for hit in hits})==TOP_K
        assert {hit["document_id"] for hit in candidate}=={r["document_id"] for r in row["routes"]}
        before=describe(baseline,row["evidence"])
        after=describe(candidate,row["evidence"])
        results.append({"id":row["id"],"baseline":before,"candidate":after})
        print(row["id"], before["excerpt_ranks"], "->",after["excerpt_ranks"],flush=True)
    baseline_count=sum(row["baseline"]["complete"] for row in results)
    candidate_count=sum(row["candidate"]["complete"] for row in results)
    regressions=[row["id"] for row in results if row["baseline"]["complete"] and not row["candidate"]["complete"]]
    context=json.loads((pilot.folder/"collection_context.json").read_text(encoding="utf-8"))
    report={"dataset_sha256":context["dataset_sha256"],"dev_sha256_lf":sha256(args.questions.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
            "arm":ARM,"collection":COLLECTION,"top_k":TOP_K,"count":len(results),
            "baseline_complete":baseline_count,"candidate_complete":candidate_count,
            "regressions":regressions,"gate_passed":candidate_count>baseline_count and not regressions,
            "questions":results}
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print({k:v for k,v in report.items() if k!="questions"})


if __name__=="__main__":
    main()
