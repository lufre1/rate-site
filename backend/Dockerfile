FROM python:3.11

WORKDIR /app

# stdout is block-buffered when it is not a tty, which it never is in a
# container -- so output could sit in an 8 KB buffer and be lost when the
# process dies. logging.StreamHandler flushes per record, but anything a library
# prints directly still needs this.
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
