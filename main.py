import pyrealsense2 as rs
import numpy as np
import cv2
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, Response
import uvicorn
import threading
import time
import io

app = FastAPI()

# 파이프라인, 설정 전역 선언 (하지만 start는 나중에!)
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

align = rs.align(rs.stream.color)

lock = threading.Lock()
latest_frames = {
    "color": None,
    "depth": None,
    "pointcloud": None
}

def capture_frames():
    # 여기서야 pipeline.start(config) 호출
    try:
        pipeline.start(config)
        print("✅ pipeline started!")
    except RuntimeError as e:
        print("🚨 RealSense start error:", e)
        return
    
    while True:
        try:
            frames = pipeline.wait_for_frames()
            aligned_frames = align.process(frames)
            color_frame = aligned_frames.get_color_frame()
            depth_frame = aligned_frames.get_depth_frame()

            if not depth_frame or not color_frame:
                continue

            color_image = np.asanyarray(color_frame.get_data())
            depth_colormap = cv2.applyColorMap(
                cv2.convertScaleAbs(np.asanyarray(depth_frame.get_data()), alpha=0.03),
                cv2.COLORMAP_JET
            )

            pc = rs.pointcloud()
            points = pc.calculate(depth_frame)
            #points.export_to_ply("temp_pointcloud.ply", color_frame)

            with lock:
                latest_frames["color"] = color_image
                latest_frames["depth"] = depth_colormap
                latest_frames["pointcloud"] = "temp_pointcloud.ply"

        except Exception as e:
            print("⚠️ Frame capture error:", e)
        
        time.sleep(0.03)

@app.on_event("startup")
def on_startup():
    # FastAPI가 뜨는 순간 백그라운드 스레드 시작
    threading.Thread(target=capture_frames, daemon=True).start()

@app.get("/")
def index():
    return HTMLResponse("""
        <h1>Intel RealSense Streaming</h1>
        <ul>
            <li><a href='/color'>Color Stream</a></li>
            <li><a href='/depth'>Depth Stream</a></li>
            <li><a href='/pointcloud'>Download Point Cloud (.ply)</a></li>
        </ul>
    """)

def generate_video_stream(frame_type):
    while True:
        with lock:
            frame = latest_frames.get(frame_type)
            if frame is None:
                continue
            ret, jpeg = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.get("/color")
def stream_color():
    return StreamingResponse(generate_video_stream("color"), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/depth")
def stream_depth():
    return StreamingResponse(generate_video_stream("depth"), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/pointcloud")
def download_pointcloud():
    with lock:
        ply_path = latest_frames["pointcloud"]
        if ply_path is None:
            return Response(content="No pointcloud available", status_code=404)
        with open(ply_path, "rb") as f:
            data = f.read()
    return Response(content=data, media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename=pointcloud.ply"})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
