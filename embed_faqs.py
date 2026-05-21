import os
import time
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# Load the model directly to your Mac (it will download it once and save it locally)
print("Loading local embedding model (this takes a few seconds)...")
model = SentenceTransformer('all-MiniLM-L6-v2')

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"

def generate_and_save_embeddings():
    driver = GraphDatabase.driver(URL, auth=(USERNAME, PASSWORD))

    with driver.session() as session:
        print("Fetching all FAQ's from Neo4j...") 
        fetch_query = """MATCH (f:FAQ) RETURN id(f) AS node_id, f.question AS question, f.answer AS answer"""
        result = session.run(fetch_query)
        
        records = list(result)
        print(f"Found {len(records)} FAQs to embed.")
        
        for idx, record in enumerate(records):
            node_id = record['node_id']
            question = record['question']
            answer = record['answer']

            text_to_embed = f"Question: {question}\nAnswer: {answer}"
            
            # Print every 100th node to avoid spamming the console
            if idx % 100 == 0:
                print(f"[{idx+1}/{len(records)}] Embedding Node {node_id}...")

            # Use the local model to generate the embedding!
            # model.encode returns a numpy array, so we convert it to a python list
            embedding_vector = model.encode(text_to_embed).tolist()

            update_query = """
            MATCH (f:FAQ) 
            WHERE id(f) = $node_id 
            SET f.embedding = $embedding
            """
            session.run(update_query, node_id=node_id, embedding=embedding_vector)
            
        print("All Embeddings generated and saved successfully!")
        
    driver.close()

if __name__ == '__main__':
    generate_and_save_embeddings()
