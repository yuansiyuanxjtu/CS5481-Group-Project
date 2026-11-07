"""Compare passage-aware source reranking using a frozen development/holdout split."""
import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from math import log
from pathlib import Path
import re

from cross_source_pilot import CrossSourcePilot, describe, torch

HERE = Path(__file__).parent
PASSAGE_TERMS = 40
PASSAGE_STRIDE = 20
FUSION_K = 10
VARIANTS = {"balanced":1, "passage_weighted":2}
COMMON = set("""a an the in of for to how what who which does do did is are was were should can could
its it on as and or by with under at from about that this their they when each say says
report letter guidance section paragraph example according refer identify describe
mentions expect expected discuss under""".split())


def lexical_terms(text):
    words = re.findall(r"[a-z0-9]+",text.casefold())
    for word in words:
        if word in COMMON or word.isdigit() or len(word)<2:
            continue
        for suffix in ("ability","able","ing","ed","ies","s"):
            if len(word)>len(suffix)+3 and word.endswith(suffix):
                word = word[:-len(suffix)] + ("y" if suffix=="ies" else "")
                break
        yield word


class PassagePilot(CrossSourcePilot):
    def __init__(self, *args, variant="balanced", **kwargs):
        super().__init__(*args, **kwargs)
        self.variant = variant

    @lru_cache(maxsize=5)
    def passage_source(self, document_id):
        rows,*_ = self.source(document_id)
        title_terms = set(lexical_terms(rows["metadatas"][0]["title"]))
        frequencies = Counter(term for text in rows["documents"] for term in set(lexical_terms(text)))
        return len(rows["ids"]), title_terms, frequencies

    @lru_cache(maxsize=96)
    def original_candidates(self, document_id, query):
        return super().rank_source(document_id, query)

    def rank_source(self, document_id, query):
        candidates = self.original_candidates(document_id,query)
        if self.variant=="previous":
            return candidates
        count, title_terms, frequencies = self.passage_source(document_id)
        terms = set(lexical_terms(query))
        terms = (terms-title_terms) or terms
        weights = {term:log(1+(count-frequencies[term]+0.5)/(frequencies[term]+0.5))
                   for term in sorted(terms) if frequencies[term]}
        if not weights:
            return candidates
        weights_sum = sum(weights.values())
        passage_scores = []
        for hit,_ in candidates:
            words=list(lexical_terms(hit["text"]))
            windows=[set(words[i:i+PASSAGE_TERMS]) for i in range(0,len(words),PASSAGE_STRIDE)]
            score=max((sum(weight for term,weight in weights.items() if term in window)/weights_sum
                       for window in windows),default=0)
            passage_scores.append(score)
        lexical = sorted((i for i, score in enumerate(passage_scores) if score>0),
                         key=lambda i:(-passage_scores[i],i))
        ranks = {index:rank for rank,index in enumerate(lexical,1)}
        scores = []
        for i,(hit,_) in enumerate(candidates):
            bonus = VARIANTS[self.variant]/(FUSION_K+ranks[i]) if i in ranks else 0
            scores.append((hit,1/(FUSION_K+i+1)+bonus))
        return sorted(scores,key=lambda pair:-pair[1])


def rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def summarize(records):
    return {
        "complete":sum(row["complete"] for row in records),
        "excerpts":sum(sum(rank is not None for rank in row["excerpt_ranks"]) for row in records),
    }


def evaluate(pilot, inputs, variants):
    reports = {}
    for variant in variants:
        pilot.variant = variant
        results = []
        for row in inputs:
            hits = pilot.retrieve(row["question"],row["routes"])
            assert len(hits)==len({hit["chunk_id"] for hit in hits})==5
            assert {hit["document_id"] for hit in hits}=={route["document_id"] for route in row["routes"]}
            result = {"id":row["id"],**describe(hits,row["evidence"])}
            results.append(result)
            print(variant,row["id"],result["excerpt_ranks"],flush=True)
        reports[variant] = {**summarize(results),"questions":results}
    return reports


def compare(previous, candidate):
    regressions = [old["id"] for old,new in zip(previous["questions"],candidate["questions"],strict=True)
                   if old["complete"] and not new["complete"]]
    return {"regressions":regressions,"improved":candidate["complete"]>previous["complete"] and not regressions}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gold",type=Path,default=Path("data/evaluation/qa_gold.jsonl"))
    args=parser.parse_args()
    torch.set_num_threads(4)
    paths={name:HERE/f"{name}_questions.jsonl" for name in ("dev","holdout")}
    pilot=PassagePilot()
    dev=evaluate(pilot,rows(paths["dev"]),["previous",*VARIANTS])
    # Select by development results only: fewest complete-question regressions,
    # then most complete questions, then most excerpts. Ties favor balanced.
    selected=max(VARIANTS,key=lambda variant:(
        -len(compare(dev["previous"],dev[variant])["regressions"]),
        dev[variant]["complete"],dev[variant]["excerpts"]))
    print("Selected on dev:",selected,flush=True)
    holdout=evaluate(pilot,rows(paths["holdout"]),["previous",selected])
    plan=json.loads((HERE/"formal_routes.json").read_text(encoding="utf-8"))
    assert sha256(args.gold.read_bytes().replace(b"\r\n",b"\n")).hexdigest()==plan["gold_sha256_lf"]
    formal=[]
    for row in rows(args.gold):
        if row["id"] in plan["routes"]:
            route=plan["routes"][row["id"]]
            assert row["question"]==route["question"]
            evidence=[{**e,"page_number":e["page_start"]} for e in row["evidence"]]
            assert all(e["page_end"]==e["page_number"] for e in evidence)
            formal.append({**row,"routes":route["sources"],"evidence":evidence})
    diagnostic=evaluate(pilot,formal,["previous",selected])
    report={"selected_on_dev":selected,"rule":"40 lexical tokens, stride 20; title terms suppressed; 2+2+1 fixed.",
            "input_sha256_lf":{name:sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
                               for name,path in paths.items()},
            "dev":dev,"holdout":holdout,"formal_diagnostic":diagnostic,
            "dev_gate":compare(dev["previous"],dev[selected]),
            "holdout_gate":compare(holdout["previous"],holdout[selected]),
            "llm_api_calls":0}
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
        stream.write("\n")


if __name__=="__main__":
    main()
