from pydantic import BaseModel, Extra
from typing import List, Dict


class Config(BaseModel, extra=Extra.ignore):
    record_path: str = 'record.json'
    inverted_index_path: str = 'inverted_index.json'
    quote_superuser: Dict[str, List[str]] = {}
    global_superuser: List[str] = []
    superusers: set[str]
    quote_needat: bool = True
    quote_startcmd: str = ''
    quote_path: str = 'quote'
    emulating_font_path: str = ''

def check_font(emulating_font_path):
    # 判断字体是否配置
    return not (emulating_font_path == '')