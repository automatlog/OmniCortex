# OmniCortex System Context: Rich Media Responses

**Objective:** Enable the AI Agent within OmniCortex (FastAPI Backend + Next.js Admin Frontend) to generate and handle rich media responses (Images, Videos, Documents, Locations, Buttons) consistently across both Web Chat and WhatsApp interfaces.

## 1. Architectural Overview

### A. The Core Concept: "Unified Tagging"
Instead of returning JSON or complex objects directly from the LLM, we instruct the LLM (via System Prompt) to output specific **Tags** within its text response. These tags are then parsed by the backend and handled differently depending on the client (Web vs WhatsApp).

**Tag Syntax:**
*   `[image][filename.ext]` -> Sends an image.
*   `[video][filename.mp4]` -> Sends a video.
*   `[document][filename.pdf]` -> Sends a document.
*   `[location][lat,long][name][address]` -> Sends a location pin.
*   `[buttons][Title][Option1|Option2]` -> Sends interactive buttons.
*   `[link][url][text]` -> Standard hyperlink.

### B. Backend Implementation (`api.py` & `core/`)

**1. `core/response_parser.py`**
*   **Role:** The central parsing engine.
*   **Key Function:** `parse_response(text)` -> Returns a structured list of dictionaries (`type`, `content`, `url`, etc.).
*   **Key Function:** `process_rich_response_for_frontend(text)` -> Converts tags into Markdown formats (e.g., `![alt](url)`, `[Video: name](url)`) for the Web Frontend.
*   **Logic:** Uses regex to identify tags and resolves filenames (e.g., `pizza.png`) to full URLs using the `Agent` database record (`image_urls`, `video_urls`).

**2. `core/whatsapp.py` (WhatsApp Integration)**
*   **Role:** Handles native WhatsApp API calls.
*   **Key Methods:** `send_image`, `send_video`, `send_document`, `send_location`, `send_interactive_buttons`.
*   **Flow:**
    1.  `api.py` receives a user message (`whatsapp_webhook`).
    2.  LLM generates a response with tags.
    3.  `api.py` calls `parse_response()`.
    4.  It iterates through the parsed parts.
    5.  It calls the corresponding `whatsapp.send_...` method for each part.

**3. `core/llm.py` & `core/chat_service.py` (LLM Context)**
*   **Role:** Guiding the AI.
*   **Prompt Engineering:** The System Prompt explicitly defines the tag formats and rules.
*   **Context Injection:** `chat_service.py` fetches the agent's available media (images/videos/docs) from the database and appends them to the prompt (e.g., "Available Images: ..."), ensuring the LLM only references files that actually exist.

### C. Frontend Implementation (`admin/src/components/MessageContent.tsx`)

**1. Role:** Rendering the chat interface in the Admin Dashboard.
**2. Logic:**
    *   Receives the Markdown-formatted response from `api.py` (via `/query`).
    *   Uses a custom tokenizer/parser (regex) to identify:
        *   Standard Markdown Images `![alt](url)` -> Renders `<img />`
        *   Custom Video Links `[Video: name](url)` -> Renders `<video controls />`
        *   Custom Doc Links `[Download name](url)` -> Renders a Document Card.
        *   Location Strings `📍 Location: ...` -> Renders an embedded Google Map.
        *   Button Groups `**Title**\nOptions: ...` -> Renders visual buttons.

## 2. Key Files for Context

*   **Backend:**
    *   `api.py`: Main entry point, webhook handler.
    *   `core/response_parser.py`: Regex logic.
    *   `core/whatsapp.py`: WhatsApp API client.
    *   `core/llm.py`: Prompt definitions.
*   **Frontend:**
    *   `admin/src/components/MessageContent.tsx`: Chat bubble rendering component.
*   **Database:**
    *   `core/database.py`: `Agent` model schema (includes `image_urls`, `video_urls`).

## 3. Current Status
*   **Implemented:** Full support for Image, Video, Doc, Location, Button tags.
*   **Verified:** Validated via `test_media_parser.py` and manual checks.
