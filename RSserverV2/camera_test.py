import pyrealsense2 as rs

# Create a pipeline
pipeline = rs.pipeline()
config = rs.config()

# Add the same configuration as the server
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

try:
    # Start streaming
    pipeline.start(config)
    print("카메라가 성공적으로 연결되었습니다!")
    
    # Get a few frames to make sure everything is working
    for i in range(3):
        frames = pipeline.wait_for_frames(timeout_ms=5000)
        print(f"프레임 {i+1} 수신 성공")
    
except Exception as e:
    print(f"에러 발생: {str(e)}")
finally:
    pipeline.stop() 