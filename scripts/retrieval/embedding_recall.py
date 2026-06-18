"""
Embedding recall net — ONNX-based semantic retrieval for Otto.

Uses all-MiniLM-L6-v2 in ONNX format (~86MB) for 384-dim embeddings.
Falls back to TF-IDF cosine similarity if ONNX model unavailable.

Architecture:
1. Encode all memory entries + policies + task descriptions into 384-dim vectors
2. Cache vectors in memory (rebuild on write to policy/memory dirs)
3. At query time: encode query → cosine similarity against all vectors
4. Return top-K with scores, filtered by threshold
"""

import hashlib
import json
import os
import pickle
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable

import numpy as np

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
MODEL_DIR = os.path.join(HERMES_HOME, "models", "miniLM-onnx")
CACHE_FILE = os.path.join(HERMES_HOME, "logs", "retrieval", "embedding_cache.pkl")
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
MEMORY_FILE = os.path.join(HERMES_HOME, "memories", "MEMORY.md")

# 384-dim embeddings from all-MiniLM-L6-v2
EMBED_DIM = 384

# Singleton
_session = None
_tokenizer = None


def _load_tokenizer():
    """Load the WordPiece tokenizer from the model directory."""
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer

    try:
        import tokenizers
        vocab_path = os.path.join(MODEL_DIR, "tokenizer.json")
        if os.path.exists(vocab_path):
            _tokenizer = tokenizers.Tokenizer.from_file(vocab_path)
            return _tokenizer
    except Exception:
        pass

    # Fallback: simple whitespace tokenizer for TF-IDF mode
    return None


def _load_session():
    """Load the ONNX inference session (singleton)."""
    global _session
    if _session is not None:
        return _session

    import onnxruntime as ort
    model_path = os.path.join(MODEL_DIR, "onnx", "model.onnx")
    if os.path.exists(model_path):
        _session = ort.InferenceSession(
            model_path,
            providers=['CPUExecutionProvider']
        )
    return _session


def tokenize(texts: List[str], max_len: int = 128) -> Dict[str, np.ndarray]:
    """Tokenize texts for all-MiniLM-L6-v2.

    Returns dict with input_ids, attention_mask, token_type_ids.
    """
    tok = _load_tokenizer()
    if tok is None:
        return _fallback_tokenize(texts, max_len)

    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
    token_type_ids = np.zeros((len(texts), max_len), dtype=np.int64)

    # all-MiniLM-L6-v2 uses [CLS]=101, [SEP]=102, [PAD]=0
    CLS_ID = 101
    SEP_ID = 102
    PAD_ID = 0

    for i, text in enumerate(texts):
        text = text.lower().strip()[:10000]  # safety cap
        if not text:
            input_ids[i, 0] = CLS_ID
            attention_mask[i, 0] = 1
            continue

        encoded = tok.encode(text)
        ids = encoded.ids[:max_len - 2]  # leave room for [CLS] and [SEP]

        input_ids[i, 0] = CLS_ID
        for j, tid in enumerate(ids):
            input_ids[i, j + 1] = tid
        input_ids[i, len(ids) + 1] = SEP_ID

        seq_len = min(len(ids) + 2, max_len)
        attention_mask[i, :seq_len] = 1

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    }


def _fallback_tokenize(texts: List[str], max_len: int = 128) -> Dict[str, np.ndarray]:
    """Fallback tokenizer when tokenizers library not available.
    Uses simple whitespace + BPE-like chunking for basic use.
    """
    input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)

    for i, text in enumerate(texts):
        words = text.lower().split()[:max_len - 2]
        input_ids[i, 0] = 101  # [CLS]
        for j, w in enumerate(words):
            # Simple hash-based token ID for fallback
            input_ids[i, j + 1] = (hash(w) % 30000) + 100
        input_ids[i, len(words) + 1] = 102  # [SEP]
        seq_len = min(len(words) + 2, max_len)
        attention_mask[i, :seq_len] = 1

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": np.zeros_like(input_ids),
    }


