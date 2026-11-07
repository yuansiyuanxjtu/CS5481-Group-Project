"""General fixed-eight retrieval candidates. No labels, oracle pages or API client."""
from collections import Counter, defaultdict
from functools import cached_property, lru_cache
from math import log
import re

import numpy as np
from budget_retrieval import BudgetRetriever
from boundary_retrieval import content_query, POSITION
from passage_rerank import lexical_terms

VARIANTS = ('source_neighbor8', 'closure8', 'body_source8', 'body_closure8')
END = re.compile(r'[.!?;:]\s*$')
ABBREVIATION = re.compile(r'\b[A-Z]\.$')
RELATION = re.compile(r'\b(?:cit(?:e[sd]?|ing|ation)|referenc\w*|bibliograph\w*|supersed\w*|replac\w*)\b', re.I)
BOILERPLATE = re.compile(r'\b(?:ISSN|ISBN|JEL classification|All rights reserved|To contact the|Authorised by the Chair)\b', re.I)
LEFT_CONNECTOR = re.compile(r'^(?:and|or|which|that|whose|including|such as|these|those)\b', re.I)


def needs_right(text):
    text = text.rstrip()
    return not END.search(text) or bool(ABBREVIATION.search(text)) or text.count('(') > text.count(')')


def nonbody(text):
    """A soft penalty, never a deletion of a corpus record or a source page."""
    if BOILERPLATE.search(text) or re.search(r'\.{4,}', text):
        return True
    if re.match(r'^\s*(?:table of contents|contents|references|bibliography)\b', text, re.I):
        return True
    citations = len(re.findall(r'\((?:19|20)\d{2}[a-z]?\)', text))
    return citations >= 3 and len(re.findall(r'[“”"]', text)) >= 2


