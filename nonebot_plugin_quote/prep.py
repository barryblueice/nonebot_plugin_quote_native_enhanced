import ujson as json
from paddleocr import PaddleOCR
from .config import Config, check_font
from nonebot import get_driver
from nonebot.rule import to_me
import os
from nonebot.log import logger
from .task import inverted2forward

ocr = PaddleOCR(use_angle_cls=True, lang='ch')
try:
    import numpy as np
    dummy = np.zeros((100,100,3), dtype=np.uint8)
    ocr.predict(dummy)
except Exception:
    pass

plugin_config = Config.model_validate(get_driver().config.model_dump())
plugin_config.global_superuser = list({*plugin_config.global_superuser, *plugin_config.superusers})

need_at = {}
if (plugin_config.quote_needat):
    need_at['rule'] = to_me()

record_dict = {}
inverted_index = {}
quote_path = plugin_config.quote_path
emulating_font_path = plugin_config.emulating_font_path

# 判断参数配置情况
if quote_path == 'quote':
    quote_path = './data'
    logger.warning('未配置quote文件路径，使用默认配置: ./data')
os.makedirs(quote_path, exist_ok=True)

if not check_font(emulating_font_path):
    logger.warning('未配置字体路径，部分功能无法使用')
    
# 首次运行时导入表
try:
    with open(plugin_config.record_path, 'r', encoding='UTF-8') as fr:
        record_dict = json.load(fr)

    with open(plugin_config.inverted_index_path, 'r', encoding='UTF-8') as fi:
        inverted_index = json.load(fi)
    logger.info('nonebot_plugin_quote路径配置成功')
except Exception as e:
    with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
        json.dump(record_dict, f, indent=4, ensure_ascii=False)

    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as fc:
        json.dump(inverted_index, fc, indent=4, ensure_ascii=False)
    logger.warning('已创建json文件')

# 运行前去除数据中的重复内容
try:
    for i in record_dict:
        record_dict[i] = list(set(record_dict[i]))
    with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
        json.dump(record_dict, f, indent=4, ensure_ascii=False)

    for i in inverted_index:
        for j in inverted_index[i]:
            inverted_index[i][j] = list(set(inverted_index[i][j]))
    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as f:
        json.dump(inverted_index, f, indent=4, ensure_ascii=False)
    logger.info('已去除语录数据库中的重复内容')
except Exception as e:
    logger.error(f'错误: {e}! ')

# 运行前将绝对路径修改为相对路径
try:
    for i in record_dict:
        for idx, val in enumerate(record_dict[i]):
            record_dict[i][idx] = os.path.basename(val)
    with open(plugin_config.record_path, 'w', encoding='UTF-8') as f:
        json.dump(record_dict, f, indent=4, ensure_ascii=False)

    for i in inverted_index:
        for j in inverted_index[i]:
            for idx, val in enumerate(inverted_index[i][j]):
                inverted_index[i][j][idx] = os.path.basename(val)
    with open(plugin_config.inverted_index_path, 'w', encoding='UTF-8') as f:
        json.dump(inverted_index, f, indent=4, ensure_ascii=False)
    logger.info('已去除语录数据库中的绝对路径内容')
except Exception as e:
    logger.error(f'错误: {e}! ')

forward_index = inverted2forward(inverted_index)

