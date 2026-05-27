from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer, CrossEncoder
from agent_state import GraphState
import os
from langchain_cerebras import ChatCerebras
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv(override=True)
CEREBRAS_API_KEY=os.getenv("CEREBRAS_API_KEY")
client = ChatCerebras(model ="llama3.1-8b",api_key=CEREBRAS_API_KEY)


URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"
driver = GraphDatabase.driver(URL, auth=(USERNAME, PASSWORD))
print("Loading Embedding Model")
model = SentenceTransformer('all-MiniLM-L6-v2')

print("Loading Reranking Model")
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

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
    
    # 0.1 Generalized Brand Normalizer
    # Find any phrase like "Jio Plus", "Jio Fiber", "Jio Cinema"
    import re
    jio_compounds = re.findall(r'(?i)\bjio\s+\w+\b', question)
    glued_compounds = [comp.replace(" ", "") for comp in jio_compounds]
    
    # Expand the question to include BOTH spaced and unspaced versions
    expanded_question = question + " " + " ".join(glued_compounds)
    
    # 1. Vector Search uses the expanded question
    question_vector = model.encode(expanded_question).tolist()

    # 2. Extract Keywords locally
    words = re.findall(r'\b\w+\b', question)
    stopwords = {"is", "what", "how", "the", "a", "an", "for", "to", "in", "on", "of", "and", "or", "tell", "me", "about", "are", "do", "does", "i", "can", "something", "some"}
    keywords = [w for w in words if w.lower() not in stopwords]
    
    # Add our glued compounds to the keyword search as well
    keywords.extend(glued_compounds)
        
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
        return {"context": ""}

    # 4. Rerank candidates using CrossEncoder
    # Create question-candidate pairs using the expanded question
    cross_inp = [[expanded_question, context] for context in candidates]
    scores = reranker.predict(cross_inp)

    # Combine candidates with scores and sort by score descending
    scored_candidates = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    
    print("\n--- Cross Encoder Scores ---")
    for doc, score in scored_candidates:
        print(f"Score {score:.4f} | {doc[:80]}...")
    print("----------------------------\n")

    # Select the top 3 best matching candidates
    top_3_candidates = [candidate for candidate, score in scored_candidates[:3]]
    
    retrieved_context = "\n".join(top_3_candidates) + "\n"
    return {"context": retrieved_context}

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
    response = client.invoke(messages)

    return {"answer":response.content}