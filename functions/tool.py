import json
from typing import List, Optional, Tuple, NamedTuple
import astrbot.api.message_components as Comp
from astrbot.api import logger
from datetime import date
from pathlib import Path
import random
import base64
import tempfile
import asyncio
import sqlite3
import numpy as np

max_base64_size = 20 * 1024 * 1024 # 20MB的最大Base64文件大小

class DatabaseQuery:
    def __init__(self, db_path):
        """初始化时传入 .db 文件路径"""
        self.db_path = db_path
        self.connection = None

    def __enter__(self):
        """进入上下文时建立连接"""
        self.connection = sqlite3.connect(self.db_path)
        # 将结果映射为字典格式（可选，方便通过字段名取值）
        self.connection.row_factory = sqlite3.Row
        return self

    def query(self, sql, params=()):
        """
        执行查询语句
        :param sql: SQL 查询语句
        :param params: 查询参数（元组格式），防止 SQL 注入
        :return: 结果列表
        """
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        # 转换为常规字典列表
        return [dict(row) for row in rows]

    def insert_many(self, sql, data_list):
        """
        批量插入数据
        :param sql: SQL 插入语句，例如 "INSERT INTO users (name, age) VALUES (?, ?)"
        :param data_list: 包含元组的列表，例如 [('Alice', 25), ('Bob', 30)]
        :return: 成功插入的行数
        """
        try:
            cursor = self.connection.cursor()
            # executemany 是批量操作的神器
            cursor.executemany(sql, data_list)
            # 别忘了提交事务，否则数据不会真正写入硬盘
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            # 如果出错，回滚事务，确保数据一致性
            self.connection.rollback()
            logger.error(f"【insert_many】批量插入失败: {e}")
            return None

    def execute_sql(self, sql, params=()):
        """
        执行更新或删除语句 (UPDATE / DELETE)
        :param sql: SQL 语句
        :param params: 参数元组
        :return: 受影响的行数
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            self.connection.commit()
            # 返回受影响的行数，用于判断是否操作成功（比如更新了0行还是1行）
            return cursor.rowcount
        except Exception as e:
            self.connection.rollback()
            logger.error(f"【execute_sql】执行失败: {e}")
            return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时关闭连接"""
        if self.connection:
            self.connection.close()

def readJson(path):
    with open(path, 'r',encoding='utf-8') as f:
        tempData = json.load(f)
        f.close()
    return tempData

def extract_imageSources_from_messageEvent(event) -> List[str]:
    """从消息事件获取图片"""
    image_sources = []
    try:
        messages = event.get_messages()

        if not messages:
            logger.error("【消息事件解析图片】event.get_messages() 返回空")
            return image_sources

        logger.info(f"【消息事件解析图片】从get_messages()获取到消息链，长度: {len(messages)}")

        def _extract_from_image_component(component: Comp.Image):
            """从Image组件提取图像URL"""
            # 优先检查url属性
            if hasattr(component, "url") and component.url:
                logger.info(f"【消息事件解析图片】从Image组件找到url属性")  # ✅ debug级别
                return component.url

            # 其次检查file属性
            if hasattr(component, "file") and component.file:
                logger.info(f"【消息事件解析图片】从Image组件找到file属性")  # ✅ debug级别

                # 如果是base64格式
                if isinstance(component.file, str) and component.file.startswith(
                        "base64://"
                ):
                    return component.file
                # 如果是普通字符串
                elif isinstance(component.file, str):
                    return component.file

            # 检查其他可能的属性
            for attr_name in ["data", "path", "content"]:
                if hasattr(component, attr_name):
                    attr_value = getattr(component, attr_name)
                    if attr_value:
                        logger.info(f"【消息事件解析图片】从Image组件找到{attr_name}属性")  # ✅ debug级别
                        if isinstance(attr_value, str):
                            return attr_value

            logger.warning(f"【消息事件解析图片】Image组件没有找到有效的URL属性")  # ✅ debug级别
            return None

        for component in messages:
            if isinstance(component, Comp.Image):
                url = _extract_from_image_component(component)
                if url:
                    image_sources.append(url)
                    logger.info(f"【消息事件解析图片】提取到图片: {url[:50]}...")

            elif isinstance(component, Comp.Reply):
                if hasattr(component, "chain") and component.chain:
                    for reply_component in component.chain:
                        if isinstance(reply_component, Comp.Image):
                            url = _extract_from_image_component(
                                reply_component
                            )
                            if url:
                                image_sources.append(url)
                                logger.info(f"【消息事件解析图片】从回复消息提取到图片")

        logger.info(f"【消息事件解析图片】总共找到 {len(image_sources)} 个图像源")
        return image_sources

    except (AttributeError, TypeError, KeyError, IndexError, ValueError) as e:
        logger.error(f"【消息事件解析图片】提取图像源失败: {type(e).__name__}: {e}", exc_info=True)
        return []

