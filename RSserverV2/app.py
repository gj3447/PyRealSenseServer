from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from dependencies import get_camera_service
from routers import api, web
from settings import get_settings
from service.pipeline_service import PipelineService
from service.camera_service import CameraService

# DDNS 설정
DDNS_URL = "http://fouronesystem.asuscomm.com:19000"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 서비스 초기화
    settings = get_settings()
    pipeline_service = PipelineService(settings)
    camera_service = CameraService(pipeline_service)
    camera_service.start()
    yield
    # 종료 시 카메라 서비스 정리
    camera_service.stop()

app = FastAPI(lifespan=lifespan)

# 정적 파일과 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        DDNS_URL,
        "*"  # 개발 중에는 모든 origin 허용
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(web.router)  # 웹 페이지 라우터
app.include_router(api.router)  # API 라우터

# 상태 체크 엔드포인트
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request
    })

@app.get("/camera/color")
async def color_page(request: Request):
    settings = get_settings()
    return templates.TemplateResponse("color.html", {
        "request": request,
        "width": settings.RS_WIDTH,
        "height": settings.RS_HEIGHT,
        "fps": settings.RS_FPS
    })
