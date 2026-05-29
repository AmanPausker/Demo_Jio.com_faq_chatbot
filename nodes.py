import requests
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer, CrossEncoder
from agent_state import GraphState
import os
from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

from langchain_groq import ChatGroq
load_dotenv(override=True)
CEREBRAS_API_KEY=os.getenv("CEREBRAS_API_KEY")
client = ChatCerebras(model="gpt-oss-120b", api_key=CEREBRAS_API_KEY)
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



def general_generation_node(State: GraphState):
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    client = ChatGroq(model = "llama-3.1-8b-instant", api_key = GROQ_API_KEY)

    tools = [get_weather, get_current_location]
    llm_with_tools = client.bind_tools(tools)
    question = State["question"]
    system_prompt = f"""
    You are a general purpose AI assistant.
    If the user asks a general question, just answer it normally in plain text.
    
    HOWEVER, if someone asks about the weather, you MUST use the get_weather tool to fetch real data.
    IMPORTANT: When calling a tool, do NOT output anything else. Just call the tool.
    CRITICAL: You ONLY have access to `get_weather` and `get_current_location`. DO NOT attempt to use `brave_search` or any other tool that is not explicitly provided.
    
    If and ONLY if you are providing weather information, respond ONLY in the A2UI JSON format.
    You have access to the following component in the frontend catalog:
    - "WeatherCard": Requires props: {{"city": "str", "temperature": "num", "condition": "str"}}
    Example weather output:
    {{
    "type": "WeatherCard",
    "props": {{
        "city": "Mumbai",
        "temperature": 32,
        "condition": "haze"
    }}
    }}
    You have two tools get_weather and get_current_location : you are free to use those tools incase necessary.
    """
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
    
    try:
        response = llm_with_tools.invoke(messages)

        while response.tool_calls:
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
            
        return {"answer": response.content}
    except Exception as e:
        print(f"LLM Generation Error: {e}")
        return {"answer": "I'm sorry, but I couldn't process that request properly. Could you try rephrasing?"}


"""Retrieving node takes the question from user ( TypedDict class )->converts that question to a embedding_vector
 and then we search that vector with the closest vector in neo4j database. If no relevant data found then r
 eturns an empty result otherwise we extract the top results that are closest to the question"""
def retrieve_node(state:GraphState):
    print("Retreiving from neo4j")
    question = state['question']
    
    # 0. Ultimate Fuzzy Logic Normalizer (Phonetic + String Similarity)
    # Automatically corrects mistranscriptions and typos.
    import jellyfish
    import difflib
    import re
    
    JIO_DICTIONARY = ["Jio", "Fiber", "AirFiber", "Postpaid", "Prepaid", "Cinema", "Saavn", "Mart", "Plus", "Hotstar", "Netflix", "Amazon", "Swiggy", "Zomato", "MyJio"]
    phonetic_lookup = {jellyfish.metaphone(word): word for word in JIO_DICTIONARY}
    
    def fuzzy_replace(match):
        word = match.group(0)
        if len(word) <= 2 and word.lower() not in ["4g", "5g"]:
            return word
            
        # 1. Phonetic Check (Catches "Geo" -> "Jio")
        code = jellyfish.metaphone(word)
        if code in phonetic_lookup:
            return phonetic_lookup[code]
            
        # 2. String Similarity Check (Catches "siggy" -> "Swiggy", "fibre" -> "Fiber")
        # We check against the dictionary ignoring case, but difflib is case-sensitive, so we use titlecase
        close_matches = difflib.get_close_matches(word.title(), JIO_DICTIONARY, n=1, cutoff=0.7)
        if close_matches:
            return close_matches[0]
            
        return word
    
    question = re.sub(r'\b[A-Za-z]+\b', fuzzy_replace, question)
    
    # 0.1 Specific Brand Normalizer
    # Only glue specific brands that are written as single words in the FAQ
    brand_map = {
        r"(?i)\bjio\s*plus\b": "JioPlus",
        r"(?i)\bjio\s*cinema\b": "JioCinema",
        r"(?i)\bjio\s*saavn\b": "JioSaavn",
        r"(?i)\bjio\s*tv\b": "JioTV",
        r"(?i)\bjio\s*mart\b": "JioMart",
        r"(?i)\bmy\s*jio\b": "MyJio"
    }
    
    keyword_question = question
    for pattern, replacement in brand_map.items():
        keyword_question = re.sub(pattern, replacement, keyword_question)
    
    # 1. Vector Search uses the normalized question
    question_vector = model.encode(keyword_question).tolist()

    # 2. Extract Keywords locally
    words = re.findall(r'\b\w+\b', keyword_question)
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

    if not candidates:
        print("Semantic Router: No candidates found. Routing to General Agent.")
        return {"context": "", "router": 1}

    # 4. Rerank candidates using CrossEncoder
    # Create question-candidate pairs using the normalized question
    cross_inp = [[keyword_question, context] for context in candidates]
    scores = reranker.predict(cross_inp)

    # Combine candidates with scores and sort by score descending
    scored_candidates = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    
    print("\n--- Cross Encoder Scores ---")
    for doc, score in scored_candidates:
        print(f"Score {score:.4f} | {doc[:80]}...")
    print("----------------------------\n")

    # Semantic Routing Logic: check if the best match is actually a good match
    best_score = scored_candidates[0][1]
    if best_score < 0.0:
        print(f"Semantic Router: Best score {best_score:.4f} < 0.0. Routing to General Agent.")
        return {"context": "", "router": 1}

    print(f"Semantic Router: Best score {best_score:.4f} >= 0.0. Routing to Jio FAQ Agent.")
    # Select the top 3 best matching candidates
    top_candidates = [candidate for candidate, score in scored_candidates[:3]]
    
    retrieved_context = "\n".join(top_candidates) + "\n"
    return {"context": retrieved_context, "router": 2}

def generate_node(state:GraphState):
    question = state["question"]
    context = state["context"]
    system_prompt =f"""You are a helpful JIO customer support assistant.
    Use the following CONTEXT to answer the user's question. 
    
    IMPORTANT INSTRUCTIONS:
    1. Answer the user's query clearly and in detail using ONLY the provided context.
    2. If the user's query is broad (e.g., "Tell me about X"), find the most relevant FAQ in the context and provide its details.
    3. Treat slight variations in spelling or spacing (e.g., "Jio Plus" vs "JioPlus", "Swiggy" vs "siggy") as the same thing.
    4. If the context does not contain the answer at all, say you couldn't find information about that in the Jio FAQs.
    5. Do not create new information or guess outside the context.
    
    CONTEXT:
    {context}"""

    messages = [SystemMessage(content=system_prompt), HumanMessage(content = question)]
    
    try:
        response = client.invoke(messages)
        return {"answer": response.content}
    except Exception as e:
        print(f"Cerebras API Error: {e}")
        return {"answer": "The AI service is currently experiencing high traffic (Queue Exceeded). Please wait a few moments and try your question again!"}