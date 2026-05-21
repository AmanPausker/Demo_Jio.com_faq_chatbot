# Jio FAQ Chatbot

An intelligent, context-aware FAQ Chatbot built for Jio.com's support queries. It utilizes a **Graph Database (Neo4j)** for structuring data and a robust **Hybrid Search (Vector + Enhanced BM25)** pipeline powered by **LangGraph** and **Llama 3.1 8B**.

## 🚀 Features & Architecture

### 1. Data Pipeline
- **Extraction**: Scraped API links of each main topic and sub-topic from the official Jio.com FAQ section.
- **Processing**: Extracted Q&A data from each link and compiled everything into a structured `jio_faq_data.json` file.

### 2. Graph Database (Neo4j)
- Hosted locally using a Neo4j Docker container.
- Structured with entities: `Topic`, `Subtopic`, `Question`, `Answer`.
- Pre-defined relationships map the data logically: `(Topic)-[:HAS_SUBTOPIC]->(Subtopic)-[:CONTAINS_FAQ]->(FAQ)`

### 3. Embeddings (Local)
- Explored Gemini embeddings and HuggingFace API, but settled on a fully local approach to bypass rate limits and network issues.
- Used `sentence_transformers` (`all-MiniLM-L6-v2`, ~90MB) locally to generate high-quality vector embeddings.
- Embeddings are written directly back into the Neo4j nodes.

### 4. Chatbot Engine (LangGraph & Cerebras)
- Powered by **LangGraph** to manage conversational state and logic.
- Uses **Cerebras (Llama 3.1 8B)** to generate accurate, polite, and contextual answers based solely on the retrieved FAQ data.

### 5. Intelligent Hybrid Search 
To solve the issue of the LLM missing context for highly niche topics, we implemented a sophisticated Hybrid Search:
- **Vector Search**: Catches semantic similarities and generalized intent.
- **Enhanced BM-25 Full-Text Search**: Acts as a precise sniper for exact niche keywords.
  - **LLM Keyword Extraction**: The user's raw query is first passed to an LLM which extracts the 2-4 most critical keywords.
  - **Lucene `AND` Logic**: These keywords are dynamically joined with `AND` operators. In Apache Lucene, `OR` gives broader results (higher recall), but `AND` enforces strict, precise results (mapping internally to `MUST` clauses). This forces the database to return only the most highly relevant documents for niche queries.
- **Reranking**: The candidates from both searches are scored using a Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) to surface the absolute best context for generation.

---

## 🛠️ How to Run Locally

### Prerequisites
- [Docker](https://www.docker.com/) installed and running.
- Python 3.10+
- An API Key for Cerebras (for Llama 3.1 8B).

### 1. Clone & Setup
```bash
git clone https://github.com/AmanPausker/Demo_Jio.com_faq_chatbot.git
cd Demo_Jio.com_faq_chatbot

# Create a virtual environment and activate it
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install neo4j sentence-transformers langchain-cerebras langchain-core python-dotenv gradio
```

### 2. Setup Neo4j (Docker)
Run the following command to start a local Neo4j instance:
```bash
docker run -d --name neo4j -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_apoc_export_file_enabled=true \
  -e NEO4J_apoc_import_file_enabled=true \
  -e NEO4J_apoc_import_file_use__neo4j__config=true \
  neo4j:latest
```

### 3. Environment Variables
Create a `.env` file in the root directory and add your Cerebras API key:
```env
CEREBRAS_API_KEY="your_cerebras_api_key_here"
```

### 4. Build the Database
Run the following scripts in order to populate your Neo4j database:

1. **Scrape Data** (Optional if `jio_faq_data.json` is already present):
   ```bash
   python collection_data.py
   ```
2. **Load into Graph**:
   ```bash
   python load_to_graph.py
   ```
3. **Generate & Store Embeddings**:
   ```bash
   python embed_faqs.py
   ```
4. **Create Full-Text Index**:
   ```bash
   python create_index.py
   ```

### 5. Run the Chatbot
Finally, start the Gradio app:
```bash
python app.py
```
Open the provided local URL in your browser to start chatting with the Jio FAQ assistant!
