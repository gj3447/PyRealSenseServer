from fastapi import Depends
from functools import lru_cache
from typing import Annotated

from service.pipeline_service import PipelineService
from service.camera_service import CameraService
from service.pointcloud_service import PointcloudService
from settings import Settings, get_settings

@lru_cache
def get_pipeline_service(settings: Annotated[Settings, Depends(get_settings)]) -> PipelineService:
    return PipelineService(settings)

@lru_cache
def get_camera_service(pipeline_service: Annotated[PipelineService, Depends(get_pipeline_service)]) -> CameraService:
    return CameraService(pipeline_service)

@lru_cache
def get_pointcloud_service(pipeline_service: Annotated[PipelineService, Depends(get_pipeline_service)]) -> PointcloudService:
    return PointcloudService(pipeline_service) 