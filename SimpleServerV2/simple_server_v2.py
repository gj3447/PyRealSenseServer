from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, HTTPException, Request
from fastapi.responses import Response, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import asyncio
from typing import Optional, Dict
import time
import json
import sys
from pathlib import Path
import traceback
import psutil
import os
from starlette.websockets import WebSocketState
import signal

# 현재 디렉토리를 파이썬 패스에 추가
sys.path.append(str(Path(__file__).parent.parent))

from SimpleServerV2.frame_manager import frame_manager
from SimpleServerV2.camera_thread import camera_thread
from SimpleServerV2.utils import encode_frame_to_jpeg, colorize_depth, get_frame_info, create_error_frame

# 웹소켓 설정
WS_PING_INTERVAL = 5.0  # 5초마다 핑
WS_PING_TIMEOUT = 10.0  # 10초 타임아웃
WS_MAX_SIZE = 2**18    # 256KB
WS_CLOSE_TIMEOUT = 2.0 # 2초
WS_MAX_QUEUE = 8       # 최대 8개 메시지

@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 lifespan 이벤트"""
    # 시작 시
    print("\n" + "="*50)
    print("RealSense D455 스트리밍 서버 시작")
    print("="*50)
    print("\n1. 카메라 초기화 중...")
    
    try:
        # 카메라 쓰레드 상태 확인 및 초기화
        if hasattr(camera_thread, '_started') and camera_thread._started:
            print("⚠️ 기존 카메라 쓰레드가 실행 중입니다. 정리 후 재시작합니다.")
            camera_thread.stop()
            # is_alive 속성 확인
            if isinstance(getattr(camera_thread, 'is_alive', None), bool) and camera_thread.is_alive:
                camera_thread.join(timeout=5)
        
        camera_thread.reset()  # 쓰레드 상태 초기화
        camera_thread.start()
        
        initialization_success = False
        # 카메라 초기화 대기
        for i in range(10):  # 최대 10초 대기
            if camera_thread.get_device_info():
                initialization_success = True
                break
            elif camera_thread._error:
                print(f"\n❌ 카메라 초기화 실패: {camera_thread._error}")
                break
            print(f"안정화 진행 중... {(i+1)*10}%")
            await asyncio.sleep(1)
        
        if initialization_success:
            device_info = camera_thread.get_device_info()
            print("\n✅ 카메라 초기화 성공!")
            print(f"   - 장치: {device_info['name']}")
            print(f"   - 시리얼: {device_info['serial_number']}")
            print(f"   - USB: {device_info['usb_type']}")
            print(f"   - 펌웨어: {device_info['firmware_version']}")
            print(f"\n🌐 서버 시작 완료 - http://localhost:51000")
        else:
            print("\n❌ 카메라 초기화 실패")
            print("⚠️ 서버는 계속 실행됩니다. 카메라 재연결 시 자동으로 감지됩니다.")
    
    except Exception as e:
        print(f"\n❌ 서버 시작 중 오류 발생: {str(e)}")
        traceback.print_exc()
        print("⚠️ 서버는 계속 실행됩니다. 문제가 해결되면 자동으로 복구됩니다.")
    
    yield  # 서버 실행
    
    # 종료 시
    print("\n" + "="*50)
    print("서버 종료 중...")
    try:
        # 카메라 쓰레드 정리
        print("카메라 쓰레드 정리 중...")
        camera_thread.stop()
        if hasattr(camera_thread, '_started') and camera_thread._started and \
           isinstance(getattr(camera_thread, 'is_alive', None), bool) and camera_thread.is_alive:
            camera_thread.join(timeout=5)  # 최대 5초 대기
        print("✓ 카메라 쓰레드 종료")
        
        # 웹소켓 연결 정리
        print("웹소켓 연결 정리 중...")
        for client_id in list(ws_manager.active_connections.keys()):
            try:
                ws_manager.disconnect(client_id)
            except Exception as e:
                print(f"⚠️ 클라이언트 {client_id} 연결 종료 실패: {e}")
        print("✓ 웹소켓 연결 정리 완료")
        
        # 프레임 매니저 정리
        print("프레임 매니저 정리 중...")
        frame_manager.stop()
        print("✓ 프레임 매니저 정리 완료")
        
    except Exception as e:
        print(f"❌ 서버 종료 중 오류 발생: {str(e)}")
        traceback.print_exc()
    finally:
        print("✅ 서버 종료 완료")
        print("="*50)

# FastAPI 앱 생성
app = FastAPI(lifespan=lifespan)

# 정적 파일 서비스 설정
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

# 캐시 제어 미들웨어 추가
@app.middleware("http")
async def add_cache_control_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# 웹소켓 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.last_ping_times: Dict[str, float] = {}
        self.reconnect_attempts: Dict[str, int] = {}  # 재연결 시도 횟수
        self.max_reconnect_attempts = 3  # 최대 재연결 시도 횟수
    
    def get_connection_summary(self) -> str:
        """현재 연결 상태 요약"""
        color_jpeg = sum(1 for k in self.active_connections if k.startswith('color_jpeg'))
        depth_jpeg = sum(1 for k in self.active_connections if k.startswith('depth_jpeg'))
        color_raw = sum(1 for k in self.active_connections if k.startswith('color_raw'))
        depth_raw = sum(1 for k in self.active_connections if k.startswith('depth_raw'))
        return f"컬러JPEG: {color_jpeg}, 깊이JPEG: {depth_jpeg}, 컬러RAW: {color_raw}, 깊이RAW: {depth_raw}"
    
    async def connect(self, websocket: WebSocket, client_id: str):
        try:
            await websocket.accept()
            self.active_connections[client_id] = websocket
            self.last_ping_times[client_id] = time.time()
            self.reconnect_attempts[client_id] = 0  # 재연결 시도 횟수 초기화
            print(f"✓ 웹소켓 연결됨: {client_id}")
            print(f"  - 현재 연결 수: {len(self.active_connections)}")
            print(f"  - 연결 상태: {self.get_connection_summary()}")
        except Exception as e:
            print(f"❌ 웹소켓 연결 실패 ({client_id}): {str(e)}")
            raise
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            if client_id in self.last_ping_times:
                del self.last_ping_times[client_id]
            print(f"✓ 웹소켓 연결 종료: {client_id}")
            print(f"  - 현재 연결 수: {len(self.active_connections)}")
            print(f"  - 연결 상태: {self.get_connection_summary()}")
    
    async def send_frame(self, frame_data: bytes, metadata: dict, client_id: str):
        if client_id not in self.active_connections:
            print(f"⚠️ 존재하지 않는 클라이언트 ({client_id})")
            return
        
        try:
            websocket = self.active_connections[client_id]
            if websocket.application_state != WebSocketState.CONNECTED:
                print(f"⚠️ 웹소켓 연결 끊김 감지 ({client_id})")
                self.disconnect(client_id)
                return
            
            # 연결 상태 확인
            current_time = time.time()
            if current_time - self.last_ping_times.get(client_id, 0) > WS_PING_TIMEOUT:
                print(f"⚠️ 클라이언트 핑 타임아웃 ({client_id})")
                await websocket.close(code=1000)
                self.disconnect(client_id)
                return
            
            # 프레임 전송
            try:
                await websocket.send_json(metadata)
                await websocket.send_bytes(frame_data)
                self.last_ping_times[client_id] = current_time
                self.reconnect_attempts[client_id] = 0  # 성공 시 재연결 시도 횟수 초기화
            except Exception as e:
                if self.reconnect_attempts[client_id] < self.max_reconnect_attempts:
                    self.reconnect_attempts[client_id] += 1
                    print(f"⚠️ 프레임 전송 실패, 재시도 중... ({client_id}, 시도: {self.reconnect_attempts[client_id]})")
                    await asyncio.sleep(0.1)  # 잠시 대기 후 재시도
                    await self.send_frame(frame_data, metadata, client_id)
                else:
                    print(f"❌ 최대 재시도 횟수 초과 ({client_id})")
                    self.disconnect(client_id)
                    raise
        except Exception as e:
            print(f"❌ 프레임 전송 실패 ({client_id}): {str(e)}")
            self.disconnect(client_id)
            raise

# 웹소켓 매니저 인스턴스 생성
ws_manager = ConnectionManager()

# 시그널 핸들러 설정
def signal_handler(signum, frame):
    print(f"\n⚠️ 시그널 {signum} 수신")
    print("정상적인 종료를 위해 'Ctrl+C'를 한번 더 누르세요.")
    signal.signal(signum, original_sigint)

original_sigint = signal.getsignal(signal.SIGINT)
signal.signal(signal.SIGINT, signal_handler)

@app.get("/status")
async def get_status():
    """서버 및 카메라 상태 확인"""
    device_info = camera_thread.get_device_info()
    frame_stats = frame_manager.stats
    thread_status = camera_thread.get_status()
    
    return {
        "status": "healthy" if frame_manager.is_running else "error",
        "timestamp": time.time(),
        "last_update": frame_manager.last_update,
        "error": frame_manager.error,
        "camera": {
            "connected": device_info is not None,
            "running": frame_manager.is_running,
            "error": frame_manager.error,
            "device_info": device_info,
            "frame_stats": frame_stats,
            "thread_status": thread_status
        },
        "websocket_connections": {
            "total": len(ws_manager.active_connections),
            "clients": list(ws_manager.active_connections.keys())
        }
    }

@app.get("/thread_status")
async def get_thread_status():
    """카메라 쓰레드 상태만 확인"""
    status = camera_thread.get_status()
    return {
        "timestamp": time.time(),
        "thread_status": status,
        "is_alive": camera_thread.is_alive,
        "is_capturing": camera_thread.is_capturing,
        "time_since_last_frame": time.time() - camera_thread.last_frame_time
    }

@app.get("/color_jpeg")
async def get_color_jpeg():
    """JPEG 형식의 컬러 프레임 반환"""
    jpeg_data = frame_manager.get_color_jpeg()
    if not jpeg_data:
        error_frame = create_error_frame(message="No Color Frame")
        jpeg_data = encode_frame_to_jpeg(error_frame)
    
    frame = frame_manager.get_color_frame()  # 메타데이터용
    headers = {
        "X-Timestamp": str(frame.timestamp) if frame else str(time.time()),
        "X-Frame-Number": str(frame.frame_number) if frame else "0",
        "X-Image-Width": str(frame.width) if frame else "0",
        "X-Image-Height": str(frame.height) if frame else "0",
        "X-Image-Format": "jpeg"
    }
    return Response(content=jpeg_data, media_type="image/jpeg", headers=headers)

@app.get("/depth_jpeg")
async def get_depth_jpeg():
    """JPEG 형식의 깊이 프레임 반환"""
    jpeg_data = frame_manager.get_depth_jpeg()
    if not jpeg_data:
        error_frame = create_error_frame(message="No Depth Frame")
        jpeg_data = encode_frame_to_jpeg(error_frame)
    
    frame = frame_manager.get_depth_frame()  # 메타데이터용
    headers = {
        "X-Timestamp": str(frame.timestamp) if frame else str(time.time()),
        "X-Frame-Number": str(frame.frame_number) if frame else "0",
        "X-Image-Width": str(frame.width) if frame else "0",
        "X-Image-Height": str(frame.height) if frame else "0",
        "X-Image-Format": "jpeg",
        "X-Depth-Scale": str(frame.depth_scale) if frame else "0"
    }
    return Response(content=jpeg_data, media_type="image/jpeg", headers=headers)

@app.get("/color_raw")
async def get_color_raw():
    """원본 컬러 프레임 반환"""
    frame = frame_manager.get_color_frame()
    if not frame:
        raise HTTPException(status_code=503, detail="No frame available")
    
    try:
        headers = {
            "X-Timestamp": str(frame.timestamp),
            "X-Frame-Number": str(frame.frame_number),
            "X-Image-Width": str(frame.width),
            "X-Image-Height": str(frame.height),
            "X-Image-Format": frame.format
        }
        return Response(content=frame.data.tobytes(), media_type="application/octet-stream", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/depth_raw")
async def get_depth_raw():
    """원본 깊이 프레임 반환"""
    frame = frame_manager.get_depth_frame()
    if not frame:
        raise HTTPException(status_code=503, detail="No frame available")
    
    try:
        headers = {
            "X-Timestamp": str(frame.timestamp),
            "X-Frame-Number": str(frame.frame_number),
            "X-Image-Width": str(frame.width),
            "X-Image-Height": str(frame.height),
            "X-Image-Format": frame.format,
            "X-Depth-Scale": str(frame.depth_scale)
        }
        return Response(content=frame.data.tobytes(), media_type="application/octet-stream", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """메인 페이지 반환"""
    return FileResponse("static/index.html")

def get_memory_usage():
    """현재 프로세스의 메모리 사용량 확인"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # MB 단위로 변환

