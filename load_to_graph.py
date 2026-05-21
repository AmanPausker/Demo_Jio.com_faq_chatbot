import json
from neo4j import GraphDatabase

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"

def ingest_data():
    driver = GraphDatabase.driver(URL,auth=(USERNAME, PASSWORD))

    with open("jio_faq_data.json", "r", encoding ="utf-8") as f:
        faqs = json.load(f)

    print("loaded data")
    with driver.session() as session:
        for faq in faqs:
            cypher_query="""
            MERGE (t:Topic {name: $topic_name})
            MERGE (s:Subtopic {name: $sub_topic_name})
            MERGE (t)-[:HAS_SUBTOPIC]->(s)
            
            MERGE (f:FAQ {question: $question})
            SET f.answer = $answer
            
            MERGE (s)-[:CONTAINS_FAQ]->(f)
            """
            session.run(cypher_query, topic_name = faq['topic'], sub_topic_name = faq['sub_topic'], question = faq['question'], answer = faq['answer'])
    print("Ingestion Complete")
    driver.close()
if __name__ == '__main__':
    ingest_data()