"""Top-5 document-aware retrieval for a frozen offline experiment."""

import re

from routed_retrieval import ARM, COLLECTION, DEFAULT_CACHE, DEFAULT_EXPERIMENT, RoutedRetriever, plain

MODES = ("complement5", "passage_dual5", "diverse_dual5", "relation5", "passage_relation5", "diverse_relation5")
REFERENTIAL = re.compile(r"\b(?:that|the cited|the referenced|those)\s+(?:report|publication|paper|guidance|document|principles)\b", re.I)
CITATION = re.compile(r"\b(?:cite[sd]?|citing|reference[sd]?|references|refer(?:s|red)? to|bibliography)\b", re.I)
SUPERSESSION = re.compile(r"\b(?:supersed\w+|replac\w+)\b", re.I)


class RelationRetriever(RoutedRetriever):
    def __init__(self, experiment_dir=DEFAULT_EXPERIMENT, cache_dir=DEFAULT_CACHE, mode="complement5"):
        super().__init__(experiment_dir, cache_dir, "complement5")
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode

    def linked_context(self, question, source, base):
        antecedent, separator, followup = question.partition(", and ")
        if not separator or not REFERENTIAL.search(followup):
            return base
        if SUPERSESSION.search(antecedent):
            relation = "supersession"
        elif CITATION.search(antecedent):
            relation = "citation"
        else:
            return base

        matches = {}
        for hit, _ in self.ranked_passages(source, antecedent, True)[:10]:
            text = plain(hit["text"])
            for doc, title in self.titles.items():
                if doc == source or title not in text:
                    continue
                preceding_words = text.split(title, 1)[0].split()[-7:]
                supersedes = bool(SUPERSESSION.search(" ".join(preceding_words)))
                if supersedes == (relation == "supersession"):
                    matches.setdefault(doc, hit["chunk_id"])
        if len(matches) != 1:
            return base
        target, reference = next(iter(matches.items()))
        target_blocks = [hit["chunk_id"] for hit, _ in self.ranked_passages(target, followup, True)[:3]]
        return list(dict.fromkeys([reference, *target_blocks, *base]))[:5]

    def dual_context(self, routes, base, diverse):
        source_rankings = []
        for source, query in routes.items():
            hits = self.ranked_passages(source, query, True)
            if diverse:
                first_by_page = {}
                for hit, score in hits:
                    first_by_page.setdefault(hit["page_number"], hit["chunk_id"])
                first = set(first_by_page.values())
                hits = sorted(hits, key=lambda item: item[0]["chunk_id"] not in first)
            source_rankings.append(hits)
        left, right = source_rankings
        selected = [left[0], right[0], left[1], right[1], max(left[2], right[2], key=lambda item: item[1])]
        return list(dict.fromkeys([*(hit["chunk_id"] for hit, _ in selected), *base]))[:5]

    def candidates(self, question, modes):
        base, vector = super().candidates(question, ["complement5", "hybrid5"])
        complement = base["complement5"]
        routes = self.routed_queries(question)
        result = {}
        for mode in modes:
            if mode in base:
                result[mode] = base[mode]
            elif len(routes) == 1 and "relation" in mode:
                result[mode] = self.linked_context(question, next(iter(routes)), complement)
            elif len(routes) == 2 and mode.startswith(("passage_", "diverse_")):
                result[mode] = self.dual_context(routes, complement, mode.startswith("diverse_"))
            else:
                result[mode] = complement
        return result, vector
