import requests
import os
import json

BASE_URL = "http://127.0.0.1:8000"

def test_upload_flow():
    print("🚀 Starting Upload Flow verification...")
    
    # 1. Health Check
    try:
        resp = requests.get(f"{BASE_URL}/")
        if resp.status_code != 200:
            print(f"❌ API not healthy: {resp.status_code}")
            return
        print("✅ API is online")
    except Exception as e:
        print(f"❌ API connection failed: {e}")
        print("💡 Hint: Run './deploy.sh' or 'python scripts/service_manager.py monitor' first.")
        return

    # 2. Create Test Agent
    agent_data = {
        "name": "Upload_Test_Agent",
        "description": "Agent for verifying file uploads"
    }
    resp = requests.post(f"{BASE_URL}/agents", json=agent_data)
    if resp.status_code not in [200, 201]:
        print(f"❌ Failed to create agent: {resp.text}")
        return
    
    agent = resp.json()
    agent_id = agent["id"]
    print(f"✅ Created Agent: {agent['name']} ({agent_id})")

    # 3. Create Dummy File
    filename = "test_upload_doc.txt"
    content = "This is a test document uploaded via the verification script.\nIt verifies the Next.js -> API -> Postgres flow."
    with open(filename, "w") as f:
        f.write(content)
        
    # 4. Upload File
    print(f"📤 Uploading {filename}...")
    with open(filename, "rb") as f:
        files = {"files": (filename, f, "text/plain")}
        resp = requests.post(f"{BASE_URL}/agents/{agent_id}/documents", files=files)
        
    if resp.status_code != 200:
        print(f"❌ Upload failed: {resp.text}")
    else:
        print(f"✅ Upload success: {resp.json()}")

    # 5. Verify Document Listing
    resp = requests.get(f"{BASE_URL}/agents/{agent_id}/documents")
    docs = resp.json()
    found = False
    for d in docs:
        if d["filename"] == filename:
            found = True
            print(f"✅ Verified document in DB: {d['filename']} (Size: {d['file_size']} bytes)")
            
    if not found:
        print("❌ Document not found in list after upload!")

    # 6. Cleanup
    # Clean up file
    os.remove(filename)
    
    # Clean up agent (optional, maybe keep it for user to see?)
    # requests.delete(f"{BASE_URL}/agents/{agent_id}")
    # print("🧹 Cleanup complete")
    print(f"\n🎉 Verification Complete! You can view this agent at: http://localhost:3000/agents/{agent_id}/documents")

if __name__ == "__main__":
    test_upload_flow()
