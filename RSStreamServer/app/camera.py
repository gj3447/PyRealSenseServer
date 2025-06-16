import pyrealsense2 as rs
import numpy as np
import logging

logger = logging.getLogger(__name__)

class RealSenseCamera:
    def __init__(self, width=640, height=480, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self._started = False
        
        # Color 스트림 설정
        self.config.enable_stream(
            rs.stream.color,
            width,
            height,
            rs.format.bgr8,
            fps
        )
    
    def start(self):
        """카메라 시작"""
        if not self._started:
            try:
                logger.info("카메라 시작 중...")
                self.pipeline.start(self.config)
                self._started = True
                logger.info("✅ 카메라 시작됨")
                return True
            except Exception as e:
                logger.error(f"카메라 시작 실패: {str(e)}")
                return False
    
    def stop(self):
        """카메라 중지"""
        if self._started:
            try:
                self.pipeline.stop()
                self._started = False
                logger.info("카메라 중지됨")
            except Exception as e:
                logger.error(f"카메라 중지 실패: {str(e)}")
    
    def get_frame(self):
        """컬러 프레임 가져오기"""
        if not self._started:
            return None
            
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=5000)
            color_frame = frames.get_color_frame()
            
            if color_frame:
                return np.asanyarray(color_frame.get_data())
            return None
                
        except Exception as e:
            logger.error(f"프레임 가져오기 실패: {str(e)}")
            return None 