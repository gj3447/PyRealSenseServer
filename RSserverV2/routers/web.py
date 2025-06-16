from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from settings import get_settings

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="templates")

@router.get("/")
async def root(request: Request):
    """메인 페이지 렌더링"""
    return templates.TemplateResponse("index.html", {
        "request": request
    })

@router.get("/web/color_stream")
async def color_page(request: Request):
    """컬러 스트림 페이지 렌더링"""
    settings = get_settings()
    return templates.TemplateResponse("color.html", {
        "request": request,
        "width": settings.RS_WIDTH,
        "height": settings.RS_HEIGHT,
        "fps": settings.RS_FPS
    }) 