def mean_pooling(hidden_states: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean pooling over token embeddings, masked by attention_mask."""
    input_mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(float)
    sum_embeddings = np.sum(hidden_states * input_mask_expanded, axis=1)
    sum_mask = np.clip(np.sum(input_mask_expanded, axis=1), 1e-9, None)
    return sum_embeddings / sum_mask


def encode(texts: List[str], batch_size: int = 32) -> np.ndarray:
    """Encode texts into 384-dim embeddings using ONNX model.

    Falls back to TF-IDF if ONNX model unavailable.
    Returns (N, 384) numpy array.
    """
    session = _load_session()
    if session is None:
        return _tfidf_encode(texts)

    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        tokens = tokenize(batch)

        outputs = session.run(
            ["last_hidden_state"],
            {
                "input_ids": tokens["input_ids"],
                "attention_mask": tokens["attention_mask"],
                "token_type_ids": tokens["token_type_ids"],
            }
        )

        embeddings = mean_pooling(outputs[0], tokens["attention_mask"])
        # Normalize to unit length for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.clip(norms, 1e-9, None)
        all_embeddings.append(embeddings)

    return np.vstack(all_embeddings) if all_embeddings else np.zeros((0, EMBED_DIM))


def _tfidf_encode(texts: List[str]) -> np.ndarray:
    """TF-IDF based fallback when ONNX model is unavailable.

    Produces crude embeddings from term frequency. Works for short texts.
    """
    # Build vocabulary from all texts
    vocab = {}
    for text in texts:
        for word in text.lower().split():
            if word not in vocab:
                vocab[word] = len(vocab)

    V = len(vocab)
    N = len(texts)
    embeddings = np.zeros((N, min(V, EMBED_DIM)))

    # Document frequency for IDF
    df = np.zeros(V)
    for i, text in enumerate(texts):
        words = set(text.lower().split())
        for word in words:
            if word in vocab:
                df[vocab[word]] += 1

    idf = np.log((N + 1) / (df + 1)) + 1

    # TF-IDF vectors
    for i, text in enumerate(texts):
        words = text.lower().split()
        for word in words:
            if word in vocab:
                j = vocab[word]
                tf = words.count(word) / max(len(words), 1)
                embeddings[i, j % EMBED_DIM] += tf * idf[j]

    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.clip(norms, 1e-9, None)

    return embeddings


def cosine_similarity(query_vec: np.ndarray, corpus_vecs: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query and corpus.
    query_vec: (D,) or (1, D)
    corpus_vecs: (N, D)
    Returns: (N,) similarity scores.
    """
    query_vec = query_vec.reshape(1, -1)
    return np.dot(corpus_vecs, query_vec.T).flatten()


class EmbeddingIndex:
    """In-memory embedding index with disk cache.

    Builds vectors for all memory entries and policies.
    Caches on disk to avoid recomputing on every load.
    """

    def __init__(self):
        self.entries: List[dict] = []   # each has text, source, tags
        self.vectors: Optional[np.ndarray] = None
        self._version = 0

    def _get_snapshot_hash(self) -> str:
        """Quick hash of all source files to detect changes."""
        hasher = hashlib.sha256()
        paths = [
            MEMORY_FILE,
            POLICY_DIR,
        ]
        for p in paths:
            if os.path.isfile(p):
                hasher.update(str(os.path.getmtime(p)).encode())
                hasher.update(str(os.path.getsize(p)).encode())
            elif os.path.isdir(p):
                for fname in sorted(os.listdir(p)):
                    fp = os.path.join(p, fname)
                    if fname.endswith(".json"):
                        hasher.update(str(os.path.getmtime(fp)).encode())
        return hasher.hexdigest()[:16]

    def _load_entries(self) -> List[dict]:
        """Load all retrievable entries from memory + policies."""
        entries = []

        # Load memory entries
        from retrieval import tag_filter
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE) as f:
                content = f.read()
            current = ""
            for line in content.split("\n"):
                if line.startswith("[tags:"):
                    if current.strip():
                        tags = tag_filter.extract_tags(current.strip())
                        entries.append({
                            "text": current.strip()[:2000],
                            "source": "memory",
                            "tags": tags,
                        })
                    current = line
                else:
                    current += "\n" + line
            if current.strip():
                tags = tag_filter.extract_tags(current.strip())
                entries.append({
                    "text": current.strip()[:2000],
                    "source": "memory",
                    "tags": tags,
                })

        # Load policies
        if os.path.isdir(POLICY_DIR):
            for fname in sorted(os.listdir(POLICY_DIR)):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(POLICY_DIR, fname)) as f:
                            p = json.load(f)
                        policy_text = (
                            f"Policy {p.get('id', fname)}: "
                            f"Trigger: {p.get('trigger', '')}. "
                            f"Rule: {p.get('rule', '')}. "
                            f"Status: {p.get('status', '')}. "
                            f"Scope: {p.get('scope', '')}"
                        )
                        entries.append({
                            "text": policy_text[:2000],
                            "source": "policy",
                            "tags": {"project": "hermes-config", "domain": "infra", "type": "lesson"},
                            "policy_id": p.get("id", fname),
                            "status": p.get("status", ""),
                        })
                    except (json.JSONDecodeError, IOError):
                        continue

        return entries

    def build(self, force: bool = False):
        """Build or rebuild the embedding index."""
        snapshot = self._get_snapshot_hash()

        # Try cache
        if not force and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "rb") as f:
                    cached = pickle.load(f)
                if cached.get("hash") == snapshot:
                    self.entries = cached["entries"]
                    self.vectors = cached["vectors"]
                    self._version = cached["version"]
                    return
            except Exception:
                pass

        # Build fresh
        t0 = time.time()
        self.entries = self._load_entries()
        texts = [e["text"] for e in self.entries]

        if texts:
            self.vectors = encode(texts)
        else:
            self.vectors = np.zeros((0, EMBED_DIM))

        self._version += 1

        # Cache
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "wb") as f:
            pickle.dump({
                "hash": snapshot,
                "entries": self.entries,
                "vectors": self.vectors,
                "version": self._version,
            }, f)

        elapsed = time.time() - t0
        print(f"[EmbeddingIndex] Built {len(self.entries)} entries in {elapsed:.1f}s", file=__import__('sys').stderr)

    def query(self, query_text: str, top_k: int = 10,
              threshold: float = 0.3,
              source_filter: Optional[str] = None,
              tag_filter_dict: Optional[Dict[str, str]] = None) -> List[dict]:
        """Query the index. Returns list of {entry, score, source, tags}."""
        if self.vectors is None or len(self.entries) == 0:
            return []

        query_vec = encode([query_text])[0]
        scores = cosine_similarity(query_vec, self.vectors)

        results = []
        for i, score in enumerate(scores):
            entry = self.entries[i]

            # Source filter
            if source_filter and entry.get("source") != source_filter:
                continue

            # Tag filter
            if tag_filter_dict:
                entry_tags = entry.get("tags", {})
                match = all(
                    entry_tags.get(k) == v
                    for k, v in tag_filter_dict.items()
                )
                if not match:
                    continue

            if score >= threshold:
                results.append({
                    **entry,
                    "score": float(score),
                })

        results.sort(key=lambda x: -x["score"])
        return results[:top_k]

    def query_policies(self, query_text: str, top_k: int = 5,
                       threshold: float = 0.3) -> List[dict]:
        """Query only policies relevant to the task."""
        return self.query(
            query_text,
            top_k=top_k,
            threshold=threshold,
            source_filter="policy",
        )

    def query_memory(self, query_text: str, top_k: int = 5,
                     threshold: float = 0.3) -> List[dict]:
        """Query only memory entries."""
        return self.query(
            query_text,
            top_k=top_k,
            threshold=threshold,
            source_filter="memory",
        )


