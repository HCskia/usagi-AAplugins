from astrbot.api import logger
import re
import hashlib
import aiohttp
import json
import time
import cv2
import base64
import asyncio
import numpy as np
from typing import NamedTuple, List, Optional, Tuple
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from .tool import *
except ImportError:
    try:
        from tool import *
    except ImportError:
        pass

"""
AAocr逻辑部分
"""
# PaddleOCR AI Studio 异步任务接口相关常量
AAOCR_BUILD = "2.0.0-async-job"
DEFAULT_OCR_MODEL = "PP-OCRv6"
# 与官方示例保持一致的可选参数
OPTIONAL_OCR_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
}
OCR_IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".jp2": "image/jp2",
}

# 定义类型别名
class BILLINFO(NamedTuple):
    """账单信息"""
    qq: str
    amount: str

class AAocrHandler:
    def __init__(self,ocrapis:list,testMode:bool=False,trade_shop_list:list=[],plugin_name: str= "astrbot_plugin_Yumis_usagi"):
        self.timeout = aiohttp.ClientTimeout(total=45)
        self.max_download_size = 15 * 1024 * 1024 # 15MB的最大下载文件大小
        # 异步任务接口的超时与轮询参数
        self.job_request_timeout = 90 # 单次HTTP请求（上传/查询/下载）超时，单位秒
        self.job_max_wait = 120 # 单个OCR任务整体最长等待时间，单位秒
        self.job_poll_interval = 1.0 # 轮询起始间隔，单位秒
        self.job_poll_interval_max = 3.0 # 轮询最大间隔，单位秒
        self.plugin_name = plugin_name
        self.ocrapi = ocrapis
        self.testMode = testMode
        self.QQ_PATTERN = re.compile(r'^\d{5,12}$')
        self.AMOUNT_PATTERN_AA = re.compile(r'^[+-]?\d+\.?\d*$')
        self.trade_shop_list = trade_shop_list

    def _is_similar_qq(self, ocr_qq: str, sender_qq: str) -> bool:
        """
        判断识别到的QQ与发送者QQ是否相似（编辑距离不超过1，容忍1位错漏）
        """
        if not ocr_qq or not sender_qq:
            return False

        ocr_qq = ocr_qq.strip()
        sender_qq = sender_qq.strip()

        # 1. 完全相同
        if ocr_qq == sender_qq:
            return True

        # 2. 长度差异超过1位，则认为不相似
        len_ocr = len(ocr_qq)
        len_sender = len(sender_qq)
        if abs(len_ocr - len_sender) > 1:
            return False

        # 3. 编辑距离计算
        if len_ocr == len_sender:
            # 替换：最多1位不同
            mismatch_count = sum(c1 != c2 for c1, c2 in zip(ocr_qq, sender_qq))
            return mismatch_count <= 1
        elif len_ocr < len_sender:
            # 缺失：ocr_qq 是由 sender_qq 删掉1位构成的
            for i in range(len_sender):
                if sender_qq[:i] + sender_qq[i+1:] == ocr_qq:
                    return True
            return False
        else:
            # 多余：ocr_qq 是由 sender_qq 增加1位构成的
            for i in range(len_ocr):
                if ocr_qq[:i] + ocr_qq[i+1:] == sender_qq:
                    return True
            return False

    async def process(self, event):
        """
        ocr处理单元

        Args:
            event: 消息事件
        """
        try:
            user_id = event.get_sender_id()

            ####  预留检测用户ocr频率限制部分 ####

            logger.info(f"【AAocr】用户：{user_id}，触发AAocr识别")

            # 1.判断并且获取用户发送的图片
            image_sources = extract_imageSources_from_messageEvent(event)
            logger.info(f"【AAocr】获取到图片个数：{len(image_sources)}")

            if not image_sources:
                return "NoneImage"

            if len(image_sources) != 1:
                return "MuiltyImage"

            # 2.处理图片
            try:
                image_input_path = await self._get_image_file(image_sources[0])
                # 下载/读取失败时返回的是错误码字符串，直接透传给上层
                if isinstance(image_input_path, str):
                    logger.error(f"【AAocr】图片获取失败：{image_input_path}")
                    return image_input_path
                if not image_input_path:
                    return "NoneImagePath"

                status,message = await self._ocr_process(image_input_path, user_qq=str(event.get_sender_id()))

                # 图片处理失败逻辑
                if not status:
                    return message

            except Exception as e:
                logger.error(f"【AAocr】处理图片发生错误：{e}")
                return None

            # 3.处理ocr数据
            text_process_result = await self._ocr_text_process(message,self.trade_shop_list,event.get_sender_id())

            # 如果是纯字符串则为报错
            if isinstance(text_process_result, str):
                return text_process_result

            logger.info(f"【AAocr】ocr检测成功：{text_process_result}")

            if self._is_similar_qq(text_process_result.qq, str(event.get_sender_id())):
                # 容错匹配成功，自动校准为真实的发送者QQ，以便后续入账逻辑能完美执行
                text_process_result = text_process_result._replace(qq=str(event.get_sender_id()))
                return text_process_result

            else:
                return "QQnotFit"

        except Exception as e:
            logger.error(f"【AAocr】process流程发生错误：{e}")

    async def _ocr_text_process(self,ocr_data: List,trade_shop_list:list, user_qq:str):
        ocr_str = str(ocr_data)

        # 1. 支付宝小荷包 (Alipay Pocket Money)
        # 支持 中文简体、中文繁体、英文
        if any(kw in ocr_str for kw in ["小荷包", "转账备注", "轉賬備註", "Transfer notes", "Transaction Details"]):
            res = await self._text_process_alipay_XHB(ocr_data)
            if isinstance(res, BILLINFO):
                return res

        # 2. AA收款 (Alipay Split Bills)
        # 支持 中文简体、中文繁体、英文
        if any(kw in ocr_str for kw in ["AA收款", "Dutch", "Go Dutch", "Me", "我", "已付", "已支付", "paid"]):
            if any(kw in ocr_str for kw in ["Dutch", "Go Dutch", "Me"]):
                res = await self._text_process_alipay_AA_ENG(ocr_data, user_qq)
            else:
                res = await self._text_process_alipay_AA(ocr_data)
            if isinstance(res, BILLINFO):
                return res

        # 3. 经营小店
        if any(shop in ocr_str for shop in trade_shop_list) or "备注QQ" in ocr_str or "支付记录" in ocr_str:
            res = await self._text_process_alipay_JYXD(ocr_data, trade_shop_list)
            if isinstance(res, BILLINFO):
                return res

        # 4. 全局兜底：如果关键词分类不明显，依次尝试解析
        res_xhb = await self._text_process_alipay_XHB(ocr_data)
        if isinstance(res_xhb, BILLINFO):
            return res_xhb

        res_aa = await self._text_process_alipay_AA(ocr_data)
        if isinstance(res_aa, BILLINFO):
            return res_aa

        return "NoneOfOcrType"

    def _clean_amount(self, text: str) -> Optional[str]:
        """从字符串中干净地提取付款金额,过滤货币符号和汉字,并防范误匹配QQ"""
        if not text:
            return None
        # 去除多余的空格
        t = text.replace(' ', '')
        # 移除常见的货币符号
        t = re.sub(r'[￥¥$元]', '', t.lower())
        # 移除收付款状态描述
        t = re.sub(r'paid|paic|paio|pai|pay|payable|已付|已支付', '', t)
        # 正则提取浮点数或纯数字
        match = re.search(r'\d+\.\d+|\d+', t)
        if match:
            val = match.group(0)
            # 带小数点的一定是金额（如 2.50 / 17.00）
            if '.' in val:
                return val
            # 纯数字：只有位数不足5位（QQ号为5-15位）才可能是金额
            if len(val) < 5:
                return val
        return None

    async def _text_process_alipay_XHB(self,ocr_data: List):
        """解析器-小荷包"""
        try:
            qq = None
            amount = None

            # 1. 寻找交易金额：在小荷包账单中，金额通常是带有+-前缀的浮点数，位于顶部
            for item in ocr_data:
                if not isinstance(item, str):
                    continue
                item_str = item.strip()
                if re.match(r'^[+-]?\d+\.\d+$', item_str):
                    amount = item_str.lstrip('+-')
                    break

            # 2. 寻找QQ号：位于转账备注（英文Transfer notes，繁体轉賬備註）标签下方/附近
            for i, item in enumerate(ocr_data):
                if not isinstance(item, str):
                    continue
                if any(keyword in item for keyword in ["转账备注", "轉賬備註", "Transfer notes"]):
                    # 优先检测QQ是否与标签在同一行中合并识别了（例如 "转账备注1234567890"）
                    clean_line = item
                    for kw in ["转账备注", "轉賬備註", "Transfer notes"]:
                        clean_line = clean_line.replace(kw, "")
                    clean_line = clean_line.strip().replace('-', '').replace(' ', '')
                    if clean_line.isdigit() and 5 <= len(clean_line) <= 15:
                        qq = clean_line
                        break

                    # 检查标签后面的2-3行内是否有合法的QQ号
                    for j in range(1, 4):
                        if i + j < len(ocr_data):
                            val = str(ocr_data[i + j]).strip().replace('-', '').replace(' ', '')
                            if val.isdigit() and 5 <= len(val) <= 15:
                                qq = val
                                break
                    if qq:
                        break

            if qq and amount:
                return BILLINFO(qq=qq, amount=amount)
            return "OcrNoneQQorAmount"
        except Exception as e:
            logger.error(f"【AAocr】text_process_alipay_XHB出错！：{e}")
            return None

    async def _text_process_alipay_AA_ENG(self, ocr_data: List, user_qq: str):
        """解析器-AA收款 英文逻辑"""
        try:
            qq = None
            amount = None

            # 寻找所有的 "Me" (英文的"我"位置)
            my_indexes = []
            for idx, item in enumerate(ocr_data):
                if isinstance(item, str) and item.strip().lower() == "me":
                    my_indexes.append(idx)

            for my_index in my_indexes:
                # 扫描 "Me" 后续的6行区域 (本地滑动窗口)
                window = ocr_data[my_index + 1 : my_index + 7]

                # 提取QQ号
                for item in window:
                    if not isinstance(item, str):
                        continue
                    clean_item = item.strip().replace('-', '').replace(' ', '')
                    if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                        qq = clean_item
                        break

                # 提取金额
                for i, item in enumerate(window):
                    if not isinstance(item, str):
                        continue
                    item_lower = item.lower()
                    if any(k in item_lower for k in ["paid", "paic", "paio", "pai", "pay", "payable"]):
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break
                        # 支持金额和支付关键字分行的场景
                        if i + 1 < len(window):
                            amt = self._clean_amount(window[i + 1])
                            if amt:
                                amount = amt
                                break

                # 在窗口内如果还没有提取到金额，则提取窗口中除了QQ号之外的第一个有效数字
                if not amount:
                    for item in window:
                        if not isinstance(item, str):
                            continue
                        clean_item = item.strip().replace('-', '').replace(' ', '')
                        if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                            continue
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break

                if qq and amount:
                    return BILLINFO(qq=qq, amount=amount)

            # 全局兜底
            if not qq or not amount:
                for item in ocr_data:
                    if not isinstance(item, str):
                        continue
                    clean_item = item.strip().replace('-', '').replace(' ', '')
                    if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                        qq = clean_item
                        break
                for item in ocr_data:
                    if not isinstance(item, str):
                        continue
                    item_lower = item.lower()
                    if any(k in item_lower for k in ["paid", "paic", "paio", "pai", "pay", "payable"]):
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break

            if qq and amount:
                return BILLINFO(qq=qq, amount=amount)

            return "OcrNoneQQorAmount"
        except Exception as e:
            logger.error(f"【AAocr】text_process_alipay_AA_ENG出错！：{e}")
            return None

    async def _text_process_alipay_AA(self, ocr_data: List):
        """解析器-AA收款 中文逻辑"""
        try:
            qq = None
            amount = None

            # 寻找所有的 "我" 位置
            my_indexes = []
            for idx, item in enumerate(ocr_data):
                if isinstance(item, str) and item.replace(' ', '') == "我":
                    my_indexes.append(idx)

            for my_index in my_indexes:
                # 扫描 "我" 后续的6行区域 (本地滑动窗口)
                window = ocr_data[my_index + 1 : my_index + 7]

                # 1. 提取QQ号 (5-15位数字)
                for item in window:
                    if not isinstance(item, str):
                        continue
                    clean_item = item.strip().replace('-', '').replace(' ', '')
                    if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                        qq = clean_item
                        break

                # 2. 提取金额：查找含有"已付"、"已支付"的行
                for i, item in enumerate(window):
                    if not isinstance(item, str):
                        continue
                    if "已付" in item or "已支付" in item:
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break
                        # 如果金额与“已付”两字分在了不同行（例如2.png, 3.png）
                        if i + 1 < len(window):
                            amt = self._clean_amount(window[i + 1])
                            if amt:
                                amount = amt
                                break

                # 在窗口内若仍未提取到金额，则寻找除了QQ号之外的第一个有效数字
                if not amount:
                    for item in window:
                        if not isinstance(item, str):
                            continue
                        clean_item = item.strip().replace('-', '').replace(' ', '')
                        if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                            continue
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break

                if qq and amount:
                    return BILLINFO(qq=qq, amount=amount)

            # 全局兜底
            if not qq or not amount:
                for item in ocr_data:
                    if not isinstance(item, str):
                        continue
                    clean_item = item.strip().replace('-', '').replace(' ', '')
                    if clean_item.isdigit() and 5 <= len(clean_item) <= 15:
                        qq = clean_item
                        break
                for item in ocr_data:
                    if not isinstance(item, str):
                        continue
                    if "已付" in item or "已支付" in item:
                        amt = self._clean_amount(item)
                        if amt:
                            amount = amt
                            break

            if qq and amount:
                return BILLINFO(qq=qq, amount=amount)

            return "OcrNoneQQorAmount"
        except Exception as e:
            logger.error(f"【AAocr】text_process_alipay_AA出错！：{e}")
            return None

    async def _text_process_alipay_JYXD(self, ocr_data: List, trade_shop_list:list, isEnglish: bool = False):
        """解析器-经营小店"""
        try:
            # 检测是否含有经营小店店铺名
            trade_shop = None
            for shop_name in trade_shop_list:
                if shop_name in ocr_data:
                    trade_shop = shop_name
                    break
            if not trade_shop and trade_shop_list:
                return "NoneTradeShop"

            qq = None
            amount = None
            text_marked_qq = "备注QQ"

            # 1.找到"备注QQ"的位置
            try:
                marked_qq_index = ocr_data.index(text_marked_qq)

                # 2.解析QQ信息："备注"后面跟着的是"QQ号"
                for index_gap in range(1, 4):
                    if marked_qq_index + index_gap < len(ocr_data):
                        val = str(ocr_data[marked_qq_index + index_gap]).replace('-', '').replace(' ', '').strip()
                        if val.isdigit() and 5 <= len(val) <= 15:
                            qq = val
                            break

                for index_gap in range(1, 8):
                    if marked_qq_index + index_gap < len(ocr_data):
                        my_payment_str = str(ocr_data[marked_qq_index + index_gap])
                        if "￥" in my_payment_str or "¥" in my_payment_str:
                            match = re.search(r'[￥¥](\d+\.?\d*)', my_payment_str)
                            if match:
                                amount = match.group(1)
                                break
            except ValueError:
                pass

            # 如果没有找到"备注QQ"关键字，但全文有明显的QQ和金额，作为经营小店的宽容匹配
            if not qq or not amount:
                for item in ocr_data:
                    if not isinstance(item, str):
                        continue
                    # 寻找QQ
                    if "备注QQ" in item:
                        # 先清理空格与连字符，防止OCR分割噪音
                        clean_item = item.replace(' ', '').replace('-', '')
                        # 支持5到15位数字匹配
                        match = re.search(r'\d{5,15}', clean_item)
                        if match:
                            qq = match.group(0)
                    # 寻找金额
                    if "￥" in item or "¥" in item:
                        match = re.search(r'[￥¥](\d+\.?\d*)', item)
                        if match:
                            amount = match.group(1)

            if qq and amount:
                return BILLINFO(qq=qq,amount=amount)
            return "OcrNoneQQorAmount"

        except Exception as e:
            logger.error(f"【AAocr】text_process_alipay_JYXD出错！：{e}")
            return None

    # ---------------- OCR 请求层：PaddleOCR AI Studio 异步任务接口（兼容旧版同步接口） ----------------

    @staticmethod
    def _is_job_api(url: str) -> bool:
        """判断配置的API地址是否为异步任务（job）接口"""
        lowered = url.strip().lower().rstrip("/")
        if "aistudio-app.com" in lowered:
            return True
        return lowered.endswith("/jobs") or "/jobs/" in lowered

    @staticmethod
    def _normalize_job_url(url: str) -> str:
        """把用户填写的地址规范化为异步任务接口地址

        - AI Studio 域名（含专属应用域名 xxx.aistudio-app.com）统一为
          https://<host>/api/v2/ocr/jobs，用户多写的 /ocr 等路径会被忽略
        - 其他域名补全缺失的 /api/v2/ocr/jobs，已经是 /jobs 的保持不变
        """
        raw = url.strip()
        if not raw.lower().startswith(("http://", "https://")):
            raw = f"https://{raw}"

        parsed = urlsplit(raw)
        path = parsed.path.rstrip("/")
        host = (parsed.hostname or "").lower()

        if host.endswith("aistudio-app.com"):
            path = "/api/v2/ocr/jobs"
        elif path.lower().endswith("/jobs"):
            pass
        else:
            for suffix in ("/api/v2/ocr", "/ocr"):
                if path.lower().endswith(suffix):
                    path = path[: -len(suffix)]
                    break
            path = f"{path}/api/v2/ocr/jobs"

        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    @staticmethod
    def _extract_rec_texts(result: dict) -> List[str]:
        """从 OCR 响应体的 result 字段中提取识别文本"""
        texts: List[str] = []
        if not isinstance(result, dict):
            return texts
        for res in result.get("ocrResults") or []:
            if not isinstance(res, dict):
                continue
            pruned = res.get("prunedResult") or {}
            for text in pruned.get("rec_texts") or []:
                if isinstance(text, str) and text.strip():
                    texts.append(text)
        return texts

    @classmethod
    def _parse_jsonl_texts(cls, payload: str) -> List[str]:
        """解析异步任务返回的 JSONL 结果（多页时为多行）"""
        texts: List[str] = []
        for line in payload.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"【AAocr】OCR结果行解析失败，已跳过：{e}")
                continue
            if item.get("errorCode"):
                logger.warning(f"【AAocr】OCR结果行返回错误：{item.get('errorMsg')}")
            texts.extend(cls._extract_rec_texts(item.get("result")))
        return texts

    async def _submit_ocr_job(self, session: aiohttp.ClientSession, job_url: str, headers: dict,
                              model: str, image_data: bytes) -> Tuple[Optional[str], Optional[str]]:
        """提交OCR任务（multipart上传图片二进制），返回 (job_id, error)"""
        ext = detect_image_format(image_data) or ".jpg"
        form = aiohttp.FormData()
        form.add_field("model", model)
        form.add_field("optionalPayload", json.dumps(OPTIONAL_OCR_PAYLOAD))
        form.add_field(
            "file",
            image_data,
            filename=f"AAocr{ext}",
            content_type=OCR_IMAGE_MIME_TYPES.get(ext, "application/octet-stream"),
        )

        async with session.post(job_url, data=form, headers=headers) as response:
            body_text = await response.text()
            if response.status != 200:
                logger.error(f"【AAocr】OCR任务提交失败：HTTP {response.status} | {body_text[:300]}")
                return None, "OcrServerError"

        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            logger.error(f"【AAocr】OCR任务提交响应解析失败：{body_text[:300]}")
            return None, "OcrServerError"

        job_id = (body.get("data") or {}).get("jobId")
        if not job_id:
            logger.error(f"【AAocr】OCR任务提交未返回jobId：{body_text[:300]}")
            return None, "OcrServerError"

        logger.info(f"【AAocr】OCR任务提交成功，jobId：{job_id}")
        return str(job_id), None

    async def _wait_ocr_job(self, session: aiohttp.ClientSession, job_url: str, headers: dict,
                            job_id: str) -> Tuple[Optional[str], Optional[str]]:
        """轮询OCR任务状态，返回 (jsonl_url, error)"""
        deadline = time.monotonic() + self.job_max_wait
        interval = self.job_poll_interval
        failures = 0

        while True:
            if time.monotonic() > deadline:
                logger.error(f"【AAocr】OCR任务轮询超时（>{self.job_max_wait}s），jobId：{job_id}")
                return None, "OcrJobTimeout"

            await asyncio.sleep(interval)
            interval = min(interval * 1.5, self.job_poll_interval_max)

            async with session.get(f"{job_url}/{job_id}", headers=headers) as response:
                if response.status in (401, 403):
                    logger.error(f"【AAocr】OCR任务查询鉴权失败：HTTP {response.status}，请检查Token配置")
                    return None, "OcrServerError"
                if response.status != 200:
                    failures += 1
                    logger.warning(f"【AAocr】OCR任务查询异常：HTTP {response.status}（第{failures}次）")
                    if failures >= 3:
                        return None, "OcrServerError"
                    continue
                body = await response.json()

            data = body.get("data") or {}
            state = data.get("state")

            if state == "done":
                progress = data.get("extractProgress") or {}
                logger.info(f"【AAocr】OCR任务完成，成功识别页数：{progress.get('extractedPages')}")
                jsonl_url = (data.get("resultUrl") or {}).get("jsonUrl")
                if not jsonl_url:
                    logger.error("【AAocr】OCR任务完成但未返回结果地址")
                    return None, "NoneOcrResponse"
                return jsonl_url, None

            if state == "failed":
                logger.error(f"【AAocr】OCR任务处理失败：{data.get('errorMsg')}")
                return None, "OcrJobFailed"

            if state == "running":
                progress = data.get("extractProgress") or {}
                logger.debug(
                    f"【AAocr】OCR任务处理中：{progress.get('extractedPages')}/{progress.get('totalPages')}"
                )

    async def _request_job_api(self, api_url: str, token: str, model: str,
                               image_data: bytes, tag: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """异步任务接口：提交任务 → 轮询状态 → 下载JSONL → 提取文本"""
        job_url = self._normalize_job_url(api_url)
        if job_url != api_url.strip():
            logger.info(f"【AAocr】OCR接口地址已规范化：{api_url.strip()} -> {job_url}")
        headers = {"Authorization": f"bearer {token}"} if token else {}
        timeout = aiohttp.ClientTimeout(total=self.job_request_timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            job_id, error = await self._submit_ocr_job(session, job_url, headers, model, image_data)
            if not job_id:
                return None, error

            jsonl_url, error = await self._wait_ocr_job(session, job_url, headers, job_id)
            if not jsonl_url:
                return None, error

            async with session.get(jsonl_url) as response:
                if response.status != 200:
                    logger.error(f"【AAocr】OCR结果下载失败：HTTP {response.status}")
                    return None, "NoneOcrResponse"
                jsonl_text = await response.text()

        texts = self._parse_jsonl_texts(jsonl_text)
        if not texts:
            logger.warning(f"【AAocr】OCR结果为空（{tag}）")
            return None, "NoneOcrResult"
        return texts, None

    @staticmethod
    def _map_sync_status(status: int) -> str:
        """把同步接口的HTTP状态码映射为插件内部错误码"""
        if status in (401, 403):
            return "OcrAuthError"
        if status == 400:
            return "OcrBadRequest"
        if status == 413:
            return "OcrImageTooLarge"
        if status == 422:
            return "OcrImageInvalid"
        if status == 504:
            return "OcrJobTimeout"
        return "OcrServerError"

    async def _request_legacy_api(self, api_url: str, token: str, model: str,
                                  image_data: bytes, tag: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """同步接口（局域网 PaddleX 风格 OCR 服务）：base64 直传

        请求体与 PaddleX 保持一致：{"file": "<图片base64>", "fileType": 1}
        """
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"token {token}"
        payload = {
            "file": base64.b64encode(image_data).decode("utf-8"),
            "fileType": 1,
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                body_text = await response.text()
                if response.status != 200:
                    logger.error(f"【AAocr】OCR接口请求失败（{tag}）：HTTP {response.status} | {body_text[:300]}")
                    return None, self._map_sync_status(response.status)

        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            logger.error(f"【AAocr】OCR接口响应解析失败（{tag}）：{body_text[:300]}")
            return None, "NoneOcrResponse"

        if not isinstance(body, dict) or "result" not in body:
            logger.error(f"【AAocr】OCR接口响应缺少result字段（{tag}）：{body_text[:300]}")
            return None, "NoneOcrResponse"

        # 服务端推理耗时与执行后端，用于确认是否真的走了 GPU
        elapsed_ms = body.get("elapsed_ms")
        provider = body.get("provider")
        if elapsed_ms is not None or provider:
            logger.debug(f"【AAocr】OCR识别完成（{tag}）：耗时{elapsed_ms}ms，后端{provider}")

        texts = self._extract_rec_texts(body.get("result"))
        if not texts:
            logger.warning(f"【AAocr】OCR结果为空（{tag}）")
            return None, "NoneOcrResult"
        return texts, None

    async def _ocr_recognize(self, image_data: bytes, tag: str = "") -> Tuple[Optional[List[str]], Optional[str]]:
        """依次调用配置的OCR接口，返回 (识别文本列表, 错误码)"""
        error = "NoneOcrResponse"
        for api in self.ocrapi:
            url = str((api or {}).get("url") or "").strip()
            if not url:
                continue
            token = str((api or {}).get("token") or "").strip()
            model = str((api or {}).get("model") or "").strip() or DEFAULT_OCR_MODEL
            logger.debug(f"【AAocr】尝试请求API（{tag}）：{url}")

            try:
                if self._is_job_api(url):
                    texts, error = await self._request_job_api(url, token, model, image_data, tag)
                else:
                    texts, error = await self._request_legacy_api(url, token, model, image_data, tag)
            except asyncio.TimeoutError:
                logger.error(f"【AAocr】OCR请求超时（{tag}）：{url}")
                error = "OcrJobTimeout"
                continue
            except aiohttp.ClientError as e:
                logger.error(f"【AAocr】OCR网络请求出错（{tag}）：{url} | {type(e).__name__}: {e}")
                error = "OcrServerError"
                continue
            except Exception as e:
                logger.error(f"【AAocr】OCR请求发生未知错误（{tag}）：{url} | {type(e).__name__}: {e}")
                error = "OcrServerError"
                continue

            if texts:
                return texts, None

        return None, error

    def _preprocess_image(self, image_data: bytes) -> Optional[bytes]:
        """OpenCV 图像预处理流水线：灰度 → 放大 → 高斯模糊 → 自适应二值化 → 闭运算"""
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return None

            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            binary = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 25, 5
            )
            kernel = np.ones((2, 2), np.uint8)
            processed_image = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            is_success, im_buf_arr = cv2.imencode(".png", processed_image)
            if not is_success:
                return None
            return im_buf_arr.tobytes()
        except Exception as e:
            logger.error(f"【AAocr】图像预处理出错：{e}")
            return None

    async def _ocr_process(self, image_data: bytes, user_qq: str = ""):
        """图像ocr主逻辑（采用高容错、双通路设计：原图直传通路 + 备用图像预处理通路）"""
        try:
            if not image_data or not isinstance(image_data, (bytes, bytearray)):
                return False, "NoneInputPath"

            raw_bytes = bytes(image_data)

            # --- 通路1: 原图直传 (Fast-path) ---
            logger.info("【AAocr】启用直传通路进行极速OCR识别...")
            fast_texts, fast_error = await self._ocr_recognize(raw_bytes, "直传")

            if fast_texts:
                # 运行模拟解析，验证直传数据能否在一次解析中完美提取到 QQ 和 金额
                parsed = await self._ocr_text_process(fast_texts, self.trade_shop_list, user_qq)
                if isinstance(parsed, BILLINFO):
                    if not user_qq or self._is_similar_qq(parsed.qq, user_qq):
                        logger.info(f"【AAocr】直传极速通路解析大成功！结果预览：{fast_texts[:5]}")
                        return True, fast_texts
                    logger.warning(f"【AAocr】直传OCR结果QQ {parsed.qq} 与用户QQ {user_qq} 不匹配，准备降级至图像预处理备用通路...")
                else:
                    logger.warning("【AAocr】直传OCR结果数据缺失或不完整，准备自动降级至图像预处理备用通路...")
            else:
                logger.warning(f"【AAocr】直传通路未获取到识别结果（{fast_error}），准备降级至图像预处理备用通路...")

            # --- 通路2: 备用图像预处理 (Fallback-path) ---
            logger.info("【AAocr】启用自适应图像处理备用通路...")
            pre_bytes = self._preprocess_image(raw_bytes)
            if pre_bytes is None:
                # 图像无法解码时再做同样的请求没有意义，直接返回直传通路的错误
                logger.error("【AAocr】图像预处理失败，无法启用备用通路")
                return False, fast_error or "NoneOcrResponse"

            pre_texts, pre_error = await self._ocr_recognize(pre_bytes, "预处理")
            if not pre_texts:
                logger.error(f"【AAocr】预处理备用通路识别失败：{pre_error}")
                return False, pre_error or "NoneOcrResponse"

            logger.info(f"【AAocr】预处理备用通路识别成功，结果预览：{pre_texts[:5]}")
            return True, pre_texts

        except Exception as e:
            logger.error(f"【AAocr】ocr_process备用流程发生错误：{e}")
            return False, str(e)

    async def _get_image_file(self, image_source: str) -> Optional[bytes]:
        """获取图片文件（统一返回图片二进制数据）"""
        # 在线图片获取
        if image_source.startswith(("http://", "https://")):
            return await self._download_image(image_source)

        # Base64编码图片解析
        elif image_source.startswith("base64://"):
            source_hashcode = hashlib.md5(image_source.encode()).hexdigest()[:16]
            return await self._base64_image_analysis(image_source, source_hashcode)

        # 本地图片获取
        else:
            return self._get_local_image(image_source)

    async def _base64_image_analysis(self, image_source: str, source_hashcode: str = "") -> Optional[bytes]:
        """解析 base64:// 协议的图片数据，直接返回二进制数据（不落地临时文件）"""
        try:
            b64_data = image_source[len("base64://"):].strip()
            if not b64_data:
                logger.error("【AAocr】base64图片数据为空")
                return None

            # 部分适配器会带上 data URI 前缀，这里统一剥离
            if b64_data.startswith("data:"):
                b64_data = b64_data.split(",", 1)[-1]

            image_data = base64.b64decode(b64_data, validate=False)
            if not image_data:
                logger.error("【AAocr】base64图片解码结果为空")
                return None
            if len(image_data) > self.max_download_size:
                logger.error(f"【AAocr】base64图片超过限制大小{len(image_data)}bytes")
                return "DownloadImageOverSied"

            logger.debug(f"【AAocr】base64图片解析成功，大小：{len(image_data)}，hash：{source_hashcode}")
            return image_data
        except Exception as e:
            logger.error(f"【AAocr】base64图片解析失败：{e}")
            return None

    async def _download_image(self, image_source: str) -> Optional[bytes]:
        """下载图片"""
        logger.info(f"【AAocr】图片下载：{image_source}")

        try:
            async with aiohttp.request("GET", image_source, timeout=self.timeout) as resp:
                if resp.status != 200:
                    logger.error(f"【AAocr】图片下载失败，状态码{resp.status}")
                    return None
                buffer = bytearray()
                async for chunk in resp.content.iter_chunked(8192):
                    buffer.extend(chunk)
                    if len(buffer) > self.max_download_size:
                        logger.error(f"【AAocr】下载图片超过限制大小{len(buffer)}bytes")
                        return "DownloadImageOverSied"
                logger.debug(f"【AAocr】图片下载成功，大小：{len(buffer)}")
                return bytes(buffer)
        except aiohttp.ServerTimeoutError:
            logger.error(f"【AAocr】图片下载超时：{image_source}")
            return "DownloadTimeout"
        except Exception as e:
            logger.error(f"【AAocr】下载图片失败 {image_source}: {str(e)}")
            return None

    def _get_local_image(self, file_path: str) -> Optional[bytes]:
        """获取本地图片"""
        logger.info(f"【AAocr】读取本地图片：{file_path}")

        try:
            path = Path(file_path)
            # 校验文件是否存在且是否为文件
            if not path.is_file():
                logger.error(f"【AAocr】本地图片文件不存在或不是有效文件：{file_path}")
                return None

            # 校验文件大小限制（与下载大小限制一致）
            file_size = path.stat().st_size
            if file_size > self.max_download_size:
                logger.error(f"【AAocr】本地图片超过限制大小{file_size}bytes")
                return "DownloadImageOverSied"

            # 读取二进制图片数据
            buffer = path.read_bytes()
            logger.debug(f"【AAocr】读取本地图片成功，大小：{len(buffer)}")
            return buffer

        except Exception as e:
            logger.error(f"【AAocr】读取本地图片失败 {file_path}: {str(e)}")
            return None

# 工具方法
def _check_position_1_3(Text, sub):
    pos = Text.find(sub)
    if pos == -1:
        return False

    total = len(Text)
    last_third_start = (2 * total) // 3
    return True if pos >= last_third_start else False

# 模块加载标记：用于确认插件是否已重载到最新代码
logger.info(f"【AAocr】OCR模块已加载：{AAOCR_BUILD}（PaddleOCR AI Studio 异步任务接口）")
