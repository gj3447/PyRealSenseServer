import numpy as np
import pyrealsense2 as rs
from service.pipeline_service import PipelineService

class PointcloudService:
    def __init__(self, pipeline_service: PipelineService):
        self.pipeline_service = pipeline_service
        self.pc = rs.pointcloud()
        
    def get_pointcloud(self):
        frames = self.pipeline_service.get_frames()
        if not frames["depth"] or not frames["color"]:
            return None
            
        # 포인트 클라우드 생성
        points = self.pc.calculate(frames["depth"])
        # 텍스처 매핑
        self.pc.map_to(frames["color"])
        
        # 버텍스 좌표를 numpy 배열로 변환
        vertices = np.asanyarray(points.get_vertices())
        # 텍스처 좌표를 numpy 배열로 변환
        texture = np.asanyarray(points.get_texture_coordinates())
        
        return {
            "vertices": vertices,
            "texture": texture
        }
