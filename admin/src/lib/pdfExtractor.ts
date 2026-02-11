// PDF Text Extraction Utility
import * as pdfjsLib from 'pdfjs-dist';

// Set worker path - use a more reliable CDN
if (typeof window !== 'undefined') {
  pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.js`;
}

export async function extractTextFromPDF(file: File): Promise<string> {
  try {
    const arrayBuffer = await file.arrayBuffer();
    const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
    const pdf = await loadingTask.promise;
    
    let fullText = '';
    
    // Extract text from each page
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const textContent = await page.getTextContent();
      const pageText = textContent.items
        .map((item: any) => {
          if ('str' in item) {
            return item.str;
          }
          return '';
        })
        .filter(text => text.trim().length > 0)
        .join(' ');
      
      if (pageText.trim()) {
        fullText += pageText + '\n\n';
      }
    }
    
    if (!fullText.trim()) {
      throw new Error('No text content found in PDF');
    }
    
    return fullText.trim();
  } catch (error: any) {
    console.error('PDF extraction error:', error);
    throw new Error(`Failed to extract text from PDF: ${error.message || error}`);
  }
}

export async function extractTextFromFile(file: File): Promise<{ filename: string; text: string }> {
  const filename = file.name;
  const ext = filename.split('.').pop()?.toLowerCase();
  
  if (ext === 'pdf') {
    const text = await extractTextFromPDF(file);
    return { filename, text };
  } else if (ext === 'txt' || ext === 'csv') {
    const text = await file.text();
    return { filename, text };
  } else {
    throw new Error(`Unsupported file type: ${ext}`);
  }
}
