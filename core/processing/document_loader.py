"""
Document Loader - Process PDF, TXT, CSV, DOCX files
"""
from typing import List, Tuple
from pypdf import PdfReader


def extract_text_from_files(files) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Extract text from uploaded files
    
    Args:
        files: List of file objects
    
    Returns:
        Tuple of (list of (filename, text), list of (filename, error) for skipped files)
    """
    extracted_files = []
    skipped = []
    
    for file in files:
        try:
            filename = file.name
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            
            if ext == 'pdf':
                text = extract_pdf(file)
            elif ext == 'txt':
                text = file.read().decode('utf-8', errors='ignore')
            elif ext == 'csv':
                text = file.read().decode('utf-8', errors='ignore')
            elif ext == 'docx':
                text = extract_docx(file)
            else:
                skipped.append((filename, f"Unsupported format: {ext}"))
                continue
            
            if text.strip():
                extracted_files.append((filename, text))
            else:
                skipped.append((filename, "No text content"))
                
        except Exception as e:
            skipped.append((file.name, str(e)))
    
    return extracted_files, skipped


def extract_pdf(file) -> str:
    """Extract text from PDF"""
    reader = PdfReader(file)
    text_parts = []
    
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    
    return "\n".join(text_parts)


def extract_docx(file) -> str:
    """Extract text from DOCX"""
    try:
        from docx import Document
        doc = Document(file)
        return "\n".join([para.text for para in doc.paragraphs])
    except ImportError:
        raise ImportError("python-docx required for DOCX files")


def validate_extraction(text: str, skipped: List[Tuple]) -> dict:
    """Validate extracted text"""
    result = {"warning": None, "error": None}
    
    if skipped:
        names = [s[0] for s in skipped]
        result["warning"] = f"Skipped: {', '.join(names)}"
    
    if not text.strip():
        result["error"] = "No text could be extracted"
    
    return result


def get_file_info(file) -> dict:
    """Get file metadata"""
    filename = file.name
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'unknown'
    size = file.size if hasattr(file, 'size') else 0
    
    return {
        "filename": filename,
        "type": ext,
        "size": size
    }
