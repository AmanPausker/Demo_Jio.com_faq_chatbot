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

@tool
def save_user_memory(fact: str) -> str:
    """Use this tool to permanently save a fact across all chat sessions. This includes personal facts about the user (e.g. their name, preferences) AND facts about your own identity.
    CRITICAL: Save ONLY concise, atomic facts (e.g., "User's name is Aman", "User likes red"). DO NOT save conversational loops, verbatim dialogue, generic statements, or ephemeral actions (e.g. "User asked for the weather"). Be extremely clear about pronouns. If the user tells you their name, save it as 'The user's name is X'."""
    pass



def general_generation_node(State: GraphState):
    NVDIA_API_KEY = os.getenv("NVDIA_API_KEY")
    client = ChatNVIDIA(model="meta/llama-3.1-8b-instruct", nvidia_api_key=NVDIA_API_KEY)

    tools = [get_weather, get_current_location, save_user_memory]
    llm_with_tools = client.bind_tools(tools)
    question = State["question"]
    long_term_memory = State.get("long_term_memory", "")
    system_prompt = f"""
    You are a general purpose AI assistant. Unless specified otherwise in the LONG TERM MEMORY, your default name is Jio Assistant.
    If the user asks a general question, just answer it normally in plain text.
    
    USER'S LONG TERM MEMORY (PRIORITIZE THESE FACTS ABOUT YOUR IDENTITY AND THE USER):
    {long_term_memory}
    
    CRITICAL RULE: You MUST remember and acknowledge the user's name or personal details if they tell you.
    If the user tells you something about you (like assigning you a new name), you must prioritize that new name and remember it!
    DO NOT say "I don't retain information" - you DO have access to history and long-term memory!
    If a new concise fact is revealed about the user OR about your own identity, YOU MUST call the `save_user_memory` tool to save it.
    CRITICAL: DO NOT save conversational loops, verbatim dialogue, or ephemeral queries (like asking for the weather). Only save explicit, atomic, long-term facts (e.g. "User's name is Aman").
    
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
    For ALL OTHER normal questions and conversations (such as answering "what is my name", general chat, or if the weather tool fails), you MUST reply in normal, conversational PLAIN TEXT. DO NOT output JSON unless you are specifically generating the WeatherCard.
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
                elif tool_name == "save_user_memory":
                    print(f"LLM called save_user_memory with args: {tool_args}")
                    fact = tool_args.get("fact", "")
                    # Reject garbage facts that are too short or generic
                    if len(fact.strip()) < 10 or fact.strip().lower() in ["the user", "the assistant", "user", "assistant"]:
                        tool_output = f"Rejected: fact too short or generic: '{fact}'"
                        print(f"[WARN] {tool_output}")
                    else:
                        try:
                            from supabase import create_client, ClientOptions
                            user_supabase = create_client(os.getenv("VITE_SUPABASE_URL"), os.getenv("VITE_SUPABASE_ANON_KEY"), options=ClientOptions(headers={"Authorization": f"Bearer {State['token']}"}))
                            res = user_supabase.table("user_memory").select("facts").eq("user_id", State['user_id']).execute()
                            existing_facts = res.data[0].get("facts", []) if res.data else []
                            if existing_facts is None: existing_facts = []
                            existing_facts.append(fact)
                            
                            if res.data:
                                user_supabase.table("user_memory").update({"facts": existing_facts}).eq("user_id", State['user_id']).execute()
                            else:
                                user_supabase.table("user_memory").insert({"user_id": State['user_id'], "facts": existing_facts}).execute()
                            tool_output = f"Successfully saved memory: {fact}"
                            print(tool_output)
                        except Exception as e:
                            tool_output = f"Failed to save memory: {e}"
                            print(tool_output)
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
            r'save_user_memory',            # raw tool name
            r'</?tool_call>',               # XML tool tags
            r'"name"\s*:\s*"get_',          # JSON tool format
            r'parameters\s*[:\{]',          # parameters: or parameters{
            r'\btool\s*call\b',             # "tool call"
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
    # Create question-candidate pairs using the raw natural language question
    cross_inp = [[state["question"], context] for context in candidates]
    scores = reranker.predict(cross_inp)

    # Combine candidates with scores, apply a massive boost to uploaded documents, and sort
    scored_candidates = []
    for context, score in zip(candidates, scores):
        if "Uploaded Document Context:" in context:
            score += 5.0  # Massive priority boost for user's personal documents
        scored_candidates.append((context, score))
        
    scored_candidates = sorted(scored_candidates, key=lambda x: x[1], reverse=True)
    
    print("\n--- Cross Encoder Scores ---")
    for doc, score in scored_candidates:
        print(f"Score {score:.4f} | {doc[:80]}...")
    print("----------------------------\n")

    # Semantic Routing Logic: check if the best match is actually a good match
    best_score = scored_candidates[0][1]
    if best_score < -1.5:
        print(f"Semantic Router: Best score {best_score:.4f} < -1.5. Routing to General Agent.")
        return {"context": "", "router": 1}

    print(f"Semantic Router: Best score {best_score:.4f} >= -1.5. Routing to Jio FAQ Agent.")
    # Select the top 3 best matching candidates
    top_candidates = [candidate for candidate, score in scored_candidates[:3]]
    
    retrieved_context = "\n".join(top_candidates) + "\n"
    return {"context": retrieved_context, "router": 2}

def generate_node(state:GraphState):
    question = state["question"]
    context = state["context"]
    long_term_memory = state.get("long_term_memory", "")
    system_prompt =f"""You are a helpful JIO customer support assistant. Unless specified otherwise in the LONG TERM MEMORY, your default name is Jio Assistant.
    Use the provided CONTEXT to answer the user's question about Jio. 
    
    USER'S LONG TERM MEMORY (PRIORITIZE THESE FACTS ABOUT YOUR IDENTITY AND THE USER):
    {long_term_memory}
    
    IMPORTANT INSTRUCTIONS:
    1. For questions about Jio services, plans, or FAQs, answer using ONLY the provided context.
    2. If the user asks about personal details they shared earlier, or asks about your name/identity, you MUST use the long term memory and conversation history to answer them warmly.
    3. Treat slight variations in spelling or spacing (e.g., "Jio Plus" vs "JioPlus", "Swiggy" vs "siggy") as the same thing.
    4. If the context does not contain the answer to a Jio-related question, say you couldn't find information about that in the Jio FAQs.
    5. Do not create new information or guess outside the context for Jio-related facts.
    
    CONTEXT:
    {context}"""

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    
    try:
        response = client.invoke(messages)
        return {"answer": response.content, "messages":[response]}
    except Exception as e:
        print(f"NVIDIA API Error: {e}")
        return {"answer": "The AI service is currently experiencing high traffic (Queue Exceeded). Please wait a few moments and try your question again!"}