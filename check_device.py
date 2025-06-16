import pyrealsense2 as rs
import numpy as np
import cv2
import time
import os
from datetime import datetime

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"✓ 디렉토리 생성됨: {directory}")

def save_frame_to_image(frame, frame_type, image_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if frame_type == "color":
        # 컬러 이미지 처리
        color_image = np.asanyarray(frame.get_data())
        filename = os.path.join(image_dir, f"color_{timestamp}.png")
        cv2.imwrite(filename, color_image)
        print(f"✓ 컬러 이미지 저장됨: {filename}")
        return color_image
    else:
        # 깊이 이미지 처리
        depth_image = np.asanyarray(frame.get_data())
        # 깊이 이미지를 시각화 (0-65535를 0-255로 변환)
        depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)
        filename = os.path.join(image_dir, f"depth_{timestamp}.png")
        cv2.imwrite(filename, depth_colormap)
        print(f"✓ 깊이 이미지 저장됨: {filename}")
        return depth_colormap

def check_realsense_info():
    print("\n📷 RealSense 장치 검색 중...")
    
    try:
        # RealSense 컨텍스트 생성
        ctx = rs.context()
        devices = ctx.query_devices()
        
        if len(devices) == 0:
            print("❌ RealSense 카메라를 찾을 수 없습니다.")
            return
            
        # 발견된 모든 장치 정보 출력
        for i, dev in enumerate(devices):
            print(f"\n[장치 {i+1}]")
            print(f"모델명: {dev.get_info(rs.camera_info.name)}")
            print(f"시리얼: {dev.get_info(rs.camera_info.serial_number)}")
            print(f"펌웨어: {dev.get_info(rs.camera_info.firmware_version)}")
            print("\n[USB 정보]")
            print(f"포트 ID: {dev.get_info(rs.camera_info.physical_port)}")
            print(f"USB 타입: {dev.get_info(rs.camera_info.usb_type_descriptor)}")
            
            # 추가 정보 시도
            try:
                print(f"USB 설명: {dev.get_info(rs.camera_info.debug_op_code)}")
            except:
                pass
                
        print("\n[파이프라인 테스트]")
        # 파이프라인 설정
        pipeline = rs.pipeline()
        config = rs.config()
        
        print("1. 설정 적용 중...")
        config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
        
        print("2. 파이프라인 시작 시도...")
        profile = pipeline.start(config)
        print("✅ 파이프라인 시작 성공")
        
        # 이미지 저장 디렉토리 생성
        image_dir = "images"
        ensure_dir(image_dir)
        
        print("3. 프레임 수신 및 이미지 저장...")
        # 처음 몇 프레임은 건너뛰기 (카메라 안정화)
        for _ in range(5):
            pipeline.wait_for_frames()
            time.sleep(0.1)
            
        # 실제 캡처 및 저장
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        depth_frame = frames.get_depth_frame()
        
        if color_frame and depth_frame:
            # 이미지 저장 및 디스플레이용 이미지 얻기
            color_image = save_frame_to_image(color_frame, "color", image_dir)
            depth_image = save_frame_to_image(depth_frame, "depth", image_dir)
            
            # 이미지 표시 (선택사항)
            cv2.namedWindow('Color', cv2.WINDOW_AUTOSIZE)
            cv2.namedWindow('Depth', cv2.WINDOW_AUTOSIZE)
            cv2.imshow('Color', color_image)
            cv2.imshow('Depth', depth_image)
            print("\n이미지 확인을 위해 아무 키나 누르세요...")
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        
        print("\n4. 파이프라인 정상 종료 중...")
        pipeline.stop()
        print("✅ 모든 테스트 완료")
                
    except Exception as e:
        print(f"\n❌ 에러 발생: {str(e)}")
        print(f"에러 타입: {type(e).__name__}")
        if 'pipeline' in locals():
            try:
                pipeline.stop()
            except:
                pass

if __name__ == "__main__":
    check_realsense_info() 