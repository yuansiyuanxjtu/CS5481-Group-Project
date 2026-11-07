"""Equal-budget context expansion preserving the existing five original chunks."""
from functools import cached_property
from boundary_retrieval import BASELINE, POSITION, BoundaryRetriever
from relation_retrieval import ARM, COLLECTION

MODES = (BASELINE, "dense_expand8", "neighbor_expand8", "source_expand8", "source_neighbor8",
         "dense_expand10", "dense8_neighbor10", "neighbor_expand10", "source_expand10",
         "neighbor_source10", "reading_order10")
BUDGET = {mode: 5 if mode == BASELINE else 10 if mode.endswith("10") else 8 for mode in MODES}


class BudgetRetriever(BoundaryRetriever):
    def __init__(self, *args, mode=BASELINE, **kwargs):
        super().__init__(*args, mode=BASELINE, **kwargs)
        if mode not in MODES:
            raise ValueError(f"Unknown budget mode: {mode}")
        self.mode = mode

    @cached_property
    def next_reading_chunk(self):
        documents = {}
        for chunk in self.indexed_text:
            match = POSITION.search(chunk)
            if match:
                documents.setdefault(self.source_by_chunk[chunk], []).append((int(match[1]), int(match[2]), chunk))
        following = {}
        for rows in documents.values():
            ordered = sorted(rows)
            for left, right in zip(ordered, ordered[1:]):
                if right[0] == left[0] or right[:2] == (left[0] + 1, 1):
                    following[left[2]] = right[2]
        return following

    def expansion_choices(self, question, modes):
        baseline, vector = super().candidates(question, [BASELINE])
        base = baseline[BASELINE]
        dense = self.collection.query(query_embeddings=[vector.tolist()], n_results=30, include=["distances"])
        dense_ids = [chunk for chunk, _ in sorted(zip(dense["ids"][0], dense["distances"][0], strict=True),
                                                  key=lambda pair: (pair[1], pair[0]))]
        neighbors = [self.next_on_page[seed] for seed in base[:3]
                     if seed in self.next_on_page
                     and not self.indexed_text[seed].rstrip().endswith((".", "!", "?", ";", ":"))
                     and self.next_on_page[seed] not in base]
        reading_neighbors = [self.next_reading_chunk[seed] for seed in base
                             if seed in self.next_reading_chunk
                             and not self.indexed_text[seed].rstrip().endswith((".", "!", "?", ";", ":"))
                             and self.next_reading_chunk[seed] not in base]
        routes = self.routed_queries(question)
        source_rows = [self.ranked_passages(doc, query, True) for doc, query in routes.items()]
        source_ids = []
        for rank in range(max((len(rows) for rows in source_rows), default=0)):
            source_ids.extend(rows[rank][0]["chunk_id"] for rows in source_rows if rank < len(rows))
        first_source = [chunk for chunk in source_ids if chunk not in base]
        dense_eight = list(dict.fromkeys([*base, *dense_ids]))[:8]
        queues = {
            BASELINE: [],
            "dense_expand8": dense_ids,
            "neighbor_expand8": [*neighbors, *dense_ids],
            "source_expand8": [*source_ids, *dense_ids],
            "source_neighbor8": [*neighbors[:1], *first_source[:2], *neighbors[1:], *source_ids, *dense_ids],
            "dense_expand10": dense_ids,
            "dense8_neighbor10": [*dense_eight, *neighbors, *dense_ids],
            "neighbor_expand10": [*neighbors, *dense_ids],
            "source_expand10": [*source_ids, *dense_ids],
            "neighbor_source10": [*neighbors, *source_ids, *dense_ids],
            "reading_order10": [*reading_neighbors, *source_ids, *dense_ids],
        }
        return {mode: list(dict.fromkeys([*base, *queues[mode]]))[:BUDGET[mode]] for mode in modes}, vector

    def retrieve(self, question, top_k=None, *, collection=COLLECTION, arm=ARM):
        if (top_k not in (None, BUDGET[self.mode]) or collection != COLLECTION or arm != ARM):
            raise ValueError("Experiment mode and Top-K differ")
        choices, vector = self.expansion_choices(question, [self.mode])
        return self.materialize(choices[self.mode], vector)
