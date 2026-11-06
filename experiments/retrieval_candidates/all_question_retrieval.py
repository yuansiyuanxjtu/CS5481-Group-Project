"""Offline all-question retrieval trial over the existing 150/30 collection."""
import argparse
from collections import Counter
from functools import cached_property
from hashlib import sha256
import json
from math import log
from pathlib import Path
from statistics import mean

from cross_source_pilot import ARM, COLLECTION, CrossSourcePilot, DEFAULT_CACHE, DEFAULT_EXPERIMENT, normalize, tokens, torch

HERE = Path(__file__).parent
BASELINE = "dense5"
BUDGET = {"dense5":5, "hybrid5":5, "dense8":8, "guarded8":8}
SEARCH_LIMIT = 30
RRF_K = 20


class AllQuestionRetriever(CrossSourcePilot):
    def __init__(self, experiment_dir=DEFAULT_EXPERIMENT, cache_dir=DEFAULT_CACHE, mode="guarded8"):
        super().__init__(experiment_dir,cache_dir)
        if mode not in BUDGET:
            raise ValueError(f"Unknown retrieval mode: {mode}")
        self.mode = mode

    @cached_property
    def corpus(self):
        records = self.collection.get(include=["documents","metadatas"])
        texts = records["documents"]
        counts = [Counter(tokens(text)) for text in texts]
        lengths = [sum(counter.values()) for counter in counts]
        frequencies = Counter(term for counter in counts for term in counter)
        return records, counts, lengths, frequencies

    def rankings(self, question):
        records, counts, lengths, frequencies = self.corpus
        size = len(records["ids"])
        vector = self.encoder.encode([question.strip()],batch_size=1)
        dense = self.collection.query(query_embeddings=vector.tolist(),n_results=min(SEARCH_LIMIT,size),
                                      include=["distances"])
        dense_ids = [chunk for chunk,_ in sorted(zip(dense["ids"][0],dense["distances"][0],strict=True),
                                                key=lambda entry:(entry[1],entry[0]))]
        terms = set(tokens(question)) & frequencies.keys()
        weights = {term:log(1+(size-frequencies[term]+0.5)/(frequencies[term]+0.5))
                   for term in sorted(terms)}
        average = mean(lengths)
        scores = []
        for counter, length in zip(counts,lengths,strict=True):
            normalizer = 1.2*(0.25+0.75*length/average)
            scores.append(sum(weight*counter[term]*2.2/(counter[term]+normalizer)
                              for term,weight in weights.items() if counter[term]))
        ids = records["ids"]
        lexical_ids = [ids[i] for i in sorted((i for i,s in enumerate(scores) if s>0),
                                             key=lambda i:(-scores[i],ids[i]))[:SEARCH_LIMIT]]
        fused = Counter()
        for ranking in (dense_ids,lexical_ids):
            for rank,chunk_id in enumerate(ranking,1):
                fused[chunk_id] += 1/(RRF_K+rank)
        hybrid_ids = sorted(fused,key=lambda chunk_id:(-fused[chunk_id],chunk_id))
        guarded_ids = list(dict.fromkeys([*dense_ids[:5],*lexical_ids,*dense_ids]))
        choices = {"dense5":dense_ids[:5],"hybrid5":hybrid_ids[:5],
                   "dense8":dense_ids[:8],"guarded8":guarded_ids[:8]}
        return choices, vector[0]

    def materialize(self, ids, vector):
        # Compute a real cosine distance even for a BM25-only hit.
        data = self.collection.get(ids=ids,include=["documents","metadatas","embeddings"])
        lookup = {chunk_id:i for i,chunk_id in enumerate(data["ids"])}
        hits = []
        for chunk_id in ids:
            i = lookup[chunk_id]
            metadata = data["metadatas"][i]
            hit = {key:metadata[key] for key in ("document_id","source_url","page_number",
                                               "title","publication_date","regulatory_status")}
            dot = float(data["embeddings"][i] @ vector)
            hit.update(chunk_id=chunk_id,text=data["documents"][i],distance=1-max(-1,min(1,dot)))
            hits.append(hit)
        return hits

    def retrieve(self, question, top_k=5, *, collection=COLLECTION, arm=ARM):
        if (top_k,collection,arm)!=(BUDGET[self.mode],COLLECTION,ARM):
            raise ValueError("QAService configuration must match the selected experiment mode")
        choices,vector = self.rankings(question)
        return self.materialize(choices[self.mode],vector)


def read_rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def describe(hits, evidence):
    ranks = [next((i for i,hit in enumerate(hits,1)
                   if hit["document_id"]==label["document_id"]
                   and label.get("page_start",label.get("page_number"))<=hit["page_number"]
                   <=label.get("page_end",label.get("page_number"))
                   and normalize(label["excerpt"]) in normalize(hit["text"])),None)
             for label in evidence]
    return {"blocks":[{key:hit[key] for key in ("chunk_id","document_id","page_number","source_url")} for hit in hits],
            "excerpt_ranks":ranks,"complete":all(rank is not None for rank in ranks),
            "text_chars":sum(len(hit["text"]) for hit in hits)}


def evaluate(engine, rows, modes):
    results = []
    for row in rows:
        choices,vector = engine.rankings(row["question"])
        evidence = row["evidence"]
        contexts = {mode:describe(engine.materialize(choices[mode],vector),evidence) for mode in modes}
        for mode,context in contexts.items():
            assert len({hit["chunk_id"] for hit in context["blocks"]})==BUDGET[mode]
            assert context["text_chars"]<=40000
        results.append({"id":row["id"],"contexts":contexts})
    return results


def summary(results, mode):
    contexts = [row["contexts"][mode] for row in results]
    return {"complete":sum(c["complete"] for c in contexts),
            "excerpts":sum(sum(rank is not None for rank in c["excerpt_ranks"]) for c in contexts),
            "mean_chars":round(mean(c["text_chars"] for c in contexts)),
            "regressions":[row["id"] for row in results
                           if row["contexts"][BASELINE]["complete"] and not row["contexts"][mode]["complete"]]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gold",type=Path,default=Path("data/evaluation/qa_gold.jsonl"))
    args=parser.parse_args()
    torch.set_num_threads(4)
    engine=AllQuestionRetriever()
    dev_path=HERE/"dev_questions.jsonl"
    dev=evaluate(engine,read_rows(dev_path),BUDGET)
    dev_metrics={mode:summary(dev,mode) for mode in BUDGET}
    selected=max(BUDGET,key=lambda mode:(-len(dev_metrics[mode]["regressions"]),
                dev_metrics[mode]["complete"],dev_metrics[mode]["excerpts"],-BUDGET[mode]))
    print("Frozen on development questions:",selected,dev_metrics,flush=True)
    modes=list(dict.fromkeys([BASELINE,selected,*(["dense8"] if BUDGET[selected]==8 else [])]))
    formal=evaluate(engine,read_rows(args.gold),modes)
    metrics={mode:summary(formal,mode) for mode in modes}
    report={"arm":ARM,"collection":COLLECTION,"selected_on_dev":selected,"budget":BUDGET[selected],
            "dev_sha256_lf":sha256(dev_path.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
            "gold_sha256_lf":sha256(args.gold.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
            "llm_api_calls":0,"dev_metrics":dev_metrics,"formal_metrics":metrics,"dev":dev,"formal":formal}
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("Formal:",metrics)


if __name__=="__main__":
    main()
