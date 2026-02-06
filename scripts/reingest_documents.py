"""
🔄 Re-ingest Documents with Fixed Pipeline
This script re-ingests all agent documents using the agent-safe ingestion method
"""
import os
from pathlib import Path
from core.database import init_db
from core.agent_manager import get_all_agents
from core.ingestion_fixed import ingest_agent_document
from core.document_loader import extract_text_from_files


def find_agent_documents(agent_name: str) -> list:
    """Find document files for an agent in storage folder"""
    storage_path = Path("storage")
    
    # Convert agent name to folder name (e.g., "Pizza Store" -> "Pizza_Store")
    folder_name = agent_name.replace(" ", "_")
    agent_folder = storage_path / folder_name
    
    if not agent_folder.exists():
        return []
    
    # Find all PDF, TXT, DOCX files
    documents = []
    for ext in ['*.pdf', '*.txt', '*.docx', '*.csv']:
        documents.extend(agent_folder.glob(ext))
    
    return documents


def reingest_agent(agent_id: str, agent_name: str) -> dict:
    """Re-ingest documents for a single agent"""
    result = {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": "UNKNOWN",
        "files_found": 0,
        "chunks_created": 0,
        "errors": []
    }
    
    try:
        # Find documents
        doc_files = find_agent_documents(agent_name)
        result["files_found"] = len(doc_files)
        
        if not doc_files:
            result["status"] = "NO_FILES"
            result["errors"].append(f"No documents found in storage/{agent_name.replace(' ', '_')}")
            return result
        
        # Process each document
        total_chunks = 0
        for doc_path in doc_files:
            try:
                print(f"   Processing: {doc_path.name}...", end=" ")
                
                # Read file
                with open(doc_path, 'rb') as f:
                    # Extract text
                    extracted, skipped = extract_text_from_files([f])
                    
                    if not extracted:
                        print("❌ No text extracted")
                        result["errors"].append(f"{doc_path.name}: No text extracted")
                        continue
                    
                    # Get text
                    _, text = extracted[0]
                    
                    if not text.strip():
                        print("❌ Empty text")
                        result["errors"].append(f"{doc_path.name}: Empty text")
                        continue
                    
                    # Ingest with fixed pipeline
                    chunk_count = ingest_agent_document(
                        agent_id=agent_id,
                        agent_name=agent_name,
                        raw_text=text,
                        source=doc_path.suffix[1:]  # Remove the dot
                    )
                    
                    total_chunks += chunk_count
                    print(f"✅ {chunk_count} chunks")
                    
            except Exception as e:
                print(f"❌ Error: {e}")
                result["errors"].append(f"{doc_path.name}: {str(e)}")
        
        result["chunks_created"] = total_chunks
        result["status"] = "SUCCESS" if total_chunks > 0 else "FAILED"
        
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(str(e))
    
    return result


def main():
    print("\n" + "="*60)
    print("RE-INGESTING DOCUMENTS WITH FIXED PIPELINE")
    print("="*60 + "\n")
    
    # Initialize database
    init_db()
    
    # Get all agents
    agents = get_all_agents()
    print(f"Found {len(agents)} agents\n")
    
    if not agents:
        print("❌ No agents found")
        return
    
    # Re-ingest each agent
    results = []
    for i, agent in enumerate(agents, 1):
        print(f"[{i}/{len(agents)}] {agent['name']}")
        result = reingest_agent(agent['id'], agent['name'])
        results.append(result)
        
        if result['status'] == 'SUCCESS':
            print(f"   ✅ Success: {result['chunks_created']} chunks from {result['files_found']} files\n")
        elif result['status'] == 'NO_FILES':
            print(f"   ⚠️ No files found in storage folder\n")
        else:
            print(f"   ❌ Failed: {result['errors']}\n")
    
    # Summary
    print("="*60)
    print("SUMMARY")
    print("="*60)
    
    successful = [r for r in results if r['status'] == 'SUCCESS']
    no_files = [r for r in results if r['status'] == 'NO_FILES']
    failed = [r for r in results if r['status'] not in ['SUCCESS', 'NO_FILES']]
    
    print(f"Total agents: {len(results)}")
    print(f"✅ Successfully re-ingested: {len(successful)}")
    print(f"⚠️ No files found: {len(no_files)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"\nTotal chunks created: {sum(r['chunks_created'] for r in results)}")
    
    if no_files:
        print("\n⚠️ Agents with no files:")
        for r in no_files:
            print(f"   - {r['agent_name']}")
        print("\nNote: These agents need documents uploaded to their storage folders")
    
    if failed:
        print("\n❌ Failed agents:")
        for r in failed:
            print(f"   - {r['agent_name']}: {r['errors']}")
    
    print("\n" + "="*60)
    print("Next step: Run 'python test_fixes.py' to validate")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
