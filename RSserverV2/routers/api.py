from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Annotated
import cv2
import numpy as np
import asyncio
import json
from datetime import datetime
import logging

from service.camera_service import CameraService
from service.pointcloud_service import PointcloudService
from dependencies import get_camera_service, get_pointcloud_service

router = APIRouter(prefix="/api", tags=["api"])

logger = logging.getLogger(__name__)

@router.get("/camera/status")
async def get_camera_status(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """카메라 서비스와 파이프라인의 상태를 확인"""
    try:
        # 테스트 프레임을 가져와서 상태 확인
        frames = camera_service.get_frames()
        pipeline_status = camera_service.pipeline_service._started

        return {
            "status": "healthy" if pipeline_status else "stopped",
            "pipeline_running": pipeline_status,
            "last_frame_received": frames["color"] is not None,
            "frame_shape": frames["color"].shape if frames["color"] is not None else None,
            "error_count": camera_service.pipeline_service.error_count
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "pipeline_running": False,
            "last_frame_received": False,
            "error_count": camera_service.pipeline_service.error_count if hasattr(camera_service.pipeline_service, 'error_count') else -1
        }

async def generate_color_frames(camera_service: CameraService):
    while True:
        try:
            frames = camera_service.get_frames()
            if frames is not None and frames["color"] is not None:
                # JPEG로 인코딩
                _, buffer = cv2.imencode('.jpg', frames["color"])
                # MJPEG 형식으로 프레임 전송
                yield (b'--frame\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            await asyncio.sleep(1/30)  # 30 FPS
        except Exception as e:
            logger.error(f"프레임 생성 중 오류: {str(e)}")
            await asyncio.sleep(1)  # 오류 발생시 1초 대기

@router.get("/camera/stream")
async def color_stream(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """Color 카메라 스트림을 MJPEG 형식으로 제공"""
    return StreamingResponse(
        generate_color_frames(camera_service),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@router.get("/camera/frames")
async def get_frames(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """현재 프레임 데이터를 단일 이미지로 제공"""
    frames = camera_service.get_frames()
    
    if not frames["color"]:
        return {"error": "No frames available"}
    
    # 이미지를 JPEG로 인코딩
    _, buffer = cv2.imencode('.jpg', frames["color"])
    
    return Response(
        content=buffer.tobytes(),
        media_type="image/jpeg"
    )

@router.get("/camera/imu")
async def get_imu_data(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """IMU 센서 데이터 제공"""
    frames = camera_service.get_frames()
    return {
        "accelerometer": frames["accel"],
        "gyroscope": frames["gyro"]
    }

@router.get("/pointcloud/data")
async def get_pointcloud(
    pointcloud_service: Annotated[PointcloudService, Depends(get_pointcloud_service)]
):
    """포인트클라우드 데이터 제공"""
    pc_data = pointcloud_service.get_pointcloud()
    if pc_data is None:
        return {"error": "No pointcloud data available"}
    
    return {
        "vertices": pc_data["vertices"].tolist(),
        "texture": pc_data["texture"].tolist()
    }

async def generate_status_stream(camera_service: CameraService):
    while True:
        status = camera_service.get_status()
        # JSON 형식으로 변환
        json_data = json.dumps(status)
        yield f"data: {json_data}\n\n"
        await asyncio.sleep(1)  # 1초마다 상태 업데이트

@router.get("/camera/status/stream")
async def stream_status(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """카메라 상태를 Server-Sent Events로 스트리밍"""
    return StreamingResponse(
        generate_status_stream(camera_service),
        media_type="text/event-stream"
    )

@router.post("/camera/restart")
async def restart_pipeline(
    camera_service: Annotated[CameraService, Depends(get_camera_service)]
):
    """카메라 파이프라인을 재시작"""
    logs = []
    
    def log_collector(message):
        logs.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "message": message
        })
    
    try:
        log_collector("파이프라인 재시작 시작")
        log_collector("현재 상태: " + camera_service.pipeline_service.status)
        
        # 현재 파이프라인 중지
        log_collector("파이프라인 중지 시도...")
        camera_service.stop()
        log_collector("파이프라인 중지 완료")
        
        # 잠시 대기
        log_collector("안정화를 위해 1초 대기")
        await asyncio.sleep(1)
        
        # 파이프라인 재시작
        log_collector("파이프라인 시작 시도...")
        camera_service.start()
        log_collector("파이프라인 시작 완료")
        
        # 최종 상태 확인
        status = camera_service.get_status()
        log_collector(f"최종 상태: {status['pipeline_status']['status']}")
        
        if status['pipeline_status']['status'] == 'running':
            return {
                "status": "success",
                "message": "파이프라인이 성공적으로 재시작되었습니다.",
                "logs": logs,
                "pipeline_status": status['pipeline_status']
            }
        else:
            raise Exception(f"파이프라인이 정상 상태가 아님: {status['pipeline_status']['status']}")
            
    except Exception as e:
        error_details = str(e)
        log_collector(f"오류 발생: {error_details}")
        
        if "failed to set power state" in error_details.lower():
            error_msg = "카메라 전원 상태 설정 실패. USB 연결을 확인해주세요."
        elif "frame didn't arrive" in error_details.lower():
            error_msg = "프레임 수신 타임아웃. 카메라가 정상 작동하는지 확인해주세요."
        elif "device not found" in error_details.lower():
            error_msg = "카메라를 찾을 수 없습니다. USB 연결을 확인해주세요."
        else:
            error_msg = f"재시작 중 오류 발생: {error_details}"
        
        return {
            "status": "error",
            "message": error_msg,
            "details": str(e),
            "logs": logs
        } 