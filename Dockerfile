# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install curl and other system dependencies for CSV processing
RUN apt-get update && apt-get install -y curl jq && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code into the container at /app
COPY . .

# Create necessary directories
RUN mkdir -p uploads logs exports temp_uploads

# Make sure upload directories have proper permissions
RUN chmod 755 uploads logs exports temp_uploads

# Expose the port the app runs on (Railway will use the PORT env var)
EXPOSE $PORT

# Define environment variables
ENV FLASK_APP=simple_app.py
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Command to run the application
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --worker-class sync --max-requests 1000 --max-requests-jitter 100 simple_app:app 