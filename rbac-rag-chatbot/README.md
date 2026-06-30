to run backend:
# 1. Navigate to your project directory (if you aren't already there)
cd /Users/mac/Desktop/100daysofAI/rbac-rag-chatbot

# 2. Activate the virtual environment
source venv/bin/activate

# 3. Start the FastAPI backend server using Uvicorn
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

to run frontend:

streamlit run streamlit_app.py    