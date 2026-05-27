from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer, CrossEncoder
import re

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"
driver = GraphDatabase.driver(URL, auth=(USERNAME, PASSWORD))

model = SentenceTransformer('all-MiniLM-L6-v2')
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

question = "Tell me about Jio Plus"
jio_compounds = re.findall(r'(?i)\bjio\s+\w+\b', question)
glued_compounds = [comp.replace(" ", "") for comp in jio_compounds]

keyword_question = question
for compound, glued in zip(jio_compounds, glued_compounds):
    keyword_question = re.sub(re.escape(compound), glued, keyword_question, flags=re.IGNORECASE)

words = re.findall(r'\b\w+\b', keyword_question)
stopwords = {"is", "what", "how", "the", "a", "an", "for", "to", "in", "on", "of", "and", "or", "tell", "me", "about", "are", "do", "does", "i", "can", "something", "some"}
keywords = [w for w in words if w.lower() not in stopwords]
keyword_query = " OR ".join(keywords) if keywords else question

print(f"Executing keyword query: {keyword_query}")

cypher_query = """
CALL () {
    CALL db.index.vector.queryNodes('faq_embeddings', 10, $question_embedding) YIELD node AS vector_node
    RETURN collect(vector_node) AS vector_nodes
}
CALL () {
    CALL db.index.fulltext.queryNodes('faq_text_index', $keyword_query, {limit: 10}) YIELD node AS text_node
    RETURN collect(text_node) AS text_nodes
}
UNWIND (vector_nodes + text_nodes) AS f
WITH DISTINCT f
MATCH (t:Topic)-[:HAS_SUBTOPIC]->(s:Subtopic)-[:CONTAINS_FAQ]->(f)
RETURN "Topic: " + t.name + " | Subtopic: " + s.name + " | Question: " + f.question + " | Answer: " + f.answer AS context_string, f.question as q
"""

candidates = []
with driver.session() as session:
    result = session.run(cypher_query, question_embedding=model.encode(keyword_question).tolist(), keyword_query=keyword_query)
    for record in result:
        candidates.append(record['context_string'])

# Using keyword_question instead of expanded_question
cross_inp = [[keyword_question, context] for context in candidates]
scores = reranker.predict(cross_inp)
scored_candidates = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

print("\n--- Cross Encoder Scores ---")
for doc, score in scored_candidates:
    print(f"Score {score:.4f} | {doc[:80]}...")
print("----------------------------\n")
