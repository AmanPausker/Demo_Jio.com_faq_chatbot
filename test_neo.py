from neo4j import GraphDatabase

URL = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD  = "password123"

driver = GraphDatabase.driver(URL, auth=(USERNAME, PASSWORD))

query1 = """
CALL db.index.fulltext.queryNodes('faq_text_index', "JioPlus") YIELD node
RETURN count(node) as c
"""

query2 = """
CALL db.index.fulltext.queryNodes('faq_text_index', "Jio Plus") YIELD node
RETURN count(node) as c
"""

with driver.session() as session:
    res1 = session.run(query1).single()['c']
    res2 = session.run(query2).single()['c']
    print(f"JioPlus count: {res1}")
    print(f"Jio Plus count: {res2}")
