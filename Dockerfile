FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --upgrade yt-dlp   # সর্বশেষ ভার্সন নিশ্চিত করে
COPY . .
CMD ["python", "app.py"]
