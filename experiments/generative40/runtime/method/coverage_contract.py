"""Experimental explicit-part evidence selection; not an automatic semantic verifier."""
from hashlib import sha256
import json
import re

PART = re.compile(r"\band\s+(?=(?:what|which|who|when|where|how|can\s+you|could\s+you)\b)",re.I)
POSITION = re.compile(r"_p(\d+)_c(\d+)_fixed_")
BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u201c\"(])")


def question_parts(question):
    if not isinstance(question,str) or not question.strip() or len(question)>2000:
        raise ValueError("Expected a nonempty bounded question")
    starts=[0,*[m.start() for m in PART.finditer(question)]]
    return [{"part_id":i+1,"start":start,"end":end,"request_text":question[start:end]}
            for i,(start,end) in enumerate(zip(starts,[*starts[1:],len(question)],strict=True))]


def source_units(evidence):
    """Join verified overlaps on ONE physical page, retaining original citation slices."""
    pages={}
    ids=set()
    for hit in evidence:
        number=POSITION.search(hit["chunk_id"])
        if (number is None or int(number[1])!=hit["page_number"] or hit["evidence_id"] in ids):
            raise ValueError("Expected unique original evidence IDs and physical page IDs")
        ids.add(hit["evidence_id"])
        pages.setdefault((hit["document_id"],hit["page_number"]),[]).append((int(number[2]),hit))
    chains=[]
    for (doc,page),hits in sorted(pages.items()):
        previous=None;chain=None
        for number,hit in sorted(hits,key=lambda item:(item[0],item[1]["evidence_id"])):
            text=" ".join(hit["text"].split())
            overlap=0
            if previous is not None and number==previous+1:
                overlap=next((n for n in range(min(len(chain["text"]),len(text)),15,-1)
                              if chain["text"].endswith(text[:n])),0)
            if overlap:
                start=len(chain["text"])-overlap
                chain["text"]+=text[overlap:]
            else:
                chain={"document_id":doc,"physical_page":page,"text":"","sources":[]}
                chains.append(chain);start=0;chain["text"]=text
            chain["sources"].append({"start":start,"end":start+len(text),"hit":hit})
            previous=number
    units=[];seen=set()
    for chain in chains:
        text=chain["text"]
        starts=[0,*[m.end() for m in BOUNDARY.finditer(text)]]
        ends=[m.start() for m in BOUNDARY.finditer(text)]+[len(text)]
        for a,b in zip(starts,ends,strict=True):
            while a<b and text[a].isspace():a+=1
            while b>a and text[b-1].isspace():b-=1
            value=text[a:b]
            # Conservative mechanical boundaries; no claim of linguistically complete sentences.
            if not 8<=len(value)<=1200 or not value.endswith((".","!","?")) or re.search(r"https?://|[\[\]<>]",value):
                continue
            segments=[];covered=a
            while covered<b:
                choices=[s for s in chain["sources"] if s["start"]<=covered<s["end"]]
                if not choices:break
                source=max(choices,key=lambda s:s["end"])
                left=max(a,source["start"]);right=min(b,source["end"])
                quote=text[left:right]
                if len(quote)<8:break
                segments.append({"id":source["hit"]["evidence_id"],"quote":quote})
                covered=right
            if covered<b:continue
            signature=(chain["document_id"],chain["physical_page"],value)
            if signature in seen:continue
            seen.add(signature)
            unit={"document_id":chain["document_id"],"physical_page":chain["physical_page"],"text":value,
                  "evidence":segments,"start_boundary":"unverified_chain_start" if a==0 else "mechanical_punctuation_boundary"}
            identity=json.dumps(unit,ensure_ascii=False,sort_keys=True)
            unit["unit_id"]="U"+sha256(identity.encode()).hexdigest()[:16]
            units.append(unit)
    return units


def selection_payload(question,evidence):
    return {"question":question,"question_parts":question_parts(question),"evidence":evidence,
            "source_units":source_units(evidence)}


def render_selection(selection,question,evidence):
    """Enforce declared coverage and render original quotes; semantic relevance is model-reviewed."""
    if not isinstance(selection,dict) or set(selection)!={"parts"} or not isinstance(selection["parts"],list):
        raise ValueError("Expected exactly a parts list")
    required=question_parts(question)
    entries=selection["parts"]
    if len(entries)!=len(required):raise ValueError("Every supplied question part must be explicitly represented")
    units={r["unit_id"]:r for r in source_units(evidence)}
    chosen=[];missing=False
    for index,entry in enumerate(entries,1):
        if (not isinstance(entry,dict) or set(entry)!={"part_id","supported","unit_ids"}
                or type(entry["part_id"]) is not int or entry["part_id"]!=index
                or type(entry["supported"]) is not bool or not isinstance(entry["unit_ids"],list)):
            raise ValueError("Part IDs/order/types differ from the supplied request parts")
        values=entry["unit_ids"]
        if any(not isinstance(v,str) or v not in units for v in values) or len(set(values))!=len(values):
            raise ValueError("Invalid or repeated source unit")
        if entry["supported"] and not values:raise ValueError("A supported part requires selected evidence")
        if not entry["supported"] and values:raise ValueError("An unsupported part must not carry asserted support")
        missing|=not entry["supported"]
        chosen.extend(values)
    if missing:
        content={"status":"insufficient_evidence","claims":[]}
    else:
        chosen=list(dict.fromkeys(chosen))
        if not 1<=len(chosen)<=6:raise ValueError("Original six-claim limit applies")
        content={"status":"answered","claims":[{"text":units[key]["text"],"evidence":units[key]["evidence"]} for key in chosen]}
    encoded=json.dumps(content,ensure_ascii=False)
    return {"content":encoded,"selection":selection,
            "declared_coverage_complete":not missing,"semantic_coverage_guaranteed":False}


def convert_selection(selection,question,evidence):
    from rag_app.grounding import validate_generation
    rendered=render_selection(selection,question,evidence)
    return {**rendered,"validated":validate_generation(rendered["content"],evidence)}
