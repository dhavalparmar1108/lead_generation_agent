import streamlit as st
import requests
import json
from datetime import datetime
import sqlite3
from pathlib import Path

# Page config
st.set_page_config(
    page_title="SalesBot - Lead Capture Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Styling
st.markdown("""
<style>
    .chat-message {
        padding: 10px;
        border-radius: 8px;
        margin: 10px 0;
        display: flex;
        flex-direction: column;
    }
    .user-message {
        background-color: #e3f2fd;
        margin-left: 20px;
        border-left: 4px solid #2196F3;
    }
    .bot-message {
        background-color: #f5f5f5;
        margin-right: 20px;
        border-left: 4px solid #4CAF50;
    }
    .lead-captured {
        background-color: #1f2f45;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #4CAF50;
    }
    .lead-incomplete {
        background-color: #1f2f45;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #FF9800;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# State Management
# ─────────────────────────────────────────────────────────────────────────────

if "conversation_id" not in st.session_state:
    import uuid
    st.session_state.conversation_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "api_url" not in st.session_state:
    st.session_state.api_url = "http://localhost:8001"

if "lead_info" not in st.session_state:
    st.session_state.lead_info = {
        "name": None,
        "email": None,
        "mobile": None,
        "requirement": None,
        "captured": False
    }


# ─────────────────────────────────────────────────────────────────────────────
# API Functions
# ─────────────────────────────────────────────────────────────────────────────

def send_message(message: str) -> dict:
    """Send message to SalesBot API."""
    try:
        response = requests.post(
            f"{st.session_state.api_url}/chat",
            json={
                "message": message,
                "conversation_id": st.session_state.conversation_id
            },
            timeout=240
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {
            "error": "Cannot connect to SalesBot server. Make sure it's running on port 8001."
        }
    except Exception as e:
        return {"error": f"Error: {str(e)}"}


def get_all_leads() -> list:
    """Get all captured leads from API."""
    try:
        response = requests.get(
            f"{st.session_state.api_url}/leads",
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("leads", [])
    except Exception as e:
        st.error(f"Error fetching leads: {e}")
        return []


def get_conversation(conv_id: str) -> dict:
    """Get conversation history."""
    try:
        response = requests.get(
            f"{st.session_state.api_url}/conversations/{conv_id}",
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# UI Components
# ─────────────────────────────────────────────────────────────────────────────

def display_chat_history():
    """Display chat messages."""
    for message in st.session_state.messages:
        if message["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(message["content"])
        else:
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(message["content"])


def display_lead_status():
    """Display current lead capture status."""
    lead = st.session_state.lead_info
    
    col1, col2 = st.columns(2)
    
    with col1:
        if lead["captured"]:
            st.markdown("""
            <div class="lead-captured">
                <h4>✅ Lead Captured!</h4>
                <p><strong>Name:</strong> {}</p>
                <p><strong>Email:</strong> {}</p>
                <p><strong>Mobile:</strong> {}</p>
                <p><strong>Requirement:</strong> {}</p>
            </div>
            """.format(
                lead.get("name", ""),
                lead.get("email", ""),
                lead.get("mobile", ""),
                lead.get("requirement", "")
            ), unsafe_allow_html=True)
        else:
            missing = []
            if not lead.get("name"):
                missing.append("Name")
            if not lead.get("email"):
                missing.append("Email")
            if not lead.get("mobile"):
                missing.append("Mobile")
            if not lead.get("requirement"):
                missing.append("Requirement")
            
            if missing:
                st.markdown(f"""
                <div class="lead-incomplete">
                    <h4>⏳ Lead Info Incomplete</h4>
                    <p><strong>Captured:</strong> {4 - len(missing)}/4</p>
                    <p><strong>Missing:</strong> {', '.join(missing)}</p>
                </div>
                """, unsafe_allow_html=True)
    
    with col2:
        st.info(f"**Conversation ID:** `{st.session_state.conversation_id}`")


# ─────────────────────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.title("🤖 SalesBot - Lead Capture Assistant")
    st.markdown("AI-powered sales assistant that captures leads and answers product queries")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # API URL
        api_url = st.text_input(
            "API URL",
            value=st.session_state.api_url,
            help="SalesBot server URL"
        )
        if api_url != st.session_state.api_url:
            st.session_state.api_url = api_url
        
        # Test connection
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔗 Test Connection"):
                try:
                    response = requests.get(f"{st.session_state.api_url}/health", timeout=5)
                    if response.status_code == 200:
                        st.success("✅ Connected!")
                    else:
                        st.error("❌ Server error")
                except:
                    st.error("❌ Cannot connect")
        
        with col2:
            if st.button("🔄 New Chat"):
                import uuid
                st.session_state.conversation_id = str(uuid.uuid4())
                st.session_state.messages = []
                st.session_state.lead_info = {
                    "name": None,
                    "email": None,
                    "mobile": None,
                    "requirement": None,
                    "captured": False
                }
                st.rerun()
        
        st.divider()
        
        # View leads
        st.subheader("📊 Captured Leads")
        if st.button("📥 Refresh Leads"):
            st.session_state.leads = get_all_leads()
        
        if "leads" in st.session_state:
            if st.session_state.leads:
                st.success(f"Total leads: {len(st.session_state.leads)}")
                for i, lead in enumerate(st.session_state.leads[:5], 1):
                    with st.expander(f"{i}. {lead.get('name', 'Unknown')} - {lead.get('email', 'N/A')}"):
                        st.write(f"**Mobile:** {lead.get('mobile', 'N/A')}")
                        st.write(f"**Requirement:** {lead.get('requirement', 'N/A')}")
                        st.write(f"**Date:** {lead.get('created_at', 'N/A')}")
            else:
                st.info("No leads captured yet")
    
    # Main chat area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("💬 Chat")
        
        # Display chat history
        display_chat_history()
        
        # Chat input
        st.divider()
        user_input = st.chat_input(
            "Type your message...",
            key="chat_input"
        )
        
        if user_input:
            # Add user message to session
            st.session_state.messages.append({
                "role": "user",
                "content": user_input
            })
            
            # Send to API
            with st.spinner("🔄 Waiting for response..."):
                response = send_message(user_input)
            
            if "error" in response:
                st.error(f"Error: {response['error']}")
            else:
                # Add assistant response
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.get("reply", "")
                })
                
                # Update lead info
                lead_data = response.get("lead", {})
                if lead_data.get("captured"):
                    st.session_state.lead_info = {
                        "name": lead_data.get("data", {}).get("name"),
                        "email": lead_data.get("data", {}).get("email"),
                        "mobile": lead_data.get("data", {}).get("mobile"),
                        "requirement": lead_data.get("data", {}).get("requirement"),
                        "captured": True
                    }
                else:
                    if lead_data.get("data"):
                        st.session_state.lead_info.update(lead_data.get("data", {}))
                
                st.rerun()
    
    with col2:
        st.subheader("📋 Lead Status")
        display_lead_status()
        
        st.divider()
        
        st.subheader("ℹ️ Info")
        st.markdown("""
        **How to use:**
        
        1. Ask about products
        2. Share your information
        3. Bot captures lead details
        4. View captured leads in sidebar
        
        **Example queries:**
        - "I need a CRM"
        - "Tell me about sales tools"
        - "Thanks, sounds good!"
        - "I'm John, john@example.com"
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Advanced Features
# ─────────────────────────────────────────────────────────────────────────────

def show_database_stats():
    """Show database statistics in a separate tab."""
    try:
        conn = sqlite3.connect("salesbot.db")
        cursor = conn.cursor()
        
        # Count conversations
        cursor.execute("SELECT COUNT(*) FROM conversations")
        conv_count = cursor.fetchone()[0]
        
        # Count leads
        cursor.execute("SELECT COUNT(*) FROM leads")
        lead_count = cursor.fetchone()[0]
        
        conn.close()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Conversations", conv_count)
        with col2:
            st.metric("Total Leads", lead_count)
    except Exception as e:
        st.error(f"Database error: {e}")


if __name__ == "__main__":
    main()
