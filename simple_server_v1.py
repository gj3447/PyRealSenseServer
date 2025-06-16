import pyrealsense2 as rs
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.responses import Response, JSONResponse
import uvicorn
import asyncio
from typing import List
from contextlib import asynccontextmanager
import time
import cv2
from fastapi.responses import StreamingResponse
import io
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

def initialize_camera():
    try:
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
        
        print("\n2. 파이프라인 설정...")
        pipeline = rs.pipeline()
        config = rs.config()
        
        # 특정 장치 선택
        config.enable_device(device.get_info(rs.camera_info.serial_number))
        
        print("✓ 스트림 설정 (1280x720, 30fps)...")
        config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
        config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
        
        print("\n3. 파이프라인 시작...")
        try:
            profile = pipeline.start(config)
            print("✅ 카메라 초기화 완료")
            
            print("카메라 안정화 중...")
            for _ in range(5):
                frames = pipeline.wait_for_frames(timeout_ms=5000)  # 5초 타임아웃 추가
                if not frames:
                    raise RuntimeError("프레임을 받아오지 못했습니다.")
                time.sleep(0.1)
            
            return pipeline, profile
        except Exception as e:
            print(f"파이프라인 시작 실패: {str(e)}")
            if pipeline:
                try:
                    pipeline.stop()
                except:
                    pass
            raise
            
    except Exception as e:
        print(f"\n❌ 카메라 초기화 실패: {str(e)}")
        print(f"에러 타입: {type(e).__name__}")
        if 'pipeline' in locals() and pipeline:
            try:
                pipeline.stop()
            except:
                pass
        return None, None

# 전역 변수 선언
pipeline = None
profile = None
streaming = False
stream_task = None

# FastAPI 앱 설정
@asynccontextmanager
async def lifespan(app: FastAPI):
    
    # Startup
    print("서버 시작...")
    global pipeline, profile
    
    # 카메라 초기화
    print("카메라 초기화 시작...")
    pipeline, profile = initialize_camera()
    
    if not pipeline:
        print("카메라 초기화 실패. 서버를 종료합니다.")
        exit(1)
    
    yield
    
    # Shutdown
    print("서버 종료...")
    global streaming
    streaming = False
    if stream_task:
        stream_task.cancel()
    if pipeline:
        pipeline.stop()

app = FastAPI(lifespan=lifespan)

# 정적 파일 서빙 설정
app.mount("/static", StaticFiles(directory="static"), name="static")

# 웹소켓 클라이언트 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data: bytes):
        for connection in self.active_connections:
            try:
                await connection.send_bytes(data)
            except:
                await self.disconnect(connection)

# 웹소켓 매니저 초기화
color_raw_manager = ConnectionManager()
depth_raw_manager = ConnectionManager()
color_jpeg_manager = ConnectionManager()
depth_jpeg_manager = ConnectionManager()

# 스트리밍 상태 관리
color_raw_streaming = False
depth_raw_streaming = False
color_jpeg_streaming = False
depth_jpeg_streaming = False

# 스트리밍 태스크
color_raw_stream_task = None
depth_raw_stream_task = None
color_jpeg_stream_task = None
depth_jpeg_stream_task = None

