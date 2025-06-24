FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# expose the port your websocket server listens on
EXPOSE 8765
CMD ["python","server.py"]