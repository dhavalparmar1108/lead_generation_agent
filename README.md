# 🤖 SalesBot - Lead Capture Assistant

An AI-powered sales assistant that captures leads and answers product queries using LangGraph agents, MCP servers, and Streamlit.

## 📋 Project Overview

**SalesBot** is a conversational AI system that:
- 🎯 Answers questions about a product catalog (CRM, sales tools, etc.)
- 👤 Captures lead information (name, email, mobile, requirements)
- 📊 Stores conversations and leads in SQLite database
- 🔌 Uses MCP (Model Context Protocol) for tool management
- 💻 Provides a user-friendly Streamlit web interface

---

## 🚀 Quick Start (For Complete Beginners)

### Step 1: Install Python
Make sure you have **Python 3.10 or higher** installed on your system.

```bash
python --version  # Check your Python version
```

If you don't have Python, download it from [python.org](https://www.python.org/downloads/)

### Step 2: Set Up Your Project

1. **Download/Extract the project folder**
   - You should have a folder containing:
     - `streamlit_app.py` (web interface)
     - `products.py` (product catalog)
     - `mcp_server/` (backend server)
     - `requirements.txt` (requirements)

2. **Navigate to the project folder**
   ```bash
   cd path/to/your/project
   ```

3. **Create a virtual environment** (optional but recommended)
   ```bash
   python -m venv venv
   ```
   
   Activate it:
   - **On Windows:**
     ```bash
     venv\Scripts\activate
     ```
   - **On macOS/Linux:**
     ```bash
     source venv/bin/activate
     ```

### Step 3: Install Dependencies

Run this command to install all required packages:

```bash
pip install -r requirements.txt
```

**Don't have a `requirements.txt`?** Install manually:
```bash
pip install streamlit requests starlette uvicorn aiosqlite mcp langchain langchain-anthropic faiss-cpu sentence-transformers
```

---

## 🔧 Running the Application

### Terminal 1: Start the MCP Server from the root directory

The MCP server is the backend that handles all the AI logic and database operations.

```bash
python -m mcp_server.main
```

**What to expect:**
```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     Database initialized at salesbot.db
INFO:     SalesBot server ready!
```

✅ **If you see "SalesBot server ready!", the backend is running!**

> 🔗 The server runs on `http://localhost:8001`

### Terminal 2: Start the Streamlit App

Open a **new terminal window** in the same project folder and run:

```bash
streamlit run streamlit_app.py
```

**What to expect:**
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://xxx.xxx.xxx.xxx:8501
```

✅ **A web browser should automatically open to the Streamlit interface!**

---

## 📱 Using the Application

### Step 1: Access the Web Interface
- Open your browser and go to `http://localhost:8501`
- You should see the **SalesBot - Lead Capture Assistant** interface

### Step 2: Test the Connection
1. Click **"🔗 Test Connection"** in the left sidebar
2. You should see a green **"✅ Connected!"** message
3. If you see an error, make sure Terminal 1 (MCP server) is still running

### Step 3: Start a Conversation
1. Type a message in the chat box, e.g.:
   - "I need a CRM solution"
   - "Tell me about sales tools"
   - "I'm looking for pipeline management"

2. The bot will respond with relevant product information

### Step 4: Provide Your Information
Share your details when asked:
- "My name is John Doe"
- "My email is john@example.com"
- "My phone is 9876543210"
- "I need a CRM for managing customer relationships"

### Step 5: View Captured Leads
1. Click **"📥 Refresh Leads"** in the sidebar
2. All captured lead information appears below
3. Each lead shows: Name, Email, Mobile, Requirements, and Date

---

## 📁 Project Structure

```
your-project-folder/
├── streamlit_app.py              # Web interface (frontend)
├── mcp_server/
│   ├── main.py                   # MCP server & API endpoints
│   ├── agent.py                  # LangGraph agent logic
│   ├── vector_store/
│   │   └── store.py             # Vector database for products
│   ├── dataset/
│   │   └── products.py           # Database for products
│   |── indexes/                  # FAISS & BM25 indexes
│   └── models/                  # SentenceTransformer cached
|── requirements.txt             # requirements file
|── test_concurrency.py          #test file to test concurrency
└── salesbot.db                   # SQLite database (auto-created)
```

---

## 🛠️ Troubleshooting

### Problem: "Cannot connect to SalesBot server"

**Solution:** Make sure the MCP server is running
1. Check Terminal 1 - is the server still running?
2. Restart it: `python -m mcp_server.main`
3. Verify it says "SalesBot server ready!"

### Problem: "ModuleNotFoundError: No module named 'mcp_server'"

**Solution:** Make sure you're running from the correct directory
```bash
# Run from the project root folder containing mcp_server/
pwd  # (or cd on Windows)
# Should show: /path/to/project

python -m mcp_server.main
```

