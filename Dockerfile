FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Schema is applied at container start (data lives on a volume) — see deploy/docker-compose.yml
CMD ["python", "-m", "surfaces.bot.telegram"]
