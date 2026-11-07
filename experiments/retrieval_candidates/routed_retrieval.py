"""Experimental Top-5 retrieval using only the query and the local corpus."""

import json
import re
from functools import cached_property

from all_question_retrieval import AllQuestionRetriever, ARM, COLLECTION, DEFAULT_CACHE, DEFAULT_EXPERIMENT
from passage_rerank import PassagePilot

MODES = ("hybrid5", "scoped5", "passage5", "linked5", "anchored5", "complement5")
ALIAS = re.compile(r"\b(hkma|hong kong monetary authority|fsb|financial stability board|bis|fsi|bank for international settlements|financial stability institute)\b")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
CLAUSE = re.compile(r"(?:[,;]\s*|\s+and\s+)(?=(?:in|under|according to|what|how|where|which)\b)", re.I)
LINK = re.compile(r"\b(?:cite[sd]?|citing|reference[sd]?|refer(?:s|red)? to|mention(?:s|ed)?)\b", re.I)
FOLLOWUP = re.compile(r"\b(?:that|the cited|the referenced)\s+(?:report|publication|paper|guidance|document)\b", re.I)


def plain(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


class RoutedRetriever(AllQuestionRetriever):
    def __init__(self, experiment_dir=DEFAULT_EXPERIMENT, cache_dir=DEFAULT_CACHE, mode="hybrid5"):
        super().__init__(experiment_dir, cache_dir, "hybrid5")
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self.passages = PassagePilot(experiment_dir, cache_dir, variant="passage_weighted")

    @cached_property
    def documents(self):
        path = self.folder.parent / "temporal_catalog.json"
        documents = json.loads(path.read_text(encoding="utf-8"))["documents"]
        return {doc["document_id"]: doc for doc in documents}

    @cached_property
    def titles(self):
        return {
            doc_id: plain(re.sub(r"^Annex [A-Z]:\s*", "", doc["title"]).split(":", 1)[0])
            for doc_id, doc in self.documents.items()
        }

    def explicit_documents(self, query):
        text = plain(query)
        matches = {doc_id for doc_id, title in self.titles.items() if title in text}
        aliases = list(ALIAS.finditer(text))
        if not aliases:
            return matches
        # A year may precede or follow its issuer. Associate it to the nearest issuer.
        years = {i: set() for i in range(len(aliases))}
        for year in YEAR.finditer(text):
            i = min(range(len(aliases)), key=lambda index: min(
                abs(year.start() - aliases[index].end()), abs(aliases[index].start() - year.end())
            ))
            years[i].add(year.group())
        for i, alias in enumerate(aliases):
            word = alias.group()
            group = (word if word in {"hkma", "fsb", "bis"} else
                     {"hong": "hkma", "financial": "fsb" if word.endswith("board") else "bis",
                      "bank": "bis", "fsi": "bis"}[word.split()[0]])
            sources = {doc_id for doc_id, doc in self.documents.items()
                       if doc_id.startswith(group + "_")
                       and (not years[i] or doc["publication_date"][:4] in years[i])}
            if years[i] or len(sources) == 1:
                matches.update(sources)
        return matches

    def routed_queries(self, question):
        full_matches = self.explicit_documents(question)
        if not 1 <= len(full_matches) <= 2:
            return {}
        clauses = CLAUSE.split(question)
        scoped = {}
        if len(full_matches) == 2:
            for clause in clauses:
                found = self.explicit_documents(clause)
                if len(found) == 1 and found <= full_matches:
                    scoped.setdefault(next(iter(found)), clause)
        return {doc_id: scoped.get(doc_id, question) for doc_id in sorted(full_matches)}

    def ranked_passages(self, doc_id, query, rerank):
        return (self.passages.rank_source(doc_id, query) if rerank
                else self.passages.original_candidates(doc_id, query))

    @cached_property
    def source_by_chunk(self):
        records, *_ = self.corpus
        return dict(zip(records["ids"], (meta["document_id"] for meta in records["metadatas"]), strict=True))

    def anchored_context(self, routes, baseline, rankings, use_passages):
        picks = []
        spares = []
        for (source, query), ranking in zip(routes.items(), rankings, strict=True):
            local = [hit["chunk_id"] for hit, _ in ranking]
            anchor = next((chunk for chunk in baseline if self.source_by_chunk[chunk] == source), local[0])
            other = local
            if use_passages:
                other = [hit["chunk_id"] for hit, _ in self.ranked_passages(source, query, True)]
            complement = next(chunk for chunk in other if chunk != anchor)
            picks.extend((anchor, complement))
            spares.extend(chunk for chunk in local[:3] if chunk not in (anchor, complement))
        # Give the spare slot to the best unused global hit from a requested source.
        relevant = [chunk for chunk in baseline if self.source_by_chunk[chunk] in routes]
        return list(dict.fromkeys([*picks, *relevant, *spares]))[:5]

    def candidates(self, question, modes):
        base, vector = self.rankings(question)
        baseline = base["hybrid5"]
        choices = {mode: baseline for mode in modes}
        modes = [mode for mode in modes if mode != "hybrid5"]
        if not modes:
            return choices, vector
        routes = self.routed_queries(question)
        if not routes:
            return choices, vector
        for mode in modes:
            use_passages = mode in {"passage5", "linked5"}
            rankings = [self.ranked_passages(doc_id, query, use_passages)
                        for doc_id, query in routes.items()]
            if len(rankings) == 2:
                if mode in {"anchored5", "complement5"}:
                    choices[mode] = self.anchored_context(routes, baseline, rankings, mode == "complement5")
                    continue
                first, second = rankings
                picks = [first[0], second[0], first[1], second[1], max(first[2], second[2], key=lambda hit: hit[1])]
                choices[mode] = [hit["chunk_id"] for hit, _ in picks]
                continue
            local = rankings[0]
            if mode == "linked5" and LINK.search(question) and FOLLOWUP.search(question):
                doc_id = next(iter(routes))
                followup = CLAUSE.split(question)[-1]
                links = [(hit, target) for hit, _ in local[:10] for target, title in self.titles.items()
                         if target != doc_id and title in plain(hit["text"])]
                targets = {target for _, target in links}
                if len(targets) == 1:
                    reference, target = links[0]
                    other = self.ranked_passages(target, followup, True)
                    preferred = [reference["chunk_id"], *(hit["chunk_id"] for hit, _ in other[:2]),
                                 *(hit["chunk_id"] for hit, _ in local[:2])]
                    choices[mode] = list(dict.fromkeys([*preferred, *baseline]))[:5]
                    continue
            preferred = [hit["chunk_id"] for hit, _ in local[:3]]
            choices[mode] = list(dict.fromkeys([*preferred, *baseline]))[:5]
        return choices, vector

    def retrieve(self, question, top_k=5, *, collection=COLLECTION, arm=ARM):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string")
        if (top_k, collection, arm) != (5, COLLECTION, ARM):
            raise ValueError("Use enhanced fixed_150_overlap_30 with Top-5")
        choices, vector = self.candidates(question, [self.mode])
        return self.materialize(choices[self.mode], vector)
