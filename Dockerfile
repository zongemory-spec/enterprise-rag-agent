FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY rag_app ./rag_app
COPY data/synthetic ./data/synthetic
COPY data/questions.json ./data/questions.json
COPY init_demo.py ./
RUN useradd --create-home rag && chown -R rag:rag /app
USER rag
ENV RAG_DB=/app/runtime/rag.sqlite3
ENV RAG_AUTH_FILE=/app/runtime/demo_auth.json
EXPOSE 8001
CMD ["sh","-c","python init_demo.py && uvicorn rag_app.api:create_app --factory --host 0.0.0.0 --port 8001 --no-access-log"]