async def stream_frames(websocket: WebSocket, client_id: str, get_frame, process_frame=None):
    """프레임 스트리밍 핸들러"""
    try:
        await ws_manager.connect(websocket, client_id)
        frame_count = 0
        last_stats_time = time.time()
        
        while True:
            if not camera_thread.is_capturing:
                await asyncio.sleep(0.1)
                continue
            
            try:
                # 웹소켓 상태 확인
                if websocket.application_state != WebSocketState.CONNECTED:
                    break
                
                # 프레임 가져오기
                frame = get_frame()
                if not frame:
                    await asyncio.sleep(0.01)
                    continue
                
                # 프레임 처리
                if process_frame:
                    frame_data = process_frame(frame.data)
                else:
                    frame_data = frame.data.tobytes()
                
                # 메타데이터 준비
                metadata = get_frame_info(frame)
                
                # 프레임 전송
                await ws_manager.send_frame(frame_data, metadata, client_id)
                
                # 통계 업데이트 (1초마다)
                frame_count += 1
                current_time = time.time()
                if current_time - last_stats_time >= 1.0:
                    fps = frame_count / (current_time - last_stats_time)
                    print(f"📊 {client_id} FPS: {fps:.1f}")
                    frame_count = 0
                    last_stats_time = current_time
                
                # 프레임 레이트 제어
                await asyncio.sleep(0.01)  # 최대 100fps
                
            except Exception as e:
                if isinstance(e, (WebSocketDisconnect, ClientDisconnected)):
                    print(f"ℹ️ 클라이언트 연결 종료 ({client_id})")
                    break
                print(f"❌ 스트리밍 에러 ({client_id}): {str(e)}")
                traceback.print_exc()
                break
    
    except Exception as e:
        print(f"❌ 웹소켓 연결 에러 ({client_id}): {str(e)}")
        traceback.print_exc()
    
    finally:
        ws_manager.disconnect(client_id)

