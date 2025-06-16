import cv2
import numpy as np
from typing import Dict, Any

def encode_frame_to_jpeg(frame_data: np.ndarray, quality: int = 90) -> bytes:
    """프레임을 JPEG로 인코딩"""
    success, encoded = cv2.imencode('.jpg', frame_data, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("JPEG 인코딩 실패")
    return encoded.tobytes()

def colorize_depth(depth_data: np.ndarray, min_depth: float = 0.0, max_depth: float = 5.0) -> np.ndarray:
    """깊이 데이터를 컬러맵으로 변환"""
    depth_colormap = cv2.applyColorMap(
        cv2.convertScaleAbs(depth_data, alpha=255/max_depth),
        cv2.COLORMAP_JET
    )
    return depth_colormap

def get_frame_info(frame) -> Dict[str, Any]:
    """프레임 메타데이터 추출"""
    frame_data = frame.data
    height, width = frame_data.shape[:2]
    
    metadata = {
        "timestamp": frame.timestamp,
        "frame_number": frame.frame_number,
        "width": width,
        "height": height,
        "format": frame.format
    }
    
    if hasattr(frame, 'depth_scale'):
        metadata["depth_scale"] = frame.depth_scale
    
    return metadata

def create_error_frame(message: str = "No Frame", width: int = 640, height: int = 480) -> np.ndarray:
    """에러 메시지를 포함한 프레임 생성"""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    
    # 텍스트 설정
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    thickness = 2
    color = (0, 0, 255)  # 빨간색
    
    # 텍스트 크기 계산
    (text_width, text_height), _ = cv2.getTextSize(message, font, font_scale, thickness)
    
    # 텍스트 위치 계산 (중앙)
    x = (width - text_width) // 2
    y = (height + text_height) // 2
    
    # 텍스트 그리기
    cv2.putText(frame, message, (x, y), font, font_scale, color, thickness)
    
    return frame 