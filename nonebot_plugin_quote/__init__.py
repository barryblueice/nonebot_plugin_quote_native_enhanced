from nonebot import on_command, on_keyword, on_startswith, get_driver, on_regex
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageEvent, PrivateMessageEvent, MessageSegment, exception, GroupMessageEvent
from nonebot.typing import T_State  
from nonebot.plugin import PluginMetadata
from nonebot_plugin_session import EventSession
import re
import ujson as json
import random
import os
import shutil
import asyncio
from .prep import plugin_config, need_at, quote_path, ocr, emulating_font_path, record_dict, inverted_index, forward_index, save_json
from .task import offer, query, delete, findAlltag, addTag, delTag
from .task import copy_images_files
from .config import Config, check_font
from nonebot.log import logger
import httpx
import hashlib
from .qq_make_image import generate_emulating_native_qq_style_image
from .task import reply_handle

# v0.4.3

__plugin_meta__ = PluginMetadata(
    name='群聊语录库',
    description='一款QQ群语录库——支持上传聊天截图为语录，随机投放语录，关键词搜索语录精准投放',
    usage='语录 上传 删除',
    type="application",
    homepage="https://github.com/RongRongJi/nonebot_plugin_quote",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        'author': 'RongRongJi',
        'version': 'v0.4.3',
    },
)

save_img = on_regex(pattern="^{}上传$".format(re.escape(plugin_config.quote_startcmd)), **need_at)

@save_img.handle()
async def save_img_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    message_id = event.message_id
    user_id = Session.id1

    global inverted_index
    global record_dict
    global forward_index
    
    if event.reply:
        raw_message = str(event.reply.message)
        match = re.search(r'file=([^,]+)', raw_message)
        if match:
            file_name = match.group(1).strip('"\'')
        else:
            await make_record.finish(MessageSegment.at(user_id) + MessageSegment.text(" 未检测到图片，请回复所需上传的图片消息来上传语录"))
    else:
        await make_record.finish(MessageSegment.at(user_id)+ MessageSegment.text(" 请回复所需上传的图片消息来上传语录"))

    try:
        resp = await bot.call_api('get_image', **{'file': file_name})
        image_path = resp['file']
        shutil.copy(image_path, os.path.join(quote_path, os.path.basename(image_path)))
    
    except Exception as e:
        logger.warning(f"bot.call_api 失败，可能在使用Lagrange，使用 httpx 进行下载: {e}")
        image_url = file_name
        match = re.search(r'filename=([^,]+)', raw_message)
        file_name = match.group(1).strip('"\'')
        async with httpx.AsyncClient() as client:
            image_url = image_url.replace('&amp;', '&')
            response = await client.get(image_url)
            if response.status_code == 200:
                image_path = os.path.join(quote_path, file_name)
                with open(image_path, "wb") as f:
                    f.write(response.content)
                resp = {"file": image_path}
            else:
                raise Exception("httpx 下载失败")
    
    image_path = os.path.abspath(os.path.join(quote_path, os.path.basename(image_path)))
    image_name = os.path.basename(image_path)
    logger.info(f"图片已保存到 {image_path}")
    loop = asyncio.get_running_loop()
    ocr_result = await loop.run_in_executor(None, ocr.predict, image_path)
    ocr_result = ocr_result[0]['rec_texts']
    try:
        ocr_result.remove('')
    except:
        pass
    ocr_result = list(set(ocr_result))
    ocr_content = ''
    try:
        for line in ocr_result:
            ocr_content += f"{line} "
    except Exception as e:
        ocr_content = ''
        logger.error(f"OCR识别失败: {e}")

    group_id = Session.id2

    inverted_index, forward_index = offer(group_id, image_name, ocr_content, inverted_index, forward_index)

    if group_id not in list(record_dict.keys()):
        record_dict[group_id] = [image_name]
    else:
        if image_name not in record_dict[group_id]:
            record_dict[group_id].append(image_name)

    save_json(record_dict, inverted_index)

    await save_img.finish(MessageSegment.reply(message_id)+MessageSegment.text('保存成功'))

