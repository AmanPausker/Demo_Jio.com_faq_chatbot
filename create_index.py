from neo4j import GraphDatabase

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"
driver = GraphDatabase.driver(URL, auth = (USERNAME, PASSWORD))
def create_fulltext_index():
    cypher_query="""CREATE FULLTEXT INDEX faq_text_index IF NOT EXISTS FOR (n:FAQ) ON EACH [n.question, n.answer]"""
    with driver.session() as session:
        print("Creating full-text index in neo4j")
        session.run(cypher_query)
    print("Index created successfully")
    driver.close()
if __name__ == '__main__':
    create_fulltext_index()