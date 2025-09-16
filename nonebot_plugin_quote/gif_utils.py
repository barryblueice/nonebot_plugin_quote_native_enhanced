from PIL import Image, ImageSequence
import io



def load_gif_from_bytes(gif_bytes: bytes, target_width: int, target_height: int):
    """
    将字节数据加载为gif
    """
    gif = Image.open(io.BytesIO(gif_bytes))
    frames, durations = [], []
    for frame in ImageSequence.Iterator(gif):
        frame = frame.convert("RGBA")
        # 缩放到指定大小
        frame = frame.resize((target_width, target_height), resample=Image.Resampling.LANCZOS)
        frames.append(frame)
        durations.append(frame.info.get("duration", 100))
    return frames, durations

def overlay_gifs(base_image: Image.Image, gifs_with_pos):
    """
    返回合成后的帧列表
    """
    max_frames = max(len(frames) for frames, _, _ in gifs_with_pos)

    all_frames = []
    for i in range(max_frames):
        canvas = base_image.copy().convert("RGBA")
        for frames, durations, pos in gifs_with_pos:
            frame = frames[i % len(frames)]
            canvas.paste(frame, pos, frame)
        all_frames.append(canvas)
    return all_frames

def save_gif(frames, output:bool,path: str, durations=None):
    """
    保存最终 GIF
    """
    if not durations:
        durations = [100] * len(frames)
    if output:
        # 创建一个内存中的字节流，用于保存 GIF 数据
        gif_bytes_io = io.BytesIO()
        # 将 GIF 保存到内存中
        frames[0].save(
            gif_bytes_io,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            loop=0,
            duration=durations,
            disposal=2
        )
        # 获取二进制数据
        gif_binary = gif_bytes_io.getvalue()
        # 可选：关闭字节流
        gif_bytes_io.close()
        return gif_binary
    else:
        # 保存到文件
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            loop=0,
            duration=durations,
            disposal=2
        )
        return None  # 或者不写 return，默认返回 None