@app.websocket("/ws/color_jpeg")
async def websocket_color_jpeg(websocket: WebSocket):
    """JPEG 형식의 컬러 프레임 스트리밍"""
    client_id = f"color_jpeg_{time.time()}"
    await stream_frames(
        websocket,
        client_id,
        frame_manager.get_color_frame,
        lambda x: encode_frame_to_jpeg(x)
    )

@app.websocket("/ws/depth_jpeg")
async def websocket_depth_jpeg(websocket: WebSocket):
    """JPEG 형식의 깊이 프레임 스트리밍"""
    client_id = f"depth_jpeg_{time.time()}"
    await stream_frames(
        websocket,
        client_id,
        frame_manager.get_depth_frame,
        lambda x: encode_frame_to_jpeg(colorize_depth(x))
    )

@app.websocket("/ws/color_raw")
async def websocket_color_raw(websocket: WebSocket):
    """원본 컬러 프레임 스트리밍"""
    client_id = f"color_raw_{time.time()}"
    await stream_frames(websocket, client_id, frame_manager.get_color_frame)

@app.websocket("/ws/depth_raw")
async def websocket_depth_raw(websocket: WebSocket):
    """원본 깊이 프레임 스트리밍"""
    client_id = f"depth_raw_{time.time()}"
    await stream_frames(websocket, client_id, frame_manager.get_depth_frame)

