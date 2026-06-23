import requests
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer, CrossEncoder
from agent_state import GraphState
import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

from file_workflow import search_qdrant
from system_instructions import (
    get_general_generation_prompt,
    get_faq_generation_prompt,
    MEMORY_EVALUATION_PROMPT,
    STM_SUMMARIZATION_PROMPT
)
from logger import logger
load_dotenv(override=True)
from langchain_ollama import ChatOllama
client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True, num_ctx=8192)
from tools import get_weather, get_current_location

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"
driver = GraphDatabase.driver(URL, auth=(USERNAME, PASSWORD))
print("Loading Embedding Model")
model = SentenceTransformer('all-MiniLM-L6-v2')

print("Loading Reranking Model")
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

CLOUDFARE_ID = os.getenv("CLOUDFARE_ACCOUNT_ID")
WORKERS_API_KEY = os.getenv("WORKERS_API_KEY")

from langchain_core.tools import tool

async def general_generation_node(State: GraphState):
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True, num_ctx=8192)

    tools = [get_weather, get_current_location]
    question = State.get("question", "").lower()
    
    weather_keywords = ["weather", "temperature", "forecast", "rain", "hot", "cold", "climate", "location", "where am i", "current city"]
    if any(kw in question for kw in weather_keywords):
        llm_with_tools = client.bind_tools(tools)
    else:
        llm_with_tools = client
    user_id = State.get("user_id", "")
    token = State.get("token", "")
    memory_context = fetch_user_memories(user_id, token)

    system_prompt = get_general_generation_prompt(memory_context)
    raw_messages = [SystemMessage(content=system_prompt)] + State["messages"]
    
    messages = []
    for m in raw_messages:
        if isinstance(m, SystemMessage) and len(messages) > 0:
            messages[0].content += "\n\n" + m.content
        else:
            messages.append(m)
    
    try:
        response = None
        async for chunk in llm_with_tools.astream(messages):
            if response is None:
                response = chunk
            else:
                response += chunk

        max_tool_rounds = 5
        tool_round = 0
        while response.tool_calls and tool_round < max_tool_rounds:
            tool_round += 1
            messages.append(response)
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                if tool_name == "get_weather":
                    tool_output = get_weather.invoke(tool_args)
                elif tool_name == "get_current_location":
                    tool_output = get_current_location.invoke(tool_args)
                else:
                    tool_output = "Unknown tool"
                    
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_call["id"]))
                
                # "One-Call" Exception: Return immediately for weather to save LLM round trip
                if tool_name == "get_weather" and "WeatherCard" in str(tool_output):
                    return {"answer": str(tool_output), "messages": messages}
                
            response = None
            async for chunk in llm_with_tools.astream(messages):
                if response is None:
                    response = chunk
                else:
                    response += chunk
        
        if tool_round >= max_tool_rounds:
            print(f"[WARN] Tool call loop hit max {max_tool_rounds} rounds, breaking out")
        
        answer = response.content
        

        # -- Restored Leaked Tool Interceptor for cow/gemma2_tools:2b --
        import json
        import re as _re
        json_match = _re.search(r'(\{[\s\S]*"name"\s*:\s*"get_weather"[\s\S]*\})', answer)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if parsed.get("name") == "get_weather":
                    tool_args = parsed.get("parameters", {}) or parsed.get("arguments", {})
                    tool_output = get_weather.invoke(tool_args)
                    if "WeatherCard" in str(tool_output):
                        print("[TOOL] One-Call Exception triggered for leaked JSON get_weather. Returning raw JSON.")
                        return {"answer": str(tool_output), "messages": [response]}
            except Exception as e:
                print(f"[WARN] Failed to parse leaked tool JSON: {e}")
        # -----------------------------------------------------------
        
        # Guard: if the model leaked a tool call as plain text instead of using
        # the structured tool API, retry without tools to get a real answer.
        tool_leak_patterns = [
            r'function\s*[:\(]',           # function:get_weather or function(
            r'get_weather',                 # raw tool name
            r'get_current_location',        # raw tool name
            r'</?tool_call>',               # XML tool tags
            r'"name"\s*:\s*"get_',          # JSON tool format
            r'parameters\s*[:\{]',          # parameters: or parameters{
            r'\btool\s*call\b',             # "tool call"
            r'function call',               # "function call"
            r'specific function',           # "specific function"
        ]
        combined_pattern = '|'.join(tool_leak_patterns)
        if _re.search(combined_pattern, answer, _re.IGNORECASE):
            print(f"[WARN] Model leaked tool call as text, retrying without tools.")
            print(f"[WARN] Original answer: {answer[:200]}")
            plain_llm = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, streaming=True, num_ctx=8192)
            raw_plain = [SystemMessage(content=system_prompt)] + State["messages"]
            plain_messages = []
            for m in raw_plain:
                if isinstance(m, SystemMessage) and len(plain_messages) > 0:
                    plain_messages[0].content += "\n\n" + m.content
                else:
                    plain_messages.append(m)
            response = None
            async for chunk in plain_llm.astream(plain_messages):
                if response is None:
                    response = chunk
                else:
                    response += chunk
            answer = response.content
            
        return {"answer": answer, "messages":[response]}
    except Exception as e:
        print(f"LLM Generation Error: {e}")
        return {"answer": "I'm sorry, but I couldn't process that request properly. Could you try rephrasing?"}


