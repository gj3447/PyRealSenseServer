import pyrealsense2 as rs
from settings import get_settings, Settings
from fastapi import Depends
import numpy as np
import sys
import os
import logging
import traceback
from datetime import datetime
import time

# 로그 설정
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PipelineService:
    def __init__(self,
                 settings: Settings = Depends(get_settings)):
        self.settings = settings
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.error_count = 0
        self.total_frames_received = 0
        self.total_errors = 0
        self.last_frame_time = None
        self.status = "stopped"
        
        # Color stream 설정
        self.config.enable_stream(
            rs.stream.color,
            settings.RS_WIDTH,
            settings.RS_HEIGHT,
            rs.format.bgr8,
            settings.RS_FPS
        )
        
        self._started = False
        logger.info(f"PipelineService initialized: {settings.RS_WIDTH}x{settings.RS_HEIGHT} @ {settings.RS_FPS}fps")
    
    def get_status(self):
        """파이프라인의 현재 상태를 반환"""
        return {
            "is_running": self._started,
            "status": self.status,
            "error_count": self.error_count,
            "total_frames": self.total_frames_received,
            "total_errors": self.total_errors,
            "last_frame_time": self.last_frame_time.strftime('%Y-%m-%d %H:%M:%S.%f') if self.last_frame_time else None,
            "fps_setting": self.settings.RS_FPS,
            "resolution": f"{self.settings.RS_WIDTH}x{self.settings.RS_HEIGHT}"
        }
    
    def start(self):
        """파이프라인 시작"""
        if not self._started:
            try:
                logger.info("파이프라인 시작 시도...")
                self.pipeline.start(self.config)
                self._started = True
                self.status = "running"
                logger.info("파이프라인 시작됨")
            except Exception as e:
                self.status = "error"
                logger.error(f"파이프라인 시작 실패: {str(e)}")
                raise
    
    def stop(self):
        """파이프라인 중지"""
        if self._started:
            try:
                self.pipeline.stop()
                self._started = False
                self.status = "stopped"
                logger.info("파이프라인 중지됨")
            except Exception as e:
                logger.error(f"파이프라인 중지 실패: {str(e)}")
                raise
    
    def get_frames(self):
        """단일 프레임 세트 가져오기"""
        if not self._started:
            raise RuntimeError("파이프라인이 시작되지 않음")
            
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=5000)
            color_frame = frames.get_color_frame()
            
            if color_frame:
                self.error_count = 0
                self.total_frames_received += 1
                self.last_frame_time = datetime.now()
                return {
                    "color": np.asanyarray(color_frame.get_data()),
                    "depth": None,
                    "accel": None,
                    "gyro": None
                }
            else:
                self.error_count += 1
                self.total_errors += 1
                return None
                
        except Exception as e:
            self.error_count += 1
            self.total_errors += 1
            logger.error(f"프레임 가져오기 실패: {str(e)}")
            raise