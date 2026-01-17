# 1. 파이썬 3.10 기반 이미지
FROM python:3.10-slim

# 2. 필수 패키지 설치 (wget, unzip, gnupg 등)
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    gnupg \
    --no-install-recommends

# 3. 구글 크롬 브라우저 직접 다운로드 및 설치 (이 방식이 apt-key 에러를 피함)
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# 4. 시간대 설정 (KST)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 5. 작업 폴더 설정 및 패키지 설치
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 소스코드 복사
COPY . .

# 7. 실행
CMD ["python", "bot_runner.py"]