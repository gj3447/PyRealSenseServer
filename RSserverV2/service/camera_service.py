from service.pipeline_service import PipelineService
import logging
import asyncio
from datetime import datetime
import threading
import time

logger = logging.getLogger(__name__)

class CameraService:
    def __init__(self, pipeline_service: PipelineService):
        self.pipeline_service = pipeline_service
        self._started = False
        self._capture_thread = None
        self._stop_flag = False
        self.current_frame = None
        self.last_frame_time = None
        self.frame_count = 0
        self.error_count = 0
    
    def get_status(self):
        """카메라 서비스의 현재 상태를 반환"""
        pipeline_status = self.pipeline_service.get_status()
        thread_status = "running" if (self._capture_thread and self._capture_thread.is_alive()) else "stopped"
        return {
            "camera_service_running": self._started,
            "thread_status": thread_status,
            "pipeline_status": pipeline_status,
            "frame_count": self.frame_count,
            "error_count": self.error_count,
            "last_frame_time": self.last_frame_time.strftime('%Y-%m-%d %H:%M:%S.%f') if self.last_frame_time else None
        }
    
    def _capture_loop(self):
        """프레임 캡처 루프 - 별도 스레드에서 실행"""
        logger.info("프레임 캡처 루프 시작")
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5
        
        while not self._stop_flag:
            try:
                frames = self.pipeline_service.get_frames()
                if frames and frames["color"] is not None:
                    self.current_frame = frames
                    self.last_frame_time = datetime.now()
                    self.frame_count += 1
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    self.error_count += 1
                    logger.warning(f"프레임 없음 (연속 {consecutive_errors}회)")
                    
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"연속 {MAX_CONSECUTIVE_ERRORS}회 프레임 수신 실패")
                    self.stop()  # 서비스 중지
                    break
                    
                time.sleep(1/30)  # ~30 FPS
                
            except Exception as e:
                consecutive_errors += 1
                self.error_count += 1
                logger.error(f"프레임 캡처 중 오류: {str(e)}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("연속 오류 한계 초과, 서비스 중지")
                    self.stop()
                    break
    
    def start(self):
        if not self._started:
            # 이미 실행 중인 쓰레드가 있다면 종료
            if self._capture_thread and self._capture_thread.is_alive():
                logger.warning("이전 캡처 쓰레드가 아직 실행 중, 종료 시도...")
                self._stop_flag = True
                self._capture_thread.join(timeout=5)
            
            logger.info("카메라 서비스 시작...")
            self.pipeline_service.start()
            self._stop_flag = False
            self._capture_thread = threading.Thread(target=self._capture_loop)
            self._capture_thread.daemon = True
            self._capture_thread.start()
            self._started = True
            logger.info("✅ 카메라 서비스 시작됨")
    
    def stop(self):
        if self._started:
            logger.info("카메라 서비스 중지 중...")
            self._stop_flag = True
            if self._capture_thread:
                self._capture_thread.join(timeout=5)
            self.pipeline_service.stop()
            self._started = False
            logger.info("🛑 카메라 서비스 중지됨")
    
    def get_frames(self):
        """현재 프레임 반환"""
        if not self._started:
            logger.warning("카메라 서비스가 시작되지 않음")
            return None
        return self.current_frame 