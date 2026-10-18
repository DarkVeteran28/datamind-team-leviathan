"""Interactive command line entry point for DataMind."""
import sys
from pathlib import Path

# Keep direct `python datamind_demo.py` working from a checkout.
sys.path.insert(0, str(Path(__file__).parent / "src"))
from datamind.pipeline import ask


def main():
    print("\nDataMind | Talk to Your Data")
    print("Dataset: Snowflake TPC-H CUSTOMER")
    print("Type 'exit' to quit.\n")
    while True:
        question = input("Ask your data > ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue
        result = ask(question)
        print("\n" + result["answer"])
        if result["sql"]:
            print("\nSQL:")
            print(result["sql"])
        if result["columns"]:
            print("\nActual Snowflake results:")
            print(" | ".join(result["columns"]))
            for row in result["rows"]:
                print(" | ".join("NULL" if value is None else str(value) for value in row))
        if result["query_id"]:
            print(f"\nSnowflake query ID: {result['query_id']}")
        if result["assumptions"]:
            print(f"Model assumptions: {result['assumptions']}")
        for warning in result["warnings"]:
            print(f"Warning: {warning}")
        print()


if __name__ == "__main__":
    main()
