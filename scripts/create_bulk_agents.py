import os
import glob
import requests
import time

# Configuration
API_URL = "http://localhost:8000"
DOCS_DIR = "/workspace/OmniCortex/tests/test_docs"

def delete_all_agents():
    """Fetches and deletes all existing agents."""
    print("🧹 Cleaning up existing agents...")
    try:
        response = requests.get(f"{API_URL}/agents")
        if response.status_code == 200:
            agents = response.json()
            print(f"found {len(agents)} agents to delete.")
            
            for agent in agents:
                agent_id = agent['id']
                print(f"   Deleting {agent['name']} ({agent_id})...", end=" ")
                del_resp = requests.delete(f"{API_URL}/agents/{agent_id}")
                if del_resp.status_code == 200:
                    print("✅")
                else:
                    print(f"❌ {del_resp.status_code}")
                time.sleep(0.1)
        else:
            print(f"❌ Failed to fetch agents: {response.text}")
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")

def create_agents_from_docs():
    """Scans DOCS_DIR and creates agents."""
    if not os.path.exists(DOCS_DIR):
        print(f"❌ Directory not found: {DOCS_DIR}")
        return

    pdf_files = glob.glob(os.path.join(DOCS_DIR, "*.pdf"))
    if not pdf_files:
        print(f"⚠️ No PDF files found in {DOCS_DIR}")
        return

    print(f"\n🚀 Starting bulk creation for {len(pdf_files)} agents...\n")
    
    success_count = 0
    fail_count = 0

    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        name = filename.replace(".pdf", "").replace("_", " ").strip()
        
        payload = {
            "name": name,
            "description": f"Agent created automatically from {filename}",
            "file_paths": [file_path]
        }
        
        print(f"Creating: {name}...", end=" ")
        try:
            response = requests.post(f"{API_URL}/agents", json=payload)
            if response.status_code == 200:
                print("✅")
                success_count += 1
            else:
                print(f"❌ {response.status_code}")
                fail_count += 1
        except Exception as e:
            print(f"❌ Error: {e}")
            fail_count += 1
            
        time.sleep(0.5)

    print(f"\n🎉 Finished! Created: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    delete_all_agents()
    create_agents_from_docs()
