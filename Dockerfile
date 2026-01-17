# 파이썬 3.10 버전 기반 (버전은 형님 로컬이랑 맞추세요)
FROM python:3.10-slim

# 시간대를 서울로 설정 (주식 봇에 필수!)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 작업 폴더 생성
WORKDIR /app

# 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

# 실행 명령어는 docker-compose에서 정할 거라 여기선 비워둠
CMD ["bash"]