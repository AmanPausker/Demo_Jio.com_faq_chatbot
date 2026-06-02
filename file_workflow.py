
from docling.document_converter import DocumentConverter
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models
qdrant_client = QdrantClient(path = "./qdrant_db")
COLLECTION_NAME="jio_documents"

#Converting to Markdown instead of txt because markdown preserves the structure of the document.
#Which makes it easier for the LLM to understand the context
def converter_pdf(pdf_path:str)-> str:
    """Convert a PDF file to Markdown using docling.
    Returns:
        Markdown content as a string
    """
    converter = DocumentConverter()
    result = converter.convert(pdf_path)

    markdown_content = result.document.export_to_markdown()
    return markdown_content
from typing import TypedDict, List, Optional

class Chunk(TypedDict):
    chunk_id: str
    document_id: str
    text: str
    page_number: Optional[int]
    section: Optional[str]

# pyrefly: ignore [missing-import]
from langchain_text_splitters import RecursiveCharacterTextSplitter

   
def create_chunking(markdown :str, document_id:str)->List[Chunk]:
    splitter = RecursiveCharacterTextSplitter(chunk_size = 1000, chunk_overlap=200)
    chunks = splitter.split_text(markdown)
    chunk_list:List[Chunk] = []

    for chunk in chunks:
        chunk_data = {
            "chunk_id":str(uuid.uuid4()),
            "document_id":document_id,
            "text":chunk,
            "page_number":None,
            "section":None
        }
        chunk_list.append(chunk_data)
    return chunk_list 

from sentence_transformers import SentenceTransformer

    
def create_embeddings(chunks: list[Chunk]) -> list[list[float]]:
    model = SentenceTransformer('all-MiniLM-L6-v2')
    chunk_texts = [chunk["text"] for chunk in chunks]
    embeddings = model.encode(
        chunk_texts,
        convert_to_numpy=True
    )
    return embeddings.tolist()

def init_qdrant():
    """Create collection if it doesnt exist."""
    try:
        qdrant_client.get_collection(COLLECTION_NAME)
    except Exception:
        qdrant_client.create_collection(collection_name = COLLECTION_NAME, vectors_config = models.VectorParams(size=384, distance = models.Distance.COSINE), )
init_qdrant()

def store_in_qdrant(chunks:list[Chunk], embeddings:list[list[float]]):
    """Store chunks and their embeddings into Qdrant"""
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        point=models.PointStruct(id = chunk["chunk_id"],
        vector = embedding, payload = {
                "document_id": chunk["document_id"],
                "text": chunk["text"],
                "page_number": chunk.get("page_number"),
                "section": chunk.get("section")
            }
        )
        points.append(point)
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points = points)


def search_qdrant(query_vector:list[float], limit:int =5) -> list[str]:
    """Search Qdrant using a pre-computed vector and return text chunks."""

    try:
        search_response = qdrant_client.query_points(collection_name = COLLECTION_NAME, query = query_vector, limit= limit)
        return [hit.payload["text"] for hit in search_response.points]
    except Exception as e:
        print(f"Qdrant search skipped: {e}")
        return []
