"""
PersonaPlex (Moshi) Integration Guide for OmniCortex

WHAT IS PERSONAPLEX?
====================
PersonaPlex is NVIDIA's full-duplex speech-to-speech AI model that:
- Listens and speaks simultaneously (like real conversations)
- Supports persona control via text prompts
- Supports voice control via audio embeddings
- Handles interruptions, backchanneling ("uh-huh"), natural pauses
- 7B parameter model based on Moshi architecture
- Real-time, low-latency conversations

KEY FEATURES:
- Full-duplex: Can interrupt and be interrupted naturally
- Persona control: Define role/personality via text
- Voice control: 16 pre-packaged voices (8 natural, 8 varied)
- Real conversations: Trained on synthetic + real conversations
- Open source: MIT license for code, NVIDIA license for weights

HOW WE USE IT IN OMNICORTEX:
=============================

1. CURRENT SETUP (Basic):
   - PersonaPlex runs as separate server on port 8998
   - Web UI accessible at http://localhost:8998
   - Users interact via browser-based interface
   - No direct API integration (WebSocket only)

2. ARCHITECTURE:
   
   User Browser
        │
        ▼
   PersonaPlex Web UI (port 8998)
        │ WebSocket
        ▼
   PersonaPlex Server (.moshi-venv)
        │
        ▼
   GPU (Real-time inference)

3. DEPLOYMENT FLOW:
   
   Step 1: Setup Moshi Environment
   --------------------------------
   ./setup_environments.sh
   # Creates .moshi-venv with PyTorch nightly
   
   Step 2: Start PersonaPlex Server
   ---------------------------------
   source .moshi-venv/bin/activate
   python -m moshi.server --port 8998
   
   # Or use service manager:
   python scripts/service_manager.py monitor
   
   Step 3: Access Web UI
   ----------------------
   Open browser: http://localhost:8998
   
   Step 4: Configure Persona & Voice
   ----------------------------------
   In Web UI:
   - Select voice (NATF0-3, NATM0-3, VARF0-4, VARM0-4)
   - Enter text prompt for persona
   - Start conversation

4. INTEGRATION OPTIONS:

   OPTION A: Web UI Only (Current - Simplest)
   -------------------------------------------
   Pros:
   - No code changes needed
   - Full-duplex works perfectly
   - All features available
   - Easy to use
   
   Cons:
   - Separate interface from main app
   - No integration with agent system
   
   Usage:
   1. Start PersonaPlex: python -m moshi.server --port 8998
   2. Direct users to: http://localhost:8998
   3. Users interact directly with PersonaPlex
   
   OPTION B: Offline Processing (Batch)
   -------------------------------------
   Pros:
   - Can process audio files
   - Integrate with agent system
   - Control persona programmatically
   
   Cons:
   - Not real-time
   - No full-duplex
   - Loses natural conversation flow
   
   Usage:
   python -m moshi.offline \
     --voice-prompt "NATF2.pt" \
     --text-prompt "You are a helpful assistant" \
     --input-wav "input.wav" \
     --output-wav "output.wav"
   
   OPTION C: WebSocket Integration (Advanced)
   -------------------------------------------
   Pros:
   - Real-time in your app
   - Full-duplex support
   - Integrated with agent system
   
   Cons:
   - Complex implementation
   - Requires WebSocket handling
   - Frontend changes needed
   
   Implementation:
   1. PersonaPlex server exposes WebSocket
   2. Frontend connects via WebSocket
   3. Stream audio bidirectionally
   4. Handle interruptions, backchanneling

5. RECOMMENDED APPROACH FOR OMNICORTEX:

   PHASE 1: Web UI (Current - Keep as is)
   ---------------------------------------
   - PersonaPlex runs on port 8998
   - Users access via separate tab/window
   - No code changes needed
   - Full features available
   
   PHASE 2: Embed Web UI (Simple)
   -------------------------------
   - Add iframe in Next.js frontend
   - Embed PersonaPlex Web UI
   - Single interface for users
   
   Code:
   // admin/src/app/voice/page.tsx
   export default function VoicePage() {
     return (
       <iframe 
         src="http://localhost:8998" 
         width="100%" 
         height="800px"
         style={{border: 'none'}}
       />
     );
   }
   
   PHASE 3: WebSocket Integration (Advanced)
   ------------------------------------------
   - Implement WebSocket client in frontend
   - Stream audio to/from PersonaPlex
   - Integrate with agent system
   - Add persona selection UI

6. PERSONA EXAMPLES:

   Assistant (QA):
   ---------------
   "You are a wise and friendly teacher. Answer questions or 
   provide advice in a clear and engaging way."
   
   Customer Service:
   -----------------
   "You work for TechSupport Inc and your name is Sarah. 
   Information: Company hours 9 AM - 6 PM. Support ticket 
   system available. Premium support costs $50/month."
   
   Casual Conversation:
   --------------------
   "You enjoy having a good conversation. Have a casual 
   discussion about technology and AI."
   
   Custom Agent:
   -------------
   "You are {agent.name}. {agent.description}. 
   Answer questions based on your knowledge base."

7. VOICE OPTIONS:

   Natural Female: NATF0, NATF1, NATF2, NATF3
   Natural Male:   NATM0, NATM1, NATM2, NATM3
   Variety Female: VARF0, VARF1, VARF2, VARF3, VARF4
   Variety Male:   VARM0, VARM1, VARM2, VARM3, VARM4

8. CURRENT CODE STATUS:

   ✅ Environment setup: .moshi-venv created
   ✅ Service manager: Starts/stops PersonaPlex
   ✅ Basic integration: core/voice/moshi_engine.py
   ⚠️  Limited functionality: Only server check
   ❌ No WebSocket client
   ❌ No frontend integration
   ❌ No persona management

9. QUICK START:

   # Start PersonaPlex server
   source .moshi-venv/bin/activate
   python -m moshi.server --port 8998
   
   # Or use service manager
   source .venv/bin/activate
   python scripts/service_manager.py monitor
   
   # Access Web UI
   Open browser: http://localhost:8998
   
   # Select voice and persona, start talking!

10. PRODUCTION DEPLOYMENT:

    # Systemd service (already configured)
    sudo systemctl start omnicortex  # Starts PersonaPlex
    
    # Nginx reverse proxy (optional)
    location /voice/ {
        proxy_pass http://localhost:8998/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Access via domain
    https://yourdomain.com/voice/

11. FUTURE ENHANCEMENTS:

    - [ ] Embed Web UI in Next.js frontend
    - [ ] WebSocket client implementation
    - [ ] Persona management UI
    - [ ] Voice selection UI
    - [ ] Integration with agent system
    - [ ] Custom voice training
    - [ ] Multi-language support

12. RESOURCES:

    GitHub: https://github.com/NVIDIA/personaplex
    HuggingFace: https://huggingface.co/nvidia/personaplex-7b-v1
    Research: https://research.nvidia.com/labs/adlr/personaplex/
    
    Model License: NVIDIA Open Model License
    Code License: MIT

SUMMARY:
========
PersonaPlex is already integrated and working in OmniCortex!
- Server runs on port 8998
- Managed by service_manager.py
- Access via Web UI
- Full-duplex conversations
- Persona and voice control

For most use cases, the Web UI is sufficient and provides
the best experience. Advanced integration (WebSocket) is
possible but not necessary for basic usage.
"""