### Problem: "Port 8001 already in use"

**Solution:** Either:
1. Kill the existing process on port 8001
2. Or change the port in `mcp_server/main.py` line 519: `port=8002`

### Problem: "Port 8501 already in use"

**Solution:** Streamlit will suggest an alternative port
- The output will show something like: `Local URL: http://localhost:8502`
- Just use that URL instead

### Problem: "No module named 'streamlit'"

**Solution:** Reinstall dependencies
```bash
pip install streamlit
# Or reinstall everything
pip install -r requirements.txt
```

---

## 🔐 API Endpoints (For Developers)

If you want to integrate SalesBot into another application:

### Health Check
```bash
GET http://localhost:8001/health
```

### Chat Endpoint
```bash
POST http://localhost:8001/chat
Content-Type: application/json

{
  "message": "I need a CRM",
  "conversation_id": "optional-uuid"
}
```

**Response:**
```json
{
  "reply": "Here are great CRM solutions...",
  "conversation_id": "abc123def456",
  "lead": {
    "captured": false,
    "data": null,
    "missing_fields": ["name", "email", "mobile", "requirement"]
  }
}
```

### Get All Leads
```bash
GET http://localhost:8001/leads
```

### Get Conversation History
```bash
GET http://localhost:8001/conversations/{conversation_id}
```

---

## 📊 Database

The application uses **SQLite** with two main tables:

### `conversations` table
- Stores full conversation state and history
- Includes lead information associated with each conversation

### `leads` table
- Stores only complete leads (all 4 fields: name, email, mobile, requirement)
- Denormalized for quick querying

**Access the database:**
```bash
sqlite3 salesbot.db

# View all leads
SELECT * FROM leads;

# View conversation history
SELECT id, created_at FROM conversations;
```

---

## 🎯 Example Conversation Flow

1. **User:** "I'm looking for a CRM"
   - **Bot:** "Great! I found several CRM solutions. What's your name?"

2. **User:** "I'm Alice"
   - **Bot:** "Nice to meet you, Alice! What's your email?"

3. **User:** "alice@company.com"
   - **Bot:** "Thanks! And what's your mobile number?"

4. **User:** "555-1234567"
   - **Bot:** "Perfect! Can you tell me more about your requirements?"

5. **User:** "I need something for managing customer relationships"
   - **Bot:** "✅ Lead captured! Our team will reach out soon."

---

## 🔄 Stopping the Application

### To stop the MCP Server:
- Press `Ctrl+C` in Terminal 1

### To stop the Streamlit App:
- Press `Ctrl+C` in Terminal 2
- Or close the browser tab

---

## 📚 Advanced Usage

### Change the API URL (if running on different machines)

1. In the Streamlit sidebar, find "API URL" field
2. Change from `http://localhost:8001` to your server IP
3. Example: `http://192.168.1.100:8001`

### Run on a Different Port

**MCP Server:**
Edit `mcp_server/main.py` at the bottom:
```python
uvicorn.run(
    starlette_app,
    host="0.0.0.0",
    port=8002,  # Change 8001 to 8002
    log_level="info"
)
```

**Streamlit App:**
```bash
streamlit run streamlit_app.py --server.port 8502
```

### Deploy to Production

For production deployment:
1. Use a production ASGI server (Gunicorn with Uvicorn workers)
2. Set up proper logging and monitoring
3. Use environment variables for configuration
4. Set up a reverse proxy (Nginx) for the frontend

---

## 🤝 Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Server won't start | Check Python version (3.10+), reinstall dependencies |
| Database error | Delete `salesbot.db` to reset, server will recreate it |
| Slow responses | First time loading the model is slow, subsequent requests are faster |
| Leads not saving | Make sure lead has all 4 fields (name, email, mobile, requirement) |

---

## 📞 Support

If you encounter any issues:

1. **Check the terminal output** - MCP server logs all errors
2. **Verify both services are running** - Check Terminal 1 and Terminal 2
3. **Test the connection** - Use the "Test Connection" button in Streamlit
4. **Check the database** - Look at `salesbot.db` to see if data is being saved

---

## 📝 Notes

- The application requires **internet connection** for the first model download
- Models are cached locally in `models/` folder for faster subsequent loads
- All data is stored locally in `salesbot.db` - no external API calls for data storage
- Conversations are preserved even after app restart

---

## ✨ Features

- ✅ Product catalog search with semantic matching
- ✅ Lead capture with validation
- ✅ Conversation history tracking
- ✅ Real-time lead status display
- ✅ Multi-turn dialogue support
- ✅ SQLite persistence
- ✅ MCP tool integration
- ✅ Error handling and logging

---

**Happy selling! 🚀**