def image_to_base64(image_data):
    """图片转换base64格式"""
    logger.info(f"【图片转base64】输入文件类型：{type(image_data)}")
    if isinstance(image_data, bytes):
        base64_bytes = base64.b64encode(image_data)
        return base64_bytes.decode("ascii")
    else:
        logger.info(f"【图片转base64】以路径格式处理 -> {image_data}")
        with open(image_data, "rb") as File:
            file_content = File.read()
            logger.info(f"【图片转base64】读取字节数：{len(file_content)}")
            encoded_string = base64.b64encode(file_content)
            result = encoded_string.decode("ascii")
            logger.info(f"【图片转base64】base64长度：{len(result)}")
            logger.info(f"【图片转base64】base64预览：{result[:50]}...")
        return result

user_random = random.Random()  # 创建独立的随机实例
def get_daily_waifu(user_id, group_id,glist):
    """娶群友获取每日老婆"""
    today = date.today().strftime("%y%m%d")
    seed = int(f"{today}{user_id}{group_id}")
    print(seed)
    user_random.seed(seed)
    return user_random.randint(0, len(glist) - 1)

async def _base64_image_analysis(self, base64_data: str, data_hash: str = None) -> Optional[Path]:
    """解析Base64编码图片"""
    try:
        if base64_data.startswith("base64://"):
            base64_data = base64_data[len("base64://"):]

        max_size = max_base64_size
        if len(base64_data) > max_size:
            logger.error(f"【Base64解析】数据过长！： {len(base64_data)}字符 > {max_size}字符")
            return None

        loop = asyncio.get_running_loop()

        def base64_decode_in_loop():
            return base64.b64decode(base64_data, validate=True)

        image_data = await loop.run_in_executor(None, base64_decode_in_loop)

        if len(image_data) > max_size:
            logger.error(f"【Base64解析】解析后的图片文件过大！： {len(image_data)}字节 > {max_size}字节")
            return None

        source_info = data_hash if data_hash else f"base64_{len(base64_data)}"
        ext = detect_image_format(image_data) or ".png"
        return await _save_temp_file(image_data, source_info, ext)

    except Exception as e:
        logger.error(f"【Base64解析】解析出错：{e}")

async def _save_temp_file(data: bytes, prefix: str, extension: str,data_dir:str) -> Optional[Path]:
    """保存临时文件"""
    try:
        unique_prefix = f"usagi_{prefix}_"
        with tempfile.NamedTemporaryFile(
                prefix=unique_prefix,
                suffix=extension,
                delete=False,
                dir=data_dir,
        ) as tmp:
            tmp.write(data)
            return Path(tmp.name)
    except Exception as e:
        logger.error(f"【保存临时文件】保存临时文件失败: {e}")
        return None

def detect_image_format(data: bytes) -> Optional[str]:
    """检测图像格式"""
    if len(data) < 12:
        return None

    magic = {
        "gif": ([b"GIF87a", b"GIF89a"], 6),
        "png": (b"\x89PNG\r\n\x1a\n", 8),
        "jpeg": (b"\xff\xd8\xff", 3),
        "jpeg2000": (b"\x00\x00\x00\x0c\x6a\x50\x20\x20\x0d\x0a\x87\x0a", 12),
        "webp": (b"RIFF", 4, b"WEBP", 8),
        "bmp": (b"BM", 2),
        "avif": (b"ftyp", 4, [b"avif", b"avis"], 8),
        "ico": ([b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"], 4),
        "tiff": ([b"II\x00\x2a", b"MM\x00\x2a"], 4),
    }

    if data[:6] in magic["gif"][0]:
        if len(data) > 13:
            image_descriptor_count = data.count(b"\x2c")
            if image_descriptor_count > 1:
                logger.info(f"【图像格式检测】检测到动态GIF，包含 {image_descriptor_count} 帧")
        return ".gif"

    if data[:8] == magic["png"][0]:
        return ".png"

    if data[:12] == magic["jpeg2000"][0]:
        return ".jp2"

    if data[:3] == magic["jpeg"][0]:
        return ".jpg"

    if data[:4] == magic["webp"][0] and data[8:12] == magic["webp"][2]:
        return ".webp"

    if data[:2] == magic["bmp"][0]:
        return ".bmp"

    if (
            len(data) > 12
            and data[4:8] == magic["avif"][0]
            and data[8:12] in magic["avif"][2]
    ):
        return ".avif"

    if data[:4] in magic["ico"][0]:
        return ".ico"

    if data[:4] in magic["tiff"][0]:
        return ".tiff"

    return None

def change_ocr_groups(config,group_id:str,price:float,mode:str):
    if not config:
        return None
    if mode not in ["add", "remove"]:
        return None

    temp_config = config
    if mode == "add":
        ocr_group_list = temp_config.get('ocr_group')
        if not ocr_group_list:
            ocr_group_list = []
        ocr_group_list.append({
            "__template_key": "template_1",
            "group_id": f"{group_id}",
            "price": price,
        })
        temp_config['ocr_group'] = ocr_group_list
        try:
            config.save_config(temp_config)
        except:
            return None
    elif mode == "remove":
        ocr_group_list = temp_config.get('ocr_group')
        group_list_after_remove = []
        if not ocr_group_list:
            return None
        for ocr_group in ocr_group_list:
            if ocr_group['group_id'] != str(group_id):
                group_list_after_remove.append(ocr_group)
        temp_config['ocr_group'] = group_list_after_remove
        try:
            config.save_config(temp_config)
        except:
            return None

    return "success"

def is_float(s):
    try:
        float(s)
        return True
    except Exception:
        return False