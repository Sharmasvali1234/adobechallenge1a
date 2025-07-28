# Specifying AMD64 platform explicitly
FROM --platform=linux/amd64 python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the Python script
COPY pdf_parser.py .

# Install Python dependencies with pinned versions
RUN pip install --no-cache-dir \
    PyMuPDF==1.23.6 \
    pytesseract==0.3.10 \
    pandas==2.0.3 \
    numpy==1.23.5 \
    Pillow==10.0.0

# Ensure input and output directories exist
RUN mkdir -p /app/input /app/output

# Set default command to run the script
CMD ["python", "pdf_parser.py"]