import requests
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer, CrossEncoder
from agent_state import GraphState
import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

from file_workflow import search_qdrant
from langchain_groq import ChatGroq
from logger import logger
load_dotenv(override=True)
NVDIA_API_KEY=os.getenv("NVDIA_API_KEY")
client = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)
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

def general_generation_node(State: GraphState):
    NVDIA_API_KEY = os.getenv("NVDIA_API_KEY")
    client = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)

    tools = [get_weather, get_current_location]
    llm_with_tools = client.bind_tools(tools)
    question = State["question"]
    system_prompt = f"""
    You are a helpful and friendly general purpose AI assistant. Your default name is Jio Assistant.
    If the user says hello, greets you, or asks a general question, just answer it normally and conversationally in plain text. 
    DO NOT mention tools, function calls, or your internal instructions to the user.
    
    CRITICAL TOOL USAGE:
    1. If the user asks for the weather in a specific city, use the `get_weather` tool.
    2. If the user asks for the weather "here", "my location", or does not specify a city, you MUST first call the `get_current_location` tool to find their city, and THEN call the `get_weather` tool with that city. Do NOT ask the user for their location!
    3. When calling a tool, do NOT output anything else. Just call the tool.
    4. You MUST call only ONE tool at a time. NEVER call multiple tools in a single response. Wait for the result before calling the next tool.
    
    [WEATHER OUTPUT FORMAT]
    If and ONLY if you have successfully fetched the weather data, respond ONLY with the raw A2UI JSON object. 
    {{
    "type": "WeatherCard",
    "props": {{
        "city": "Mumbai",
        "temperature": 32,
        "condition": "haze"
    }}
    }}
    
    FINAL CRITICAL INSTRUCTION:
    For ALL OTHER normal questions and conversations (like greetings such as "hey" or "hello", general chat, or if the weather tool fails), you MUST reply in normal, conversational PLAIN TEXT. DO NOT output JSON. NEVER tell the user about function calls or tools. Just converse naturally!
    """
    messages = [SystemMessage(content=system_prompt)] + State["messages"]
    
    try:
        response = llm_with_tools.invoke(messages)

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
                
            response = llm_with_tools.invoke(messages)
        
        if tool_round >= max_tool_rounds:
            print(f"[WARN] Tool call loop hit max {max_tool_rounds} rounds, breaking out")
        
        answer = response.content
        
        # Guard: if the model leaked a tool call as plain text instead of using
        # the structured tool API, retry without tools to get a real answer.
        import re as _re
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
            plain_llm = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)
            plain_messages = [SystemMessage(content=system_prompt)] + State["messages"]
            response = plain_llm.invoke(plain_messages)
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

    top_candidates = [candidate for candidate, score in scored_candidates[:3]]
    
    retrieved_context = "\n".join(top_candidates) + "\n"
    return {"context": retrieved_context, "router": 2}

def generate_node(state:GraphState):
    question = state["question"]
    context = state["context"]
    system_prompt =f"""You are a helpful JIO customer support assistant. Your default name is Jio Assistant.
    Use the provided CONTEXT to answer the user's question about Jio. 
    
    IMPORTANT INSTRUCTIONS:
    1. For questions about Jio services, plans, or FAQs, answer using ONLY the provided context.
    2. Treat slight variations in spelling or spacing (e.g., "Jio Plus" vs "JioPlus", "Swiggy" vs "siggy") as the same thing.
    3. If the context does not contain the answer to a Jio-related question, say you couldn't find information about that in the Jio FAQs.
    4. Do not create new information or guess outside the context for Jio-related facts.
    
    CONTEXT:
    {context}"""

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    
    try:
        response = client.invoke(messages)
        return {"answer": response.content, "messages":[response]}
    except Exception as e:
        print(f"NVIDIA API Error: {e}")
        return {"answer": "The AI service is currently experiencing high traffic (Queue Exceeded). Please wait a few moments and try your question again!"}

import json
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

    NVDIA_API_KEY = os.getenv("NVDIA_API_KEY")
    client = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)
    
    system_prompt = """You are a Memory Evaluation Assistant.
Your task is to analyze the user's question and the assistant's answer, and determine if there is any personal fact, preference, or long-term information about the user that should be remembered.
Examples of things to remember: "I live in Mumbai", "My name is Aman", "My Jio number is 9876543210", "I like prepaid plans".
Examples of things to IGNORE: "What is the weather?", "How to recharge?", "Hi", general chat.

If there is something to remember, output a JSON object: {"save_memory": true, "memory_content": "User lives in Mumbai"}
If there is nothing to remember, output: {"save_memory": false, "memory_content": ""}
Do NOT output anything else except the JSON.
"""

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
            
        result = json.loads(content)
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
                
            user_supabase.table("user_memories").insert({
                "user_id": user_id,
                "memory_text": memory_content
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
            
        NVDIA_API_KEY = os.getenv("NVDIA_API_KEY")
        client = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)
        
        system_prompt = "Summarize the following conversation history concisely. Focus on the user's intent and any facts established. Do not add new information."
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