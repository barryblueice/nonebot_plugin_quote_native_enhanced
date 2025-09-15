from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
import os,requests
from nonebot.adapters.onebot.v11 import Bot

env = Environment(loader=FileSystemLoader(os.path.dirname(os.path.abspath(__file__))))
template = env.get_template('template.html')

async def generate_emulating_native_qq_style_image(userid: int, groupid: int, fontpath: str,  raw_message: list, bot: Bot, multimessage = False, max_width=600, scale=3) -> bytes:

    
    msglist = []
    for i in raw_message:
        if i["type"] == "text":
            msglist.append([i["type"], i["data"]["text"]])
        elif i["type"] == "image":
            msglist.append([i["type"], f'<img src="{i["data"]["url"]}" alt="image">'])
        elif i["type"] == "at":
            response = await bot.call_api('get_group_member_info', **{
                'group_id': groupid,
                'user_id': i["data"]["qq"]
            })
            msglist.append(["text",f"@{response['card_or_nickname']} "])

    raw_message = msglist

    response = await bot.call_api('get_group_member_info', **{
                'group_id': groupid,
                'user_id': userid
            })

    if not multimessage:
        data = {
            "messages": [
                {
                    "username": response['card_or_nickname'],
                    "level": int(response['level']),
                    "user_type": response['role'],
                    "avatar": f"https://q.qlogo.cn/g?b=qq&nk={userid}&s=640",
                    "title": response['title'],
                    "message": ""
                }
            ],
            "font_path": fontpath
            }
        for i in raw_message:
            # data['messages'].append({
            #     "username": response['card_or_nickname'],
            #     "level": int(response['level']),
            #     "user_type": response['role'],
            #     "avatar": f"https://q.qlogo.cn/g?b=qq&nk={userid}&s=640",
            #     "message": i[1]
            #     })
            data["messages"][0]["message"] += i[1]

    html_content = template.render(**data)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': max_width, 'height': 100}, device_scale_factor=scale)

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

        img = await page.screenshot()
        await browser.close()
        return img
