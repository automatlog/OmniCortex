"""
Quick stress runner for OmniCortex.

Flow:
1) Create one agent via POST /agents
2) Ask at least 20 questions via POST /query
3) Print latency + success summary

Auth:
- Preferred: Authorization: Bearer <token>
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
import uuid
from typing import Any, Dict, List, Tuple

import httpx


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_CONCURRENCY = 5
MIN_QUESTIONS = 20


QUESTIONS: List[str] = [
    "Hi, who are you?",
    "What can you help me with?",
    "Explain SQL basics simply.",
    "Explain Python loops with one example.",
    "Give me 3 beginner study tips.",
    "Suggest a daily learning plan.",
    "How do I improve problem solving?",
    "Share one quick revision strategy.",
    "How should I start database design?",
    "Difference between list and tuple in Python?",
    "What is normalization in DBMS?",
    "Explain primary key and foreign key.",
    "How to prepare for coding interviews?",
    "Give me one mini project idea.",
    "How to write a better prompt?",
    "Can you summarize what you know so far?",
    "What is the best order to learn SQL topics?",
    "How to avoid common beginner mistakes?",
    "Share a short motivation line for learning.",
    "What should I practice today?",
    "Send me course images",
    "Can you suggest a weekly roadmap?",
    "How to balance theory and practice?",
    "Explain joins in SQL in short.",
    "Give me one quiz question.",
]


def _build_auth_headers(token: str = "") -> Dict[str, str]:
    value = token.strip()
    if not value:
        raise SystemExit("Missing auth. Provide --token.")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {value}",
    }
    return headers


def _agent_payload(agent_id: str) -> Dict[str, Any]:
    return {
        "id": agent_id,
        "agentname": "Personal AI BOT",
        "agent_type": "personal",
        "subagent_type": "NULL",
        "role_type": "personal assistance",
        "description": "For My Assignment Helping.",
        "model_selection": "default",
        "website_data": [
            "https://www.w3schools.com/sql/",
            "https://www.w3schools.com/python/",
        ],
        "document_data": {
            "image_urls": [
                "https://i0.wp.com/learn.onemonth.com/wp-content/uploads/2019/07/image2-1.png",
                "https://kunalcybersecurity.com/wp-content/uploads/2023/08/Python-Symbol.png",
            ],
            "video_urls": [
                "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
            ],
            "documents_text": [
                {
                    "url": "https://www.lkouniv.ac.in/site/writereaddata/siteContent/202003291621085101sanjeev_rdbms_unit-I_sql_bba_ms_4_sem.pdf",
                    "type": "pdf",
                },
                {
                    "url": "https://ncert.nic.in/textbook/pdf/keip103.pdf",
                    "type": "pdf",
                },
                {
                    "url": "https://github.com/automatlog/OmniCortex/blob/main/tests/test_docs/github.txt",
                    "type": "txt",
                },
            ],
        },
        "system_prompt": "Prompts/PersonalAsistance/01-PersonalAssistant.json",
        "logic": {
            "handler": "personal-ai-bot",
            "timeout_seconds": "120",
            "max_tokens": "4096",
            "rule": "",
        },
        "instruction": "Basic to Advance",
        "conversation_starters": [{"prompt": "🤔Hola Amigo!!!"}],
        "conversation_end": [{"prompt": "Thank you for learning with Smart AI"}],
    }


async def create_agent(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    agent_id: str,
) -> Tuple[bool, str]:
    payload = _agent_payload(agent_id)
    url = f"{base_url.rstrip('/')}/agents"
    response = await client.post(url, json=payload, headers=headers)
    if response.status_code in (200, 201):
        return True, f"Created agent {agent_id}"

    # Duplicate id/name may already exist; continue to query on same id.
    if response.status_code in (400, 409):
        text = response.text.lower()
        if "already exists" in text or "already" in text:
            return True, f"Agent already exists, reusing {agent_id}"

    return False, f"Create failed [{response.status_code}] {response.text[:300]}"


async def ask_one(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    agent_id: str,
    question: str,
    idx: int,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    payload = {
        "id": agent_id,
        "channel_name": "TEXT",
        "channel_type": "MARKETING",
        "query": question,
    }
    url = f"{base_url.rstrip('/')}/query"

    async with semaphore:
        start = time.perf_counter()
        try:
            response = await client.post(url, json=payload, headers=headers)
            latency = time.perf_counter() - start
            ok = response.status_code == 200
            return {
                "index": idx,
                "question": question,
                "status": response.status_code,
                "ok": ok,
                "latency": latency,
            }
        except Exception as exc:
            latency = time.perf_counter() - start
            return {
                "index": idx,
                "question": question,
                "status": 0,
                "ok": False,
                "latency": latency,
                "error": str(exc),
            }


def _build_question_batch(count: int) -> List[str]:
    # At least 20 questions as requested.
    count = max(MIN_QUESTIONS, count)
    if count <= len(QUESTIONS):
        return QUESTIONS[:count]
    extra = [random.choice(QUESTIONS) for _ in range(count - len(QUESTIONS))]
    return QUESTIONS + extra


def _print_summary(results: List[Dict[str, Any]]) -> None:
    total = len(results)
    success = sum(1 for r in results if r["ok"])
    failed = total - success
    latencies = [r["latency"] for r in results]

    avg = statistics.mean(latencies) if latencies else 0.0
    p95 = (sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)] if latencies else 0.0)
    fastest = min(latencies) if latencies else 0.0
    slowest = max(latencies) if latencies else 0.0

    print("\n" + "=" * 60)
    print("QUICK STRESS SUMMARY")
    print("=" * 60)
    print(f"Total Questions:   {total}")
    print(f"Success:           {success}")
    print(f"Failed:            {failed}")
    print(f"Avg Latency:       {avg:.3f}s")
    print(f"P95 Latency:       {p95:.3f}s")
    print(f"Fastest:           {fastest:.3f}s")
    print(f"Slowest:           {slowest:.3f}s")
    print("=" * 60)

    if failed:
        print("\nFailed Requests:")
        for item in results:
            if not item["ok"]:
                print(f"- #{item['index']} status={item['status']} q={item['question']}")


async def run(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    headers = _build_auth_headers(token=args.token)
    agent_id = args.agent_id.strip() or str(uuid.uuid4())
    questions = _build_question_batch(args.questions)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=120.0)
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)

    print(f"Base URL:       {base_url}")
    print(f"Agent ID:       {agent_id}")
    print(f"Questions:      {len(questions)}")
    print(f"Concurrency:    {args.concurrency}")

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        ok, msg = await create_agent(client, base_url, headers, agent_id)
        print(msg)
        if not ok:
            raise SystemExit(1)

        tasks = [
            ask_one(client, base_url, headers, agent_id, q, i + 1, semaphore)
            for i, q in enumerate(questions)
        ]
        results = await asyncio.gather(*tasks)
        _print_summary(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quick stress test: create agent + >=20 queries")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--agent-id", default="a990c567-f5a4-4c2b-bbb9-536d6b77f3d3", help="Agent ID to create/use")
    parser.add_argument("--questions", type=int, default=20, help="Total questions (minimum 20)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent /query requests")
    parser.add_argument("--token", default="", help="Bearer token")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
