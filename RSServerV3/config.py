# 서버 설정
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000
ENABLE_RELOAD = True  # 개발 중 코드 변경 시 자동 재시작

# RealSense 카메라 설정
CAMERA_CONFIG = {
    "color": {
        "width": 640,
        "height": 480,
        "fps": 30,
        "format": "bgr8"
    },
    "depth": {
        "width": 640,
        "height": 480,
        "fps": 30,
        "format": "z16"
    }
}

# 스트리밍 설정
TARGET_FPS = 30  # 목표 FPS
STREAM_INTERVAL = 1.0 / TARGET_FPS  # FPS에 따른 대기 시간
DEPTH_SCALE_ALPHA = 0.03  # depth 이미지 스케일링 값

# 프레임 캡처 설정
MAX_RETRY_COUNT = 3  # 프레임 캡처 실패 시 최대 재시도 횟수
RETRY_DELAY = 1.0  # 재시도 사이의 대기 시간 (초)
ERROR_THRESHOLD = 5  # 연속 에러 발생 시 카메라 재시작 임계값

# API 설정
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

# CORS 설정
CORS_SETTINGS = {
    "allow_origins": ["*"],
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"]
} 