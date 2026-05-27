from agent_state import GraphState
from nodes import driver

def test_query():
    with driver.session() as session:
        # Test 1: exact match
        print("Exact search 'jio':")
        res = session.run("CALL db.index.fulltext.queryNodes('faq_text_index', 'jio') YIELD node RETURN count(node) AS c")
        print(res.single()['c'])
        
        # Test 2: fuzzy search 'geo~'
        print("Fuzzy search 'geo~':")
        res = session.run("CALL db.index.fulltext.queryNodes('faq_text_index', 'geo~') YIELD node RETURN node.question AS q LIMIT 3")
        for r in res: print(r['q'])

        # Test 3: fuzzy search 'fibre~'
        print("Fuzzy search 'fibre~':")
        res = session.run("CALL db.index.fulltext.queryNodes('faq_text_index', 'fibre~') YIELD node RETURN node.question AS q LIMIT 3")
        for r in res: print(r['q'])

test_query()