"""Retrieving node takes the question from user ( TypedDict class )->converts that question to a embedding_vector
 and then we search that vector with the closest vector in neo4j database. If no relevant data found then r
 eturns an empty result otherwise we extract the top results that are closest to the question"""
from langchain_core.runnables import RunnableConfig

def retrieve_node(state:GraphState, config: RunnableConfig):
    print("Retreiving from neo4j")
    question = state['question']
    
    # 0. Intelligent Token-Free Fuzzy Normalizer
    # Automatically corrects missing spaces (jioplus -> Jio Plus) and typos (siggy -> Swiggy) locally
    import difflib
    import re
    
    JIO_DICTIONARY = [
        "Jio", "Fiber", "AirFiber", "Postpaid", "Prepaid", 
        "JioPlus", "Jio Fiber", "Jio AirFiber", "JioCinema", 
        "JioSaavn", "JioMart", "Hotstar", "Netflix", "Amazon", 
        "Swiggy", "Zomato", "MyJio", "JioTV"
    ]
    
    product_mapping = {
        r'\bjio\s*plus\b': 'JioPlus',
        r'\bjio\s*fiber\b': 'Jio Fiber',
        r'\bair\s*fiber\b': 'Air Fiber',
        r'\bjio\s*air\s*fiber\b': 'Jio AirFiber',
        r'\bjio\s*cinema\b': 'JioCinema',
        r'\bjio\s*saavn\b': 'JioSaavn',
        r'\bjio\s*mart\b': 'JioMart',
        r'\bmy\s*jio\b': 'MyJio',
        r'\bjio\s*tv\b': 'JioTV'
    }
    
    for pattern, replacement in product_mapping.items():
        question = re.sub(pattern, replacement, question, flags=re.IGNORECASE)
    
    def fuzzy_replace(match):
        word = match.group(0)
        if len(word) <= 2 and word.lower() not in ["4g", "5g"]:
            return word
            
        word_lower = word.lower()
        
        # Check exact match case-insensitively (including checking if the unspaced version matches)
        for dict_word in JIO_DICTIONARY:
            if word_lower == dict_word.lower() or word_lower == dict_word.replace(" ", "").lower():
                return dict_word
                
        # Find best match using difflib ignoring case
        best_match = None
        best_ratio = 0
        for dict_word in JIO_DICTIONARY:
            ratio = difflib.SequenceMatcher(None, word_lower, dict_word.lower()).ratio()
            if ratio > best_ratio and ratio >= 0.75:
                best_ratio = ratio
                best_match = dict_word
                
        if best_match:
            return best_match
            
        return word
        
    question = re.sub(r'\b[A-Za-z]+\b', fuzzy_replace, question)
    state['question'] = question
    
    # 1. Vector Search uses the corrected question
    question_vector = model.encode(question).tolist()

    # 2. Extract Keywords locally
    words = re.findall(r'\b\w+\b', question)
    stopwords = {"is", "what", "how", "the", "a", "an", "for", "to", "in", "on", "of", "and", "or", "tell", "me", "about", "are", "do", "does", "i", "can", "something", "some"}
    keywords = [w for w in words if w.lower() not in stopwords]
        
    keyword_query = " OR ".join(keywords) if keywords else question
        
    print(f"Executing keyword query: {keyword_query}")

    cypher_query = """
    // 1. Vector Search
    CALL () {
        CALL db.index.vector.queryNodes('faq_embeddings', 10, $question_embedding) YIELD node AS vector_node
        RETURN collect(vector_node) AS vector_nodes
    }
    
    // 2. Keyword Search
    CALL () {
        CALL db.index.fulltext.queryNodes('faq_text_index', $keyword_query, {limit: 10}) YIELD node AS text_node
        RETURN collect(text_node) AS text_nodes
    }
    
    // 3. Combine, Remove Duplicates, and Traverse Graph
    UNWIND (vector_nodes + text_nodes) AS f
    WITH DISTINCT f
    MATCH (t:Topic)-[:HAS_SUBTOPIC]->(s:Subtopic)-[:CONTAINS_FAQ]->(f)
    RETURN "Topic: " + t.name + " | Subtopic: " + s.name + " | Question: " + f.question + " | Answer: " + f.answer AS context_string
    """
    
    candidates = []
    with driver.session() as session:
        result = session.run(cypher_query, question_embedding=question_vector, keyword_query=keyword_query)
        for record in result:
            candidates.append(record['context_string'])
    
    user_id = state.get("user_id", "")
    session_id = config.get("configurable", {}).get("thread_id", "")
    qdrant_results = search_qdrant(question_vector, user_id=user_id, session_id=session_id)
    for chunk in qdrant_results:
        # We wrap it in a string so the LLM knows where it came from
        candidates.append(f"Uploaded Document Context: {chunk}")
        
    if not candidates:
        print("Semantic Router: No candidates found. Routing to General Agent.")
        return {"context": "", "router": 1}

    # 4. Rerank candidates using CrossEncoder
    cross_inp = [[state["question"], context] for context in candidates]
    scores = reranker.predict(cross_inp)

    # Combine candidates with scores, apply a massive boost to uploaded documents, and sort
    scored_candidates = []
    for context, score in zip(candidates, scores):
        if "Uploaded Document Context:" in context:
            score += 5.0  # Massive priority boost for user's personal documents
        scored_candidates.append((context, score))

    scored_candidates = sorted(scored_candidates, key=lambda x: x[1], reverse=True)
    best_score = scored_candidates[0][1]

    # Semantic Routing Logic
    if best_score < -1.5:
        # Score too low — route to general agent, no logging (not a FAQ hit)
        print(f"Semantic Router: Best score {best_score:.4f} < -1.5. Routing to General Agent.")
        return {"context": "", "router": 1}

    # Score is good enough — log it to Loki
    print(f"Semantic Router: Best score {best_score:.4f} >= -1.5. Routing to Jio FAQ Agent.")
    logger.info(
        f"[RERANK] question='{state['question'][:80]}' "
        f"best_score={best_score:.4f} "
        f"top_match='{scored_candidates[0][0][:80]}...'"
    )

    top_candidates = [candidate for candidate, score in scored_candidates[:1]]
    
    retrieved_context = "\n".join(top_candidates) + "\n"
    return {"context": retrieved_context, "router": 2}

