# RepoMatrix.ai - Deployment Guide

## Overview

RepoMatrix.ai explains WHY code was written in any GitHub or GitLab commit.

## Features

- **Commit Analyzer**: Paste any commit URL and get AI-powered explanations
- **Git Guide**: Learn git concepts through real repository examples
- **Issue Finder**: Discover good first issues to contribute to

## Local Development

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### Frontend

Open `frontend/index.html` directly in browser, or use a local server:

```bash
cd frontend
python -m http.server 8080
# Then open http://localhost:8080
```

## Deployment

### Backend - Render

1. Create a new Web Service on [Render](https://render.com)
2. Connect your GitHub repository
3. Set:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Add environment variables:
   - `GITHUB_TOKEN`
   - `GITLAB_TOKEN`
   - `GROQ_API_KEY`
   - `TAVILY_API_KEY`
   - `E2B_API_KEY` (optional, for code execution)

### Frontend - Vercel

1. Create a new project on [Vercel](https://vercel.com)
2. Import your repository
3. Set:
   - **Framework Preset**: `Other`
   - **Root Directory**: `frontend`
   - **Build Command**: (leave empty)
   - **Output Directory**: (leave empty)
4. Add rewrite for API:
   ```json
   {
     "rewrites": [
       {
         "source": "/api/(.*)",
         "destination": "https://your-render-url.onrender.com/api/$1"
       }
     ]
   }
   ```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/commit` | POST | Analyze a commit URL |
| `/api/execute` | POST | Execute code from a commit |
| `/api/git-guide` | POST | Get git concept explanations |
| `/api/issues` | GET | Find good first issues |
| `/api/health` | GET | Server health check |

## Environment Variables

Create a `.env` file in the backend directory:

```env
GITHUB_TOKEN=your_github_token
GITLAB_TOKEN=your_gitlab_token
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
E2B_API_KEY=your_e2b_key
```

## Tech Stack

- **Frontend**: HTML, CSS, Vanilla JS
- **Backend**: Python, Flask
- **AI**: Groq (Llama 3.3)
- **Search**: Tavily API
- **Code Execution**: E2B Sandbox
