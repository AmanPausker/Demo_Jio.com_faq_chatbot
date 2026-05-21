import json
import urllib.request
import urllib.parse
import re
import time

def clean_html(raw_html):
    if not raw_html:
        return ""
    # Remove html tags
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    # Decode basic HTML entities
    cleantext = cleantext.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # Remove extra whitespaces
    cleantext = ' '.join(cleantext.split())
    return cleantext

def collect_data():
    print("Loading topics.json...")
    with open('topics.json', 'r', encoding='utf-8') as f:
        topics_config = json.load(f)
    
    # Create mapping from subtopic name to list of topics
    subtopic_to_topics = {}
    for topic, subtopics in topics_config.items():
        for subtopic in subtopics:
            if subtopic not in subtopic_to_topics:
                subtopic_to_topics[subtopic] = []
            subtopic_to_topics[subtopic].append(topic)
            
    faq_results = []
    
    page = 1
    page_count = 1
    
    # Using the /jcms-api/jio-faqs endpoint to fetch all FAQs, 
    # which is much more efficient than guessing URLs for 200+ subtopics.
    print("Fetching FAQs from Jio CMS API...")
    while page <= page_count:
        url = f"https://www.jio.com/jcms-api/jio-faqs?pagination[pageSize]=100&pagination[page]={page}"
        print(f"Fetching page {page}/{page_count}...")
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                
                if page == 1:
                    page_count = data.get('meta', {}).get('pagination', {}).get('pageCount', 1)
                
                faqs = data.get('data', [])
                for faq in faqs:
                    attrs = faq.get('attributes', {})
                    question = attrs.get('title', '')
                    answer_html = attrs.get('description', '') or attrs.get('myjioDescription', '')
                    answer = clean_html(answer_html)
                    
                    cat_data = attrs.get('jioFaqsCategory', {}).get('data')
                    if cat_data:
                        cat_attrs = cat_data.get('attributes', {})
                        subtopic_name = cat_attrs.get('name', '')
                        
                        # Match with our topics.json
                        if subtopic_name in subtopic_to_topics:
                            for t in subtopic_to_topics[subtopic_name]:
                                faq_results.append({
                                    "topic": t,
                                    "sub_topic": subtopic_name,
                                    "question": question,
                                    "answer": answer
                                })
                                
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            time.sleep(2)
            continue
            
        page += 1
        
    print(f"Total FAQs collected matching topics.json: {len(faq_results)}")
    
    output_file = 'jio_faq_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(faq_results, f, indent=4, ensure_ascii=False)
        
    print(f"Data successfully saved to {output_file}")

if __name__ == '__main__':
    collect_data()
