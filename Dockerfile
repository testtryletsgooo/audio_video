# Use a lightweight Python image
FROM python:3.9-slim

# 1. Install system-level FFmpeg
# This ensures the converter has the necessary engine to run
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 2. Set the working directory
WORKDIR /app

# 3. Copy dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of your application code
COPY . .

# 5. Create the storage folders explicitly so errors don't occur
RUN mkdir -p uploads processed

# 6. Run the application using Gunicorn
# Render expects the app to listen on port 10000 by default
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]