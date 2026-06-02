# Memory Saving

The chatbot employs several memory-saving strategies across conversation state persistence, token/window management, audio processing, and model caching.

## 1. LangGraph SQLite Checkpointing

Conversation history is persisted to disk via SQLite checkpoints rather than keeping everything in-memory.

### Gradio (`app.py:6-9`)

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
memory = SqliteSaver(conn)

app = workflow.compile(checkpointer=memory)
```

### FastAPI (`server.py:113-115`)

The async variant is used in the production server, with the Supabase `user_id` as the thread key:

```python
async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
    langgraph_app = workflow.compile(checkpointer=memory)
    final_state = await langgraph_app.ainvoke(initial_state, config=config)
```

Where `config = {"configurable": {"thread_id": user_id}}` ensures each user's conversation history is stored and loaded independently.

### How Checkpointing Saves Memory

- Only the **current state** (latest `messages` list, `context`, `answer`) is held in memory during execution
- Past conversation turns are serialized to `checkpoints.db` on disk
- On subsequent invocations with the same `thread_id`, previous messages are loaded from SQLite, not recomputed

## 2. TTS Text Chunking (`get_audio.py:36-46`)

Before sending text to the Sarvam AI TTS API, long responses are split into manageable chunks to avoid overwhelming the API:

```python
chunks = []
current_chunk = ""
for s in sentences:
    if len(current_chunk) + len(s) < 200:
        current_chunk += s + " "
    else:
        if current_chunk:
            chunks.append(current_chunk.strip())
        current_chunk = s + " "
```

- **Max chunk size**: 200 characters
- Chunks are dispatched in **parallel** via `asyncio.gather`, then reassembled in order

## 3. Audio Duration Capping (`frontend/src/utils/audioUtils.js:17-20`)

Client-side audio recording is capped to stay within Sarvam AI's API limits:

```javascript
const MAX_SAMPLES = 25 * 16000;  // 25 seconds at 16kHz
if (data.length > MAX_SAMPLES) { data = data.slice(0, MAX_SAMPLES); }
```

## 4. RAG Context Truncation (`nodes.py:208`)

From the retrieved candidates, only the **top 3** are passed to the LLM after CrossEncoder reranking:

```python
top_candidates = [candidate for candidate, score in scored_candidates[:3]]
retrieved_context = "\n".join(top_candidates) + "\n"
```

This limits the prompt size by discarding low-relevance contexts rather than passing everything.

## 5. Document Chunking (`file_workflow.py:46`)

Uploaded PDFs are split into overlapping chunks before embedding:

```python
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
```

- **chunk_size**: 1000 characters
- **chunk_overlap**: 200 characters (preserves context across chunk boundaries)

## 6. Model Caching

Compute-intensive models are loaded **once at module import time** and reused across all requests:

**`nodes.py:22-25`:**
```python
model = SentenceTransformer('all-MiniLM-L6-v2')
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
```

**`file_workflow.py:65`:**
```python
model = SentenceTransformer('all-MiniLM-L6-v2')
```

This avoids re-loading the model into memory on every request.

## Summary

| Technique | Location | What it does |
|---|---|---|
| SQLite checkpointing | `app.py:6-9`, `server.py:113` | Persists conversation state to disk |
| TTS chunking | `get_audio.py:36-46` | Splits text into ≤200 char chunks |
| Audio capping | `frontend/src/utils/audioUtils.js:17-20` | Caps recording at 25s |
| Context truncation | `nodes.py:208` | Keeps only top 3 reranked results |
| Document chunking | `file_workflow.py:46` | 1000-char chunks with 200 overlap |
| Model caching | `nodes.py:22-25` | Loads embeddings/reranker once |