@app.post("/camera/restart")
async def restart_camera():
    """카메라 쓰레드 재시작"""
    try:
        # 기존 쓰레드 정리
        camera_thread.stop()
        camera_thread.join(timeout=5)  # 최대 5초 대기
        
        # 새 쓰레드 시작
        camera_thread.reset()  # 새로 추가할 메서드
        camera_thread.start()
        
        # 초기화 대기
        for _ in range(10):  # 최대 10초 대기
            if camera_thread.get_device_info() or camera_thread._error:
                break
            await asyncio.sleep(1)
        
        if camera_thread._error:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": camera_thread._error
                }
            )
        
        return {
            "success": True,
            "message": "카메라 재시작 완료",
            "device_info": camera_thread.get_device_info()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.get("/camera/calibration")
async def get_camera_calibration():
    """현재 저장된 캘리브레이션 정보를 반환합니다."""
    calibration_info = frame_manager.get_calibration_dict()
    if not calibration_info:
        raise HTTPException(
            status_code=503,
            detail="캘리브레이션 정보를 사용할 수 없습니다. 카메라가 연결되어 있는지 확인해주세요."
        )
    return calibration_info

@app.get("/camera/config")
async def get_camera_config():
    """카메라 설정 정보를 반환합니다."""
    try:
        config_path = Path(__file__).parent / "camera_config.json"
        if not config_path.exists():
            raise HTTPException(
                status_code=404,
                detail="카메라 설정 파일을 찾을 수 없습니다."
            )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        return config
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="카메라 설정 파일 형식이 올바르지 않습니다."
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"카메라 설정을 읽는 중 오류가 발생했습니다: {str(e)}"
        )

