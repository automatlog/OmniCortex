"""
🤖 Bulk Create 42 Agents for Stress Testing
Usage: uv run python scripts/create_42_agents.py

Description:
    scans 'tests/test_docs' for PDFs and 'storage/agents' for summary.txt.
    Randomly assigns a persona to each of the 42 agents.
    Uses the API to create them.
"""
import os
import random
import httpx
import time
import glob

# CONFIG
API_URL = "http://localhost:8000"
NUM_AGENTS = 42
DOCS_DIR = os.path.abspath("tests/test_docs")
SUMMARY_FILE = os.path.abspath("storage/agents/summary.txt")

def main():
    print(f"🚀 Starting Bulk Agent Creation ({NUM_AGENTS} Agents)...")
    
    # 1. Gather Files
    pdf_files = glob.glob(os.path.join(DOCS_DIR, "*.pdf"))
    if not pdf_files:
        print(f"❌ No PDFs found in {DOCS_DIR}")
        return

    summary_exists = os.path.exists(SUMMARY_FILE)
    if not summary_exists:
        print(f"⚠️ Warning: Summary file not found at {SUMMARY_FILE}")
        
    print(f"✅ Found {len(pdf_files)} Persona PDFs.")
    
    # 2. Creation Loop
    created_count = 0
    
    with httpx.Client(timeout=30.0) as client:
        # Check API
        try:
            client.get(API_URL)
        except:
            print(f"❌ API is down at {API_URL}. Start it first!")
            return

        for i in range(1, NUM_AGENTS + 1):
            # Pick a persona
            pdf_path = random.choice(pdf_files)
            persona_name = os.path.basename(pdf_path).replace("_Full_Profile.pdf", "").replace("_", " ")
            
            agent_name = f"Agent_{i:02d}_{persona_name.replace(' ', '')}"
            description = f"Stress Test Agent {i}. Role: {persona_name}"
            
            # Prepare file paths
            files_to_send = [pdf_path]
            if summary_exists:
                files_to_send.append(SUMMARY_FILE)
            
            payload = {
                "name": agent_name,
                "description": description,
                "file_paths": files_to_send
            }
            
            try:
                print(f"Creating {agent_name}...", end=" ")
                resp = client.post(f"{API_URL}/agents", json=payload)
                
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"✅ OK (ID: {data['id'][:8]} Docs: {data['document_count']})")
                    created_count += 1
                else:
                    print(f"❌ FAIL ({resp.status_code}: {resp.text})")
            except Exception as e:
                print(f"❌ ERROR: {e}")
                
            # Slight delay to be nice
            if i % 10 == 0:
                time.sleep(1)

    print("\n" + "="*50)
    print(f"🎉 API Creation Complete. {created_count}/{NUM_AGENTS} Agents Created.")
    print("="*50)

if __name__ == "__main__":
    main()
