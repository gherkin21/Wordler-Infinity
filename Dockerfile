# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies needed for Pillow (fonts)
# Installing fontconfig allows Pillow to find fonts better in some cases
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev zlib1g-dev libfreetype6-dev liblcms2-dev libwebp-dev libharfbuzz-dev libfribidi-dev libxcb1-dev \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the font file(s) into the container
# Create the target directory first
RUN mkdir -p /app/fonts
COPY fonts/ /app/fonts/

# Copy the rest of the application code
COPY . .

# Ensure the data directory exists (will be mounted over by volume)
RUN mkdir -p /app/data

# Specify the command to run on container start
CMD ["python", "bot.py"]