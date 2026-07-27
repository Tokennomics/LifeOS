FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Run as a non-root user. Nothing here needs root, and on a public box "nothing needs it"
# is the whole argument. The app directory is chowned so the mounted data volume stays
# writable for the same uid.
RUN useradd --create-home --uid 10001 lifeos \
    && mkdir -p /app/data \
    && chown -R lifeos:lifeos /app
USER lifeos

# Schema is applied at container start (data lives on a volume) — see deploy/docker-compose.yml
# (NucBox / LAN) or deploy/vps/compose.yml (public box, behind TLS).
CMD ["python", "-m", "surfaces.bot.telegram"]
