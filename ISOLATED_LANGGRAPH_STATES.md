# Isolated LangGraph States

The chatbot uses LangGraph's `StateGraph` with a single typed state definition and per-user isolation via thread-level checkpointing.

## State Definition (`agent_state.py`)

```python
from typing import TypedDict, List, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class GraphState(TypedDict):
    messages : Annotated[list[BaseMessage], add_messages]  # Conversation history
    router   : str                                          # 1 = general, 2 = jio-faq
    question : str                                          # Current user question
    context  : str                                          # Retrieved FAQ/document context
    answer   : str                                          # Final LLM-generated answer
```

### Key Design Choices

- **`messages`** uses the `add_messages` reducer, which **appends** new messages to the list instead of overwriting. Each node that returns `{"messages": [response]}` contributes to the accumulated conversation history.
- **`router`**, **`question`**, **`context`**, **`answer`** are plain strings with no reducer — they use **last-write-wins** semantics.

## Per-User State Isolation

State isolation is achieved via the `thread_id` configuration parameter, not through separate state definitions.

### FastAPI (`server.py:104`)

```python
config = {"configurable": {"thread_id": user_id}}
```

The `user_id` comes from Supabase JWT verification (`get_current_user`). This means:

- Each user gets their own isolated **conversation thread** in SQLite
- LangGraph loads the relevant checkpointed state for that `thread_id` on each `ainvoke()`
- Conversational memory (accumulated `messages`) is **scoped per user**
- Two users never see each other's conversation history

## Workflow Graph (`app.py:11-33`)

```
START
  |
  v
retrieve_node (hybrid search + reranking)
  |
  |--- router = "1" (score < 0.0) --> general_generation_node --> END
  |
  |--- router = "2" (score >= 0.0) --> generate_node -----------> END
```

The `route_request` function decides the path based on the CrossEncoder score:

```python
def route_request(state: GraphState):
    router_value = str(state.get("router", "2")).strip()
    if "1" in router_value:
        return "general_generation"
    else:
        return "generate"
```

### Node Behaviors

**`retrieve_node`** (`nodes.py:93-211`):
- Reads `state["question"]`
- Performs hybrid search (vector + keyword + graph traversal)
- CrossEncoder reranking with semantic routing
- Returns `{"context": ..., "router": 1|2}` — writes to `context` and `router`

**`generate_node`** (`nodes.py:213-236`):
- Reads `state["question"]` and `state["context"]`
- Calls `ChatCerebras("gpt-oss-120b")` with FAQ context
- Returns `{"answer": ..., "messages": [response]}` — appends to both `answer` and `messages`

**`general_generation_node`** (`nodes.py:32-87`):
- Reads `state["messages"]` and `state["question"]`
- Calls `ChatGroq("llama-3.1-8b-instant")` with tools for weather/general queries
- Returns `{"answer": ..., "messages": [response]}` — appends to both `answer` and `messages`

## How `add_messages` Works

The `add_messages` reducer (from `langgraph.graph.message`) is an Annotated reducer that:

1. **Appends** `BaseMessage` objects to the existing list
2. **Replaces** messages with the same `id` (deduplication)
3. Preserves the full conversation history across graph nodes

Example flow:
```
Initial: messages = []
retrieve_node returns: (no messages)
generate_node returns: {"messages": [AIMessage("...")]}
  → messages = [AIMessage("...")]
Next invocation (same thread_id):
  → messages loaded from checkpoint = [AIMessage("...")]
retrieve_node returns: (no messages)
generate_node returns: {"messages": [AIMessage("...")]}
  → messages = [AIMessage("..."), AIMessage("...")]
```

## State Isolation Boundaries

| Boundary | Mechanism | Scope |
|---|---|---|
| Per-user | `thread_id = user_id` | Full conversation isolation |
| Cross-node | `add_messages` reducer | Messages accumulate within a thread |
| Cross-field | Last-write-wins for strings | Each node overwrites `answer`/`context` |
