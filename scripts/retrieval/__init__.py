"""F1 — Retrieval Layer for Otto.

Three-tier retrieval:
1. Tag-filter (keyword, fast first-pass)
2. Embedding recall (semantic, via mini embedding model)
3. Self-query routing (determines what to retrieve per task)

Policy-level slicing: inject only policies relevant to the current task.
"""
