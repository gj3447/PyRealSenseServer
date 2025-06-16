import pyrealsense2 as rs
import numpy as np
import cv2
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import uvicorn
import threading
import time
import io
import base64
from fastapi.middleware.cors import CORSMiddleware

from config import (
    SERVER_HOST,
    SERVER_PORT,
    ENABLE_RELOAD,
    CAMERA_CONFIG,
    STREAM_INTERVAL,
    DEPTH_SCALE_ALPHA,
    API_PREFIX,
    CORS_SETTINGS,
    MAX_RETRY_COUNT,
    RETRY_DELAY,
    ERROR_THRESHOLD,
    TARGET_FPS
)

app = FastAPI(title="RealSense API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    **CORS_SETTINGS
)

# 정적 파일과 템플릿 설정
static_path = Path("static")
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

class RealSenseCamera:
    def __init__(self):
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.align = rs.align(rs.stream.color)
        self.error_count = 0
        self.is_running = False
        self.setup_camera()

    def setup_camera(self):
        # 카메라 설정 적용
        self.config.enable_stream(
            rs.stream.depth,
            CAMERA_CONFIG["depth"]["width"],
            CAMERA_CONFIG["depth"]["height"],
            getattr(rs.format, CAMERA_CONFIG["depth"]["format"]),
            CAMERA_CONFIG["depth"]["fps"]
        )
        self.config.enable_stream(
            rs.stream.color,
            CAMERA_CONFIG["color"]["width"],
            CAMERA_CONFIG["color"]["height"],
            getattr(rs.format, CAMERA_CONFIG["color"]["format"]),
            CAMERA_CONFIG["color"]["fps"]
        )

    def start(self):
        if self.is_running:
            return True

        try:
            self.pipeline.start(self.config)
            self.is_running = True
            self.error_count = 0
            print("✅ RealSense 카메라 시작됨")
            return True
        except RuntimeError as e:
            print(f"🚨 RealSense 시작 오류: {e}")
            return False

    def stop(self):
        if self.is_running:
            self.pipeline.stop()
            self.is_running = False
            print("✅ RealSense 카메라 종료됨")

    def restart(self):
        print("🔄 카메라 재시작 중...")
        self.stop()
        time.sleep(RETRY_DELAY)
        return self.start()

    def get_frames(self):
        """프레임을 가져오고 처리하는 메소드"""
        if not self.is_running:
            if not self.start():
                return None, None

        for _ in range(MAX_RETRY_COUNT):
            try:
                frames = self.pipeline.wait_for_frames()
                aligned_frames = self.align.process(frames)
                color_frame = aligned_frames.get_color_frame()
                depth_frame = aligned_frames.get_depth_frame()

                if not depth_frame or not color_frame:
                    raise RuntimeError("프레임이 유효하지 않습니다")

                color_image = np.asanyarray(color_frame.get_data())
                depth_colormap = cv2.applyColorMap(
                    cv2.convertScaleAbs(np.asanyarray(depth_frame.get_data()), alpha=DEPTH_SCALE_ALPHA),
                    cv2.COLORMAP_JET
                )

                self.error_count = 0  # 성공적으로 프레임을 가져왔으므로 에러 카운트 리셋
                return color_image, depth_colormap

            except Exception as e:
                self.error_count += 1
                print(f"⚠️ 프레임 캡처 오류 (시도 {_ + 1}/{MAX_RETRY_COUNT}): {e}")
                if self.error_count >= ERROR_THRESHOLD:
                    print(f"🚨 연속된 에러 발생 (count: {self.error_count})")
                    if not self.restart():
                        return None, None
                time.sleep(RETRY_DELAY)

        return None, None

# 카메라 인스턴스 생성
camera = RealSenseCamera()

# 프레임 저장용 전역 변수
lock = threading.Lock()
latest_frames = {
    "color": None,
    "depth": None
}

def capture_frames():
    """프레임 캡처 루프"""
    while True:
        loop_start_time = time.time()
        
        color_image, depth_colormap = camera.get_frames()
        
        if color_image is not None and depth_colormap is not None:
            with lock:
                latest_frames["color"] = color_image
                latest_frames["depth"] = depth_colormap
        
        # FPS 조절
        processing_time = time.time() - loop_start_time
        if processing_time < STREAM_INTERVAL:
            time.sleep(STREAM_INTERVAL - processing_time)
        else:
            actual_fps = 1.0 / processing_time
            if actual_fps < TARGET_FPS * 0.8:  # FPS가 20% 이상 떨어지면 경고
                print(f"⚠️ 성능 경고: 현재 FPS {actual_fps:.1f} (목표: {TARGET_FPS})")

@app.on_event("startup")
def on_startup():
    threading.Thread(target=capture_frames, daemon=True).start()

@app.on_event("shutdown")
async def shutdown_event():
    camera.stop()

def frame_to_base64(frame):
    """프레임을 base64 문자열로 변환"""
    _, buffer = cv2.imencode('.jpg', frame)
    return base64.b64encode(buffer).decode('utf-8')

@app.get("/")
async def root():
    return {
        "status": "running",
        "endpoints": {
            "color": f"{API_PREFIX}/color",
            "depth": f"{API_PREFIX}/depth",
            "frames": f"{API_PREFIX}/frames"
        }
    }

@app.get(f"{API_PREFIX}/color")
async def get_color():
    with lock:
        if latest_frames["color"] is None:
            return JSONResponse(
                status_code=503,
                content={"error": "color 이미지를 사용할 수 없습니다."}
            )
        return Response(
            content=cv2.imencode('.jpg', latest_frames["color"])[1].tobytes(),
            media_type="image/jpeg"
        )

@app.get(f"{API_PREFIX}/depth")
async def get_depth():
    with lock:
        if latest_frames["depth"] is None:
            return JSONResponse(
                status_code=503,
                content={"error": "depth 이미지를 사용할 수 없습니다."}
            )
        return Response(
            content=cv2.imencode('.jpg', latest_frames["depth"])[1].tobytes(),
            media_type="image/jpeg"
        )

@app.get(f"{API_PREFIX}/frames")
async def get_frames():
    """color와 depth 이미지를 모두 base64로 인코딩하여 반환"""
    with lock:
        if latest_frames["color"] is None or latest_frames["depth"] is None:
            return JSONResponse(
                status_code=503,
                content={"error": "이미지를 사용할 수 없습니다."}
            )
        
        return {
            "color": frame_to_base64(latest_frames["color"]),
            "depth": frame_to_base64(latest_frames["depth"]),
            "timestamp": time.time()
        }

@app.get("/", response_class=HTMLResponse)
async def index(request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

def generate_video_stream(frame_type):
    while True:
        with lock:
            frame = latest_frames.get(frame_type)
            if frame is None:
                continue
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.get("/video_feed/{stream_type}")
async def video_feed(stream_type: str):
    if stream_type not in ["color", "depth"]:
        return Response(content="Invalid stream type", status_code=400)
    return StreamingResponse(
        generate_video_stream(stream_type),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=ENABLE_RELOAD
    )