def fetch_user_memories(user_id: str, token: str) -> str:
    if not user_id:
        return ""
    try:
        from supabase import create_client, ClientOptions
        SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
        SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY")
        if token:
            user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
        else:
            user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        
        res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
        if res.data:
            facts = res.data[0].get("facts", []) or []
            if facts:
                return "User Profile / Long-Term Memories:\n" + "\n".join(f"- {m}" for m in facts) + "\n"
    except Exception as e:
        print(f"Error fetching memories: {e}")
    return ""

async def generate_node(state:GraphState):
    question = state["question"]
    context = state["context"]
    user_id = state.get("user_id", "")
    token = state.get("token", "")
    memory_context = fetch_user_memories(user_id, token)

    system_prompt = get_faq_generation_prompt(memory_context, context)

    raw_messages = [SystemMessage(content=system_prompt)] + state["messages"]
    messages = []
    for m in raw_messages:
        if isinstance(m, SystemMessage) and len(messages) > 0:
            messages[0].content += "\n\n" + m.content
        else:
            messages.append(m)
    
    try:
        response = None
        async for chunk in client.astream(messages):
            if response is None:
                response = chunk
            else:
                response += chunk
        return {"answer": response.content, "messages":[response]}
    except Exception as e:
        print(f"NVIDIA API Error: {e}")
        return {"answer": "The AI service is currently experiencing high traffic (Queue Exceeded). Please wait a few moments and try your question again!"}

