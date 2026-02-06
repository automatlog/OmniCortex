"""
🧪 Agent Test Suite - Validates agent functionality and performance
Combines golden testing (correctness) with performance monitoring.
"""
import time
import asyncio
import threading
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import psutil

# Optional GPU monitoring
try:
    import GPUtil
    HAS_GPU = True
except ImportError:
    HAS_GPU = False


# ============== SYSTEM MONITOR ==============

class SystemMonitor:
    """Background system resource monitor"""
    
    def __init__(self):
        self.running = False
        self.stats = []
        self._thread = None
    
    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
    
    def _loop(self):
        while self.running:
            stat = {
                "cpu": psutil.cpu_percent(interval=0.1),
                "mem": psutil.virtual_memory().percent,
                "gpu": 0,
                "gpu_mem": 0
            }
            if HAS_GPU:
                try:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        stat["gpu"] = gpus[0].load * 100
                        stat["gpu_mem"] = gpus[0].memoryUtil * 100
                except:
                    pass
            self.stats.append(stat)
            time.sleep(0.5)
    
    def summary(self) -> Dict:
        if not self.stats:
            return {}
        return {
            "avg_cpu": sum(s["cpu"] for s in self.stats) / len(self.stats),
            "max_cpu": max(s["cpu"] for s in self.stats),
            "avg_gpu": sum(s["gpu"] for s in self.stats) / len(self.stats),
            "max_gpu": max(s["gpu"] for s in self.stats),
        }


# ============== GOLDEN TEST ==============

def golden_test_agent(agent_id: str, agent_name: str) -> Dict:
    """
    Validate single agent: documents exist, retrieval works, LLM responds.
    
    Returns:
        dict with status, reason, response_preview
    """
    from core import get_llm
    from core.rag.vector_store import load_vector_store
    from core.rag.ingestion_fixed import get_agent_retriever, validate_agent_documents
    from core.adaptive_llm import adaptive_llm_call
    
    result = {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": "UNKNOWN",
        "reason": None,
        "response_preview": None
    }
    
    try:
        # Step 1: Check documents exist
        validation = validate_agent_documents(agent_id, agent_name)
        if validation.get("status") != "OK":
            result["status"] = "FAIL"
            result["reason"] = "NO_DOCUMENTS"
            return result
        
        # Step 2: Test retrieval
        store = load_vector_store(agent_id)
        retriever = get_agent_retriever(store, agent_id, agent_name, k=2)
        docs = retriever.invoke("Describe your role")
        
        if not docs:
            result["status"] = "FAIL"
            result["reason"] = "RETRIEVAL_FAILED"
            return result
        
        # Step 3: Test LLM generation
        llm = get_llm()
        prompt = f"""You are {agent_name}.
Context: {docs[0].page_content[:400]}
Question: What is your primary responsibility?
Answer briefly:"""
        
        response = adaptive_llm_call(lambda: llm.invoke(prompt))
        answer = response.content if hasattr(response, "content") else str(response)
        
        result["status"] = "PASS"
        result["response_preview"] = answer[:100]
        
    except FileNotFoundError:
        result["status"] = "FAIL"
        result["reason"] = "NO_VECTOR_STORE"
    except Exception as e:
        result["status"] = "FAIL"
        result["reason"] = str(e)[:80]
    
    return result


# ============== PERFORMANCE TEST ==============

def perf_test_agent(agent: Dict) -> Dict:
    """
    Performance test: measure latency for queries.
    """
    from core import process_question
    
    agent_id = agent["id"]
    name = agent["name"]
    
    try:
        t0 = time.time()
        process_question("Hello, who are you?", agent_id=agent_id, max_history=0, verbosity="short")
        t1 = time.time()
        
        process_question("Tell me something interesting.", agent_id=agent_id, max_history=2, verbosity="short")
        t2 = time.time()
        
        return {
            "agent": name,
            "latency_hello": round(t1 - t0, 2),
            "latency_query": round(t2 - t1, 2),
            "status": "OK"
        }
    except FileNotFoundError:
        return {"agent": name, "status": "NO_DOCS"}
    except Exception as e:
        return {"agent": name, "status": f"ERROR: {str(e)[:30]}"}


# ============== MAIN TEST RUNNERS ==============

def run_golden_tests(agent_ids: List[str] = None) -> Dict:
    """
    Run golden tests on all or specified agents.
    
    Returns:
        dict with passed, failed, results
    """
    from core import get_all_agents
    
    agents = get_all_agents()
    if agent_ids:
        agents = [a for a in agents if a["id"] in agent_ids]
    
    print(f"\n{'='*50}")
    print(f"GOLDEN TEST - Testing {len(agents)} agents")
    print(f"{'='*50}\n")
    
    results = []
    for agent in agents:
        print(f"Testing: {agent['name']}...", end=" ")
        result = golden_test_agent(agent["id"], agent["name"])
        results.append(result)
        
        if result["status"] == "PASS":
            print("✅ PASS")
        else:
            print(f"❌ FAIL ({result['reason']})")
    
    passed = len([r for r in results if r["status"] == "PASS"])
    
    print(f"\n{'='*50}")
    print(f"RESULT: {passed}/{len(results)} passed")
    print(f"{'='*50}\n")
    
    return {"passed": passed, "failed": len(results) - passed, "results": results}


async def run_perf_tests(max_agents: int = 10) -> Dict:
    """
    Run concurrent performance tests.
    
    Returns:
        dict with total_time, resource_usage, results
    """
    from core import get_all_agents
    
    agents = get_all_agents()[:max_agents]
    
    print(f"\n{'='*50}")
    print(f"PERFORMANCE TEST - {len(agents)} agents")
    print(f"{'='*50}\n")
    
    monitor = SystemMonitor()
    monitor.start()
    
    t0 = time.time()
    
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [loop.run_in_executor(executor, perf_test_agent, a) for a in agents]
        results = await asyncio.gather(*futures)
    
    total_time = time.time() - t0
    monitor.stop()
    
    print(f"\nTotal Time: {total_time:.2f}s")
    print(f"\nPer-Agent Latency:")
    print(f"{'Agent':<20} | {'Hello':<8} | {'Query':<8}")
    print("-" * 40)
    for r in results:
        if r.get("status") == "OK":
            print(f"{r['agent']:<20} | {r.get('latency_hello', 0):.2f}s    | {r.get('latency_query', 0):.2f}s")
    
    return {
        "total_time": total_time,
        "resources": monitor.summary(),
        "results": results
    }


# ============== CLI ==============

if __name__ == "__main__":
    import sys
    from core.database import init_db
    
    init_db()
    
    if len(sys.argv) > 1 and sys.argv[1] == "perf":
        asyncio.run(run_perf_tests())
    else:
        run_golden_tests()
