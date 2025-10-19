# Use Python 3.10 slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy only B-Client application code
COPY . .

# Create instance directory for SQLite database
RUN mkdir -p instance

# Set environment variables
ENV B_CLIENT_ENVIRONMENT=production
ENV HOST=0.0.0.0
ENV PORT=3000
ENV DEBUG=false
ENV NSN_PRODUCTION_URL=https://comp693nsnproject.pythonanywhere.com
ENV NSN_PRODUCTION_HOST=comp693nsnproject.pythonanywhere.com
ENV NSN_PRODUCTION_PORT=443

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:3000/api/health')" || exit 1

# Start the application
CMD ["python", "run.py"]
