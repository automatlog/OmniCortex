"""
OmniCortex - Modern RAG Chatbot
Streamlit UI with Agent Management, Document Viewer, and Chat
"""
import streamlit as st
# ... (imports)
from core import (
    get_all_agents,
    create_agent,
    get_agent,
    delete_agent,
    process_question,
    process_documents,
    get_conversation_history,
    save_message,
    get_agent_documents,
    delete_document,
    get_usage_stats,
)
# ...

def settings_page():
    st.header("⚙️ Configuration")
    st.divider()
    
    # 1. General Settings
    st.subheader("Memory & Stats")
    st.session_state.max_history = st.slider(
        "Memory length", 1, MAX_HISTORY_LIMIT, st.session_state.max_history
    )
    
    st.info(f"**Model:** {LLM_MODEL}")
    
    agents = get_cached_agents()
    c1, c2, c3 = st.columns(3)
    c1.metric("Agents", len(agents))
    c2.metric("Documents", sum(a['document_count'] for a in agents))
    c3.metric("Messages", sum(a['message_count'] for a in agents))
    
    st.divider()
    
    # 2. WhatsApp Integration
    st.subheader("WhatsApp Integration")
    st.info("Configure your Meta App Credentials here. Changes apply to the current session.")
    
    # Load from config/env initially, but allow session override
    from core.config import WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_ID
    
    if "wa_token" not in st.session_state:
        st.session_state.wa_token = WHATSAPP_ACCESS_TOKEN
    if "wa_phone_id" not in st.session_state:
        st.session_state.wa_phone_id = WHATSAPP_PHONE_ID
        
    new_token = st.text_input("Access Token", value=st.session_state.wa_token, type="password")
    new_phone_id = st.text_input("Phone Number ID", value=st.session_state.wa_phone_id)
    
    if st.button("Save WhatsApp Settings"):
        st.session_state.wa_token = new_token
        st.session_state.wa_phone_id = new_phone_id
        
        # Update Runtime Config
        import core.config
        core.config.WHATSAPP_ACCESS_TOKEN = new_token
        core.config.WHATSAPP_PHONE_ID = new_phone_id
        
        st.success("Settings updated for this session!")
        
    st.divider()
    st.markdown("### Webhook Setup")
    st.markdown(f"**Callback URL**: `{{YOUR_PUBLIC_URL}}/api/v1/whatsapp/webhook`")
    st.markdown(f"**Verify Token**: `omnicortex_token`")


# ...

def main():
    # removed validate_env call
    
    init_state()
    sidebar()
    
    views = {
        'agents': agents_page,
        'chat': chat_page,
        'conversations': conversations_page,
        'metrics': metrics_page,
        'webhooks': webhook_logs_page,
        'settings': settings_page
    }
    views.get(st.session_state.view, agents_page)()

from core.config import DEFAULT_MAX_HISTORY, MAX_HISTORY_LIMIT, LLM_MODEL, TTS_PROVIDER, MODEL_BACKENDS
from audio_recorder_streamlit import audio_recorder

# ... (existing imports/config)

