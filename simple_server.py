import pyrealsense2 as rs
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import Response, JSONResponse
import uvicorn
import asyncio
from typing import List
from contextlib import asynccontextmanager
import time

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("서버 시작...")
    yield
    # Shutdown
    print("서버 종료...")
    global streaming, pipeline
    streaming = False
    if stream_task:
        stream_task.cancel()
    try:
        if pipeline and pipeline.is_active():
            pipeline.stop()
    except Exception as e:
        print(f"파이프라인 종료 중 에러: {e}")

app = FastAPI(lifespan=lifespan)

# 웹소켓 클라이언트 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data: bytes, data_type: str):
        for connection in self.active_connections:
            try:
                await connection.send_bytes(data)
            except:
                await self.disconnect(connection)

manager = ConnectionManager()

def initialize_camera():
    try:
        # 1. 컨텍스트 생성 및 장치 확인
        print("\n1. RealSense 컨텍스트 초기화...")
        ctx = rs.context()
        devices = ctx.query_devices()
        
        if len(devices) == 0:
            print("❌ RealSense 카메라를 찾을 수 없습니다.")
            return None, None
            
        device = devices[0]
        print(f"✓ 발견된 장치: {device.get_info(rs.camera_info.name)}")
        print(f"✓ 시리얼 번호: {device.get_info(rs.camera_info.serial_number)}")
        print(f"✓ USB 타입: {device.get_info(rs.camera_info.usb_type_descriptor)}")
        
        # 2. 파이프라인 설정
        print("\n2. 파이프라인 설정...")
        pipeline = rs.pipeline()
        config = rs.config()
        
        # 3. 스트림 설정 (USB 3.2 활용)
        print("✓ 스트림 설정 (1280x720, 30fps)...")
        config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
        config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
        
        # 4. 파이프라인 시작
        print("\n4. 파이프라인 시작...")
        profile = pipeline.start(config)
        print("✅ 카메라 초기화 완료")
        
        # 5. 처음 몇 프레임 버리기 (카메라 안정화)
        print("카메라 안정화 중...")
        for _ in range(5):
            pipeline.wait_for_frames()
            time.sleep(0.1)
        
        return pipeline, profile
            
    except Exception as e:
        print(f"\n❌ 카메라 초기화 실패: {str(e)}")
        print(f"에러 타입: {type(e).__name__}")
        if 'pipeline' in locals() and pipeline:
            try:
                pipeline.stop()
            except:
                pass
        return None, None

# 카메라 초기화
pipeline, profile = initialize_camera()

# 스트리밍 상태 관리
streaming = False
stream_task = None

async def stream_frames():
    while streaming and pipeline:
        try:
            # 프레임 가져오기
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            
            if not color_frame or not depth_frame:
                print("⚠️ 유효하지 않은 프레임 스킵")
                continue
                
            # 데이터 전송
            try:
                await manager.broadcast(color_frame.get_data().tobytes(), "color")
                await manager.broadcast(depth_frame.get_data().tobytes(), "depth")
            except Exception as e:
                print(f"전송 에러: {e}")
            
            # 프레임 레이트 조절
            await asyncio.sleep(1/30)  # 30fps
            
        except Exception as e:
            print(f"스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                print("❌ 카메라 연결이 끊어졌습니다.")
                break
            await asyncio.sleep(0.1)  # 에러 발생시 잠시 대기

@app.get("/")
async def root():
    if not pipeline:
        return {"status": "error", "message": "카메라가 연결되지 않았습니다"}
    return {"status": "running", "endpoints": ["/color", "/depth"]}

@app.get("/color")
async def get_color():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        
        if not color_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        return Response(content=color_frame.get_data().tobytes(), 
                      media_type="application/octet-stream")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/depth")
async def get_depth():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()
        
        if not depth_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        return Response(content=depth_frame.get_data().tobytes(),
                      media_type="application/octet-stream")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not pipeline:
        await websocket.close(code=1013, reason="카메라가 연결되지 않았습니다")
        return
        
    global streaming, stream_task
    await manager.connect(websocket)
    
    try:
        if not streaming:
            streaming = True
            stream_task = asyncio.create_task(stream_frames())
        
        while True:
            data = await websocket.receive_text()
            if data == "stop":
                break
    except Exception as e:
        print(f"웹소켓 에러: {e}")
    finally:
        manager.disconnect(websocket)
        if not manager.active_connections:
            streaming = False
            if stream_task:
                stream_task.cancel()

if __name__ == "__main__":
    # reload=False로 설정하여 중복 초기화 방지
    uvicorn.run("simple_server:app", 
                host="0.0.0.0", 
                port=8000, 
                reload=False) 