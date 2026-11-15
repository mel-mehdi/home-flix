# Use Python 3.13 slim image (matches local development)
FROM python:3.13-slim

# Print logs right away, also on hosts that run the image without docker-compose (Back4app)
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Expose port 5000
EXPOSE 5000

# Run the application
CMD ["python", "media_server.py"]
