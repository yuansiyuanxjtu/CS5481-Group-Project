"""Select three tail chunks together under the frozen eight-block budget."""
from functools import lru_cache
from itertools import combinations
from math import log
from collections import Counter

from boundary_retrieval import content_query
from evidence_completion import CompletionRetriever, nonbody
from passage_rerank import lexical_terms
from routed_retrieval import CLAUSE
from source_context import CASE, SECTION, SourceContextRetriever

VARIANTS = ('joint_pairs8', 'joint_soft8')


def terms(text):
    words = [word[:-1] if len(word) >= 4 and word.endswith('s') and not word.endswith('ss') else word
             for word in lexical_terms(text)]
    return set(words) | set(zip(words, words[1:]))


class JointContextRetriever(SourceContextRetriever):
    def queries_for_tail(self, question, original):
        if len(original) != 2:
            return original
        clauses = {doc:[] for doc in original}
        current = None
        for clause in CLAUSE.split(question):
            mentioned = self.explicit_documents(clause) & original.keys()
            if len(mentioned) == 1:
                current = next(iter(mentioned))
            elif mentioned:
                current = None
            if current is not None:
                clauses[current].append(clause.strip())
        return {doc:', '.join(clauses[doc]) or query for doc,query in original.items()}

    @lru_cache(maxsize=16)
    def source_terms(self, doc):
        by_chunk = {cid:terms(row['text']) for cid,row in self.records.items()
                    if row['meta']['document_id'] == doc}
        frequency = Counter(term for chunk in by_chunk.values() for term in chunk)
        return by_chunk, frequency

    def features(self, doc, query, baseline):
        section = SECTION.search(query)
        pages = self.section_pages.get((doc,section[1].lower().rstrip('s')),set()) if section else set()
        scoped = bool(pages)
        rankings = self.body_ranking(doc,query)
        features, frequency = self.source_terms(doc)
        weights = {term:(2.2 if isinstance(term,tuple) else 1) * log(1 + (len(features)+.5)/(frequency[term]+.5))
                   for term in terms(content_query(query)) if frequency[term]}
        ordered = sorted(weights, key=lambda t:(isinstance(t,tuple),t))
        total = sum(weights[t] for t in ordered) or 1
        def matched_score(matches):
            return sum(weights[t] for t in ordered if t in matches) / total

        matches, relevance = {}, {}
        for cid,score in rankings:
            row = self.records[cid]
            if nonbody(row['text']) or (scoped and row['meta']['page_number'] not in pages):
                continue
            matches[cid] = features[cid] & weights.keys()
            relevance[cid] = .5 * matched_score(matches[cid]) + .5 * max(score,0)
        ordered_candidates = sorted(relevance,key=lambda c:(-relevance[c],c))
        top = ordered_candidates[:6]
        if CASE.search(query) and not scoped:
            nearby = self.case_rank(doc,query,rankings,baseline)
            nearby_top = [c for c in ordered_candidates if c in nearby][:6]
            top = list(dict.fromkeys(top+nearby_top))
        return top, matches, relevance, matched_score

    def select_tail(self, baseline, steps, routes, *, atomic):
        prefix, old_tail = baseline[:5], baseline[5:]
        source = {cid:self.records[cid]['meta']['document_id'] for cid in self.records}
        required_sources = set(routes) & {source[cid] for cid in baseline}
        pairs = [(step['seed'],step['added']) for step in steps]
        per_source = [self.features(doc,q,baseline) for doc,q in routes.items()]
        pool = sorted((set(old_tail) | {c for top, *_ in per_source for c in top}) - set(prefix))

        def objective(context):
            value = 0.0
            for _,matches,relevance,matched_score in per_source:
                covered = set().union(*(matches.get(c, ()) for c in context))
                value += matched_score(covered) + .45 * max((relevance.get(c,0) for c in context),default=0)
            value += .075 * sum(a in context and b in context for a,b in pairs)
            return value

        base_set = set(baseline)
        best = tuple(old_tail)
        base_score = objective(base_set)
        best_score = base_score
        for tail in combinations(pool,3):
            context = set(prefix) | set(tail)
            if not required_sources <= {source[c] for c in context}:
                continue
            if atomic and any((a in context) != (b in context) for a,b in pairs):
                continue
            changes = len(context-base_set)
            value = objective(context) - .025 * changes
            if value > best_score + 1e-9:
                best_score, best = value, tail
        added = [c for c in best if c not in base_set]
        best_set = set(best)
        removed = [c for c in old_tail if c not in best_set]
        if not added:
            return baseline, []
        replacements = iter(added)
        final = prefix + [c if c in best_set else next(replacements) for c in old_tail]
        return final,[{'added':added,'removed':removed,'gain':best_score-base_score,
                       'kept_pairs':sum(a in final and b in final for a,b in pairs)}]

    def proposals(self, question):
        choices, vector, trace = CompletionRetriever.proposals(self,question)
        base = choices['closure8']
        routes = self.queries_for_tail(question,self.routed_queries(question))
        triggered = any(CASE.search(query) or SECTION.search(query) for query in routes.values())
        for mode in VARIANTS:
            chosen, changes = self.select_tail(base,trace['closure8'],routes,atomic=mode=='joint_pairs8') if triggered else (base,[])
            if len(chosen) != 8 or len(set(chosen)) != 8 or chosen[:5] != base[:5]:
                raise ValueError('Joint context violated the frozen budget or prefix')
            choices[mode], trace[mode] = chosen, changes
        return choices, vector, trace
