import io
import os
from typing import List, Dict

from PIL import Image  # Pillow
from jinja2 import Environment, FileSystemLoader
from nonebot.adapters.onebot.v11 import Bot
from playwright.async_api import async_playwright, Page, ElementHandle

from .gif_utils import load_gif_from_bytes, overlay_gifs, save_gif

env = Environment(loader=FileSystemLoader(os.path.dirname(os.path.abspath(__file__))))
template = env.get_template('template.html')


async def generate_emulating_native_qq_style_image(userid: int, groupid: int, fontpath: str, raw_message: list,
                                                   bot: Bot, multimessage=False, max_width=600, scale=3) -> bytes:
    raw_message = await convert_msg_list(raw_message, bot, groupid)

    response = await bot.call_api('get_group_member_info', **{
        'group_id': groupid,
        'user_id': userid
    })

    if not multimessage:
        data = {
            "messages": [
                {
                    "username": card_or_nickname(response),
                    "level": int(response['level']),
                    "user_type": response['role'],
                    "avatar": f"https://q.qlogo.cn/g?b=qq&nk={userid}&s=640",
                    "title": response['title'],
                    "message": raw_message
                }
            ],
            "font_path": fontpath
        }

    html_content = template.render(**data)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': max_width, 'height': 100}, device_scale_factor=scale)

        await enable_gif_detector(page, verbose=True)

        await page.set_content(html_content, wait_until='networkidle')

        dimensions = await page.evaluate('''() => {
            const wrapper = document.querySelector(".chat-wrapper");
            return {
                width: wrapper.scrollWidth,
                height: wrapper.scrollHeight
            };
        }''')

        actual_width = min(max(dimensions['width'], 300), max_width)
        await page.set_viewport_size({'width': int(actual_width), 'height': int(dimensions['height'])})

        img = await generate_img(page)
        await browser.close()
        return img


def card_or_nickname(response):
    return response.get("card") or response.get("nickname")


async def convert_msg_list(raw_message: list, bot: Bot, groupid: int):
    msg_list = []
    for item in raw_message:
        msg_type = item.get("type")
        data_content = item.get("data", {})
        if msg_type == "text":
            text = data_content.get("text", "")

            msg_list.append([msg_type, text])

        elif msg_type == "image":
            url = data_content.get("url", "")
            msg_list.append([msg_type, f"<img src='{url}' alt='image'>"])

        elif msg_type == "at":
            qq = data_content.get("qq", "")
            response = await bot.call_api('get_group_member_info', **{
                'group_id': groupid,
                'user_id': qq
            })
            msg_list.append(["text", f"<span style='color: #1E90FF;'>@{card_or_nickname(response)} </span>"])

        else:
            # 未知类型
            msg_list.append([msg_type, "未知类型"])
    return msg_list


async def process_gifs(gifs, page, background_bytes=None, background_path=None, output_gif="final.gif", output=True):
    if not gifs:
        return None

    if background_bytes:
        base_image = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
    elif background_path:
        base_image = Image.open(background_path).convert("RGBA")
    else:
        raise ValueError("必须提供 background_bytes 或 background_path")

    screenshot_width, screenshot_height = base_image.size

    # 计算缩放比例（根据页面实际内容尺寸和渲染尺寸）
    css_width = int(await page.evaluate("document.querySelector('.chat-wrapper').scrollWidth"))
    css_height = int(await page.evaluate("document.querySelector('.chat-wrapper').scrollHeight"))
    scale_x = screenshot_width / css_width
    scale_y = screenshot_height / css_height

    gifs_with_pos = []
    for g in gifs:
        x = int(g["x"] * scale_x)
        y = int(g["y"] * scale_y)
        width = int(g["width"] * scale_x)
        height = int(g["height"] * scale_y)

        frames, durations = load_gif_from_bytes(g["bytes"], width, height)
        gifs_with_pos.append((frames, durations, (x, y)))

    final_frames = overlay_gifs(base_image, gifs_with_pos)
    return save_gif(final_frames, output, output_gif)


async def generate_img(page):
    elements = await page.query_selector_all("img[data-gif='true']")
    if elements:
        gifs = []
        for el in elements:
            src = await el.get_attribute("src")
            box = await el.bounding_box()

            await el.evaluate("(node) => node.style.opacity = '0'")

            try:
                response = await page.request.get(src)
                if response.ok:
                    gif_bytes = await response.body()
                    gifs.append({
                        "bytes": gif_bytes,
                        "x": box["x"],
                        "y": box["y"],
                        "width": box["width"],
                        "height": box["height"]
                    })
                else:
                    #TO_DO 改为真寻日志
                    print(f"❌图片加载失败，状态码：{response.status}, src: {src}")
            except Exception as e:
                # TO_DO 改为真寻日志
                print(f"❌获取图片出错：{e}, src: {src}")

        screenshot_bytes = await page.screenshot(full_page=False)

        return await process_gifs(gifs, page, background_bytes=screenshot_bytes, output=True)
    else:

        return await page.screenshot(full_page=False)


async def enable_gif_detector(page: Page, verbose: bool = False):
    """
    使用playwright拦截请求，并分析响应体检测是否为动图
    """

    img_map: Dict[str, List[ElementHandle]] = {}

    def is_animated_image(data: bytes) -> bool:
        # GIF
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return b"\x00\x21\xF9\x04" in data and data.count(b"\x00\x2C") > 1
        # WebP
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return b"ANIM" in data
        # APNG，严格检测 acTL 在 IHDR 之后
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            ihdr_index = data.find(b'IHDR')
            actl_index = data.find(b'acTL')
            if ihdr_index != -1 and actl_index != -1 and actl_index > ihdr_index:
                return True
        return False

    async def handle_request(request):
        if request.resource_type == "image":
            url = request.url
            # print(url)
            imgs = await page.query_selector_all(f'img[src="{url}"]')
            if imgs:
                img_map[url] = imgs

    async def handle_response(resp):
        try:
            url = resp.url
            body = await resp.body()

            if is_animated_image(body) and url in img_map:
                for img in img_map[url]:
                    await img.evaluate("el => el.setAttribute('data-gif', 'true')")
                    if verbose:
                        outer_html = await img.evaluate("el => el.outerHTML")
                        # print(f"[GIF DETECTED] {url}\n{outer_html}\n")
        except Exception as e:
            raise TypeError("分析失败")

    page.on("request", handle_request)
    page.on("response", handle_response)
