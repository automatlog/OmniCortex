import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import os
import tempfile
import uuid
from urllib.parse import urlparse
from ..chat_service import process_documents
from ..agent_manager import get_agent

def scrape_url(url: str) -> str:
    """
    Scrape text content from a URL using BeautifulSoup.
    Returns the cleaned text.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
            
        # Get text
        text = soup.get_text()
        
        # Break into lines and remove leading and trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text
    except Exception as e:
        print(f"⚠️ Failed to scrape {url}: {e}")
        return ""

def process_urls(urls: List[str], agent_id: str) -> Dict:
    """
    Scrape URLs and process them as documents for the agent.
    """
    if not urls or not agent_id:
        return {"success": False, "error": "Missing URLs or Agent ID"}
        
    print(f"🌐 Processing {len(urls)} URLs for Agent {agent_id}...")
    
    agent = get_agent(agent_id)
    if not agent:
        return {"success": False, "error": "Agent not found"}
        
    temp_files = []
    file_objs = []
    
    try:
        for url in urls:
            print(f"  - Scraping {url}...")
            text = scrape_url(url)
            if not text:
                continue
                
            # Create a filename from URL
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            path = parsed.path.replace("/", "_")
            if not path or path == "_":
                path = "home"
            filename = f"url_{domain}_{path}.txt"
            # Ensure filename is not too long
            if len(filename) > 100:
                filename = filename[:100] + ".txt"
            
            # Create temp file
            # process_documents expects file objects. We'll create named temp files.
            # We use delete=False so we can close them and reopen if needed, or just pass the open file.
            # However, NamedTemporaryFile on Windows cannot be opened twice. 
            # Best to keep it open and pass it.
            
            # Actually, standard open() files are safer if we manage cleanup.
            # Let's create files in a temp dir.
            
            temp_dir = tempfile.gettempdir()
            unique_id = uuid.uuid4().hex[:8]
            temp_path = os.path.join(temp_dir, f"{unique_id}_{filename}")
            
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(f"Source URL: {url}\n\n")
                f.write(text)
            
            # Open in read mode (binary) for process_documents which expects 'read()' to return bytes usually or string depending on implementation.
            # extract_text_from_files usually handles bytes for PDF/etc and string for TXT.
            # Let's check extract_text_from_files in document_loader. But assuming 'rb' is safe.
            f = open(temp_path, "rb")
            # We must attach .name attribute for the loader to detect extension
            # File objects from open() have .name.
            
            file_objs.append(f)
            temp_files.append(temp_path)
            
        if not file_objs:
             return {"success": False, "error": "No content scraped from URLs"}
             
        # Call process_documents
        print(f"  - Ingesting {len(file_objs)} scraped pages...")
        result = process_documents(files=file_objs, agent_id=agent_id)
        
        return result
        
    except Exception as e:
        print(f"❌ Error processing URLs: {e}")
        return {"success": False, "error": str(e)}
        
    finally:
        # Close handles
        for f in file_objs:
            try:
                f.close()
            except:
                pass
        
        # Cleanup temp files
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