# Global singleton index
_index: Optional[EmbeddingIndex] = None


def get_index(force_rebuild: bool = False) -> EmbeddingIndex:
    """Get or create the global embedding index."""
    global _index
    if _index is None or force_rebuild:
        _index = EmbeddingIndex()
        _index.build(force=force_rebuild)
    return _index


# Self-query routing

def route_query(task_text: str) -> dict:
    """
    Determine what to retrieve for a given task.

    Returns routing decision:
    {
        "need_policies": bool,
        "need_memory": bool,
        "policy_themes": [str],
        "memory_themes": [str],
        "policy_threshold_boost": float,  # boost or penalize policy threshold
    }
    """
    task_lower = task_text.lower()
    decision = {
        "need_policies": False,
        "need_memory": False,
        "policy_themes": [],
        "memory_themes": [],
        "policy_threshold_boost": 0.0,
    }

    # Policy-relevant triggers — MUST have one of these to justify policy injection
    policy_triggers = [
        "correct", "fix this", "never", "avoid", "bug", "error", "mistake",
        "policy", "rule", "dispatch", "delegate", "block", "stop",
        "don't", "should not", "must not", "always",
        "violation", "violate", "forbid", "prevent",
        "background", "subagent",
    ]
    if any(t in task_lower for t in policy_triggers):
        decision["need_policies"] = True
        decision["policy_themes"].append("corrections")

    # Dispatch-related
    if any(t in task_lower for t in ["dispatch", "delegate", "subagent", "background"]):
        decision["policy_themes"].append("dispatch")

    # Anything that looks like infrastructure or agent operation
    infra_triggers = ["config", "cron", "skill", "memory", "otto", "hermes", "gate", "improver"]
    if any(t in task_lower for t in infra_triggers):
        decision["need_policies"] = True

    # Memory-relevant triggers
    memory_triggers = [
        "project", "state", "status", "where", "progress", "health",
        "prospector", "lux", "signal-engine", "otto", "hermes",
        "overview", "summary", "report",
    ]
    if any(t in task_lower for t in memory_triggers):
        decision["need_memory"] = True

    # Projects always trigger memory
    projects = ["prospector", "signal engine", "lux", "hermes"]
    if any(p in task_lower for p in projects):
        decision["need_memory"] = True

    # Domain mismatch penalty — if the task is clearly about trading/market data,
    # policies about Hermes/agent infra are unlikely to be relevant
    domain_mismatch_triggers = {
        "trading": ["btc", "usdt", "eth", "crypto", "trading", "order book", "fill", "market",
                     "momentum", "signal", "portfolio"],
        "data-science": ["dataframe", "plot", "chart", "visualize", "report", "analytics",
                          "dashboard"],
    }
    for domain, triggers in domain_mismatch_triggers.items():
        if any(t in task_lower for t in triggers):
            # Boost threshold for policy injection — domain mismatch means policies less relevant
            if domain != "infra":
                decision["policy_threshold_boost"] = -0.15  # raise effective threshold

    return decision