import json
from langchain_ollama import ChatOllama
from supabase import create_client, ClientOptions

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY")

async def evaluate_and_save_memory_bg(question: str, answer: str, user_id: str, token: str):
    """
    Evaluates the conversation in the background and saves to Supabase if necessary.
    """
    print("\n[MEMORY BACKGROUND] Evaluating conversation for long-term memory...")
    
    if not question:
        return
    from langchain_ollama import ChatOllama
    client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, num_ctx=8192)
    
    system_prompt = MEMORY_EVALUATION_PROMPT


    user_prompt = f"User Question: {question}\nAssistant Answer: {answer}"
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        response = await client.ainvoke(messages)
        content = response.content.strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        import re
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"[MEMORY BACKGROUND] -> JSON Parse Error: {e} | Content: {content}")
            return
            
        save_memory = result.get("save_memory", False)
        memory_content = result.get("memory_content", "")
        
        if save_memory and memory_content:
            print(f"[MEMORY BACKGROUND] -> DECISION: SAVE TO LTM")
            print(f"[MEMORY BACKGROUND] -> CONTENT: {memory_content}")
            
            print(f"\n[MEMORY BACKGROUND] Connecting to Supabase to store memory...")
            if token:
                user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {token}"}))
            else:
                user_supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
                
            res = user_supabase.table("user_memory").select("facts").eq("user_id", user_id).execute()
            if res.data:
                facts = res.data[0].get("facts", []) or []
                if memory_content not in facts:
                    facts.append(memory_content)
                    user_supabase.table("user_memory").update({"facts": facts}).eq("user_id", user_id).execute()
            else:
                user_supabase.table("user_memory").insert({
                    "user_id": user_id,
                    "facts": [memory_content]
                }).execute()
            
            print(f"[MEMORY BACKGROUND] -> Successfully stored memory in Supabase.")
        else:
            print("[MEMORY BACKGROUND] -> DECISION: DO NOT SAVE")
            
    except Exception as e:
        print(f"[MEMORY BACKGROUND] -> Error: {e}")
        logger.error(f"[MEMORY BACKGROUND] Error: {e}")

async def summarize_short_term_memory_bg(session_id: str):
    """
    Background task to summarize short term memory (LangGraph state) 
    if it exceeds 5 messages, to prevent context bloat.
    """
    from app import workflow
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain_core.messages import RemoveMessage, SystemMessage
    
    print(f"\n[STM SUMMARIZER] Checking session {session_id} for memory bloat...")
    config = {"configurable": {"thread_id": session_id}}
    
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as memory:
        langgraph_app = workflow.compile(checkpointer=memory)
        state = await langgraph_app.aget_state(config)
        
        if not state or not hasattr(state, "values") or "messages" not in state.values:
            return
            
        messages = state.values["messages"]
        if len(messages) <= 5:
            print(f"[STM SUMMARIZER] Only {len(messages)} messages, skipping summary.")
            return
            
        print(f"[STM SUMMARIZER] {len(messages)} messages found. Summarizing older messages...")
        
        messages_to_summarize = messages[:-2]
        
        convo_text = ""
        for m in messages_to_summarize:
            role = "User" if m.type == "human" else "AI"
            convo_text += f"{role}: {m.content}\n"
            
        from langchain_ollama import ChatOllama
        client = ChatOllama(model="cow/gemma2_tools:2b", base_url="http://localhost:11434", think=False, num_ctx=8192)
        
        system_prompt = STM_SUMMARIZATION_PROMPT
        prompt = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Conversation:\n{convo_text}")
        ]
        
        try:
            response = await client.ainvoke(prompt)
            summary = response.content.strip()
            
            delete_msgs = [RemoveMessage(id=m.id) for m in messages_to_summarize if m.id]
            summary_msg = SystemMessage(content=f"[System Note: Summary of previous conversation]\n{summary}")
            
            await langgraph_app.aupdate_state(config, {"messages": delete_msgs + [summary_msg]})
            print(f"[STM SUMMARIZER] Successfully summarized and pruned {len(messages_to_summarize)} messages.")
            
        except Exception as e:
            print(f"[STM SUMMARIZER] Error summarizing: {e}")
            logger.error(f"[STM SUMMARIZER] Error: {e}")