def metrics_page():
    st.markdown("## 📊 Usage Metrics")
    st.caption("Token usage and cost tracking")
    st.divider()
    
    stats = get_usage_stats(limit=200)
    
    if not stats:
        st.info("No usage data available yet. Start chatting!")
        return
        
    # Calculate KPIs
    total_tokens = sum(s['total_tokens'] for s in stats)
    total_cost = sum(s['cost'] for s in stats)
    avg_tokens = total_tokens / len(stats) if stats else 0
    avg_latency = sum(s.get('latency', 0) for s in stats) / len(stats) if stats else 0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tokens", f"{total_tokens:,}")
    c2.metric("Est. Cost", f"${total_cost:.4f}")
    c3.metric("Avg Latency", f"{avg_latency:.2f}s")
    c4.metric("Avg Tokens/Req", f"{int(avg_tokens)}")
    
    st.divider()
    
    # Recent Log Table
    st.subheader("Recent Calls")
    import pandas as pd
    df = pd.DataFrame(stats)
    
    # Format timestamp
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    st.dataframe(
        df[['timestamp', 'model', 'total_tokens', 'cost', 'latency', 'agent_id']],
        use_container_width=True,
        hide_index=True
    )
    
    # Document Metrics
    st.subheader("📂 Document Embeddings")
    # We need to fetch ALL documents to show embedding stats (or add a get_recent_docs function)
    # For now, let's just grab docs for current agent if selected, else all (but main.py doesn't export get_all_docs easily)
    # Let's import get_agent_documents but iterate over all agents? Expensive.
    # Better: show embedding stats if an agent is selected, or just skip if complex.
    # User asked for embedding time.
    # I'll modify the query to show recent documents across all agents?
    # Or just show the Logic: "Embedding time is tracked per document upload."
    # Let's try to query recent documents from DB directly here? No, keep it clean.
    # I'll just explain it for now or add get_all_document_stats to database.py later if needed.
    # Actually, I can allow viewing per-agent docs.
    
    agents = get_cached_agents()
    agent_options = {a['name']: a['id'] for a in agents}
    selected_agent = st.selectbox("Select Agent for Doc Stats", list(agent_options.keys()))
    
    if selected_agent:
        aid = agent_options[selected_agent]
        docs = get_agent_documents(aid)
        if docs:
            doc_df = pd.DataFrame(docs)
            # Display document stats
            if 'embedding_time' in doc_df.columns:
                 st.dataframe(
                    doc_df[['uploaded_at', 'filename', 'file_size', 'chunk_count', 'embedding_time']],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.dataframe(
                    doc_df[['uploaded_at', 'filename', 'file_size', 'chunk_count']],
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("No documents found for this agent.")
            
    # Chart
    st.subheader("Token Usage Trend")
    if not df.empty:
        chart_data = df.set_index('timestamp')[['prompt_tokens', 'completion_tokens']]
        st.bar_chart(chart_data)




# Page config
st.set_page_config(
    page_title="OmniCortex - AI Agents",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Styling
st.markdown("""
<style>
    .main .block-container { padding-top: 1.5rem; max-width: 1200px; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
    [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] .stCaption { color: white !important; }
    [data-testid="stSidebar"] button:hover { border-color: transparent !important; color: black !important; background-color: white !important; opacity: 1 !important; transform: none !important; }
    [data-testid="stSidebar"] button[kind="primary"]:hover { background-color: #ff4b4b !important; color: white !important; }
    .agent-card { border-radius: 12px; padding: 16px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
</style>
""", unsafe_allow_html=True)


# ============== CACHING ==============
@st.cache_data(ttl=5)
def get_cached_agents():
    return get_all_agents()


def clear_cache():
    get_cached_agents.clear()


# ============== SESSION STATE ==============
def init_state():
    defaults = {
        'view': 'agents',
        'agent_id': None,
        'conversations': {},
        'max_history': DEFAULT_MAX_HISTORY
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ============== DIALOGS ==============
@st.dialog("Create Agent", width="large")
def create_agent_dialog():
    name = st.text_input("Name", placeholder="Agent name")
    desc = st.text_area("Description", placeholder="What does this agent do?", height=80)
    
    st.markdown("**📁 Files** - PDF, TXT, CSV, DOCX")
    files = st.file_uploader("Upload", accept_multiple_files=True,
                             type=['pdf', 'txt', 'csv', 'docx'], label_visibility="collapsed")
    
    if files:
        st.caption(f"📄 {len(files)} file(s) ready")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("Create", type="primary", use_container_width=True):
            if not name:
                st.error("Enter a name")
            else:
                try:
                    agent_id = create_agent(name, desc)
                    if files:
                        with st.spinner("Processing documents..."):
                            process_documents(files=files, agent_id=agent_id)
                    clear_cache()
                    st.success(f"✅ {name} created!")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


import threading
import io

def copy_file_to_memory(file):
    """Copy uploaded file to memory buffer for background processing"""
    mem_file = io.BytesIO(file.getvalue())
    mem_file.name = file.name
    mem_file.size = file.size
    return mem_file


def background_upload(files, text, agent_id):
    """Run upload in background"""
    try:
        print(f"🚀 Starting background upload for agent {agent_id}")
        process_documents(files=files, text_input=text, agent_id=agent_id)
        # We can't update UI from here, but DB will be updated
        print(f"✅ Background upload complete for agent {agent_id}")
    except Exception as e:
        print(f"⚠️ Background upload failed: {e}")


@st.dialog("Upload Documents")
def upload_dialog(agent_id: str):
    agent = get_agent(agent_id)
    if not agent:
        st.error("Agent not found")
        return
    
    st.markdown(f"**{agent['name']}** ({agent['document_count']} docs)")
    
    files = st.file_uploader("Files", accept_multiple_files=True,
                             type=['pdf', 'txt', 'csv', 'docx'], label_visibility="collapsed")
    text = st.text_area("Or paste text", height=100)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True, key="up_cancel"):
            st.rerun()
    with col2:
        if st.button("Upload", type="primary", use_container_width=True, key="up_submit"):
            if not files and not text:
                st.warning("Add files or text")
            else:
                # Prepare files for background thread
                mem_files = [copy_file_to_memory(f) for f in files] if files else None
                
                # Start background thread
                thread = threading.Thread(
                    target=background_upload,
                    args=(mem_files, text, agent_id)
                )
                thread.start()
                
                # UI Feedback
                st.toast("Started processing in background... 🚀")
                st.rerun()


@st.dialog("Agent Documents", width="large")
def view_documents_dialog(agent_id: str):
    agent = get_agent(agent_id)
    if not agent:
        st.error("Agent not found")
        return
    
    st.markdown(f"### 📚 Documents for **{agent['name']}**")
    
    docs = get_agent_documents(agent_id)
    
    if not docs:
        st.info("No documents uploaded yet.")
        if st.button("Close", use_container_width=True):
            st.rerun()
        return
    
    st.caption(f"{len(docs)} document(s)")
    st.divider()
    
    for doc in docs:
        with st.container(border=True):
            col1, col2 = st.columns([5, 1])
            with col1:
                icon = {'pdf': '📕', 'txt': '📄', 'csv': '📊', 'docx': '📘', 'text': '📝'}.get(doc['file_type'], '📄')
                st.markdown(f"{icon} **{doc['filename']}**")
                
                size_kb = (doc['file_size'] or 0) / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                date = doc['uploaded_at'][:10] if doc['uploaded_at'] else 'Unknown'
                st.caption(f"📦 {size_str} • 🧩 {doc['chunk_count']} chunks • 📅 {date}")
            
            with col2:
                if st.button("🗑️", key=f"del_doc_{doc['id']}"):
                    delete_document(doc['id'])
                    st.rerun()
            
            if doc['content_preview']:
                with st.expander("📖 Preview"):
                    st.text(doc['content_preview'][:500])
    
    st.divider()
    if st.button("Close", use_container_width=True, type="primary"):
        st.rerun()


# ============== VIEWS ==============
def sidebar():
    with st.sidebar:
        st.markdown("## 🧠 OmniCortex")
        
        # Model Selection
        if "selected_model_key" not in st.session_state:
            st.session_state.selected_model_key = list(MODEL_BACKENDS.keys())[0]
            
        st.session_state.selected_model_key = st.selectbox(
            "Select AI Model",
            options=list(MODEL_BACKENDS.keys()),
            index=0,
            key="model_selector"
        )
        st.caption(f"Using: {MODEL_BACKENDS[st.session_state.selected_model_key]['model']}")
        st.divider()
        
        nav = [("🧑‍💼 Agents", "agents"), ("💬 History", "conversations"), 
               ("📊 Metrics", "metrics"), ("📥 Webhooks", "webhooks"), ("⚙️ Settings", "settings")]
        for label, view in nav:
            if st.button(label, use_container_width=True,
                        type="primary" if st.session_state.view == view else "secondary"):
                st.session_state.view = view
                st.session_state.agent_id = None
                st.rerun()
        
        if st.session_state.view == 'chat' and st.session_state.agent_id:
            st.divider()
            agent = get_agent(st.session_state.agent_id)
            if agent:
                st.markdown(f"**{agent['name']}**")
                st.caption(f"📄 {agent['document_count']} docs")
        
        st.divider()
        with st.expander("🧪 Test STS (Voice Conversion)"):
            st.caption("ElevenLabs Speech-to-Speech")
            sts_audio = audio_recorder(text="", icon_size="lg", key="sts_recorder")
            if sts_audio:
                from core.voice import voice_conversion
                with st.spinner("Transforming voice..."):
                    try:
                        converted = voice_conversion(sts_audio)
                        if converted:
                            st.audio(converted, format="audio/mp3")
                        else:
                            st.error("Conversion failed")
                    except Exception as e:
                        st.error(f"Error: {e}")
        



def agents_page():
    col1, col2, col3 = st.columns([2, 4, 2])
    with col1:
        st.markdown("## Agents")
    with col2:
        search = st.text_input("Search", placeholder="🔍 Search...", label_visibility="collapsed")
    with col3:
        if st.button("+ Add Agent", type="primary", use_container_width=True):
            create_agent_dialog()
    
    st.divider()
    
    agents = get_cached_agents()
    if search:
        agents = [a for a in agents if search.lower() in a['name'].lower()]
    
    if not agents:
        st.info("No agents yet. Create one!")
        return
    
    cols = st.columns(3)
    for i, agent in enumerate(agents):
        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(f"**{agent['name']}**")
                desc = agent.get('description') or 'No description'
                st.caption(desc[:60] + '...' if len(desc) > 60 else desc)
                st.caption(f"📄 {agent['document_count']} docs • 💬 {agent['message_count']} msgs")
                
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    if st.button("💬", key=f"chat_{agent['id']}", help="Chat"):
                        st.session_state.agent_id = agent['id']
                        st.session_state.view = 'chat'
                        st.rerun()
                with c2:
                    if st.button("📋", key=f"docs_{agent['id']}", help="Documents"):
                        view_documents_dialog(agent['id'])
                with c3:
                    if st.button("📄", key=f"up_{agent['id']}", help="Upload"):
                        upload_dialog(agent['id'])
                with c4:
                    if st.button("🗑️", key=f"del_{agent['id']}", help="Delete"):
                        delete_agent(agent['id'])
                        clear_cache()
                        st.rerun()


def chat_page():
    agent_id = st.session_state.agent_id
    if not agent_id:
        st.session_state.view = 'agents'
        st.rerun()
        return
    
    agent = get_agent(agent_id)
    if not agent:
        st.error("Agent not found")
        return
    
    col1, col2 = st.columns([1, 8])
    with col1:
        if st.button("←"):
            st.session_state.view = 'agents'
            st.rerun()
    with col2:
        st.markdown(f"## {agent['name']}")
    
    if agent['document_count'] == 0:
        st.warning("⚠️ Upload documents first")
    
    st.divider()
    
    # Voice Config (Floating Bottom Right - Inside Input Bar)
    # Styles...
    st.markdown("""
    <style>
    /* Float the Voice Settings Popover */
    .voice-settings-container {
        position: fixed;
        bottom: 18px; 
        right: 70px;
        z-index: 99999;
    }
    .voice-settings-container button {
        background-color: transparent !important;
        border: none !important;
        color: inherit !important;
        padding: 5px !important;
    }

    /* CHAT ALIGNMENT */
    /* USER MESSAGES */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        flex-direction: row-reverse;
        background-color: rgba(74, 222, 128, 0.1); /* Subtle green tint */
        border: 1px solid #4ade80;
    }
    
    /* User Message Content */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) div[data-testid="stMarkdownContainer"] {
        text-align: right;
    }

    /* User Avatar alignment fix */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) div[data-testid="chatAvatarIcon-user"] {
        margin-right: 0px;
        margin-left: 10px;
    }

    /* AGENT MESSAGES */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        background-color: rgba(59, 130, 246, 0.1); /* Subtle blue tint */
        border: 1px solid #3b82f6; 
    }
    
    @media (max-width: 640px) {
        .voice-settings-container {
            bottom: 18px;
            right: 60px;
        }
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Initialize Voice State & Verbosity
    if "use_voice" not in st.session_state:
        st.session_state.use_voice = False
    if "voice_id" not in st.session_state:
        st.session_state.voice_id = "JBFqnCBsd6RMkjVDRZzb"
    if "verbosity" not in st.session_state:
        st.session_state.verbosity = "medium"

    # Sidebar Response Config
    with st.sidebar:
        st.markdown("### 🗣️ Response Configuration")
        mode = st.select_slider(
            "Response Length",
            options=["short", "medium", "detailed"],
            value=st.session_state.verbosity,
            format_func=lambda x: {"short": "⚡ Short (5s)", "medium": "⚖️ Balanced", "detailed": "📚 Detailed"}[x]
        )
        st.session_state.verbosity = mode
        
        # Model Selection
        st.divider()
        st.markdown("### 🤖 Model Selection")
        from core.config import MODEL_BACKENDS
        model_options = list(MODEL_BACKENDS.keys())
        if "selected_model_key" not in st.session_state:
            st.session_state.selected_model_key = model_options[0]
        
        st.session_state.selected_model_key = st.selectbox(
            "LLM Model",
            options=model_options,
            index=model_options.index(st.session_state.selected_model_key),
            format_func=lambda x: f"🦙 {x}" if "Llama" in x else f"🚀 {x}"
        )
        
        # Auto-switch to short if voice is enabled (on first toggle)
        # Note: We can logic this out better, but let's keep it manual or subtle
        if st.session_state.use_voice and st.session_state.verbosity == 'detailed':
            st.info("💡 Tip: Use 'Short' mode for best voice experience.")

    # Floating Popover Container for Voice
    use_voice = st.session_state.use_voice
    with st.container():
        st.markdown('<div class="voice-settings-container">', unsafe_allow_html=True)
        with st.popover("🎙️", use_container_width=False, help="Voice Settings"):
            st.markdown("### Voice Settings")
            st.session_state.use_voice = st.toggle("Enable Voice Mode", value=st.session_state.use_voice)
            use_voice = st.session_state.use_voice
            
            if use_voice:
                voices = {
                    "pNInz6obpgDQGcFmaJgB": "👨 Rahul (Adam - Deep Male)",
                    "21m00Tcm4TlvDq8ikWAM": "👩 Riya (Rachel - Clear Female)",
                    "TxGEqnHWrfWFTfGW9XjX": "👨 Rohan (Josh - Soft Male)",
                    "EXAVITQu4vr4xnSDxMaL": "👩 Devi (Bella - Gentle Female)",
                    "PERSONAPLEX": "🦖 Nvidia PersonaPlex (Moshi 7B)",
                }
                st.session_state.voice_id = st.selectbox(
                    "Select Persona", 
                    options=list(voices.keys()), 
                    format_func=lambda x: voices[x]
                )
        st.markdown('</div>', unsafe_allow_html=True)

    # Conversation
    if agent_id not in st.session_state.conversations:
        st.session_state.conversations[agent_id] = []
    
    conv = st.session_state.conversations[agent_id]
    
    for msg in conv:
        with st.chat_message(msg['role']):
            if use_voice and msg.get('audio'):
                st.audio(msg['audio'], format='audio/wav')
                with st.expander("📝 Transcript"):
                    st.markdown(msg['content'])
            else:
                st.markdown(msg['content'])

    # Voice input
    prompt = None
    if use_voice:
        with st.container():
            st.markdown('<div class="voice-recorder-container">', unsafe_allow_html=True)
            try:
                from audio_recorder_streamlit import audio_recorder
                audio_bytes = audio_recorder(
                    text="",
                    recording_color="#e74c3c",
                    neutral_color="#3498db",
                    icon_size="2x",
                )
                
                if audio_bytes:
                    with st.spinner("Transcribing..."):
                        try:
                            from core.voice import transcribe_audio
                            import tempfile
                            import os
                            
                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                                f.write(audio_bytes)
                                temp_path = f.name
                            
                            prompt = transcribe_audio(temp_path)
                            os.unlink(temp_path)
                            
                            if prompt:
                                st.toast(f"🗣️ You said: {prompt}")
                                
                        except ImportError:
                            st.error("Install voice: uv add audio-recorder-streamlit elevenlabs")
                        except Exception as e:
                            st.error(f"Transcription failed: {e}")
            except ImportError:
                st.info("Install voice support: uv add audio-recorder-streamlit")
                use_voice = False
            st.markdown('</div>', unsafe_allow_html=True)

    # Text input (always available)
    input_text = st.chat_input("Ask a question...")
    
    # Priority: Voice > Text
    if not prompt and input_text:
        prompt = input_text

    if prompt:
        conv.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Determine verbosity
                    current_verbosity = st.session_state.verbosity
                    
                    # Get selected model from session state (set in sidebar)
                    selected_model_key = st.session_state.get("selected_model_key", None)

                    response = process_question(
                        prompt,
                        agent_id=agent_id,
                        conversation_history=conv[-(st.session_state.max_history * 2):],
                        max_history=st.session_state.max_history,
                        verbosity=current_verbosity,
                        model_selection=selected_model_key
                    )
                    
                    # TTS if voice mode
                    audio_bytes = None
                    if use_voice:
                        try:
                            from core.voice import speak
                            voice_id = st.session_state.get('voice_id')
                            audio_bytes = speak(response, voice=voice_id)
                            
                            # Autoplay new response
                            st.audio(audio_bytes, format='audio/wav', autoplay=True)
                            with st.expander("📝 Transcript"):
                                st.markdown(response)
                        except Exception as e:
                            st.caption(f"TTS unavailable: {e}")
                            st.markdown(response)
                    else:
                        st.markdown(response)
                    
                    conv.append({"role": "assistant", "content": response, "audio": audio_bytes})
                except FileNotFoundError:
                    st.error("Upload documents first")
                except Exception as e:
                    st.error(str(e))
        
        st.session_state.conversations[agent_id] = conv


def conversations_page():
    st.markdown("## Conversation History")
    st.divider()
    
    for agent in get_cached_agents():
        if agent['message_count'] > 0:
            with st.expander(f"💬 {agent['name']} ({agent['message_count']} msgs)"):
                history = get_conversation_history(agent_id=agent['id'], limit=5)
                for item in history:
                    st.markdown(f"**{item['role']}:** {item['content'][:80]}...")
                
                if st.button("Continue", key=f"cont_{agent['id']}"):
                    st.session_state.agent_id = agent['id']
                    st.session_state.view = 'chat'
                    st.rerun()


# ============== MAIN ==============
def webhook_logs_page():
    """Webhook capture logs viewer"""
    st.header("📥 Webhook Logs")
    
    # Get base URL for webhook capture
    import socket
    hostname = socket.gethostname()
    st.info(f"**Capture URL:** `http://localhost:8000/webhooks/capture`\n\nAny requests to this URL will be captured and stored.")
    
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()
        if st.button("🗑️ Clear All", type="secondary"):
            import requests
            try:
                requests.delete("http://localhost:8000/webhooks/logs")
                st.success("Cleared!")
                st.rerun()
            except:
                st.error("Failed to clear")
    
    # Fetch logs from API
    import requests
    try:
        resp = requests.get("http://localhost:8000/webhooks/logs?limit=50")
        data = resp.json()
        total = data.get("total", 0)
        logs = data.get("logs", [])
        
        st.caption(f"Total: {total} webhooks captured")
        
        if not logs:
            st.info("No webhooks captured yet. Send requests to the capture URL above.")
        else:
            for log in logs:
                with st.expander(f"{log['method']} {log['url'][:60]}... ({log['received_at'][:19]})"):
                    st.markdown(f"**ID:** {log['id']}")
                    st.markdown(f"**Method:** `{log['method']}`")
                    st.markdown(f"**URL:** `{log['url']}`")
                    st.markdown(f"**Source IP:** `{log.get('source_ip', 'N/A')}`")
                    st.markdown(f"**Received:** {log['received_at']}")
                    
                    if log.get('query_params'):
                        st.markdown("**Query Params:**")
                        st.code(log['query_params'])
                    
                    if log.get('headers'):
                        st.markdown("**Headers:**")
                        try:
                            import json
                            st.json(json.loads(log['headers']))
                        except:
                            st.code(log['headers'])
                    
                    if log.get('body'):
                        st.markdown("**Body:**")
                        try:
                            import json
                            st.json(json.loads(log['body']))
                        except:
                            st.code(log['body'])
                            
    except Exception as e:
        st.error(f"Failed to fetch logs: {e}")
        st.info("Make sure the API is running: `uv run python api.py`")


def main():
    # Environment validation removed - handled by config.py
    init_state()
    sidebar()
    
    views = {
        'agents': agents_page,
        'chat': chat_page,
        'conversations': conversations_page,
        'metrics': metrics_page,
        'webhooks': webhook_logs_page,
        'settings': settings_page
    }
    views.get(st.session_state.view, agents_page)()


if __name__ == "__main__":
    main()
