import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import os
import tempfile
import uuid
import time
from urllib.parse import urlparse
from ..chat_service import process_documents
from ..agent_manager import get_agent

SUPPORTED_FILE_EXTENSIONS = {"pdf", "txt", "csv", "docx"}


def _normalize_file_download_url(url: str) -> str:
    """
    Convert common web file links to directly downloadable URLs.
    Currently handles GitHub blob URLs.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host == "github.com" and "/blob/" in parsed.path:
        return f"https://raw.githubusercontent.com{parsed.path.replace('/blob/', '/', 1)}"
    return raw


def _infer_file_extension(url: str, content_type: str = "") -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower().lstrip(".")
    if ext in SUPPORTED_FILE_EXTENSIONS:
        return ext

    ctype = (content_type or "").lower()
    if "application/pdf" in ctype:
        return "pdf"
    if "text/plain" in ctype:
        return "txt"
    if "text/csv" in ctype or "application/csv" in ctype:
        return "csv"
    if "wordprocessingml.document" in ctype:
        return "docx"
    return ""


def _is_file_download_url(url: str) -> bool:
    resolved = _normalize_file_download_url(url)
    ext = _infer_file_extension(resolved)
    return bool(ext)


def _safe_filename_from_url(url: str, ext: str) -> str:
    name = os.path.basename(urlparse(url).path.rstrip("/")) or f"source.{ext}"
    if "." not in name:
        name = f"{name}.{ext}"
    safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in name)
    if len(safe) > 120:
        stem, suffix = os.path.splitext(safe)
        safe = f"{stem[:100]}{suffix or f'.{ext}'}"
    return safe


def _download_file_to_temp(url: str) -> tuple:
    """
    Download supported file URL to temp storage.
    Returns (temp_path, source_filename, error_message_or_None).
    """
    resolved_url = _normalize_file_download_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    last_error = None
    response = None

    for attempt in range(3):
        try:
            response = requests.get(resolved_url, headers=headers, timeout=20, allow_redirects=True)
            response.raise_for_status()
            break
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 + attempt)

    if response is None:
        return None, None, str(last_error or "download failed")

    ext = _infer_file_extension(resolved_url, response.headers.get("Content-Type", ""))
    if not ext:
        return None, None, "unsupported remote file type"

    filename = _safe_filename_from_url(resolved_url, ext)
    temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex[:8]}_{filename}")

    try:
        with open(temp_path, "wb") as handle:
            handle.write(response.content)
        return temp_path, filename, None
    except Exception as e:
        return None, None, str(e)


def _delete_local_extracted_archive(agent_id: str, source_filename: str) -> None:
    """
    Remove local extracted archive created by process_documents/save_text_to_file.
    Keeps vectors/DB records, removes disk text copy to save space.
    """
    try:
        agent = get_agent(agent_id)
        if not agent:
            return

        agent_name = agent["name"].strip().replace(" ", "_").lower()
        storage_dir = os.path.join("storage", "agents", agent_name)
        safe_filename = "".join(
            [c for c in source_filename if c.isalpha() or c.isdigit() or c in (" ", ".", "_")]
        ).rstrip()
        if not safe_filename:
            return

        archive_path = os.path.join(storage_dir, f"{safe_filename}.txt")
        if os.path.exists(archive_path):
            os.remove(archive_path)
            print(f"  - Removed local extracted archive: {archive_path}")
    except Exception as e:
        print(f"[WARN] Failed to remove local extracted archive for {source_filename}: {e}")


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
    downloaded_filenames = []
    
    try:
        for url in urls:
            if _is_file_download_url(url):
                print(f"  - Downloading file {url}...")
                temp_path, source_filename, err = _download_file_to_temp(url)
                if err or not temp_path:
                    print(f"Warning: failed to download file URL {url}: {err}")
                    continue
                f = open(temp_path, "rb")
                file_objs.append(f)
                temp_files.append(temp_path)
                if source_filename:
                    downloaded_filenames.append(source_filename)
                continue

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
             return {"success": False, "error": "No content scraped/downloaded from URLs"}
             
        # Call process_documents
        print(f"  - Ingesting {len(file_objs)} scraped pages...")
        result = process_documents(files=file_objs, agent_id=agent_id)

        # Remove local extracted copies for downloaded files to save disk space.
        for source_filename in downloaded_filenames:
            _delete_local_extracted_archive(agent_id, source_filename)
        
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
