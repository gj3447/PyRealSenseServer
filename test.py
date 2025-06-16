import pyrealsense2 as rs

def list_realsense_devices():
    # Context 생성
    ctx = rs.context()
    devices = ctx.query_devices()
    
    if not devices:
        print("⚠️  No Intel RealSense devices found.")
        return

    for i, dev in enumerate(devices):
        name     = dev.get_info(rs.camera_info.name)
        serial   = dev.get_info(rs.camera_info.serial_number)
        pid      = dev.get_info(rs.camera_info.product_id)
        firmware = dev.get_info(rs.camera_info.firmware_version)
        usb_type = dev.get_info(rs.camera_info.usb_type_descriptor)

        print(f"Device {i}: {name}")
        print(f"  · Serial Number : {serial}")
        print(f"  · Product ID    : {pid}")
        print(f"  · Firmware Ver. : {firmware}")
        print(f"  · USB Type      : {usb_type}")
        print("-" * 40)

if __name__ == "__main__":
    list_realsense_devices()