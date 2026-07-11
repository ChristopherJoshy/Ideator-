# Ideator 💡

An intelligent idea partner for founders, builders, and students to discover promising project directions and refine them into ready-to-build concepts with collision detection.

---

## 🛠️ Stack

- **Frontend**: React 19 + Vite + Vanilla CSS (Mantine + Tabler Icons)
- **Backend**: FastAPI + Uvicorn + Python 3.12
- **Databases**: MongoDB Atlas (Primary) + Redis Cloud (Cache) + Qdrant Cloud (Vector search)
- **LLM Integrations**: Groq (primary routing/generation) + OpenAI / Mistral / Cerebras fallbacks
- **Embeddings**: Sentence-Transformers (`all-MiniLM-L6-v2`)

---

## 📁 Structure

```text
├── backend/          # FastAPI server, models, routing pipelines, db services
├── frontend/         # React SPA (Vite + Mantine UI + custom styling)
├── .gitignore        # Hand-crafted exclusion rules for the project stack
└── README.md         # This documentation
```

---

## 🚀 Quick Start

### 1. Environment Configuration
Clone the `.env.example` file into `.env` at the root and fill in the required credentials and API keys:
```bash
cp .env.example .env
```

### 2. Run the Backend
Ensure you have a Python environment ready (e.g., virtual env under `.venv`):
```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Start the development server
python -m uvicorn backend.main:app --port 8000 --reload
```

### 3. Run the Frontend
```bash
cd frontend

# Install packages
npm install

# Start Vite development server
npm run dev
```

The frontend will run at `http://localhost:5173` and communicate with the backend API at `http://localhost:8000`.

---

## 🔒 License
Proprietary / Developer Personal Project