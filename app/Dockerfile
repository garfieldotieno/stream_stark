FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    build-essential \
    cron \
    util-linux \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements first (for caching)
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy the rest of your code
COPY . /app

RUN mkdir -p /repo_media


# Copy crontab and give permissions
COPY crontab.txt /etc/cron.d/sync-cron
RUN chmod 0644 /etc/cron.d/sync-cron
RUN crontab /etc/cron.d/sync-cron

# Add entrypoint to start cron + app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose app port
EXPOSE 5000

# Run entrypoint (starts cron + forwards logs + runs server.py)
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "server.py"]
