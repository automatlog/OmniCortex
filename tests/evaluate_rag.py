"""
📊 RAG Evaluation Pipeline using Ragas
Measures: Faithfulness, Answer Relevance, Context Precision, Context Recall
Usage: uv run python tests/evaluate_rag.py
"""
import os
import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevance,
    context_precision,
    context_recall,
)
from core.chat_service import process_question
from core.database import get_agent_documents
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# Configuration
EVAL_AGENT_ID = os.getenv("EVAL_AGENT_ID", "default_agent_id") # Set valid ID
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Sample Test Set (Ground Truth)
# ideally generated from docs, but strictly defined here for demo
TEST_QUESTIONS = [
    {
        "question": "What is the return policy?",
        "ground_truth": "You can return items within 30 days of purchase for a full refund."
    },
    {
        "question": "Do you offer free shipping?",
        "ground_truth": "Yes, free shipping is available on all orders over $50."
    }
]

def main():
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY required for Ragas evaluation")
        return

    print(f"🚀 Starting RAG Evaluation for Agent: {EVAL_AGENT_ID}...")
    
    results = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": []
    }
    
    # 1. Run RAG Pipeline
    for item in TEST_QUESTIONS:
        q = item["question"]
        print(f"   Asking: {q}...", end=" ")
        
        # We need to capture contexts found during retrieval
        # Current process_question doesn't return contexts, so we might need to modify it 
        # or use hybrid_search directly here to mimic it.
        from core.rag.retrieval import hybrid_search
        
        # Retrieve
        docs = hybrid_search(q, agent_id=EVAL_AGENT_ID)
        contexts = [d.page_content for d in docs]
        
        # Generate
        ans = process_question(q, agent_id=EVAL_AGENT_ID)
        
        results["question"].append(q)
        results["answer"].append(ans)
        results["contexts"].append(contexts)
        results["ground_truth"].append(item["ground_truth"])
        print("✅")

    # 2. Convert to Dataset
    ds = Dataset.from_dict(results)
    
    # 3. Evaluate using Ragas
    print("\n📊 Running Ragas Metrics...")
    metrics_result = evaluate(
        ds,
        metrics=[
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall
        ],
    )
    
    # 4. Report
    print("\n" + "="*50)
    print("EVALUATION RESULTS")
    print("="*50)
    print(metrics_result)
    
    df = metrics_result.to_pandas()
    df.to_csv("rag_evaluation_report.csv")
    print("\n✅ Saved report to rag_evaluation_report.csv")

if __name__ == "__main__":
    main()
