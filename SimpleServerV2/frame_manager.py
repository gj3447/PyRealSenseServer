import threading
import time
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple, Dict
from SimpleServerV2.utils import encode_frame_to_jpeg, colorize_depth
import traceback

@dataclass
class Frame:
    data: np.ndarray
    timestamp: float
    frame_number: int
    width: int
    height: int
    format: str
    jpeg_data: Optional[bytes] = None  # JPEG 인코딩된 데이터
    depth_scale: Optional[float] = None

@dataclass
class CalibrationInfo:
    """카메라 캘리브레이션 정보를 저장하는 데이터 클래스"""
    device_info: Dict
    timestamp: float
    depth_scale: float
    color_intrinsics: Dict
    depth_intrinsics: Dict
    depth_to_color_extrinsics: Dict

class FrameManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._color_frame: Optional[Frame] = None
        self._depth_frame: Optional[Frame] = None
        self._calibration_info: Optional[CalibrationInfo] = None
        self._last_update = 0.0
        self._last_calibration_update = 0.0
        self._is_running = False
        self._error = None
        self._stats = {
            "frames_received": 0,
            "frames_dropped": 0,
            "last_fps": 0.0,
            "avg_fps": 0.0,
            "memory_usage": 0,
            "calibration_updates": 0  # 캘리브레이션 업데이트 횟수 추가
        }
        self._fps_update_time = time.time()
        self._fps_frame_count = 0
        self._max_frame_age = 1.0  # 1초 이상 된 프레임은 삭제
        self._calibration_update_interval = 60.0  # 60초마다 캘리브레이션 업데이트
    
    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_update(self) -> float:
        return self._last_update
    
    @property
    def error(self) -> Optional[str]:
        return self._error

    @error.setter
    def error(self, value: Optional[str]):
        self._error = value
    
    @property
    def stats(self) -> Dict:
        """프레임 통계 정보 반환"""
        return self._stats.copy()

    @property
    def calibration_info(self) -> Optional[CalibrationInfo]:
        """현재 캘리브레이션 정보 반환"""
        with self._lock:
            return self._calibration_info

    @property
    def last_calibration_update(self) -> float:
        """마지막 캘리브레이션 업데이트 시간"""
        return self._last_calibration_update

    def start(self):
        """프레임 관리자 시작"""
        self._is_running = True
        self._error = None
        self._stats = {
            "frames_received": 0,
            "frames_dropped": 0,
            "last_fps": 0.0,
            "avg_fps": 0.0,
            "memory_usage": 0,
            "calibration_updates": 0
        }
        self._fps_update_time = time.time()
        self._fps_frame_count = 0
        self._last_calibration_update = 0.0

    def stop(self):
        """프레임 관리자 중지"""
        self._is_running = False
    
    def _update_fps_stats(self):
        """FPS 통계 업데이트"""
        current_time = time.time()
        self._fps_frame_count += 1
        
        # 1초마다 FPS 업데이트
        if current_time - self._fps_update_time >= 1.0:
            self._stats["last_fps"] = self._fps_frame_count / (current_time - self._fps_update_time)
            if self._stats["avg_fps"] == 0.0:
                self._stats["avg_fps"] = self._stats["last_fps"]
            else:
                self._stats["avg_fps"] = 0.95 * self._stats["avg_fps"] + 0.05 * self._stats["last_fps"]
            
            self._fps_frame_count = 0
            self._fps_update_time = current_time
    
    def _cleanup_old_frames(self):
        """오래된 프레임 정리"""
        current_time = time.time()
        with self._lock:
            if self._color_frame and (current_time - self._color_frame.timestamp) > self._max_frame_age:
                self._color_frame = None
                self._stats["frames_dropped"] += 1
            
            if self._depth_frame and (current_time - self._depth_frame.timestamp) > self._max_frame_age:
                self._depth_frame = None
                self._stats["frames_dropped"] += 1
    
    def update_frames(self, color_frame: np.ndarray, depth_frame: np.ndarray, frame_number: int, depth_scale: float):
        """새로운 프레임 업데이트 및 JPEG 변환"""
        self._cleanup_old_frames()
        
        with self._lock:
            current_time = time.time()
            
            # 컬러 프레임 업데이트 (JPEG 포함)
            color_jpeg = encode_frame_to_jpeg(color_frame)
            self._color_frame = Frame(
                data=color_frame.copy(),
                timestamp=current_time,
                frame_number=frame_number,
                width=color_frame.shape[1],
                height=color_frame.shape[0],
                format="bgr8",
                jpeg_data=color_jpeg
            )
            
            # 깊이 프레임 업데이트 (컬러맵 적용 후 JPEG 포함)
            colorized_depth = colorize_depth(depth_frame)
            depth_jpeg = encode_frame_to_jpeg(colorized_depth)
            self._depth_frame = Frame(
                data=depth_frame.copy(),
                timestamp=current_time,
                frame_number=frame_number,
                width=depth_frame.shape[1],
                height=depth_frame.shape[0],
                format="z16",
                depth_scale=depth_scale,
                jpeg_data=depth_jpeg
            )
            
            self._last_update = current_time
            self._stats["frames_received"] += 1
            
            # 메모리 사용량 추적 (JPEG 데이터 포함)
            self._stats["memory_usage"] = (
                color_frame.nbytes + depth_frame.nbytes +
                len(color_jpeg) + len(depth_jpeg)
            ) / (1024 * 1024)  # MB 단위
            
            self._update_fps_stats()
    
    def get_frames(self) -> Tuple[Optional[Frame], Optional[Frame]]:
        """현재 저장된 프레임 반환"""
        self._cleanup_old_frames()  # 가져오기 전에 정리
        with self._lock:
            return self._color_frame, self._depth_frame
    
    def get_color_frame(self) -> Optional[Frame]:
        """컬러 프레임만 반환"""
        self._cleanup_old_frames()  # 가져오기 전에 정리
        with self._lock:
            return self._color_frame
    
    def get_depth_frame(self) -> Optional[Frame]:
        """깊이 프레임만 반환"""
        self._cleanup_old_frames()  # 가져오기 전에 정리
        with self._lock:
            return self._depth_frame

    def get_color_jpeg(self) -> Optional[bytes]:
        """JPEG 인코딩된 컬러 프레임 반환"""
        self._cleanup_old_frames()
        with self._lock:
            return self._color_frame.jpeg_data if self._color_frame else None

    def get_depth_jpeg(self) -> Optional[bytes]:
        """JPEG 인코딩된 깊이 프레임 반환"""
        self._cleanup_old_frames()
        with self._lock:
            return self._depth_frame.jpeg_data if self._depth_frame else None

    def update_calibration(self, calibration_info: dict):
        """캘리브레이션 정보 업데이트"""
        try:
            # 필수 필드 검증
            required_fields = {
                "device_info": dict,
                "depth_scale": (int, float),
                "color_intrinsics": dict,
                "depth_intrinsics": dict,
                "depth_to_color_extrinsics": dict
            }
            
            for field, field_type in required_fields.items():
                if field not in calibration_info:
                    raise ValueError(f"필수 필드 누락: {field}")
                if not isinstance(calibration_info[field], field_type):
                    raise ValueError(f"잘못된 필드 타입: {field} (예상: {field_type.__name__})")
            
            # 내부 파라미터 필드 검증
            for stream_type in ["color_intrinsics", "depth_intrinsics"]:
                intrinsics = calibration_info[stream_type]
                required_intrinsics = ["width", "height", "ppx", "ppy", "fx", "fy", "model", "coeffs"]
                for field in required_intrinsics:
                    if field not in intrinsics:
                        raise ValueError(f"{stream_type}에 필수 필드 누락: {field}")
            
            # 외부 파라미터 필드 검증
            extrinsics = calibration_info["depth_to_color_extrinsics"]
            if "rotation" not in extrinsics or "translation" not in extrinsics:
                raise ValueError("depth_to_color_extrinsics에 필수 필드 누락")
            
            with self._lock:
                current_time = time.time()
                
                # 캘리브레이션 정보가 너무 오래된 경우에만 업데이트
                if (not self._calibration_info or 
                    current_time - self._last_calibration_update > self._calibration_update_interval):
                    
                    self._calibration_info = CalibrationInfo(
                        device_info=calibration_info["device_info"],
                        timestamp=current_time,
                        depth_scale=calibration_info["depth_scale"],
                        color_intrinsics=calibration_info["color_intrinsics"],
                        depth_intrinsics=calibration_info["depth_intrinsics"],
                        depth_to_color_extrinsics=calibration_info["depth_to_color_extrinsics"]
                    )
                    self._last_calibration_update = current_time
                    self._stats["calibration_updates"] += 1
                    
        except Exception as e:
            print(f"⚠️ 캘리브레이션 정보 업데이트 실패: {e}")
            traceback.print_exc()
            raise  # 상위로 에러 전파

    def get_calibration_dict(self) -> Optional[dict]:
        """캘리브레이션 정보를 딕셔너리 형태로 반환"""
        with self._lock:
            if not self._calibration_info:
                return None
            
            return {
                "device_info": self._calibration_info.device_info,
                "timestamp": self._calibration_info.timestamp,
                "depth_scale": self._calibration_info.depth_scale,
                "color_intrinsics": self._calibration_info.color_intrinsics,
                "depth_intrinsics": self._calibration_info.depth_intrinsics,
                "depth_to_color_extrinsics": self._calibration_info.depth_to_color_extrinsics
            }

# 전역 프레임 관리자 인스턴스
frame_manager = FrameManager() 