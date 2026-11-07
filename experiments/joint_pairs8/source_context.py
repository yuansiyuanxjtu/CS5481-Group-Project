"""Rerank evidence within routed sources, keeping the frozen closure8 contract."""
from collections import Counter
from functools import cached_property
import json
import re

from boundary_retrieval import content_query
from evidence_completion import CompletionRetriever, nonbody
from passage_rerank import lexical_terms

VARIANTS = ('section_and_case8', 'section8', 'case8')
SECTION = re.compile(r'\b(executive summary|introduction|conclusions?)\b', re.I)
SECTION_START = re.compile(r'^\s*(?:\d+(?:\.\d+)*[.)]?\s+)?(executive summary|introduction|conclusions?)\b', re.I)
NUMBERED_HEADING = re.compile(r'^\s*\d+(?:\.\d+)*[.)]\s+[A-Z]')
CASE = re.compile(r'\b(?:case stud(?:y|ies)|case example|case studies|worked example)\b', re.I)


class SourceContextRetriever(CompletionRetriever):
    @cached_property
    def section_pages(self):
        pages = json.loads((self.folder/'pages.json').read_bytes())
        result = {}
        previous_doc = None
        section = None
        start = 0
        for page in sorted(pages, key=lambda p:(p['document_id'], p['page_number'])):
            doc, number, text = page['document_id'], page['page_number'], page['text']
            if doc != previous_doc:
                section = None
                previous_doc = doc
            heading = SECTION_START.match(text)
            if heading and not nonbody(text[:350]):
                section = heading[1].lower().rstrip('s')
                start = number
            elif NUMBERED_HEADING.match(text):
                section = None
            if section and number - start < 4:
                result.setdefault((doc, section), set()).add(number)
        return result

    def case_rank(self, doc, query, ranked, anchors):
        """Use nearby topical text as a ranking signal, without joining output blocks."""
        previous, following = self.adjacent
        scores = dict(ranked)
        words = list(lexical_terms(content_query(query)))
        phrases = set(zip(words, words[1:]))
        choices = set()
        for seed in anchors:
            if self.records[seed]['meta']['document_id'] != doc:
                continue
            for direction in (previous, following):
                neighbor = seed
                for _ in range(3):
                    neighbor = direction.get(neighbor)
                    if neighbor is None:
                        break
                    choices.add(neighbor)
        choices.update(cid for cid, _ in ranked[:8])
        choices.update(anchors)
        result = {}
        for cid in sorted(choices & scores.keys()):
            if nonbody(self.records[cid]['text']):
                continue
            tokens = list(lexical_terms(self.records[cid]['text']))
            matched = len(phrases & set(zip(tokens,tokens[1:])))
            near = max(scores.get(previous.get(cid), 0), scores.get(following.get(cid), 0))
            result[cid] = scores[cid] + .10 * near + .12 * min(2, matched)
        return result

    def refresh(self, original, closure_trace, routes, *, section, case):
        chosen = list(original)
        protected = set(original[:5])
        for step in closure_trace:
            protected.update((step['seed'], step['added']))
        document = {cid:row['meta']['document_id'] for cid,row in self.records.items()}
        requested = {doc:m[1].lower().rstrip('s') for doc,q in routes.items() if (m := SECTION.search(q))}
        scoped = {doc:self.section_pages.get((doc,name), set()) for doc,name in requested.items()} if section else {}
        has_section = any(scoped.values())
        body = {doc:self.body_ranking(doc, query) for doc,query in routes.items()}
        all_scores = {cid:score for ranking in body.values() for cid,score in ranking}
        trace = []
        for doc, query in routes.items():
            pages = scoped.get(doc, set())
            rank = dict(body[doc])
            reason = 'source_body'
            if pages:
                if any(document[c] == doc and self.records[c]['meta']['page_number'] in pages for c in chosen):
                    continue
                rank = {c:s + .20 for c,s in rank.items() if self.records[c]['meta']['page_number'] in pages}
                reason = 'requested_section'
            elif case and CASE.search(query):
                rank = self.case_rank(doc, query, body[doc], original)
                reason = 'case_neighborhood'
            elif not has_section or doc in requested:
                continue
            if not rank:
                continue
            best = min(rank, key=lambda c:(-rank[c], c))
            if best in chosen:
                continue
            counts = Counter(document[c] for c in chosen)
            removable = [c for c in chosen[5:] if c not in protected and
                         (document[c] == doc or document[c] not in routes or counts[document[c]] > 1)]
            if not removable:
                continue
            victim = min(removable, key=lambda c:(all_scores.get(c, -.5), -chosen.index(c)))
            victim_score = rank.get(victim, all_scores.get(victim, -.5))
            if rank[best] < victim_score + .04:
                continue
            chosen[chosen.index(victim)] = best
            protected.add(best)
            trace.append({'source':doc,'reason':reason,'added':best,'removed':victim,
                          'added_score':rank[best],'removed_score':victim_score})
        return chosen, trace

    def proposals(self, question):
        choices, vector, traces = super().proposals(question)
        original = choices['closure8']
        routes = self.routed_queries(question)
        for mode in VARIANTS:
            chosen, changes = self.refresh(original, traces['closure8'], routes,
                                           section=mode!='case8', case=mode!='section8')
            if len(chosen) != 8 or len(set(chosen)) != 8 or chosen[:5] != original[:5]:
                raise ValueError('Retrieval context budget or frozen prefix changed')
            choices[mode], traces[mode] = chosen, changes
        return choices, vector, traces
