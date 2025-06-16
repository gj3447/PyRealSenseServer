import pyrealsense2 as rs
import json
import time
from pathlib import Path
from datetime import datetime

def get_camera_parameters():
    """RealSense 카메라의 모든 파라미터 정보를 가져옴"""
    try:
        # RealSense 컨텍스트 초기화
        ctx = rs.context()
        devices = ctx.query_devices()
        
        if len(devices) == 0:
            print("❌ RealSense 카메라를 찾을 수 없습니다.")
            return None
            
        # 첫 번째 장치 선택
        device = devices[0]
        
        # 기본 장치 정보
        device_info = {
            "name": device.get_info(rs.camera_info.name),
            "serial_number": device.get_info(rs.camera_info.serial_number),
            "usb_type": device.get_info(rs.camera_info.usb_type_descriptor),
            "firmware_version": device.get_info(rs.camera_info.firmware_version),
            "product_id": device.get_info(rs.camera_info.product_id),
            "product_line": device.get_info(rs.camera_info.product_line)
        }
        
        # 파이프라인 설정
        pipeline = rs.pipeline()
        config = rs.config()
        
        # 먼저 장치가 사용 가능한지 확인
        try:
            config.enable_device(device_info['serial_number'])
        except Exception as e:
            print(f"❌ 장치 활성화 실패: {str(e)}")
            return None
            
        # 스트림 설정 전에 지원 가능한 포맷인지 확인
        try:
            # 스트림 활성화
            config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 5)
            config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 5)
        except Exception as e:
            print(f"❌ 스트림 설정 실패: {str(e)}")
            return None
            
        # 파이프라인 시작 전 대기
        time.sleep(2)
        
        try:
            # 파이프라인 시작
            profile = pipeline.start(config)
        except Exception as e:
            print(f"❌ 파이프라인 시작 실패: {str(e)}")
            return None
        
        # 센서 정보 가져오기
        depth_sensor = profile.get_device().first_depth_sensor()
        color_sensor = profile.get_device().first_color_sensor()
        
        # 스트림 프로파일 가져오기
        depth_profile = profile.get_stream(rs.stream.depth).as_video_stream_profile()
        color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
        
        # Intrinsics 정보
        depth_intrinsics = depth_profile.get_intrinsics()
        color_intrinsics = color_profile.get_intrinsics()
        
        # Extrinsics 정보
        depth_to_color_extrinsics = depth_profile.get_extrinsics_to(color_profile)
        
        # 전체 파라미터 정보 구성
        parameters = {
            "device_info": device_info,
            "timestamp": datetime.now().isoformat(),
            "depth_scale": depth_sensor.get_depth_scale(),
            "color_intrinsics": {
                "width": color_intrinsics.width,
                "height": color_intrinsics.height,
                "ppx": color_intrinsics.ppx,
                "ppy": color_intrinsics.ppy,
                "fx": color_intrinsics.fx,
                "fy": color_intrinsics.fy,
                "model": str(color_intrinsics.model),
                "coeffs": list(color_intrinsics.coeffs)
            },
            "depth_intrinsics": {
                "width": depth_intrinsics.width,
                "height": depth_intrinsics.height,
                "ppx": depth_intrinsics.ppx,
                "ppy": depth_intrinsics.ppy,
                "fx": depth_intrinsics.fx,
                "fy": depth_intrinsics.fy,
                "model": str(depth_intrinsics.model),
                "coeffs": list(depth_intrinsics.coeffs)
            },
            "depth_to_color_extrinsics": {
                "rotation": list(depth_to_color_extrinsics.rotation),
                "translation": list(depth_to_color_extrinsics.translation)
            }
        }
        
        # 파이프라인 정리
        pipeline.stop()
        
        return parameters
        
    except Exception as e:
        print(f"❌ 에러 발생: {str(e)}")
        return None

def save_parameters_to_json(parameters, filename=None):
    """파라미터 정보를 JSON 파일로 저장"""
    if parameters is None:
        print("저장할 파라미터 정보가 없습니다.")
        return False
        
    if filename is None:
        # 시리얼 번호와 현재 시간으로 파일명 생성
        serial = parameters['device_info']['serial_number']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"camera_parameters_{serial}_{timestamp}.json"
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(parameters, f, indent=2, ensure_ascii=False)
        print(f"✅ 파라미터 정보가 '{filename}'에 저장되었습니다.")
        return True
    except Exception as e:
        print(f"❌ 파일 저장 중 에러 발생: {str(e)}")
        return False

def main():
    print("\n" + "="*50)
    print("RealSense 카메라 파라미터 테스트")
    print("="*50 + "\n")
    
    # 파라미터 정보 가져오기
    print("1. 카메라 파라미터 정보 가져오는 중...")
    parameters = get_camera_parameters()
    
    if parameters:
        print("\n2. 파라미터 정보를 JSON 파일로 저장 중...")
        save_parameters_to_json(parameters)
    
    print("\n완료!")

if __name__ == "__main__":
    main()