@app.get("/camera/current_info")
async def get_current_camera_info():
    """현재 카메라 상태와 프레임 정보를 반환합니다."""
    try:
        # 현재 프레임 정보 가져오기
        color_frame = frame_manager.get_color_frame()
        depth_frame = frame_manager.get_depth_frame()
        
        # 카메라 설정 로드
        config_path = Path(__file__).parent / "camera_config.json"
        config = {}
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        # 현재 프레임 정보
        current_info = {
            "camera_info": config.get("camera_info", {}),
            "current_frames": {
                "color": {
                    "available": color_frame is not None,
                    "width": color_frame.width if color_frame else 0,
                    "height": color_frame.height if color_frame else 0,
                    "format": color_frame.format if color_frame else "unknown",
                    "frame_number": color_frame.frame_number if color_frame else 0,
                    "timestamp": color_frame.timestamp if color_frame else 0
                },
                "depth": {
                    "available": depth_frame is not None,
                    "width": depth_frame.width if depth_frame else 0,
                    "height": depth_frame.height if depth_frame else 0,
                    "format": depth_frame.format if depth_frame else "unknown",
                    "frame_number": depth_frame.frame_number if depth_frame else 0,
                    "timestamp": depth_frame.timestamp if depth_frame else 0,
                    "depth_scale": depth_frame.depth_scale if depth_frame else 0.001
                }
            },
            "frame_stats": frame_manager.stats,
            "device_info": camera_thread.get_device_info(),
            "endpoints": {
                "color_jpeg": {
                    "format": "JPEG",
                    "quality": 95,
                    "resolution": f"{color_frame.width}x{color_frame.height}" if color_frame else "unknown",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "depth_jpeg": {
                    "format": "JPEG",
                    "quality": 95,
                    "resolution": f"{depth_frame.width}x{depth_frame.height}" if depth_frame else "unknown",
                    "fps": frame_manager.stats.get("last_fps", 0),
                    "max_distance": "6m"
                },
                "color_raw": {
                    "format": "BGR8",
                    "resolution": f"{color_frame.width}x{color_frame.height}" if color_frame else "unknown",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "depth_raw": {
                    "format": "Z16",
                    "resolution": f"{depth_frame.width}x{depth_frame.height}" if depth_frame else "unknown",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "ws_color_jpeg": {
                    "protocol": "WebSocket",
                    "compression": "JPEG",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "ws_depth_jpeg": {
                    "protocol": "WebSocket",
                    "visualization": "JET",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "ws_color_raw": {
                    "protocol": "WebSocket",
                    "format": "BGR8",
                    "fps": frame_manager.stats.get("last_fps", 0)
                },
                "ws_depth_raw": {
                    "protocol": "WebSocket",
                    "format": "Z16",
                    "fps": frame_manager.stats.get("last_fps", 0)
                }
            }
        }
        
        return current_info
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"현재 카메라 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    
    # 서버 설정
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=51000,
        ws_ping_interval=WS_PING_INTERVAL,
        ws_ping_timeout=WS_PING_TIMEOUT,
        ws_max_size=WS_MAX_SIZE,
        ws_max_queue=WS_MAX_QUEUE,
        backlog=128,
        timeout_keep_alive=30,
        timeout_notify=30,
        limit_concurrency=100,
        limit_max_requests=None,  # 무제한 요청 허용
        reload=False,
        workers=1,
        loop="asyncio",
        log_level="info",
        access_log=True
    )
    
    try:
        server = uvicorn.Server(config)
        server.run()
    except KeyboardInterrupt:
        print("\n서버가 사용자에 의해 종료되었습니다.")
    except Exception as e:
        print(f"\n❌ 서버 실행 중 오류 발생: {str(e)}")
        traceback.print_exc() 