def build_injection_payload(
    task_text: str,
    index: Optional[EmbeddingIndex] = None,
    max_policies: int = 5,
    max_memory: int = 5,
    threshold: float = 0.25,
) -> Tuple[str, dict]:
    """
    Build the full injection payload for a strategist dispatch.

    Uses embedding recall to select only the relevant slice:
    - Relevant policies for the task
    - Relevant memory entries
    - Routing decision metadata

    Returns (payload_text, log_entry).
    """
    from retrieval import tag_filter

    if index is None:
        index = get_index()

    route = route_query(task_text)

    # Apply routing-based threshold adjustment
    adjusted_threshold = threshold + route.get("policy_threshold_boost", 0.0)
    policy_threshold = max(0.15, adjusted_threshold)  # floor at 0.15

    retrieved_memory = []
    retrieved_policies = []

    if route["need_memory"]:
        retrieved_memory = index.query_memory(
            task_text, top_k=max_memory, threshold=threshold
        )

    if route["need_policies"]:
        retrieved_policies = index.query_policies(
            task_text, top_k=max_policies, threshold=policy_threshold
        )

    # Also run tag filter for any entries embeddings might have missed
    entries = index.entries
    tag_candidates = []
    for e in entries:
        score = tag_filter.score_entry(e["text"], task_text)
        if score >= 0.3:
            tag_candidates.append((score, e))
    tag_candidates.sort(key=lambda x: -x[0])

    # Merge: embedding results preferred, tag filter as supplement
    seen_texts = {r["text"] for r in retrieved_memory + retrieved_policies}
    for tscore, e in tag_candidates:
        if e["text"] not in seen_texts:
            # Tag-filter entries don't have scores/ids from embedding — mark them
            merge_entry = dict(e)
            merge_entry.setdefault("score", tscore)
            merge_entry.setdefault("policy_id", e.get("policy_id", "tag-match"))
            if e["source"] == "policy" and len(retrieved_policies) < max_policies:
                retrieved_policies.append(merge_entry)
                seen_texts.add(e["text"])
            elif e["source"] == "memory" and len(retrieved_memory) < max_memory:
                retrieved_memory.append(merge_entry)
                seen_texts.add(e["text"])

    # Build payload
    parts = []

    parts.append("## INVARIANTS (always injected)")
    parts.append("1. Source-or-die: every factual claim cites retrievable source or is unverifiable")
    parts.append("2. Kill-fast: cheapest decisive gate first")
    parts.append("3. Hermes owns control loop; Claude consulted at decisions; Minimax for cheap execution")
    parts.append("4. Never commit secrets to git or output")
    parts.append("5. Never substitute fabricated output for real execution results")

    if retrieved_memory:
        parts.append(f"\n## [RETRIEVED MEMORY — {len(retrieved_memory)} entries]")
        parts.append(f"  Routing: {json.dumps(route)}")
        for r in retrieved_memory:
            tags = r.get("tags", {})
            tag_str = " ".join(f"{k}:{v}" for k, v in tags.items()) if tags else "untagged"
            parts.append(f"\n  [{tag_str}] (score: {r['score']:.2f})")
            parts.append(f"  {r['text'][:500]}")

    if retrieved_policies:
        parts.append(f"\n## [ACTIVE POLICIES — {len(retrieved_policies)} relevant]")
        for p in retrieved_policies:
            parts.append(f"\n  ⚠️ ({p.get('policy_id', '?')}) — score: {p['score']:.2f}")
            parts.append(f"     Trigger: {p['text'].split('Trigger:')[-1].split('Rule:')[0].strip()[:100]}")
            parts.append(f"     Rule: {p['text'].split('Rule:')[-1].split('Status:')[0].strip()[:200]}")

    payload = "\n".join(parts)

    log_entry = {
        "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
        "task": task_text[:200],
        "routing": route,
        "retrieved_memory": len(retrieved_memory),
        "retrieved_policies": len(retrieved_policies),
        "embedding_threshold": threshold,
        "total_index_size": len(index.entries),
    }

    return payload, log_entry


def main():
    """CLI entry point."""
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not task:
        print("Usage: uv run python3 -m retrieval.embedding_recall '<task description>'")
        print("Returns structured injection payload for strategist call.")
        sys.exit(1)

    idx = get_index()
    payload, log_entry = build_injection_payload(task, index=idx)

    print(payload)
    print(f"\n--- metrics ---", file=sys.stderr)
    print(f"Index: {len(idx.entries)} entries", file=sys.stderr)
    print(f"Retrieved: {log_entry['retrieved_memory']} memory + {log_entry['retrieved_policies']} policies", file=sys.stderr)
    print(f"Routing: {json.dumps(log_entry['routing'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
