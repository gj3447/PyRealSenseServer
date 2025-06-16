# RSserverV2

FastAPI 기반의 Intel RealSense 카메라 서버입니다. 카메라의 컬러 영상, 깊이 정보, IMU 데이터, 그리고 포인트 클라우드 데이터를 제공합니다.

## 기능

- 컬러 영상 스트리밍
- 깊이 정보 시각화
- IMU 센서 데이터 (가속도계, 자이로스코프)
- 3D 포인트 클라우드 생성 및 텍스처 매핑

## 설치 방법

1. 의존성 설치:
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정 (.env 파일):
```env
RS_HOST=0.0.0.0
RS_PORT=8000
RS_WIDTH=640
RS_HEIGHT=480
RS_FPS=30
```

## 실행 방법

```bash
python main.py
```

## API 엔드포인트

- `GET /health`: 서버 상태 확인
- `GET /camera/frames`: 컬러 영상과 깊이 정보
- `GET /camera/imu`: IMU 센서 데이터
- `GET /pointcloud/data`: 3D 포인트 클라우드 데이터

## 의존성 주입 (DI)

이 프로젝트는 FastAPI의 의존성 주입 시스템을 활용하여 다음과 같은 서비스들을 관리합니다:

- PipelineService: RealSense 카메라 파이프라인 관리
- CameraService: 영상 및 IMU 데이터 처리
- PointcloudService: 3D 포인트 클라우드 생성 및 처리 