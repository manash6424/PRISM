# AI Desktop Copilot

A full-stack AI-powered platform to query, monitor, and automate databases using **natural language**.

---

## Features

- Connects to **PostgreSQL** and **MySQL** databases
- Converts **Natural Language → SQL**
- Executes queries and returns results with explanations
- Supports export of query results to **CSV, Excel, PDF, and JSON**
- Tracks query history
- FastAPI backend with **CORS support**
- Async execution for high performance

---

## Tech Stack

- **Python 3.13**
- **FastAPI** – backend framework
- **Uvicorn** – ASGI server
- **Pydantic** – data validation
- **PostgreSQL / MySQL** – database support
- **WeasyPrint** – PDF export
- **openpyxl** – Excel export

---

## Installation

1. Clone the repository and set up the environment:

```bash
git clone https://github.com/yourusername/ai-desktop-copilot.git
cd ai-desktop-copilot

# Windows
python -m venv venv
venv\Scripts\activate

# Linux/macOS
# python -m venv venv
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt