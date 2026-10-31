"""Vectorless RAG: split the policy into sections, rank with BM25 (no embeddings)."""
import math
import re
import config

STOP = set("a an the is are was to of in on for and or can i my me do it be if at by with what how when".split())


def tokenize(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


def load_chunks(path=None):
    """One chunk per '## Title' section. Chunk id = c1, c2, ... (stable while file is unchanged)."""
    text = (path or config.POLICY_PATH).read_text(encoding="utf-8")
    chunks = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        title, _, body = part.partition("\n")
        chunks.append({"id": f"c{len(chunks) + 1}", "title": title.strip(), "text": body.strip()})
    return chunks


class BM25:
    def __init__(self, chunks, k1=1.5, b=0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        # title is included so section names help ranking
        self.docs = [tokenize(c["title"] + " " + c["text"]) for c in chunks]
        self.avg = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        n = len(self.docs)
        df = {}
        for d in self.docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, q_tokens, i):
        doc, s = self.docs[i], 0.0
        for t in q_tokens:
            tf = doc.count(t)
            if tf:
                s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * len(doc) / self.avg))
        return s

    def search(self, query, top_k=None, min_score=None):
        """Top chunks scoring >= min_score. Returns [] when nothing is relevant."""
        top_k = top_k or config.TOP_K
        min_score = config.MIN_SCORE if min_score is None else min_score
        q = tokenize(query)
        scored = [(self.score(q, i), c) for i, c in enumerate(self.chunks)]
        scored = sorted((x for x in scored if x[0] >= min_score), key=lambda x: -x[0])[:top_k]
        return [{"id": c["id"], "title": c["title"], "score": round(s, 2), "text": c["text"]} for s, c in scored]