record_pool = on_startswith('{}语录'.format(plugin_config.quote_startcmd), priority=2, block=True, **need_at)

@record_pool.handle()
async def record_pool_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    ats = False

    global inverted_index
    global record_dict

    search_info = str(event.get_message()).strip()
    search_info = search_info.replace('{}语录'.format(plugin_config.quote_startcmd), '').replace(' ', '')

    group_id = Session.id2

    for i in event.model_dump()['original_message']:
        if i['type'] == 'at':
            ats = i['data']['qq']
            break

    if ats:
        try:
            target_ats_list = []
            for i in record_dict[group_id]:
                if i.startswith(f"{ats}_"):
                    target_ats_list.append(i)
            length = len(target_ats_list)
            idx = random.randint(0, length - 1)
            msg = MessageSegment.image(file=os.path.abspath(os.path.join(quote_path, os.path.basename(target_ats_list[idx]))))
        except:
            length = len(record_dict[group_id])
            idx = random.randint(0, length - 1)
            msg = '当前查询无结果, 为您随机发送。'
            msg_segment = MessageSegment.image(file=os.path.abspath(os.path.join(quote_path, os.path.basename(record_dict[group_id][idx]))))
            msg = msg + msg_segment

    elif search_info == '':
        if group_id not in list(record_dict.keys()):
            msg = '当前无语录库'
        else:
            length = len(record_dict[group_id])
            idx = random.randint(0, length - 1)
            msg = MessageSegment.image(file=os.path.abspath(os.path.join(quote_path, os.path.basename(record_dict[group_id][idx]))))
    else:
        ret = query(search_info, group_id, inverted_index)

        if ret['status'] == -1:
            msg = '当前无语录库'
        elif ret['status'] == 2:
            if group_id not in list(record_dict.keys()):
                msg = '当前无语录库'
            else:
                length = len(record_dict[group_id])
                idx = random.randint(0, length - 1)
                msg = '当前查询无结果, 为您随机发送。'
                msg_segment = MessageSegment.image(file=os.path.abspath(os.path.join(quote_path, os.path.basename(record_dict[group_id][idx]))))
                msg = MessageSegment.text(msg) + msg_segment
        elif ret['status'] == 1:
            msg = MessageSegment.image(file=os.path.abspath(os.path.join(quote_path, os.path.basename(ret['msg']))))
        else:
            msg = ret.text

    await record_pool.finish(msg)


record_help = on_keyword({"语录"}, priority=10, rule=to_me())

@record_help.handle()
async def record_help_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):
    user_id = str(event.get_user_id())
    raw_msg = str(event.get_message())
    if '怎么用' not in raw_msg and '如何' not in raw_msg:
        await record_help.finish()

    msg = ''' 您可以通过回复指定图片, 发送【上传】指令上传语录。您也可以直接发送【语录】指令, 我将随机返回一条语录。'''

    await record_help.finish(MessageSegment.at(user_id) + MessageSegment.text(msg))

delete_record = on_regex(pattern=r'^{}删除$'.format(re.escape(plugin_config.quote_startcmd)), **need_at)

@delete_record.handle()
async def delete_record_handle(bot: Bot, event: Event, state: T_State, Session: EventSession):

    global inverted_index
    global record_dict
    global forward_index

    user_id = str(event.get_user_id())
    
    group_id = Session.id2
    if user_id not in plugin_config.global_superuser:
        if group_id not in plugin_config.quote_superuser or user_id not in plugin_config.quote_superuser[group_id]:  
            await delete_record.finish(MessageSegment.at(user_id) + MessageSegment.text(' 非常抱歉, 您没有删除权限TUT'))

    errMsg = ' 请回复需要删除的语录, 并输入删除指令'
    imgs = await reply_handle(bot, errMsg, event.model_dump(), group_id, user_id, delete_record)
    
    # 搜索
    is_Delete, record_dict, inverted_index, forward_index = delete(imgs, group_id, record_dict, inverted_index, forward_index)

    if is_Delete:
        save_json(record_dict, inverted_index)
        msg = ' 删除成功'
    else:
        msg = ' 该图不在语录库中'

    await delete_record.finish(message=MessageSegment.at(user_id) + MessageSegment.text(msg))


