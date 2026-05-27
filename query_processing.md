# Query Processing

The query processing pipeline sits in `nodes.py:retrieve_node()`. It takes a raw user question, normalizes it with fuzzy logic, performs hybrid search across Neo4j, reranks results, and returns the top contexts for LLM generation.

## Pipeline Overview

```
User Question
    |
[1. Fuzzy Normalization] (phonetic + string similarity)
    |
[2. Brand Compound Expansion] (Jio Plus -> JioPlus)
    |
[3. Vector Search] (Neo4j, top 10)
[4. Keyword Fulltext Search] (Neo4j Lucene, top 10)
    |
[5. Graph Traversal] (Topic -> Subtopic -> FAQ)
    |
[6. CrossEncoder Reranking] (top 3)
    |
Retrieved Context --> generate_node()
```

## 1. Fuzzy Normalization

Corrects ASR mistranscriptions and typos before search using two complementary techniques.

### Phonetic Matching (jellyfish.metaphone)

Words are converted to their **Metaphone** phonetic code and looked up against a dictionary of Jio-related terms.

| Input | Metaphone Code | Matches | Corrected To |
|-------|---------------|---------|-------------|
| geo   | J             | Jio (J) | Jio         |
| jio   | J             | Jio (J) | Jio         |
| swiggy | SWK          | Swiggy (SWK) | Swiggy |
| siggy | SK            | no match (cutoff) | — |

### String Similarity (difflib.get_close_matches)

For words that don't match phonetically, we compute **difflib** sequence matcher similarity (cutoff >= 0.7) against the Jio dictionary in title case.

| Input | Closest Match | Score | Corrected? |
|-------|--------------|-------|-----------|
| fibre | Fiber | 0.8 | Yes |
| siggy | Swiggy | 0.73 | Yes |
| hotstar | Hotstar | 1.0 | Yes |

### Jio Dictionary

```python
JIO_DICTIONARY = [
    "Jio", "Fiber", "AirFiber", "Postpaid", "Prepaid",
    "Cinema", "Saavn", "Mart", "Plus", "Hotstar",
    "Netflix", "Amazon", "Swiggy", "Zomato", "MyJio"
]
```

### Implementation

The `fuzzy_replace()` function is applied via `re.sub(r'\b[A-Za-z]+\b', fuzzy_replace, question)` so that every alphabetic word in the question goes through both checks:

1. **Phonetic check**: If the Metaphone code exists in the lookup, replace immediately.
2. **String similarity check**: If difflib finds a close match above 0.7 cutoff, replace with the dictionary word.
3. **Short word guard**: Words <= 2 characters are skipped (except "4g", "5g").
4. **Fallback**: Return the original word unchanged.

## 2. Brand Compound Expansion

Jio brand names appear in both spaced and unspaced forms (e.g., "Jio Plus" vs "JioPlus", "Jio Fiber" vs "JioFiber"). To ensure the search catches both variants:

```python
jio_compounds = re.findall(r'(?i)\bjio\s+\w+\b', question)
glued_compounds = [comp.replace(" ", "") for comp in jio_compounds]
expanded_question = question + " " + " ".join(glued_compounds)
```

The expanded question is used for **both** vector embedding generation and keyword extraction, so both spaced and unspaced forms are searchable.

## 3. Vector Search

The expanded question is encoded using `all-MiniLM-L6-v2` (SentenceTransformer), producing a 384-dimensional embedding vector. This vector is used to query Neo4j's vector index (`faq_embeddings`), returning the top 10 most semantically similar FAQ nodes.

```
question -> all-MiniLM-L6-v2 -> embedding (384d)
                                   |
                     db.index.vector.queryNodes('faq_embeddings', 10, embedding)
                                   |
                              top 10 vector matches
```

## 4. Keyword Fulltext Search

Keywords are extracted from the raw (unexpanded) question:

1. **Tokenize**: Split on word boundaries.
2. **Stopword Removal**: Common English words are filtered out (is, what, how, the, a, an, etc.).
3. **Brand Compounds**: Glued compounds (e.g., "JioPlus") are appended as additional keywords.
4. **Lucene Query**: Keywords are joined with `OR` and searched via Neo4j's `db.index.fulltext.queryNodes('faq_text_index', ...)` with a limit of 10.

The fulltext index `faq_text_index` is a Lucene index on FAQ node properties `question` and `answer`, created by `create_index.py`.

## 5. Graph Traversal

The vector and fulltext result sets are combined and deduplicated:

```cypher
UNWIND (vector_nodes + text_nodes) AS f
WITH DISTINCT f
MATCH (t:Topic)-[:HAS_SUBTOPIC]->(s:Subtopic)-[:CONTAINS_FAQ]->(f)
RETURN "Topic: " + t.name + " | Subtopic: " + s.name
       + " | Question: " + f.question
       + " | Answer: " + f.answer AS context_string
```

Each unique FAQ node traverses the graph to build a human-readable context string that includes its topic, subtopic, question, and answer.

## 6. CrossEncoder Reranking

The candidate context strings (from both vector and fulltext paths) are scored using a CrossEncoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`).

```python
cross_inp = [[expanded_question, context] for context in candidates]
scores = reranker.predict(cross_inp)
```

Unlike bi-encoders (like the embedding model), CrossEncoders compute attention between the question and context jointly, producing more accurate relevance scores. The top 3 highest-scoring contexts are selected and concatenated into a single context string passed to `generate_node()`.

```
Candidate 1 -> Score 0.89  [SELECTED]
Candidate 2 -> Score 0.72  [SELECTED]
Candidate 3 -> Score 0.65  [SELECTED]
Candidate 4 -> Score 0.41  [DISCARDED]
...
```

## Summary

| Step | Technique | Purpose |
|------|-----------|---------|
| Fuzzy Normalization | Metaphone + difflib | Correct ASR typos and phonetic errors |
| Brand Expansion | Regex + concatenation | Match spaced/unspaced brand variants |
| Vector Search | all-MiniLM-L6-v2 + Neo4j | Semantic similarity retrieval |
| Fulltext Search | Lucene OR query (Neo4j) | Exact keyword matching |
| Graph Traversal | Cypher MATCH | Enrich FAQ nodes with topic hierarchy |
| Reranking | CrossEncoder | Select top 3 most relevant contexts |
