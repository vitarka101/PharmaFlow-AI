FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY app.py .
COPY scripts/ scripts/
COPY src/ src/
COPY frontend/ frontend/
COPY Orange_book_data_files/ Orange_book_data_files/
COPY NADAC.csv .

# Create data directories (warehouse will be built at startup)
RUN mkdir -p data/raw/orange_book data/processed data/synthetic data/warehouse

# Expose port (Cloud Run uses PORT env var)
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
