"""ChromaDB 벡터스토어 래퍼"""
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from src.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )


def get_vectorstore() -> Chroma:
    """영속화 된 ChromaDB 컬렉션을 반환한다."""
    return Chroma(
        collection_name=settings.collection_name,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )
