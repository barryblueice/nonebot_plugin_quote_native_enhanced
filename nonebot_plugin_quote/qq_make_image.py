import io
import json
import os
from typing import List, Dict

from PIL import Image, ImageChops  # Pillow
from jinja2 import Environment, FileSystemLoader
from nonebot.adapters.onebot.v11 import Bot
from playwright.async_api import async_playwright, Page, ElementHandle

from .gif_utils import load_gif_from_bytes, overlay_gifs, save_gif

env = Environment(loader=FileSystemLoader(os.path.dirname(os.path.abspath(__file__))))
template = env.get_template('template.html')


async def generate_emulating_native_qq_style_image(userid: int, groupid: int, fontpath: str, raw_message: list,
                                                   bot: Bot, max_width=600, scale=3) -> bytes:


    messages = await convert_msg_list(raw_message, bot, groupid,userid)
    # print(messages)

    data = {
        "messages":messages,
        "font_path": fontpath
    }
    html_content = template.render(**data)


    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': max_width, 'height': 100}, device_scale_factor=scale)

        await enable_gif_detector(page, verbose=False)

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


async def convert_msg_list(raw_message: list, bot: Bot, groupid: int, userid: int):

    async def get_member_info(user_id):
        """获取群成员信息"""
        try:
            return await bot.call_api('get_group_member_info', group_id=groupid, user_id=user_id)
        except Exception:
            return {}

    def build_avatar(user_id: int) -> str:
        return f"https://q.qlogo.cn/g?b=qq&nk={user_id}&s=640"

    async def parse_text(data: dict):
        return ["text", data.get("text", "")]

    async def parse_image(data: dict, sub_forward: bool):
        if not sub_forward:
            url = data.get("url", "")
            return ["image", f"<img src='{url}' alt='image'>"]
        return ["image", data.get("summary", "[图片]")]

    async def parse_at(data: dict):
        qq = data.get("qq", "")
        if qq != 'all':
            resp = await get_member_info(qq)
            at_nickname = card_or_nickname(resp)
        else:
            at_nickname="全体成员"
        return ["text", f"<span style='color: #1E90FF;'>@{at_nickname} </span>"]

    async def parse_reply(data: dict, is_reply: bool, sub_forward: bool):
        if is_reply or sub_forward:
            return None
        reply_id = data.get("id", "")
        try:
            resp = await bot.call_api("get_msg", message_id=reply_id)
            reply_nickname = card_or_nickname(resp.get("sender", {}))
            reply_msg = await parse_message(resp.get("message"), is_reply=True)
            return ["reply", reply_msg, reply_nickname]
        except Exception:
            return None

    async def parse_forward(data: dict, sub_forward: bool):
        if sub_forward:
            return ["text", "[聊天记录]"]

        forward_content = data.get("content", [])
        msgs_forward = []
        for msg_forward in forward_content:
            nickname_forward = msg_forward.get("sender", {}).get("nickname", "未知发送者")
            try:
                item_forward = await parse_message(
                    msg_forward.get("message"),
                    nickname=nickname_forward,
                    is_forward=True,
                    sub_forward=True,
                )
                msgs_forward.append(item_forward)
            except Exception as e:
                print(f"解析转发消息时出错: {e}")
                msgs_forward.append(["text", "[转发消息解析失败]"])
        return ["forward", msgs_forward, "群聊的聊天记录"]

    async def parse_json(data: dict, sub_forward: bool):
        """解析 type=json 的小程序/卡片消息"""
        data = json.loads(data.get("data"))
        detail = data.get("meta", {}).get("detail_1", {})



        title = detail.get("title", "卡片消息")
        desc = detail.get("desc", "")
        preview = detail.get("preview", "")
        icon = detail.get("icon", "")

        # 转发里的只显示简略
        if sub_forward:
            return ["text", f"[卡片消息] {title}"]

        # 返回统一格式
        return [
            "json",
            {
                "title": title,
                "desc": desc,
                "preview": preview,
                "icon": icon
            }
        ]

    async def parse_message(
            messages: list,
            user_id: int = 0,
            nickname: str = "",
            is_forward: bool = False,
            is_reply: bool = False,
            sub_forward: bool = False,
    ):
        msg_list = []

        for item in messages:
            msg_type = item.get("type")
            data = item.get("data", {})

            parser_map = {
                "text": parse_text,
                "image": lambda d=data: parse_image(d, sub_forward),
                "at": parse_at,
                "reply": lambda d=data: parse_reply(d, is_reply, sub_forward),
                "forward": lambda d=data: parse_forward(d, sub_forward),
                "face": lambda d=data: ["text", "[表情]", nickname],
                "json": lambda d=data: parse_json(d, sub_forward),
            }

            parser = parser_map.get(msg_type)
            if parser:
                result = await parser(data) if callable(parser) else parser
                if result:
                    msg_list.append(result)
            else:
                # print("未知类型:", msg_type, data)
                # msg_list.append(["未知", "未知类型"])
                if not is_forward and not sub_forward:
                    await bot.call_api('send_group_msg', **{
                        "group_id": groupid,
                        "message": [
                            {
                                "type": "text",
                                "data": {
                                    "text": "该类型不支持哦"
                                }
                            }
                        ]
                    })

                raise ValueError("未知类型",msg_type,data)

        if is_forward:
            return {
                "username": nickname,
                "avatar": build_avatar(user_id),
                "message": msg_list,
            }


        if is_reply:
            return msg_list


        resp = await get_member_info(user_id)
        return {
            "username": card_or_nickname(resp),
            "level": int(resp.get("level", 0)),
            "user_type": resp.get("role", ""),
            "avatar": build_avatar(user_id),
            "title": resp.get("title", ""),
            "message": msg_list,
        }



    if len(raw_message) == 1 and raw_message[0].get("type") == "forward":
        msg_id = raw_message[0]["data"].get("id")
        response = await bot.call_api("get_forward_msg", id=msg_id)
        # print("外层聊天记录回应:", response)

        return [
            await parse_message(
                msg.get("message"),
                user_id=msg.get("sender", {}).get("user_id", 0),  # ✅ 传 user_id
                nickname=msg.get("sender", {}).get("nickname", "未知发送者"),
                is_forward=True
            )
            for msg in response.get("messages", [])
        ]

    # 带 sender 的普通消息
    if raw_message[0].get("sender"):
        return [
            await parse_message(msg.get("message"), msg.get("sender", {}).get("user_id"))
            for msg in raw_message
        ]

    # 默认处理
    return [await parse_message(raw_message, userid)]


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
                    # print(f"❌图片加载失败，状态码：{response.status}, src: {src}")
                    raise ValueError(f"❌图片加载失败，状态码：{response.status}, src: {src}")
            except Exception as e:
                # TO_DO 改为真寻日志
                raise ValueError(f"❌获取图片出错：{e}, src: {src}")

        screenshot_bytes = await page.screenshot(full_page=False)

        return await process_gifs(gifs, page, background_bytes=screenshot_bytes, output=True)
    else:

        return await page.screenshot(full_page=False)


async def enable_gif_detector(page: Page, verbose: bool = False):
    """
    使用playwright拦截请求，并分析响应体检测是否为动图
    """

    img_map: Dict[str, List[ElementHandle]] = {}

    def is_gif_really_animated(data: bytes) -> bool:
        if data[:6] not in (b"GIF87a", b"GIF89a"):
            return False  # 不是 GIF

        img = Image.open(io.BytesIO(data))
        n_frames = getattr(img, "n_frames", 1)

        # 单帧 GIF
        if n_frames <= 1:
            return False

        prev_frame = None
        has_animation = False

        for i in range(n_frames):
            img.seek(i)
            duration = img.info.get("duration", 0)
            frame = img.convert("RGB")

            if prev_frame is not None:
                diff = ImageChops.difference(prev_frame, frame)
                if diff.getbbox() and duration > 0:
                    has_animation = True
                    break

            prev_frame = frame

        return has_animation

    # 单帧或假动图转换为 PNG
    def convert_gif_to_png(data: bytes) -> bytes | None:
        img = Image.open(io.BytesIO(data))
        n_frames = getattr(img, "n_frames", 1)

        if n_frames == 1 or not is_gif_really_animated(data):
            output = io.BytesIO()
            img.save(output, format="PNG")
            return output.getvalue()
        return None

    async def is_animated_image(resp, data: bytes) -> bool:
        # GIF
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return data.count(b"\x00\x2C") > 1
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
            status = resp.status

            # 跳过重定向响应
            if 300 <= status < 400:
                return

            body = await resp.body()

            if await is_animated_image(resp,body):
                # 匹配原始请求 URL 或 最终 URL
                if url in img_map:
                    targets = img_map[url]
                else:
                    # 如果没找到，可以尝试根据 src 重新找
                    targets = await page.query_selector_all(f'img[src="{url}"]')
                for img in targets:
                    # print("断点3", img)
                    await img.evaluate("el => el.setAttribute('data-gif', 'true')")
                    if verbose:
                        outer_html = await img.evaluate("el => el.outerHTML")
                        print(f"[GIF DETECTED] {url}\n{outer_html}\n")
        except Exception as e:
            raise TypeError("分析失败") from e

    async def handle_route(route, request):
        if request.resource_type == "image":
            resp = await route.fetch()
            body = await resp.body()

            png_data = convert_gif_to_png(body)
            if png_data:
                if verbose:
                    print(f"[STATIC GIF -> PNG] {request.url}")
                await route.fulfill(
                    status=200,
                    body=png_data,
                    headers={**resp.headers, "Content-Type": "image/png"}
                )
                return

            await route.fulfill(
                status=resp.status,
                body=body,
                headers=resp.headers
            )
        else:
            await route.continue_()

    await page.route("**/*", handle_route)
    page.on("request", handle_request)
    page.on("response", handle_response)