alltag = on_command('{}alltag'.format(plugin_config.quote_startcmd), aliases={'{}标签'.format(plugin_config.quote_startcmd), '{}tag'.format(plugin_config.quote_startcmd)}, **need_at)

@alltag.handle()
async def alltag_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    global inverted_index
    global record_dict
    global forward_index

    user_id = str(event.get_user_id())

    group_id = Session.id2

    errMsg = ' 请回复需要指定语录'
    imgs = await reply_handle(bot, errMsg, event.model_dump(), group_id, user_id, alltag)  
    tags = findAlltag(imgs, forward_index, group_id)
    if tags is None:
        msg = ' 该语录不存在'
    elif tags == set():
        msg = ' 该语录无Tag，请使用addtag手动添加Tag'
    else:
        msg = ' 该语录的所有Tag为: '
        n = 0
        for tag in tags:
            n += 1
            msg += f'\n{n}. {tag}'

    await alltag.finish(message=MessageSegment.at(user_id) + MessageSegment.text(msg))

addtag = on_regex(pattern="^{}addtag\ ".format(plugin_config.quote_startcmd), **need_at)

@addtag.handle()
async def addtag_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    global inverted_index
    global record_dict
    global forward_index
    user_id = str(event.get_user_id())
    tags = str(event.get_message()).replace('{}addtag'.format(plugin_config.quote_startcmd), '').strip().split(' ')

    group_id = Session.id2

    errMsg = ' 请回复需要指定语录'
    imgs = await reply_handle(bot, errMsg, event.model_dump(), group_id, user_id, addtag)

    flag, forward_index, inverted_index = addTag(tags, imgs, group_id, forward_index, inverted_index)
    save_json(record_dict, inverted_index)

    if flag is None:
        msg = ' 该语录不存在'
    else:
        msg = ' 已为该语录添加上{}标签'.format(tags)

    await addtag.finish(message=MessageSegment.at(user_id) + MessageSegment.text(msg))


deltag = on_regex(pattern="^{}deltag\ ".format(plugin_config.quote_startcmd), **need_at)

@deltag.handle()
async def deltag_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    global inverted_index
    global record_dict
    global forward_index
    user_id = str(event.get_user_id())
    tags = str(event.get_message()).replace('{}deltag'.format(plugin_config.quote_startcmd), '').strip().split(' ')

    group_id = Session.id2
    errMsg = ' 请回复需要指定语录'
    imgs = await reply_handle(bot, errMsg, event.model_dump(), group_id, user_id, deltag)

    flag, forward_index, inverted_index = delTag(tags, imgs, group_id, forward_index, inverted_index)
    save_json(record_dict, inverted_index)

    if flag is None:
        msg = ' 该语录不存在'
    else:
        msg = ' 已移除该语录的{}标签'.format(tags)
    await deltag.finish(message=MessageSegment.at(user_id) + MessageSegment.text(msg))


make_record = on_regex(pattern="^{}记录$".format(re.escape(plugin_config.quote_startcmd)))

@make_record.handle()
async def make_record_handle(bot: Bot, event: GroupMessageEvent, state: T_State, Session: EventSession):

    isimg = False
    group_id = Session.id2

    if not check_font(emulating_font_path):
        logger.warning('未配置字体路径，部分功能无法使用')
        await make_record.finish()

    global inverted_index
    global record_dict
    global forward_index

    if event.reply:
        size = 640
        qqid = event.reply.sender.user_id
        raw_message = event.reply.message.extract_plain_text().strip()
        card = event.reply.sender.card if event.reply.sender.card not in (None, '') else event.reply.sender.nickname
    else:
        await make_record.finish(" 请回复所需的消息")

    if str(qqid) == str(event.get_user_id()):
        await make_record.finish(" 不能记录自己的消息")

    if len(event.model_dump()['reply']['message']) != 0:
        msglist = []
        for i in event.model_dump()['reply']['message']:
            if i["type"] == "text":
                msglist.append([i["type"], i["data"]["text"]])
            elif i["type"] == "image":
                isimg = True
                msglist.append([i["type"], f'<img src="{i["data"]["url"]}" alt="image">'])
        img_data = await generate_emulating_native_qq_style_image(int(qqid), int(group_id), f"file:///{emulating_font_path}",  msglist, bot)
        image_name = f"{qqid}_{hashlib.md5(img_data).hexdigest()}.png"
        image_path = os.path.abspath(os.path.join(quote_path, os.path.basename(image_name)))
        with open(image_path, "wb") as file:
            file.write(img_data)
        loop = asyncio.get_running_loop()

        if isimg:
            ocr_result = await loop.run_in_executor(None, ocr.predict, image_path)
            ocr_result = ocr_result[0]['rec_texts']
            try:
                ocr_result.remove('')
            except:
                pass
            ocr_result = list(set(ocr_result))
            ocr_content = ''
            try:
                for line in ocr_result:
                    ocr_content += f"{line} "
            except Exception as e:
                ocr_content = ''
                logger.error(f"OCR识别失败: {e}")
            inverted_index, forward_index = offer(group_id, image_name, card + ' ' + ocr_content, inverted_index, forward_index)
        else:
            inverted_index, forward_index = offer(group_id, image_name, card + ' ' + raw_message, inverted_index, forward_index)

        if group_id not in list(record_dict.keys()):
            record_dict[group_id] = [image_name]
        else:
            if image_name not in record_dict[group_id]:
                record_dict[group_id].append(image_name)

        save_json(record_dict, inverted_index)

        msg = MessageSegment.image(img_data)
        await make_record.send(msg)
    else:
        await make_record.send('空内容')
    await make_record.finish()

render_quote = on_regex(pattern="^{}生成$".format(re.escape(plugin_config.quote_startcmd)))

@render_quote.handle()
async def render_quote_handle(bot: Bot, event: MessageEvent, state: T_State, Session: EventSession):

    group_id = Session.id2

    if not check_font(emulating_font_path):
        logger.warning('未配置字体路径，部分功能无法使用')
        await make_record.finish()

    global inverted_index
    global record_dict
    global forward_index

    if event.reply:
        size = 640
        qqid = event.reply.sender.user_id
        raw_message = event.reply.message.extract_plain_text().strip()
        card = event.reply.sender.card if event.reply.sender.card not in (None, '') else event.reply.sender.nickname
    else:
        await make_record.finish("请回复所需的消息")
    msglist = []
    for i in event.model_dump()['reply']['message']:
        if i["type"] == "text":
            msglist.append([i["type"], i["data"]["text"]])
        elif i["type"] == "image":
            msglist.append([i["type"], f'<img src="{i["data"]["url"]}" alt="image">'])
    img_data = await generate_emulating_native_qq_style_image(int(qqid), int(group_id), f"file:///{emulating_font_path}",  msglist, bot)

    image_name = f"{qqid}_{hashlib.md5(img_data).hexdigest()}.png"

    image_path = os.path.abspath(os.path.join(quote_path, os.path.basename(image_name)))

    with open(image_path, "wb") as file:
        file.write(img_data)

    inverted_index, forward_index = offer(group_id, image_name, card + ' ' + raw_message, inverted_index, forward_index)

    if group_id not in list(record_dict.keys()):
        record_dict[group_id] = [image_name]
    else:
        if image_name not in record_dict[group_id]:
            record_dict[group_id].append(image_name)

    save_json(record_dict, inverted_index)

    msg = MessageSegment.image(img_data)
    await make_record.finish(msg)