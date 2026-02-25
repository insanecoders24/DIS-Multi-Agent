# Document Intelligence System (DIS) - Multi-Agent

A regulatory-grade deterministic PDF processing pipeline with live multi-agent streaming, built to ingest, structure, and query complex documents with high provenance and accuracy.

## Architecture Highlights
- **Backend:** FastAPI (Python) powering an asynchronous, multi-stage ingestion and extraction pipeline.
- **Frontend:** Next.js (React) application with seamless Server-Sent Events (SSE) providing live insight into agent reasoning and extraction processes.
- **Data Persistence:** SQLite database (`storage/dis.db`) mapping a robust Metadata-First Storage Architecture for Entities (Documents, Pages, Sections, Blocks, Tables).
- **Core Orchestrator Engine:** Employs multiple specialized sub-agents (Ingestion, Structure, Refinement, Orchestrator) using leading LLM providers (Anthropic, Gemini, OpenAI) to process PDFs.

---

## 🚀 Getting Started

To run the application locally, you will need to start both the Python backend and the Next.js frontend servers.

### 1. Backend Setup (FastAPI)

Ensure you have Python 3.10+ installed on your machine.

1. **Navigate to the backend directory:**
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On macOS/Linux
   # or `.\venv\Scripts\activate` on Windows
   ```

3. **Install the required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file inside the `backend/` directory and populate your API keys (you can leave out ones you don't use, the system auto-falls back to available keys):
   ```env
   # AI / LLM Keys
   OPENAI_API_KEY=sk-proj-your-key-here
   ANTHROPIC_API_KEY=sk-ant-your-key-here
   GEMINI_API_KEY=AIzaSy-your-key-here
   
   # Optional: Database configuration (Defaults to local SQLite)
   # DATABASE_URL=postgresql://user:pass@host:port/dbname
   ```

5. **Start the Backend Server:**
   ```bash
   uvicorn main:app --reload
   ```
   *The backend will be running on `http://localhost:8000`. On startup, it will automatically generate the `storage/` folder for your local SQLite Database and PDF/Image caches.*

### 2. Frontend Setup (Next.js)

Ensure you have Node.js (v18+) and npm installed.

1. **Navigate to the frontend directory:**
   ```bash
   cd frontend
   ```

2. **Install npm dependencies:**
   ```bash
   npm install
   ```

3. **Environment Setup:**
   Create a `.env.local` file inside the `frontend/` directory to point to your backend:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

4. **Start the Frontend Development Server:**
   ```bash
   npm run dev
   ```
   *The frontend will be accessible at `http://localhost:3000`.*

---

## 🎨 System Walkthrough

1. **Upload a Document:** Open the frontend (`http://localhost:3000`) and upload a PDF.
2. **Watch the Agents:** As the backend processes the document, Server-Sent Events (SSE) stream the real-time thoughts, actions, and validations of the multi-agent system securely into the UI's right-side panel.
3. **Explore the Extraction:** 
   - **Ingestion Agent:** Hashes the PDF and extracts raw normalized page images.
   - **Structure Agent:** Slices the PDF into contiguous Blocks, Sections, and Tables.
   - **Refiner Agent:** Cleans up tables, anchors reference links, and highlights uncertain text for human review.
4. **Chat & Query:** Use the built-in RAG Chat interface to ask questions about your uploaded documents. The application natively cites its sources by pointing back to the exact block/page it got the info from!

---

## 📂 Project Structure

```text
DIS-Multi-Agent/
├── backend/
│   ├── agents/          # Specialized AI sub-agents (Orchestrator, Structure, Refiner)
│   ├── models/          # SQLAlchemy Entity Models (Document, Block, Section, Table)
│   ├── pipeline_stages/ # Extraction stages (PyMuPDF processing)
│   ├── storage/         # Auto-generated runtime SQLite and PDF image caches
│   ├── main.py          # FastAPI application & SSE routers
│   ├── config.py        # System logic configurations
│   └── database.py      # SQLite / Postgres runtime setup
└── frontend/
    ├── app/             # Next.js Application router pages
    ├── components/      # Reusable React components (Chat, File Uploader, Activity Panel)
    └── tailwind.config.ts
```

## Supported Models & Fallback Logic
The backend natively supports fallback redundancy. The Orchestrator agent explicitly tries API calls in this sequence (configurable in `agents/gemini_client.py`):
1. **Gemini** (`gemini-2.5-flash`)
2. **Anthropic** (`claude-3-5-sonnet`)
3. **OpenAI** (`gpt-4o-mini`)

If an API hits a Rate Limit (`429`), the system seamlessly falls back to the next available enterprise provider.
