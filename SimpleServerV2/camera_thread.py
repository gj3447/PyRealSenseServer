import threading
import time
import pyrealsense2 as rs
import numpy as np
from typing import Optional, Tuple
import sys
from pathlib import Path
import traceback
import json

# 현재 디렉토리를 파이썬 패스에 추가
sys.path.append(str(Path(__file__).parent.parent))

from SimpleServerV2.frame_manager import frame_manager

class CameraThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self._stop_event = threading.Event()
        self._reconnect_event = threading.Event()
        self._lock = threading.Lock()  # 스레드 락 추가
        
        # RealSense 파이프라인 설정
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        
        # 설정 파일 로드
        self._camera_config = self._load_config()
        
        self._frame_number = 0
        self._error: Optional[str] = None
        self._device_info: Optional[dict] = None
        self._last_frame_time = time.time()
        self._is_capturing = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 2.0  # 초기 재연결 대기 시간
        self._depth_scale = 0.001  # 기본값
        self._last_calibration_update = 0.0
        self._calibration_update_interval = 60.0  # 60초마다 업데이트
    
    @property
    def is_alive(self) -> bool:
        """쓰레드가 살아있는지 확인"""
        return super().is_alive()
    
    @property
    def is_capturing(self) -> bool:
        """현재 프레임 캡처 중인지 확인"""
        return self._is_capturing
    
    @property
    def last_frame_time(self) -> float:
        """마지막 프레임 캡처 시간"""
        return self._last_frame_time
    
    def get_status(self) -> dict:
        """현재 쓰레드 상태 반환"""
        current_time = time.time()
        return {
            "thread_alive": self.is_alive,
            "is_capturing": self.is_capturing,
            "frame_number": self._frame_number,
            "last_frame_time": self.last_frame_time,
            "time_since_last_frame": current_time - self.last_frame_time,
            "error": self._error
        }
    
    def get_device_info(self) -> Optional[dict]:
        """현재 연결된 카메라 정보 반환"""
        with self._lock:
            return self._device_info.copy() if self._device_info else None
    
    def _get_depth_scale(self) -> float:
        """현재 깊이 스케일 값 반환"""
        try:
            depth_sensor = self.pipeline.get_active_profile().get_device().first_depth_sensor()
            return depth_sensor.get_depth_scale()
        except Exception as e:
            print(f"⚠️ 깊이 스케일 가져오기 실패: {e}")
            return self._depth_scale
    
    def _handle_error(self, error: Exception, context: str):
        """에러 처리 및 재연결 결정"""
        error_str = str(error)
        error_type = type(error).__name__
        
        print(f"❌ {context}: {error_str}")
        print(f"에러 타입: {error_type}")
        
        self._error = f"{context}: {error_str}"
        frame_manager.error = self._error
        
        # USB 관련 에러나 타임아웃의 경우 재연결 시도
        if "USB" in error_str or "timeout" in error_str.lower():
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_event.set()
                print(f"재연결 시도 #{self._reconnect_attempts + 1} 예정...")
                return True
        
        return False
    
    def _wait_for_frames_safe(self) -> Optional[rs.composite_frame]:
        """안전한 프레임 대기"""
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=5000)
            if not frames:
                raise RuntimeError("프레임 없음")
            return frames
        except Exception as e:
            if self._handle_error(e, "프레임 대기 실패"):
                return None
            raise
    
    def _load_config(self) -> dict:
        """카메라 설정 파일 로드"""
        try:
            config_path = Path(__file__).parent / "camera_config.json"
            if not config_path.exists():
                print("⚠️ camera_config.json을 찾을 수 없습니다. 기본 설정을 사용합니다.")
                return {}
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            print("✓ 카메라 설정 로드 완료")
            return config.get('camera_info', {})
            
        except Exception as e:
            print(f"⚠️ 설정 파일 로드 실패: {e}")
            return {}
    
    def initialize_camera(self) -> bool:
        """카메라 초기화"""
        try:
            print("\n1. RealSense 컨텍스트 초기화...")
            ctx = rs.context()
            devices = ctx.query_devices()
            
            if len(devices) == 0:
                self._error = "RealSense 카메라를 찾을 수 없습니다."
                frame_manager.error = self._error
                print(f"❌ {self._error}")
                return False
                
            device = devices[0]
            self._device_info = {
                "name": device.get_info(rs.camera_info.name),
                "serial_number": device.get_info(rs.camera_info.serial_number),
                "usb_type": device.get_info(rs.camera_info.usb_type_descriptor),
                "firmware_version": device.get_info(rs.camera_info.firmware_version)
            }
            
            print(f"✓ 발견된 장치: {self._device_info['name']}")
            print(f"✓ 시리얼 번호: {self._device_info['serial_number']}")
            print(f"✓ USB 타입: {self._device_info['usb_type']}")
            print(f"✓ 펌웨어 버전: {self._device_info['firmware_version']}")
            
            print("\n2. 파이프라인 설정...")
            # 특정 장치 선택
            self.config.enable_device(self._device_info['serial_number'])
            
            # 설정 파일에서 스트림 설정 가져오기
            color_config = self._camera_config.get('color', {})
            depth_config = self._camera_config.get('depth', {})
            
            # USB 2.0 포트 사용 시 해상도/FPS 조정
            if "2.0" in self._device_info['usb_type']:
                print("⚠️ USB 2.0 포트 감지됨 - 성능 최적화 적용")
                width, height = 640, 480
                fps = 5
            else:
                width = color_config.get('width', 1280)
                height = color_config.get('height', 720)
                fps = color_config.get('fps', 30)
            
            print(f"✓ 스트림 설정 ({width}x{height}, {fps}fps)...")
            self.config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
            self.config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
            
            print("\n3. 파이프라인 시작...")
            profile = self.pipeline.start(self.config)
            print("✅ 카메라 초기화 완료")
            
            # 깊이 스케일 가져오기
            self._depth_scale = self._get_depth_scale()
            print(f"✓ 깊이 스케일: {self._depth_scale}")
            
            print("카메라 안정화 중...")
            for i in range(5):
                frames = self._wait_for_frames_safe()
                if not frames:
                    raise RuntimeError("안정화 중 프레임을 받아오지 못했습니다.")
                print(f"안정화 진행 중... {(i+1)*20}%")
                time.sleep(0.1)
            
            print("✅ 카메라 안정화 완료")
            return True
            
        except Exception as e:
            self._handle_error(e, "카메라 초기화 실패")
            return False
    
    def reset(self):
        """쓰레드 상태 초기화"""
        self._stop_event.clear()
        self._frame_number = 0
        self._error = None
        self._device_info = None
        self._last_frame_time = time.time()
        self._is_capturing = False
        
        # 파이프라인 재설정
        try:
            self.pipeline.stop()
        except:
            pass
        
        self.pipeline = rs.pipeline()
        self.config = rs.config()

    def stop(self):
        """쓰레드 중지"""
        print("\n카메라 쓰레드 중지 요청...")
        self._stop_event.set()
    
    def _get_calibration_info(self) -> Optional[dict]:
        """현재 카메라의 캘리브레이션 정보를 가져옵니다."""
        try:
            with self._lock:
                if not self.pipeline or not self.is_capturing:
                    return None

                profiles = self.pipeline.get_active_profile()
                if not profiles:
                    return None

                try:
                    color_stream = profiles.get_stream(rs.stream.color).as_video_stream_profile()
                    depth_stream = profiles.get_stream(rs.stream.depth).as_video_stream_profile()
                except RuntimeError as e:
                    print(f"⚠️ 스트림 프로파일 가져오기 실패: {e}")
                    return None
                
                # 내부 파라미터 가져오기
                color_intrinsics = color_stream.get_intrinsics()
                depth_intrinsics = depth_stream.get_intrinsics()
                
                # 외부 파라미터 가져오기 (깊이->컬러 변환)
                depth_to_color = depth_stream.get_extrinsics_to(color_stream)
                
                # distortion 모델을 문자열로 변환
                def get_distortion_model_name(model):
                    if model == rs.distortion.none:
                        return "none"
                    elif model == rs.distortion.modified_brown_conrady:
                        return "modified_brown_conrady"
                    elif model == rs.distortion.inverse_brown_conrady:
                        return "inverse_brown_conrady"
                    elif model == rs.distortion.brown_conrady:
                        return "brown_conrady"
                    elif model == rs.distortion.ftheta:
                        return "ftheta"
                    elif model == rs.distortion.kannala_brandt4:
                        return "kannala_brandt4"
                    else:
                        return str(model)
                
                return {
                    "device_info": self._device_info,
                    "timestamp": time.time(),
                    "depth_scale": self._depth_scale,
                    "color_intrinsics": {
                        "width": color_intrinsics.width,
                        "height": color_intrinsics.height,
                        "ppx": color_intrinsics.ppx,
                        "ppy": color_intrinsics.ppy,
                        "fx": color_intrinsics.fx,
                        "fy": color_intrinsics.fy,
                        "model": get_distortion_model_name(color_intrinsics.model),
                        "coeffs": list(color_intrinsics.coeffs)  # numpy 배열을 리스트로 변환
                    },
                    "depth_intrinsics": {
                        "width": depth_intrinsics.width,
                        "height": depth_intrinsics.height,
                        "ppx": depth_intrinsics.ppx,
                        "ppy": depth_intrinsics.ppy,
                        "fx": depth_intrinsics.fx,
                        "fy": depth_intrinsics.fy,
                        "model": get_distortion_model_name(depth_intrinsics.model),
                        "coeffs": list(depth_intrinsics.coeffs)  # numpy 배열을 리스트로 변환
                    },
                    "depth_to_color_extrinsics": {
                        "rotation": [float(x) for x in depth_to_color.rotation],  # numpy 배열을 float 리스트로 변환
                        "translation": [float(x) for x in depth_to_color.translation]  # numpy 배열을 float 리스트로 변환
                    }
                }
        except Exception as e:
            print(f"⚠️ 캘리브레이션 정보 가져오기 실패: {e}")
            traceback.print_exc()  # 스택 트레이스 추가
            return None
    
    def run(self):
        """메인 캡처 루프"""
        print("\n카메라 쓰레드 시작...")
        
        while not self._stop_event.is_set():
            try:
                if not self.initialize_camera():
                    if self._reconnect_attempts >= self._max_reconnect_attempts:
                        print("❌ 최대 재시도 횟수 초과로 쓰레드 종료")
                        return
                    self._reconnect_attempts += 1
                    time.sleep(self._reconnect_delay * self._reconnect_attempts)
                    continue
                
                self._reconnect_attempts = 0
                self._reconnect_delay = 2.0
                frame_manager.start()
                self._is_capturing = True
                print("✓ 프레임 캡처 시작")
                
                while not self._stop_event.is_set() and not self._reconnect_event.is_set():
                    frames = self._wait_for_frames_safe()
                    if not frames:
                        continue
                    
                    color_frame = frames.get_color_frame()
                    depth_frame = frames.get_depth_frame()
                    
                    if not color_frame or not depth_frame:
                        print("⚠️ 유효하지 않은 프레임")
                        continue
                    
                    # numpy 배열로 변환
                    color_image = np.asanyarray(color_frame.get_data())
                    depth_image = np.asanyarray(depth_frame.get_data())
                    
                    # 프레임 번호 증가
                    self._frame_number += 1
                    self._last_frame_time = time.time()
                    
                    if self._frame_number % 30 == 0:  # 30프레임마다 로그
                        print(f"✓ 프레임 #{self._frame_number} 캡처됨")
                    
                    # 프레임 저장
                    frame_manager.update_frames(
                        color_image, 
                        depth_image, 
                        self._frame_number,
                        self._depth_scale
                    )
                    
                    # 캘리브레이션 정보 업데이트 (필요한 경우)
                    current_time = time.time()
                    if current_time - self._last_calibration_update > self._calibration_update_interval:
                        calibration_info = self._get_calibration_info()
                        if calibration_info:
                            frame_manager.update_calibration(calibration_info)
                            self._last_calibration_update = current_time
                    
                    # 에러 상태 초기화
                    if self._error:
                        self._error = None
                        frame_manager.error = None
                
                if self._reconnect_event.is_set():
                    print("\n재연결 시도 중...")
                    self._reconnect_event.clear()
                    self.reset()
                    continue
                    
            except Exception as e:
                if not self._handle_error(e, "카메라 쓰레드 에러"):
                    break
                self.reset()
                continue
            
        # 쓰레드 종료
        self._cleanup()
    
    def _cleanup(self):
        """리소스 정리"""
        print("\n카메라 쓰레드 정리 중...")
        with self._lock:
            self._is_capturing = False
            self._device_info = None
            self._error = None
        
        frame_manager.stop()
        try:
            if self.pipeline:
                self.pipeline.stop()
                print("✓ 파이프라인 정상 종료")
        except Exception as e:
            print(f"❌ 파이프라인 종료 실패: {str(e)}")
            traceback.print_exc()
        finally:
            self.pipeline = None
            self.config = None
        print("카메라 쓰레드 종료")

# 전역 카메라 쓰레드 인스턴스
camera_thread = CameraThread() 