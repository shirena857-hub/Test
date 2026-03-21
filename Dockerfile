# Use official Python image with slim base
FROM python:3.11-slim

# Install Node.js (required for npm)
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot code
COPY . .

# Expose port for Flask keep-alive
EXPOSE 8080

# Command to run the bot
CMD ["python", "app.py"]
