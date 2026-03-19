FROM python:3.11-slim

# ffmpeg ইনস্টল
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# কাজের ডিরেক্টরি
WORKDIR /app

# requirements.txt কপি ও পাইথন প্যাকেজ ইনস্টল
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# পুরো প্রজেক্ট কপি
COPY . .

# বট চালু করার কমান্ড (ফাইলের নাম app.py)
CMD ["python", "app.py"]