async def stream_color_frames():
    while color_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            
            if not color_frame:
                continue
                
            try:
                # BGR8 원본 데이터 전송
                color_data = color_frame.get_data()
                metadata = {
                    "type": "color",
                    "width": color_frame.get_width(),
                    "height": color_frame.get_height(),
                    "format": "bgr8",
                    "timestamp": time.time()
                }
                # 메타데이터와 원본 데이터를 분리해서 전송
                for connection in color_manager.active_connections:
                    try:
                        await connection.send_json(metadata)
                        await connection.send_bytes(bytes(color_data))
                    except:
                        await color_manager.disconnect(connection)
                
                await asyncio.sleep(1/30)
                
            except Exception as e:
                print(f"컬러 전송 에러: {e}")
            
        except Exception as e:
            print(f"컬러 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

async def stream_depth_frames():
    while depth_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            
            if not depth_frame:
                continue
                
            try:
                # Z16 원본 데이터 전송
                depth_data = depth_frame.get_data()
                metadata = {
                    "type": "depth",
                    "width": depth_frame.get_width(),
                    "height": depth_frame.get_height(),
                    "format": "z16",
                    "depth_scale": depth_frame.get_units(),
                    "timestamp": time.time()
                }
                # 메타데이터와 원본 데이터를 분리해서 전송
                for connection in depth_manager.active_connections:
                    try:
                        await connection.send_json(metadata)
                        await connection.send_bytes(bytes(depth_data))
                    except:
                        await depth_manager.disconnect(connection)
                
                await asyncio.sleep(1/30)
                
            except Exception as e:
                print(f"깊이 전송 에러: {e}")
            
        except Exception as e:
            print(f"깊이 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

async def stream_color_jpeg_frames():
    while color_jpeg_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            
            if not color_frame:
                continue
                
            try:
                color_image = np.asanyarray(color_frame.get_data())
                _, jpeg_data = cv2.imencode('.jpg', color_image, [cv2.IMWRITE_JPEG_QUALITY, 80])
                await color_jpeg_manager.broadcast(jpeg_data.tobytes())
                await asyncio.sleep(1/30)
            except Exception as e:
                print(f"컬러 JPEG 전송 에러: {e}")
            
        except Exception as e:
            print(f"컬러 JPEG 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

async def stream_depth_jpeg_frames():
    while depth_jpeg_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            
            if not depth_frame:
                continue
                
            try:
                depth_image = np.asanyarray(depth_frame.get_data())
                depth_scale = depth_frame.get_units()
                max_distance = 6.0
                depth_image_scaled = np.clip(depth_image * depth_scale, 0, max_distance)
                depth_image_normalized = (depth_image_scaled / max_distance * 255).astype(np.uint8)
                depth_colormap = cv2.applyColorMap(depth_image_normalized, cv2.COLORMAP_JET)
                _, jpeg_data = cv2.imencode('.jpg', depth_colormap, [cv2.IMWRITE_JPEG_QUALITY, 80])
                await depth_jpeg_manager.broadcast(jpeg_data.tobytes())
                await asyncio.sleep(1/30)
            except Exception as e:
                print(f"깊이 JPEG 전송 에러: {e}")
            
        except Exception as e:
            print(f"깊이 JPEG 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

async def stream_color_raw_frames():
    while color_raw_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            
            if not color_frame:
                continue
                
            try:
                # BGR8 원본 데이터 전송
                color_data = color_frame.get_data()
                metadata = {
                    "type": "color",
                    "width": color_frame.get_width(),
                    "height": color_frame.get_height(),
                    "format": "bgr8",
                    "timestamp": time.time()
                }
                for connection in color_raw_manager.active_connections:
                    try:
                        await connection.send_json(metadata)
                        await connection.send_bytes(bytes(color_data))
                    except:
                        await color_raw_manager.disconnect(connection)
                await asyncio.sleep(1/30)
            except Exception as e:
                print(f"컬러 RAW 전송 에러: {e}")
            
        except Exception as e:
            print(f"컬러 RAW 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

async def stream_depth_raw_frames():
    while depth_raw_streaming and pipeline:
        try:
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            
            if not depth_frame:
                continue
                
            try:
                # Z16 원본 데이터 전송
                depth_data = depth_frame.get_data()
                metadata = {
                    "type": "depth",
                    "width": depth_frame.get_width(),
                    "height": depth_frame.get_height(),
                    "format": "z16",
                    "depth_scale": depth_frame.get_units(),
                    "timestamp": time.time()
                }
                for connection in depth_raw_manager.active_connections:
                    try:
                        await connection.send_json(metadata)
                        await connection.send_bytes(bytes(depth_data))
                    except:
                        await depth_raw_manager.disconnect(connection)
                await asyncio.sleep(1/30)
            except Exception as e:
                print(f"깊이 RAW 전송 에러: {e}")
            
        except Exception as e:
            print(f"깊이 RAW 스트리밍 에러: {e}")
            if str(e) == "Camera has been disconnected":
                break
            await asyncio.sleep(0.1)

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/status")
async def get_status():
    global pipeline, color_raw_manager, depth_raw_manager, color_jpeg_manager, depth_jpeg_manager
    
    try:
        # 카메라 상태 확인
        camera_ok = False
        if pipeline:
            try:
                frames = pipeline.wait_for_frames(timeout_ms=1000)
                camera_ok = frames is not None
            except:
                camera_ok = False
        
        # 웹소켓 연결 상태
        websocket_status = {
            "color_raw": len(color_raw_manager.active_connections),
            "depth_raw": len(depth_raw_manager.active_connections),
            "color_jpeg": len(color_jpeg_manager.active_connections),
            "depth_jpeg": len(depth_jpeg_manager.active_connections)
        }
        
        # 스트리밍 상태
        streaming_status = {
            "color_raw": color_raw_streaming,
            "depth_raw": depth_raw_streaming,
            "color_jpeg": color_jpeg_streaming,
            "depth_jpeg": depth_jpeg_streaming
        }
        
        return {
            "status": "healthy" if camera_ok else "degraded",
            "timestamp": time.time(),
            "camera": {
                "connected": pipeline is not None,
                "streaming": camera_ok,
                "error": None if camera_ok else "카메라 프레임을 받아올 수 없습니다."
            },
            "websocket_connections": websocket_status,
            "streaming_tasks": streaming_status
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "timestamp": time.time(),
                "error": str(e)
            }
        )

@app.get("/color")
async def get_color():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        
        if not color_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        # 원본 BGR 데이터 전송
        return Response(content=bytes(color_frame.get_data()), 
                      media_type="application/octet-stream",
                      headers={
                          "X-Image-Width": str(color_frame.get_width()),
                          "X-Image-Height": str(color_frame.get_height()),
                          "X-Image-Format": "bgr8"
                      })
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
        
        # 원본 깊이 데이터 전송
        return Response(content=bytes(depth_frame.get_data()), 
                      media_type="application/octet-stream",
                      headers={
                          "X-Image-Width": str(depth_frame.get_width()),
                          "X-Image-Height": str(depth_frame.get_height()),
                          "X-Image-Format": "z16",
                          "X-Depth-Scale": str(depth_frame.get_units())
                      })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/color_jpeg")
async def get_color_jpeg():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        
        if not color_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        # BGR을 JPEG으로 변환 (품질 95로 설정)
        color_image = np.asanyarray(color_frame.get_data())
        _, jpeg_data = cv2.imencode('.jpg', color_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        return Response(content=jpeg_data.tobytes(), 
                      media_type="image/jpeg",
                      headers={
                          "X-Image-Width": str(color_frame.get_width()),
                          "X-Image-Height": str(color_frame.get_height()),
                          "X-Image-Format": "jpeg",
                          "X-JPEG-Quality": "95"
                      })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/depth_jpeg")
async def get_depth_jpeg():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()
        
        if not depth_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        # 깊이 데이터를 numpy 배열로 변환
        depth_image = np.asanyarray(depth_frame.get_data())
        
        # 깊이 값을 0-255 범위로 정규화 (최대 6m 기준)
        depth_scale = depth_frame.get_units()
        max_distance = 6.0  # 최대 6m
        depth_image_scaled = np.clip(depth_image * depth_scale, 0, max_distance)
        depth_image_normalized = (depth_image_scaled / max_distance * 255).astype(np.uint8)
        
        # COLORMAP_JET을 사용하여 깊이 시각화
        depth_colormap = cv2.applyColorMap(depth_image_normalized, cv2.COLORMAP_JET)
        
        # JPEG으로 변환 (품질 95로 설정)
        _, jpeg_data = cv2.imencode('.jpg', depth_colormap, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        return Response(content=jpeg_data.tobytes(), 
                      media_type="image/jpeg",
                      headers={
                          "X-Image-Width": str(depth_frame.get_width()),
                          "X-Image-Height": str(depth_frame.get_height()),
                          "X-Image-Format": "jpeg",
                          "X-JPEG-Quality": "95",
                          "X-Depth-Scale": str(depth_frame.get_units()),
                          "X-Depth-Max-Distance": "6.0"
                      })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/color_raw")
async def get_color_raw():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        
        if not color_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        # 원본 BGR 데이터 전송
        return Response(content=bytes(color_frame.get_data()), 
                      media_type="application/octet-stream",
                      headers={
                          "X-Image-Width": str(color_frame.get_width()),
                          "X-Image-Height": str(color_frame.get_height()),
                          "X-Image-Format": "bgr8"
                      })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/depth_raw")
async def get_depth_raw():
    if not pipeline:
        return JSONResponse(status_code=503, content={"error": "카메라가 연결되지 않았습니다"})
    try:
        frames = pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()
        
        if not depth_frame:
            return JSONResponse(status_code=503, content={"error": "이미지 없음"})
        
        # 원본 깊이 데이터 전송
        return Response(content=bytes(depth_frame.get_data()), 
                      media_type="application/octet-stream",
                      headers={
                          "X-Image-Width": str(depth_frame.get_width()),
                          "X-Image-Height": str(depth_frame.get_height()),
                          "X-Image-Format": "z16",
                          "X-Depth-Scale": str(depth_frame.get_units())
                      })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.websocket("/ws/color_jpeg")
async def websocket_color_jpeg_endpoint(websocket: WebSocket):
    global color_jpeg_streaming, color_jpeg_stream_task
    await color_jpeg_manager.connect(websocket)
    print("컬러 JPEG 웹소켓 연결됨")
    
    try:
        if not color_jpeg_streaming:
            color_jpeg_streaming = True
            color_jpeg_stream_task = asyncio.create_task(stream_color_jpeg_frames())
        
        while True:
            data = await websocket.receive_text()
            if data == "stop":
                break
    except Exception as e:
        print(f"컬러 JPEG 웹소켓 에러: {e}")
    finally:
        color_jpeg_manager.disconnect(websocket)
        print("컬러 JPEG 웹소켓 연결 종료")
        if not color_jpeg_manager.active_connections:
            color_jpeg_streaming = False
            if color_jpeg_stream_task:
                color_jpeg_stream_task.cancel()

@app.websocket("/ws/depth_jpeg")
async def websocket_depth_jpeg_endpoint(websocket: WebSocket):
    global depth_jpeg_streaming, depth_jpeg_stream_task
    await depth_jpeg_manager.connect(websocket)
    print("깊이 JPEG 웹소켓 연결됨")
    
    try:
        if not depth_jpeg_streaming:
            depth_jpeg_streaming = True
            depth_jpeg_stream_task = asyncio.create_task(stream_depth_jpeg_frames())
        
        while True:
            data = await websocket.receive_text()
            if data == "stop":
                break
    except Exception as e:
        print(f"깊이 JPEG 웹소켓 에러: {e}")
    finally:
        depth_jpeg_manager.disconnect(websocket)
        print("깊이 JPEG 웹소켓 연결 종료")
        if not depth_jpeg_manager.active_connections:
            depth_jpeg_streaming = False
            if depth_jpeg_stream_task:
                depth_jpeg_stream_task.cancel()

@app.websocket("/ws/color_raw")
async def websocket_color_raw_endpoint(websocket: WebSocket):
    global color_raw_streaming, color_raw_stream_task
    await color_raw_manager.connect(websocket)
    print("컬러 RAW 웹소켓 연결됨")
    
    try:
        if not color_raw_streaming:
            color_raw_streaming = True
            color_raw_stream_task = asyncio.create_task(stream_color_raw_frames())
        
        while True:
            data = await websocket.receive_text()
            if data == "stop":
                break
    except Exception as e:
        print(f"컬러 RAW 웹소켓 에러: {e}")
    finally:
        color_raw_manager.disconnect(websocket)
        print("컬러 RAW 웹소켓 연결 종료")
        if not color_raw_manager.active_connections:
            color_raw_streaming = False
            if color_raw_stream_task:
                color_raw_stream_task.cancel()

@app.websocket("/ws/depth_raw")
async def websocket_depth_raw_endpoint(websocket: WebSocket):
    global depth_raw_streaming, depth_raw_stream_task
    await depth_raw_manager.connect(websocket)
    print("깊이 RAW 웹소켓 연결됨")
    
    try:
        if not depth_raw_streaming:
            depth_raw_streaming = True
            depth_raw_stream_task = asyncio.create_task(stream_depth_raw_frames())
        
        while True:
            data = await websocket.receive_text()
            if data == "stop":
                break
    except Exception as e:
        print(f"깊이 RAW 웹소켓 에러: {e}")
    finally:
        depth_raw_manager.disconnect(websocket)
        print("깊이 RAW 웹소켓 연결 종료")
        if not depth_raw_manager.active_connections:
            depth_raw_streaming = False
            if depth_raw_stream_task:
                depth_raw_stream_task.cancel()

if __name__ == "__main__":
    uvicorn.run("simple_server_v1:app", host="0.0.0.0", port=51000, reload=False) 