class CompletionRetriever(BudgetRetriever):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, mode='source_neighbor8', **kwargs)

    def share_encoder_and_collection(self):
        # The two pre-existing helper objects use the same pinned local model/index.
        self.passages.encoder = self.encoder
        self.passages.collection = self.collection

    @cached_property
    def records(self):
        rows = self.collection.get(include=['documents', 'metadatas', 'embeddings'])
        return {cid: {'text': text, 'meta': meta, 'vector': np.asarray(vector, dtype=np.float32)}
                for cid, text, meta, vector in zip(rows['ids'], rows['documents'], rows['metadatas'],
                                                   rows['embeddings'], strict=True)}

    @cached_property
    def adjacent(self):
        by_doc = defaultdict(list)
        for cid, row in self.records.items():
            match = POSITION.search(cid)
            if match:
                by_doc[row['meta']['document_id']].append((int(match[1]), int(match[2]), cid))
        previous, following = {}, {}
        for values in by_doc.values():
            ordered = sorted(values)
            for left, right in zip(ordered, ordered[1:]):
                contiguous = (left[0] == right[0] and right[1] == left[1] + 1) or (right[0] == left[0] + 1 and right[1] == 1)
                if contiguous:
                    following[left[2]] = right[2]
                    previous[right[2]] = left[2]
        return previous, following

    @lru_cache(maxsize=16)
    def document_index(self, document):
        ids = sorted(cid for cid, row in self.records.items() if document is None or row['meta']['document_id'] == document)
        terms = [list(lexical_terms(self.records[cid]['text'])) for cid in ids]
        counts = [Counter(words) for words in terms]
        frequencies = Counter(word for counter in counts for word in counter)
        return ids, terms, counts, frequencies

    @lru_cache(maxsize=512)
    def body_ranking(self, document, query):
        """Search every existing source chunk; titles cannot dominate query wording."""
        rewritten = content_query(query) or query
        vector = self.encoder.encode([rewritten], batch_size=1)[0]
        ids, words, counts, frequencies = self.document_index(document)
        query_terms = set(lexical_terms(rewritten))
        if document in self.documents:
            query_terms -= set(lexical_terms(self.documents[document]['title']))
        weights = {t: log(1 + (len(ids) - frequencies[t] + .5) / (frequencies[t] + .5))
                   for t in sorted(query_terms) if frequencies[t]}
        denominator = sum(weights.values()) or 1
        average = sum(len(w) for w in words) / max(1, len(words))
        relation_query = bool(RELATION.search(query))
        ranked = []
        for cid, tokens, counter in zip(ids, words, counts, strict=True):
            cosine = float(np.clip(self.records[cid]['vector'] @ vector, -1, 1))
            norm = 1.2 * (.25 + .75 * len(tokens) / max(1, average))
            bm25 = sum(weight * counter[t] * 2.2 / (counter[t] + norm)
                       for t, weight in weights.items() if counter[t])
            coverage = max((sum(weights[t] for t in sorted(set(tokens[i:i+40])) if t in weights) / denominator
                            for i in range(0, len(tokens), 20)), default=0)
            penalty = (.12 if relation_query else .35) if nonbody(self.records[cid]['text']) else 0
            score = .5 * cosine + .3 * bm25 / (bm25 + 8) + .2 * coverage - penalty
            ranked.append((cid, score))
        return sorted(ranked, key=lambda item: (-item[1], item[0]))

    def score_map(self, question):
        routes = self.routed_queries(question)
        maps = {}
        for document, query in routes.items():
            maps.update(self.body_ranking(document, query))
        if not routes:
            maps.update(self.body_ranking(None, question))
        return maps, routes

    def body_extras(self, question, base, scores, routes):
        sources = list(routes) if routes else [None]
        rankings = [self.body_ranking(doc, routes[doc] if doc is not None else question) for doc in sources]
        queue = []
        for i in range(max(len(r) for r in rankings)):
            queue.extend(r[i][0] for r in rankings if i < len(r))
        return list(dict.fromkeys([*base[:5], *queue, *base]))[:8]

    def close_context(self, chosen, scores, routes):
        """Close any selected seed, including late source additions; preserve first5."""
        chosen = list(chosen)
        protected = set(chosen[:5])
        previous, following = self.adjacent
        proposals = []
        for seed in chosen:
            text = self.records[seed]['text'].strip()
            if nonbody(text):
                continue
            neighbors = []
            if needs_right(text) and seed in following:
                neighbors.append(('right', following[seed]))
            if LEFT_CONNECTOR.search(text) and seed in previous:
                neighbors.append(('left', previous[seed]))
            for direction, neighbor in neighbors:
                if neighbor not in chosen and not nonbody(self.records[neighbor]['text']):
                    priority = scores.get(neighbor, -.5) + .2 * scores.get(seed, -.5)
                    proposals.append((priority, seed, neighbor, direction))
        events = []
        for priority, seed, neighbor, direction in sorted(proposals, key=lambda p: (-p[0], p[1], p[2])):
            if seed not in chosen or neighbor in chosen:
                continue
            counts = Counter(self.records[c]['meta']['document_id'] for c in chosen)
            removable = [c for c in chosen[5:] if c not in protected and c != seed
                         and (self.records[c]['meta']['document_id'] not in routes
                              or counts[self.records[c]['meta']['document_id']] > 1)]
            if not removable:
                continue
            victim = min(removable, key=lambda c: (scores.get(c, -.5), -chosen.index(c)))
            # Structural adjacency can rescue a cut sentence, but cannot displace
            # a much more relevant independent source passage.
            if scores.get(neighbor, -.5) + .15 < scores.get(victim, -.5):
                continue
            chosen.remove(victim)
            where = max(5, chosen.index(seed) + (direction == 'right'))
            chosen.insert(where, neighbor)
            protected.update((seed, neighbor))
            events.append({'seed': seed, 'added': neighbor, 'removed': victim, 'direction': direction,
                           'same_physical_page': self.records[seed]['meta']['page_number'] == self.records[neighbor]['meta']['page_number'],
                           'priority': priority})
        return chosen, events

    def proposals(self, question):
        frozen, vector = super().expansion_choices(question, ['source_neighbor8'])
        baseline = frozen['source_neighbor8']
        scores, routes = self.score_map(question)
        body = self.body_extras(question, baseline, scores, routes)
        closed, trace = self.close_context(baseline, scores, routes)
        body_closed, body_trace = self.close_context(body, scores, routes)
        choices = {'source_neighbor8': baseline, 'closure8': closed,
                   'body_source8': body, 'body_closure8': body_closed}
        require = all(len(ids) == len(set(ids)) == 8 and ids[:5] == baseline[:5] for ids in choices.values())
        if not require:
            raise ValueError('Fixed8 budget/original first5 contract violated')
        traces = {'source_neighbor8': [], 'closure8': trace, 'body_source8': [], 'body_closure8': body_trace}
        return choices, vector, traces