# Example: Start PersonaPlex programmatically
def start_personaplex():
    """Start PersonaPlex server"""
    import subprocess
    import os
    
    # Activate moshi environment
    moshi_venv = os.path.join(os.getcwd(), ".moshi-venv", "bin", "activate")
    
    # Start server
    cmd = [
        "bash", "-c",
        f"source {moshi_venv} && python -m moshi.server --port 8998"
    ]
    
    process = subprocess.Popen(cmd)
    print(f"✅ PersonaPlex started (PID: {process.pid})")
    print(f"🌐 Access Web UI: http://localhost:8998")
    
    return process


# Example: Offline processing
def process_audio_with_personaplex(
    input_wav: str,
    output_wav: str,
    voice: str = "NATF2",
    persona: str = "You are a helpful assistant"
):
    """Process audio file with PersonaPlex"""
    import subprocess
    import os
    
    # Activate moshi environment
    moshi_venv = os.path.join(os.getcwd(), ".moshi-venv", "bin", "python")
    
    cmd = [
        moshi_venv, "-m", "moshi.offline",
        "--voice-prompt", f"{voice}.pt",
        "--text-prompt", persona,
        "--input-wav", input_wav,
        "--output-wav", output_wav,
        "--seed", "42424242"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✅ Audio processed: {output_wav}")
        return output_wav
    else:
        print(f"❌ Error: {result.stderr}")
        return None


if __name__ == "__main__":
    print(__doc__)
