"""CLI 챗 인터페이스"""
import logging

from src.agent.graph import agent_graph
from src.config import settings


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    print("=" * 60)
    print("  Finance RAG Agent — CLI")
    print("  종료하려면 'exit' 또는 'quit' 입력")
    print("=" * 60)

    while True:
        try:
            q = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", "q"}:
            break

        result = agent_graph.invoke({"question": q, "rewrite_count": 0})

        print(f"\n답변> {result.get('answer', '')}")
        print(
            f"     [type={result.get('query_type')} "
            f"grounded={result.get('grounded')} "
            f"sources={len(result.get('retrieved_docs', []))} "
            f"rewrite={result.get('rewrite_count', 0)}]"
        )
        for i, d in enumerate(result.get("retrieved_docs", []), 1):
            src = d.metadata.get("source", "unknown")
            section = d.metadata.get("section_path", "")
            label = f"{src} — {section}" if section else src
            print(f"     [{i}] {label}")


if __name__ == "__main__":
    main()
