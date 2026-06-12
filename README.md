# Job Seeker

An intelligent, multi-agent recruitment aggregator and resume matching system designed to automate job crawling, parse job details, and rank matching positions with advanced LLM analysis.

Developed with a modern monorepo layout, Job Seeker integrates **FastAPI**, **Tauri (React + TS)**, **LangGraph**, and **ScrapegraphAI** to deliver an end-to-end job hunting and filtering experience.

---

## 🚀 Key Features

*   **Adaptive Crawler Workflow**: Uses a **LangGraph-driven multi-agent system** (Root Agent, Playwright Agent, API Agent) to dynamically inspect targets, handle Cookie prompts, bypass simple scrapers, and retrieve job links.
*   **Intelligent Job Detail Consumer**: Extracts structural job descriptions using ScrapegraphAI, implements schema normalization (resolving salary ranges and location states), and tracks page liveliness (flagging expired pages).
*   **Vector & Hybrid Resume Matching**: Processes candidate CVs (PDF, TXT, MD) using embeddings, performs fast hybrid candidate filtering (SQL metadata + vector similarity), and evaluates detailed matchups (scoring, discrepancy analysis, recommendations) using parallelized batch LLM calls.
*   **Premium Glassmorphic Desktop GUI**: A beautiful desktop dashboard powered by Tauri (Vite + React + CSS) with dark mode glassmorphism effects, reactive filters (company, location, status), and comprehensive job detail rendering.

---

## 📁 Repository Structure

```
job-seeker/
├── apps/
│   ├── crawler/      # LangGraph-based intelligent website scraper
│   ├── server/       # FastAPI backend with CV parsing & hybrid matching
│   └── gui/          # Tauri desktop client (React + TS + Vite)
├── packages/
│   └── shared/       # Common database schemas, Playwright downloader, config
├── scripts/          # Database setup and shutdown automation scripts
├── migrations/       # Alembic schema revision histories
├── tests/            # Pytest test suite (crawler, deduplicator, logic)
├── config.yaml.example # Example configuration file
├── pyproject.toml    # Python workspace definition (uv member layout)
└── docker-compose.yml # Dev environment local PostgreSQL container
```

---

## 🛠️ Prerequisites

*   **Python**: `pip` and Python `3.12+` (highly recommended to use [uv](https://github.com/astral-sh/uv) for project management).
*   **Node.js**: Node.js `18+` & `npm` (required for running the GUI).
*   **Docker**: For launching the local PostgreSQL database instance.
*   **Rust / Tauri build tools**: Optional, only required if you compile the Tauri desktop application.

---

## ⚡ Quick Start

### 1. Database Setup

Launch the local PostgreSQL container:
```bash
./scripts/start-db.sh
# Or via poe task runner:
uv run poe start-db
```

Run schema migrations to set up the database tables:
```bash
uv run poe db-upgrade
```

### 2. Configure Settings

Copy the example configuration file and fill in your API key details (Gemini or OpenAI):
```bash
cp config.yaml.example config.yaml
```
*Modify `config.yaml` to specify your preferred LLM provider, API keys, and target companies.*

### 3. Running the Crawler

Start the job listing scraper to fetch jobs from target careers websites:
```bash
uv run poe crawl
```

Start the detail consumer to parse job description structures and generate embeddings:
```bash
uv run poe consume
```

### 4. Running the Backend Server

Launch the FastAPI backend server:
```bash
uv run poe server
```
*The API server will reload on `http://127.0.0.1:8000`.*

### 5. Running the Desktop GUI

Change to the GUI directory, install NPM dependencies, and start the development Tauri app:
```bash
cd apps/gui
npm install
# Run Tauri in dev mode (requires FastAPI server running or runs in mock-fallback mode)
npm run tauri dev
```

---

## 🧪 Testing

Run the test suite using `pytest`:
```bash
uv run poe test
```

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
