FROM python:3.12-slim

WORKDIR /app

RUN groupadd --system oitc && useradd --system --gid oitc --no-create-home oitc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY oitc_mcp.py .

USER oitc

EXPOSE 8000

CMD ["python3", "oitc_mcp.py"]
