"""
Stress test utility for OmniCortex.

Default mode (recommended):
  3-step batch flow
  1) Create all agents from docs
  2) Test all questions on all agents
  3) Delete all agents

Optional mode:
  Continuous query stress mode (old behavior) using --continuous
"""
import argparse
import asyncio
import glob
import logging
import os
import random
import re
import signal
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx


LOG_DIR = Path("storage/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("stress_test_heavy")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    LOG_DIR / "stress_test_heavy.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(handler)

DEFAULT_QUERIES = [
    "What is this agent for?",
    "Summarize the latest uploaded document.",
    "Give me 3 action items from the context.",
    "Answer in short bullets.",
    "What data sources are currently available?",
]


def _preview(text: str, max_len: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def load_questions_from_file(path: str) -> List[str]:
    """
    Load questions from a text/markdown file.
    Supports:
      1. Hello, who is this?
      2. I need help...
    Also accepts plain lines ending with '?'.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")

    content = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    questions: List[str] = []
    seen = set()

    for line in content:
        raw = line.strip()
        if not raw:
            continue

        match = re.match(r"^\d+\.\s*(.+)$", raw)
        candidate = match.group(1).strip() if match else raw
        if not candidate.endswith("?"):
            continue

        if candidate not in seen:
            seen.add(candidate)
            questions.append(candidate)

    return questions


def build_headers(api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


async def list_agents(client: httpx.AsyncClient, api_base: str) -> List[Dict]:
    resp = await client.get(f"{api_base}/agents")
    if resp.status_code != 200:
        logger.error("Failed to list agents: %s %s", resp.status_code, _preview(resp.text, 300))
        return []
    return resp.json()


async def delete_all_agents(client: httpx.AsyncClient, api_base: str, headers: Dict[str, str]) -> Tuple[int, int]:
    agents = await list_agents(client, api_base)
    ok = 0
    err = 0

    print(f"[DELETE] Found {len(agents)} agents")
    for agent in agents:
        agent_id = agent.get("id")
        name = agent.get("name", "unknown")
        try:
            resp = await client.delete(f"{api_base}/agents/{agent_id}", headers=headers)
            if resp.status_code == 200:
                ok += 1
                print(f"  [OK] Deleted {name} ({agent_id})")
            else:
                err += 1
                print(f"  [ERR] Delete failed {name} ({agent_id}) -> {resp.status_code}")
        except Exception as e:
            err += 1
            print(f"  [EXC] Delete failed {name} ({agent_id}) -> {e}")
        await asyncio.sleep(0.03)

    return ok, err


async def create_agents_from_docs(
    client: httpx.AsyncClient,
    api_base: str,
    headers: Dict[str, str],
    docs_dir: str,
) -> Tuple[List[Dict], int]:
    docs_path = Path(docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"Docs directory not found: {docs_dir}")

    pdf_files = sorted(glob.glob(str(docs_path / "*.pdf")))
    if not pdf_files:
        raise RuntimeError(f"No PDF files found in {docs_dir}")

    created: List[Dict] = []
    failed = 0

    print(f"[CREATE] Creating agents from {len(pdf_files)} PDFs")
    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        agent_name = filename.replace(".pdf", "").replace("_", " ").strip()
        payload = {
            "name": agent_name,
            "description": f"Agent created automatically from {filename}",
            "file_paths": [file_path],
        }
        try:
            resp = await client.post(f"{api_base}/agents", headers=headers, json=payload)
            if resp.status_code == 200:
                body = resp.json()
                created.append({"id": body["id"], "name": body["name"], "source_file": filename})
                print(f"  [OK] Created {body['name']} ({body['id']})")
            else:
                failed += 1
                print(f"  [ERR] Create failed {agent_name} -> {resp.status_code}")
        except Exception as e:
            failed += 1
            print(f"  [EXC] Create failed {agent_name} -> {e}")
        await asyncio.sleep(0.05)

    return created, failed


async def run_all_questions(
    client: httpx.AsyncClient,
    api_base: str,
    headers: Dict[str, str],
    agents: List[Dict],
    questions: List[str],
    model_selection: str,
    mock_mode: bool,
) -> Dict[str, float]:
    total = 0
    ok = 0
    err = 0
    latencies: List[float] = []

    print(f"[TEST] Running {len(questions)} questions for {len(agents)} agents")
    for idx, agent in enumerate(agents, start=1):
        agent_id = agent["id"]
        agent_name = agent["name"]
        print(f"  [AGENT {idx}/{len(agents)}] {agent_name} ({agent_id})")

        for q_idx, question in enumerate(questions, start=1):
            payload = {
                "question": question,
                "agent_id": agent_id,
                "model_selection": model_selection,
                "mock_mode": mock_mode,
            }
            t0 = time.perf_counter()
            try:
                resp = await client.post(f"{api_base}/query", headers=headers, json=payload)
                dt = time.perf_counter() - t0
                total += 1
                latencies.append(dt)
                if resp.status_code == 200:
                    ok += 1
                    print(f"    [OK] Q{q_idx}/{len(questions)} ({dt:.2f}s)")
                else:
                    err += 1
                    print(f"    [ERR] Q{q_idx}/{len(questions)} -> {resp.status_code} ({dt:.2f}s)")
            except Exception as e:
                dt = time.perf_counter() - t0
                total += 1
                err += 1
                latencies.append(dt)
                print(f"    [EXC] Q{q_idx}/{len(questions)} -> {e} ({dt:.2f}s)")

    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
    return {
        "total": total,
        "ok": ok,
        "err": err,
        "avg_latency": avg_latency,
    }


async def _resolve_agent_id(client: httpx.AsyncClient, api_base: str) -> Optional[str]:
    agents = await list_agents(client, api_base)
    if not agents:
        return None
    return agents[0].get("id")


async def text_worker(
    worker_id: int,
    client: httpx.AsyncClient,
    api_base: str,
    api_key: str,
    agent_id: str,
    model_selection: str,
    mock_mode: bool,
    question_bank: List[str],
    stop_event: asyncio.Event,
    stats: Dict,
):
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    if not question_bank:
        question_bank = DEFAULT_QUERIES

    while not stop_event.is_set():
        question = random.choice(question_bank)
        payload = {
            "question": question,
            "agent_id": agent_id,
            "model_selection": model_selection,
            "mock_mode": mock_mode,
        }
        t0 = time.perf_counter()
        try:
            resp = await client.post(f"{api_base}/query", headers=headers, json=payload)
            dt = time.perf_counter() - t0

            stats["requests"] += 1
            stats["latency"].append(dt)
            if resp.status_code == 200:
                stats["text_ok"] += 1
            else:
                stats["errors"] += 1
                logger.error(
                    "TEXT_ERR worker=%s status=%s latency=%.3fs q=%s body=%s",
                    worker_id,
                    resp.status_code,
                    dt,
                    _preview(question),
                    _preview(resp.text, 300),
                )
        except Exception as e:
            dt = time.perf_counter() - t0
            stats["requests"] += 1
            stats["errors"] += 1
            stats["latency"].append(dt)
            logger.exception("TEXT_EX worker=%s latency=%.3fs err=%s", worker_id, dt, str(e))


async def continuous_mode(args, question_bank: List[str]):
    stats = {
        "requests": 0,
        "errors": 0,
        "text_ok": 0,
        "latency": [],
        "start_time": time.time(),
    }
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=120.0)
    limits = httpx.Limits(max_connections=500, max_keepalive_connections=200)
    stop_event = asyncio.Event()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
    except RuntimeError:
        pass

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        agent_id = args.agent_id or await _resolve_agent_id(client, args.api_base)
        if not agent_id:
            raise SystemExit("No agent found for continuous mode. Use --agent-id or create one.")

        tasks = [
            asyncio.create_task(
                text_worker(
                    worker_id=i + 1,
                    client=client,
                    api_base=args.api_base,
                    api_key=args.api_key,
                    agent_id=agent_id,
                    model_selection=args.model_selection,
                    mock_mode=args.mock_mode,
                    question_bank=question_bank,
                    stop_event=stop_event,
                    stats=stats,
                )
            )
            for i in range(args.text_workers)
        ]

        try:
            while True:
                await asyncio.sleep(1)
                if stop_event.is_set():
                    break
        except KeyboardInterrupt:
            stop_event.set()

        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = max(time.time() - stats["start_time"], 0.001)
    avg = (sum(stats["latency"]) / len(stats["latency"])) if stats["latency"] else 0.0
    print("\n" + "=" * 60)
    print("CONTINUOUS MODE RESULTS")
    print("=" * 60)
    print(f"Duration:          {elapsed:.2f}s")
    print(f"Total Requests:    {stats['requests']}")
    print(f"Text Success:      {stats['text_ok']}")
    print(f"Errors:            {stats['errors']}")
    print(f"Avg Latency:       {avg:.2f}s")
    print("=" * 60)


async def batch_mode(args, question_bank: List[str]):
    """
    3-step flow:
      1) Create all agents
      2) Test all questions on all agents
      3) Delete all agents
    """
    headers = build_headers(args.api_key)
    timeout = httpx.Timeout(connect=10.0, read=180.0, write=120.0, pool=240.0)
    limits = httpx.Limits(max_connections=300, max_keepalive_connections=120)

    if "X-API-Key" not in headers:
        raise SystemExit("Missing API key. Set --api-key or STRESS_API_KEY/TEST_API_KEY.")

    started = time.time()
    created_agents: List[Dict] = []
    create_failed = 0
    test_stats = {"total": 0, "ok": 0, "err": 0, "avg_latency": 0.0}
    delete_ok = 0
    delete_err = 0

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        try:
            if args.delete_existing_first:
                print("[STEP 0] Delete existing agents")
                d_ok, d_err = await delete_all_agents(client, args.api_base, headers)
                delete_ok += d_ok
                delete_err += d_err

            print("[STEP 1] Create all agents")
            created_agents, create_failed = await create_agents_from_docs(
                client=client,
                api_base=args.api_base,
                headers=headers,
                docs_dir=args.docs_dir,
            )

            if not created_agents:
                raise RuntimeError("No agents were created. Stopping batch test.")

            print("[STEP 2] Test all questions on all agents")
            test_stats = await run_all_questions(
                client=client,
                api_base=args.api_base,
                headers=headers,
                agents=created_agents,
                questions=question_bank,
                model_selection=args.model_selection,
                mock_mode=args.mock_mode,
            )
        finally:
            print("[STEP 3] Delete all agents")
            d_ok, d_err = await delete_all_agents(client, args.api_base, headers)
            delete_ok += d_ok
            delete_err += d_err

    duration = time.time() - started
    print("\n" + "=" * 60)
    print("BATCH FLOW RESULTS")
    print("=" * 60)
    print(f"Duration:              {duration:.2f}s")
    print(f"Questions Loaded:      {len(question_bank)}")
    print(f"Agents Created:        {len(created_agents)}")
    print(f"Agent Create Failed:   {create_failed}")
    print(f"Questions Total:       {test_stats['total']}")
    print(f"Questions Success:     {test_stats['ok']}")
    print(f"Questions Errors:      {test_stats['err']}")
    print(f"Avg Query Latency:     {test_stats['avg_latency']:.2f}s")
    print(f"Delete Success:        {delete_ok}")
    print(f"Delete Failed:         {delete_err}")
    print("=" * 60)

    logger.info(
        "BATCH_FINAL duration=%.2fs questions=%s created=%s create_failed=%s "
        "q_total=%s q_ok=%s q_err=%s avg_latency=%.3fs del_ok=%s del_err=%s",
        duration,
        len(question_bank),
        len(created_agents),
        create_failed,
        test_stats["total"],
        test_stats["ok"],
        test_stats["err"],
        test_stats["avg_latency"],
        delete_ok,
        delete_err,
    )


async def main():
    parser = argparse.ArgumentParser(description="OmniCortex stress tool (batch by default).")
    parser.add_argument("--api-base", default=os.getenv("STRESS_API_BASE", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("STRESS_API_KEY", os.getenv("TEST_API_KEY", "")))
    parser.add_argument("--docs-dir", default=os.getenv("BULK_DOCS_DIR", str(Path("tests") / "test_docs")))
    parser.add_argument("--agent-id", default=os.getenv("STRESS_AGENT_ID", ""))
    parser.add_argument("--text-workers", type=int, default=int(os.getenv("STRESS_TEXT_WORKERS", "20")))
    parser.add_argument("--model-selection", default=os.getenv("STRESS_MODEL_SELECTION", "Meta Llama 3.1"))
    parser.add_argument("--questions-file", default=os.getenv("STRESS_QUESTIONS_FILE", ""))
    parser.add_argument("--mock-mode", action="store_true", default=os.getenv("STRESS_MOCK_MODE", "false").lower() == "true")
    parser.add_argument("--delete-existing-first", action="store_true", default=True)
    parser.add_argument("--continuous", action="store_true", help="Use continuous mode instead of 3-step batch flow.")
    args = parser.parse_args()

    question_bank = list(DEFAULT_QUERIES)
    questions_file = (args.questions_file or "").strip()
    if not questions_file:
        auto_file = Path("docs/stress_questions.txt")
        if auto_file.exists():
            questions_file = str(auto_file)

    if questions_file:
        loaded = load_questions_from_file(questions_file)
        if loaded:
            question_bank = loaded
            print(f"[QUESTIONS] Loaded {len(question_bank)} from {questions_file}")
        else:
            print("[QUESTIONS] Parsed 0 questions from file, using defaults")
    else:
        print(f"[QUESTIONS] Using default bank ({len(question_bank)})")

    if args.continuous:
        await continuous_mode(args, question_bank)
    else:
        await batch_mode(args, question_bank)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
