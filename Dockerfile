FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY rag_app ./rag_app
COPY data/synthetic ./data/synthetic
COPY data/questions.json ./data/questions.json
COPY init_demo.py run_server.py sync_pg.py ./
RUN useradd --create-home rag && mkdir /app/runtime && chown -R rag:rag /app
USER rag
ENV RAG_AUTH_FILE=/app/runtime/demo_auth.json
EXPOSE 8003
CMD ["python","run_server.py","--host","0.0.0.0","--port","8003"]
