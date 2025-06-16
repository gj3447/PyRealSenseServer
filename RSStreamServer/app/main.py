from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import cv2
import asyncio
import logging
from app.camera import RealSenseCamera

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="RealSense Stream Server")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 환경에서는 모든 origin 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

camera = RealSenseCamera()

@app.on_event("startup")
async def startup_event():
    """서버 시작시 카메라 초기화"""
    if camera.start():
        logger.info("카메라 초기화 성공")
    else:
        logger.error("카메라 초기화 실패")

@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료시 카메라 정리"""
    camera.stop()
    logger.info("카메라 종료됨")

async def generate_frames():
    """프레임 스트림 생성기"""
    while True:
        frame = camera.get_frame()
        if frame is not None:
            # JPEG로 인코딩
            _, buffer = cv2.imencode('.jpg', frame)
            # MJPEG 형식으로 전송
            yield (b'--frame\r\n'
                  b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        await asyncio.sleep(1/30)  # 30 FPS

@app.get("/stream")
async def video_stream():
    """비디오 스트림 엔드포인트"""
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/frame")
async def get_frame():
    """현재 프레임을 단일 이미지로 제공"""
    frame = camera.get_frame()
    if frame is None:
        return {"error": "No frame available"}
    
    _, buffer = cv2.imencode('.jpg', frame)
    return Response(content=buffer.tobytes(), media_type="image/jpeg")

@app.get("/status")
async def get_status():
    """카메라 상태 확인"""
    return {
        "running": camera._started,
        "resolution": f"{camera.width}x{camera.height}",
        "fps": camera.fps
    } 