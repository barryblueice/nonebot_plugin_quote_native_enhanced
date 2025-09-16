def detect_image_format(data: bytes) -> str:
    # print(' '.join(f'{b:02X}' for b in data[:8]))
    if not data:
        return "png"

    # GIF
    if data.startswith(b'\x47\x49\x46\x38'):  # 'GIF8'
        return "gif"

    # PNG
    elif data.startswith(b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'):  # PNG
        return "png"

    else:
        return 'png'