import datetime

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger,AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

import astrbot.api.message_components as Comp
from .functions.AAocr import *

YumisUsagi_help = {
    "管理员事件":["邀请加群自动同意"],
    "/娶群友":"每日随机娶群友"
}

@register("yumi_s_usagi", "HCskia", "usagiBot", "1.0.0")
class YumiUsagi(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.plugin_name = self.name#"astrbot_plugin_Yumis_usagi"

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def event_monitoring(self, event: AstrMessageEvent):
        """管理员邀请加群自动同意"""
        raw_message = getattr(event.message_obj, 'raw_message', None)
        if not isinstance(raw_message, dict) or raw_message.get("post_type") != "request":
            return
        if not isinstance(event, AiocqhttpMessageEvent):
            logger.debug("事件类型不是 AiocqhttpMessageEvent，无法处理")
            return
        logger.info(f"【event_monitoring】收到请求事件: {raw_message}")

        client = event.bot
        flag = raw_message.get("flag")
        user_id = raw_message.get("user_id")

        if (
                raw_message.get("request_type") == "group" and
                raw_message.get("sub_type") == "invite"
        ):
            try:
                group_id = raw_message.get("group_id")
                await client.set_group_add_request(
                    flag=flag,
                    sub_type="invite",
                    approve=True
                )
                admin_list = [item["user_id"] for item in self.config['adminList']]
                if str(user_id) not in admin_list:
                    return

                logger.info(f"【管理员邀请加群】已自动同意群邀请: {group_id} from {user_id}")

                group_name = "未知群聊"
                try:
                    group_info = await client.get_group_info(group_id=group_id)
                    group_name = group_info.get("group_name", "未知群聊")
                except Exception as e:
                    logger.warning(f"【管理员邀请加群】获取群信息失败: {e}")

                await self.log_and_notify(
                    f"【管理员邀请加群】已自动同意群邀请: {group_name}({group_id})，邀请人: {user_id}"
                )

            except Exception as e:
                logger.error(f"【管理员邀请加群】同意群邀请失败: {e}")
        elif(
                raw_message.get("request_type") == "group" and
                raw_message.get("sub_type") == "add"
        ):
            auto_agree_groups = self.config['auto_agree_groups']
            for group_dict in auto_agree_groups:
                if str(event.get_group_id()) == group_dict['group_id']:
                    bot_id = event.get_self_id()
                    if not bot_id:
                        login_data = await client.api.call_action("get_login_info")
                        bot_id = login_data.get('user_id')

                    agree_count = int(group_dict['agree_count'])
                    if agree_count != 0:
                        params = {
                            "group_id": event.get_group_id(),
                            "no_cache": True,
                        }
                        group_mem_list = (await client.api.call_action("get_group_member_list", **params))
                        if len(group_mem_list) >= agree_count:
                            return

                    params = {
                        "group_id": event.get_group_id(),
                        "user_id": bot_id,
                        "no_cache": True
                    }
                    self_info = await client.api.call_action("get_group_member_info", **params)
                    bot_roles = self_info.get('role')
                    if bot_roles not in ['admin', 'owner']:
                        return
                    else:
                        params = {
                            "flag": flag,
                            "approve": True
                        }
                        await client.api.call_action("set_group_add_request", **params)
                        # await client.set_group_add_request(
                        #     flag=flag,
                        #     sub_type="add",
                        #     approve=True
                        # )
        return

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def poke_actions(self, event: AstrMessageEvent):
        """监听并响应戳一戳事件"""
        # 仅处理aiocqhttp平台的事件
        if event.get_platform_name() != "aiocqhttp":
            return

        raw_message = getattr(event.message_obj, "raw_message", None)

        # 检查是否为戳一戳事件
        if (
                not raw_message
                or raw_message.get('post_type') != 'notice'
                or raw_message.get('notice_type') != 'notify'
                or raw_message.get('sub_type') != 'poke'
        ):
            return

        bot_id = raw_message.get('self_id')
        sender_id = raw_message.get('user_id')

        if (
                sender_id == bot_id
                or raw_message.get('target_id') != bot_id
        ):
            return
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def qqy(self, event: AstrMessageEvent): # @filter.regex(r"^(/?娶群友|.*qqy.*)")
        """娶群友指令"""
        raw_message = event.message_str
        if not re.match(r"^(/?娶群友|.*qqy.*)", raw_message):
            return

        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        no_marry_groups = self.config['no_marry_group']
        for group_dict in no_marry_groups:
            if str(event.get_group_id()) == group_dict['group_id']:
                return

        client = event.bot
        params = {
            "group_id": event.get_group_id(),
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))
        group_mem_list.sort(key=lambda x: x['user_id'])
        #logger.debug(f"【娶群友】group_mem_list：{group_mem_list}")
        waifu = get_daily_waifu(event.get_sender_id(), event.get_group_id(), group_mem_list)
        logger.debug(f"【娶群友】waifu：{group_mem_list[waifu]}")

        if str(group_mem_list[waifu]['user_id']) == event.get_sender_id():
            msg_chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Plain(f"\n今天你的没有老婆捏")
            ]
            yield event.chain_result(msg_chain)
            return

        msg_chain = [
            Comp.At(qq=event.get_sender_id()),
            Comp.Plain(f"\n今天你的群老婆是{group_mem_list[waifu]['nickname']}！！\n（{group_mem_list[waifu]['user_id']}）\n"),
            Comp.Image.fromURL(f"https://q.qlogo.cn/headimg_dl?dst_uin={group_mem_list[waifu]['user_id']}%27&spec=640&img_type=jpg"),
        ]
        yield event.chain_result(msg_chain)
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def eat_what(self, event: AstrMessageEvent): # @filter.regex(r"^(.*吃啥.*|.*吃什么.*)")
        '''推荐吃啥'''
        raw_message = event.message_str
        if not re.match(r"^(.*吃啥.*|.*吃什么.*)", raw_message):
            return

        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        no_eatwhat_groups = self.config['no_eatwhat_group']
        for group_dict in no_eatwhat_groups:
            if str(event.get_group_id()) == group_dict['group_id']:
                return

        # 去除关键词
        raw_message = raw_message.replace("吃啥", "").replace("吃什么","")

        # 创建随机实例
        food_random = random.Random()
        food_random.seed(int(datetime.datetime.now().timestamp()))

        # sqllite实例
        db_path = Path(f"{StarTools.get_data_dir(self.plugin_name)}/db")
        db_path.mkdir(parents=True, exist_ok=True)
        food = None # 提前声明food变量
        with DatabaseQuery(Path(f"{db_path}/eat.db")) as db:
            # 引入SQL实例
            sql_statement = f"select * from foods"
            results = db.query(sql_statement)
            food = results[food_random.randint(0, len(results)-1)].get('food')
        if not food:
            return

        # 随机语气词并发送
        interjections = ["捏","呢","哦"]
        yield event.plain_result(
            f"建议{raw_message}吃{food}"+
            f"{interjections[food_random.randint(0, len(interjections)-1)]}"
        )
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def AAocr(self, event: AstrMessageEvent):
        """识别AA图片的OCR功能"""
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        msg_chain = event.get_messages()
        if (
            not (
                "Image" in str(msg_chain)
                or "image" in str(msg_chain)
            )
            and "file" not in str(msg_chain)
            and "url" not in str(msg_chain)
        ):
            return

        ocr_group_ids = [item["group_id"] for item in self.config['ocr_group']]
        if str(event.get_group_id()) not in ocr_group_ids:
            return

        user_id = str(event.get_sender_id())
        if not user_id:
            return

        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        params = {
            "group_id": event.get_group_id(),
            "user_id": bot_id,
            "no_cache": True
        }
        self_info = await client.api.call_action("get_group_member_info", **params)
        bot_roles = self_info.get('role')

        if bot_roles not in ['admin','owner']:
            send_msg_chain = [
                Comp.Plain(f"无法添加已付，因为权限不足捏:(")
            ]
            yield event.chain_result(send_msg_chain)
            return

        # 获取OCR金额
        price = 0.0
        for item in self.config['ocr_group']:
            if str(event.get_group_id()) == item['group_id']:
                price = float(item['price'])
                break
        if price == 0.0:
            yield event.plain_result(f"配置文件金额获取出错！")
            return


        result_dist = {
            None: "ocr失败",
            "OcrServerError":"OCR服务器连接出错！",
            "NoneOfUser":"群聊中未发现备注用户",
            "NoneImage":"未发现ocr图片",
            "NoneImagePath":"未获取到图片路径",
            "MuiltyImage":"ocr图片数量大于1",
            "DownloadImageOverSied":"下载图片超过限制大小",
            "DownloadTimeout":"下载图片超时",
            "NoneInputPath":"未获取到图片输入路径",
            "NoneOcrResponse":"ocr响应失败",
            "NoneOcrResult":"ocr响应出错",
            "OcrJobFailed":"OCR任务处理失败",
            "OcrJobTimeout":"OCR任务处理超时",
            "OcrAuthError":"OCR服务鉴权失败，请检查Token配置",
            "OcrBadRequest":"OCR请求参数错误（图片数据为空或base64无效）",
            "OcrImageTooLarge":"图片过大，OCR服务拒绝请求",
            "OcrImageInvalid":"OCR服务无法解码该图片",
            "OcrNoneQQorAmount":"ocr解析结果中无有效数据",
            "NoneOfOcrType":"未知的ocr图片类型",
            "QQnotFit":"QQ号不符合",
            "NoneTradeShop":"未知经营小店"
        }

        no_alert_result_list = [
            "NoneOfOcrType",
            "NoneOcrResponse",
            "NoneOcrResult",
            None
        ]

        trade_shop_list = [item["shop_name"] for item in self.config['trade_shop_list']]
        process_result = await AAocrHandler(
            self.config['ocr_api_list'],
            testMode=self.config['TestMode'],
            trade_shop_list=trade_shop_list,
            plugin_name=self.plugin_name,
        ).process(event)#plugin_dataPath = Path(get_astrbot_data_path()) / "plugin_data" / self.plugin_name
        if process_result in result_dist:
            if process_result in no_alert_result_list:
                logger.debug(f"【AAocr】{process_result}:{result_dist.get(process_result)}")
            else:
                logger.error(f"【AAocr】{process_result}:{result_dist.get(process_result)}")
                yield event.plain_result(f"识别出错！{result_dist.get(process_result)}")
            return
        # 兜底保护：返回结果既不在错误码表中、也不是有效的账单信息时，避免直接取值报错
        if getattr(process_result, "amount", None) is None:
            logger.error(f"【AAocr】未知的ocr返回结果：{process_result}")
            yield event.plain_result("识别出错！ocr返回结果异常")
            return
        logger.debug(f"【AAocr】解析结果：{process_result}")

        if float(process_result.amount) != price:
            yield event.plain_result(f"检测到您的金额与设置的识别金额不符哦！")
            return

        # 尝试设置群成员名片
        ocrTagText = self.config['OcrTagText']
        if self.config['OcrTagMode']:
            if bot_roles != 'owner':
                yield event.plain_result(f"检测到群称号模式已开启，但是权限不足，无法更改群成员称号:(")
            else:
                try:
                    params = {
                        "group_id": event.get_group_id(),
                        "user_id": user_id,
                        "special_title": f"{ocrTagText}"
                    }
                    for retry_count in range(3):
                        try:
                            await client.api.call_action("set_group_special_title", **params)
                            break
                        except Exception as e:
                            if "1200" in str(e) or "请求超频" in str(e):
                                if retry_count < 2:
                                    import asyncio
                                    await asyncio.sleep(1.5)
                                    continue
                            raise e
                except Exception as e:
                    yield event.plain_result(f"设置已付头衔失败：{e}")
        if bot_roles == 'admin':
            # 尝试获取群成员名片
            try:
                params = {
                    "group_id": event.get_group_id(),
                    "user_id": user_id,
                    "no_cache": True
                }
                sender_info = await client.api.call_action("get_group_member_info", **params)
            except Exception as e:
                yield event.plain_result(f"获取成员信息失败：{e}")
                return

            if not sender_info:
                yield event.plain_result(f"获取成员信息失败！")
                return

            params = {
                "group_id": event.get_group_id(),
                "user_id": user_id,
                "card": f"{ocrTagText} {sender_info.get('card')}"
            }
            for retry_count in range(3):
                try:
                    await client.api.call_action("set_group_card", **params)
                    break
                except Exception as e:
                    if "1200" in str(e) or "请求超频" in str(e):
                        if retry_count < 2:
                            import asyncio
                            await asyncio.sleep(1.5)
                            continue
                    # 不影响功能：提示失败但不打断后续的登记完成消息
                    yield event.plain_result(f"设置已付群名片失败：{e}")
                    break

        send_msg_chain = [
            Comp.At(qq=user_id),
            Comp.Plain(f"【{process_result.amount}元】\n本兔子大王亲自为你登记完成！乌拉！\n")
        ]

        yield event.chain_result(send_msg_chain)
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("撤回")
    async def deleteMSG(self, event: AstrMessageEvent, group_id:str="", time_hours:int=24):
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        if group_id == "":
            group_id = event.get_group_id()
        # 此处为group_id
        group_id = str(group_id)

        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        import asyncio
        from datetime import datetime, timedelta

        history_hours = time_hours       # 只读取最近 N 小时内的历史消息（可修改）
        retract_interval = 2.5   # 每条撤回之间的间隔（秒）
        retry_interval = 1.5     # 撤回失败后的重试间隔（秒）
        max_attempts = 3         # 单条消息最多尝试撤回次数
        page_size = 100          # 每次向协议端请求的历史消息条数
        max_pages = 30           # 最多翻多少页，防止锚点不前进时死循环

        deadline_ts = (datetime.now() - timedelta(hours=history_hours)).timestamp()

        def is_image_message(message) -> bool:
            """判断一条 OneBot 消息中是否含有图片"""
            if isinstance(message, list):
                return any(
                    isinstance(seg, dict) and seg.get("type") == "image"
                    for seg in message
                )
            return "[CQ:image" in str(message)

        def message_time(message) -> float:
            try:
                return float(message.get("time") or 0)
            except (TypeError, ValueError):
                return 0.0

        # 通过协议端的扩展接口 get_group_msg_history 分页回溯群历史消息
        # 参数：group_id / message_seq(锚点，取上一页最旧一条的 message_id) / count / reverseOrder
        # targets: [(message_id, 消息描述)]
        targets = []
        scanned = 0
        anchor = None
        seen_ids = set()
        try:
            for _ in range(max_pages):
                params = {
                    "group_id": int(group_id),
                    "count": page_size,
                    "reverseOrder": True,
                }
                if anchor is not None:
                    params["message_seq"] = anchor
                resp = await client.api.call_action("get_group_msg_history", **params)
                messages = resp.get("messages") if isinstance(resp, dict) else None
                if not messages:
                    break

                page_oldest = None  # 本页最旧的一条，用作下一页的锚点
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    message_id = message.get("message_id")
                    if message_id is None or message_id in seen_ids:
                        continue
                    seen_ids.add(message_id)
                    scanned += 1
                    timestamp = message_time(message)
                    if page_oldest is None or timestamp < message_time(page_oldest):
                        page_oldest = message
                    if timestamp < deadline_ts:
                        continue  # 早于时间窗口，跳过
                    if not is_image_message(message.get("message")):
                        continue  # 非图片消息
                    sender = message.get("sender") or {}
                    who = sender.get("card") or sender.get("nickname") or ""
                    when = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    targets.append((message_id, f"{who} 于 {when} 发送的图片消息"))

                if page_oldest is None:
                    break
                if message_time(page_oldest) < deadline_ts:
                    break  # 已翻到时间窗口之外，无需继续
                next_anchor = page_oldest.get("message_seq") or page_oldest.get("message_id")
                if next_anchor is None or next_anchor == anchor:
                    break  # 锚点没有前进，结束（兼容回溯方向异常的协议端版本）
                anchor = next_anchor
        except Exception as e:
            logger.error(f"【撤回消息错误】获取群历史消息失败：{e}")
            yield event.plain_result(f"获取群 {group_id} 的历史消息失败：{e}")
            return

        logger.info(f"【撤回消息】群 {group_id} 扫描 {scanned} 条历史消息，命中图片 {len(targets)} 条")
        yield event.plain_result(
            f"群 {group_id} 最近 {history_hours} 小时内的图片消息共 {len(targets)} 条"
            f"（已扫描 {scanned} 条历史消息），开始撤回……"
        )

        success_count = 0
        failed_count = 0
        skipped_count = 0
        first_call = True
        for index, (message_id, content) in enumerate(targets, start=1):
            if message_id is None:
                skipped_count += 1
                logger.warning(f"【撤回消息】第 {index} 条图片消息在日志中未找到 message_id，已跳过：{content[:30]}")
                continue
            if not first_call:
                await asyncio.sleep(retract_interval)
            first_call = False
            for attempt in range(max_attempts):
                try:
                    await client.api.call_action("delete_msg", message_id=message_id)
                    success_count += 1
                    logger.info(f"【撤回消息】已撤回群 {group_id} 的消息 {message_id}")
                    break
                except Exception as e:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(retry_interval)
                        continue
                    failed_count += 1
                    logger.error(f"【撤回消息错误】：message_id={message_id}，{e}")

        yield event.plain_result(
            f"群 {group_id} 图片消息撤回完成：成功 {success_count} 条，失败 {failed_count} 条，"
            f"日志中未找到 message_id 跳过 {skipped_count} 条。"
        )

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("群成员编号", alias={'yumi','YUMI'})
    async def GroupMemberIndexSet(self, event: AstrMessageEvent):
        '''群成员编号'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        params = {
            "group_id": event.get_group_id(),
            "user_id": bot_id,
            "no_cache": True
        }
        self_info = await client.api.call_action("get_group_member_info", **params)
        bot_roles = self_info.get('role')

        if bot_roles not in ['admin', 'owner']:
            send_msg_chain = [
                Comp.Plain(f"无法给群成员编号，因为权限不足捏:(")
            ]
            yield event.chain_result(send_msg_chain)
            return

        # 获取全部群成员信息
        params = {
            "group_id": event.get_group_id(),
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))

        # 遍历数据并编号
        index_count = 0
        wait_time = float(self.config['GroupMemIndexWaitTime']) if self.config['GroupMemIndexWaitTime'] else 0.5
        for mem_data in group_mem_list:
            if mem_data.get('role') in ['admin', 'owner']:
                continue
            params = {
                "group_id": event.get_group_id(),
                "user_id": mem_data.get('user_id'),
                "card": str("%02d" % ( index_count + 1 ))
            }
            response = await client.api.call_action("set_group_card", **params)
            logger.debug(f"【群成员编号】{mem_data.get('user_id')} -response-> {response}")
            index_count += 1
            await asyncio.sleep(wait_time)

        yield event.plain_result(f"群成员编号完成！\n共计完成{index_count}个群成员！！")
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("清空群成员编号", alias={'hc', 'HC'})
    async def GroupMemberIndexClear(self, event: AstrMessageEvent):
        '''清空群成员名片'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        params = {
            "group_id": event.get_group_id(),
            "user_id": bot_id,
            "no_cache": True
        }
        self_info = await client.api.call_action("get_group_member_info", **params)
        bot_roles = self_info.get('role')

        if bot_roles not in ['admin', 'owner']:
            send_msg_chain = [
                Comp.Plain(f"无法给群成员清除群名片，因为权限不足捏:(")
            ]
            yield event.chain_result(send_msg_chain)
            return

        # 获取全部群成员信息
        params = {
            "group_id": event.get_group_id(),
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))

        # 遍历数据并编号
        index_count = 0
        wait_time = float(self.config['GroupMemIndexWaitTime']) if self.config['GroupMemIndexWaitTime'] else 0.5
        for mem_data in group_mem_list:
            if mem_data.get('role') in ['admin', 'owner']:
                continue
            params = {
                "group_id": event.get_group_id(),
                "user_id": mem_data.get('user_id'),
                "card": ""
            }
            response = await client.api.call_action("set_group_card", **params)
            logger.debug(f"【群成员名片清除】{mem_data.get('user_id')} -response-> {response}")
            index_count += 1
            await asyncio.sleep(wait_time)

        yield event.plain_result(f"群成员名片清除完成！\n共计完成{index_count}个群成员！！")
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("共同群聊", alias={'usagi共群', 'u共群'})
    async def GetSameGroup(self, event: AstrMessageEvent, check_id: str = ""):
        '''共同群聊指令 -仅管理员'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        # admin_list = [item["user_id"] for item in self.config['adminList']]
        # if str(event.get_sender_id()) not in admin_list:
        #     return

        yield event.plain_result(f"http://ti.qq.com/friends/recall?uin={check_id}")
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("召唤未付成员", alias={'callnonepaymem', '召唤未付'})
    async def CallNonePayMem(self, event: AstrMessageEvent, no_cache:str=""):
        '''召唤未付成员'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        # 获取bot自身id
        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        # 获取全部群成员信息
        params = {
            "group_id": event.get_group_id(),
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))

        send_msg_chain = [
            Comp.Plain(f"召唤未付成员\n")
        ]
        wait_time = float(self.config['CallNonePayMemWaitTime']) if self.config['CallNonePayMemWaitTime'] else 0.2
        for mem_data in group_mem_list:
            # 规避bot自身和管理员
            if (
                str(mem_data.get('user_id')) == str(bot_id)
                or str(mem_data.get('user_id')) in admin_list
            ):
                continue

            temp_mem_data = mem_data
            # -n 参数
            if no_cache == "-n":
                params = {
                    "group_id": event.get_group_id(),
                    "user_id": mem_data.get('user_id'),
                    "no_cache": True,
                }
                response = (await client.api.call_action("get_group_member_info", **params))
                logger.debug(f"【召唤未付成员】get_group_member_info：{response}")
                temp_mem_data = response
                await asyncio.sleep(wait_time)

            logger.debug(f"【召唤未付成员】temp_mem_data：{temp_mem_data}")
            if(
                "已付" in temp_mem_data.get('card')
                or "付" in temp_mem_data.get('card')
                or "已付" in temp_mem_data.get('title')
                or "付" in temp_mem_data.get('title')
            ):
                continue
            else:
                send_msg_chain.append(Comp.At(qq=str(temp_mem_data.get('user_id'))))

        # 发送召唤消息
        logger.debug(f"【召唤未付成员】发送消息链：{send_msg_chain}")
        if len(send_msg_chain) > 1:
            yield event.chain_result(send_msg_chain)
            return
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("离开", alias={'走走', '润', 'bye'})
    async def LeaveGroup(self, event: AstrMessageEvent):
        '''退群功能'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        try:
            result = change_ocr_groups(self.config, str(event.get_group_id()), "remove")
            if not result:
                raise Exception("修改config失败")
        except Exception as e:
            logger.error(f"【离开|ocr群更改】移除ocr群失败：{e}")

        client = event.bot
        params = {
            "group_id": event.get_group_id(),
            "is_dismiss": False
        }
        yield event.plain_result("呀哈哈（离开，走走")
        await client.api.call_action("set_group_leave", **params)
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("设为ocr群", alias={'设为ocr', 'setocr'})
    async def SetOcrGroup(self, event: AstrMessageEvent, price:str="0.0"):
        '''设置群组为ocr群'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        if price == "0.0":
            yield event.plain_result("缺少金额参数！")
            return
        elif not is_float(price):
            yield event.plain_result("金额参数检测到不为数字！")
            return

        try:
            result = change_ocr_groups(self.config,str(event.get_group_id()),float(price),"add")
            if not result:
                raise Exception("修改config失败")
        except Exception as e:
            logger.error(f"【ocr群更改】添加ocr群失败：{e}")
            return

        yield event.plain_result("设为ocr群成功！")
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("取消ocr", alias={'移除ocr','cancelocr'})
    async def RemoveOcrGroup(self, event: AstrMessageEvent):
        '''取消群组为ocr群'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        try:
            result = change_ocr_groups(self.config, str(event.get_group_id()),price=0.0, mode="remove")
            if not result:
                raise Exception("修改config失败")
        except Exception as e:
            logger.error(f"【ocr群更改】移除ocr群失败：{e}")
            return

        yield event.plain_result("移除ocr群成功！")
        return


    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("停车", alias={'tc'})
    async def SaveCar(self, event: AstrMessageEvent, car_name:str):
        '''储存车群数据'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            return

        logger.debug(f"【上车记录】car_name: {car_name}")

        # 获取bot自身id
        client = event.bot
        bot_id = event.get_self_id()
        if not bot_id:
            login_data = await client.api.call_action("get_login_info")
            bot_id = login_data.get('user_id')

        # 获取群信息
        group_id = event.get_group_id() # 群号
        params = {
            "group_id": group_id
        }
        group_info = (await client.api.call_action("get_group_info", **params))
        group_name = group_info.get('group_name') # 群名称

        # 获取全部群成员信息
        insert_data = []
        params = {
            "group_id": group_id,
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))
        for mem_data in group_mem_list:
            # 规避bot自身和管理员
            if (
                str(mem_data.get('user_id')) == str(bot_id)
                or str(mem_data.get('user_id')) in admin_list
            ):
                continue
            user_id = mem_data.get('user_id')

            # 获取入群月份
            join_timestamp = mem_data.get('join_time')
            join_date_obj = datetime.datetime.fromtimestamp(join_timestamp)
            formatted_date = join_date_obj.strftime('%Y-%m')

            insert_data.append((formatted_date,user_id,group_id,group_name,car_name))

        logger.debug(f"【上车记录】insert_data: {insert_data}")
        # sqllite实例
        db_path = Path(f"{StarTools.get_data_dir(self.plugin_name)}/db")
        db_path.mkdir(parents=True, exist_ok=True)
        results = None
        with DatabaseQuery(Path(f"{db_path}/cars.db")) as db:
            # 引入SQL实例
            sql_statement = f"INSERT OR IGNORE INTO oncars (date, user_id, group_id, group_name, car_name) VALUES (?, ?, ?, ?, ?)"
            results = db.insert_many(sql_statement, insert_data)
            logger.info(f"【上车记录】已更新数据 {results} 行")

        if not results:
            yield event.plain_result("上车记录失败哩")
            return
        yield event.plain_result("上车记录成功啦")
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("上车", alias={'sc'})
    async def CheckCar(self, event: AstrMessageEvent, month: str="", user_id:str=None):
        '''查询上车数据'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        isNotAdmin = True if str(event.get_sender_id()) not in admin_list else False

        if self.config['CheckCarOnlyAdmin']:
            if isNotAdmin:
                return


        prefix_str = ""
        perfix_dict = {
            "CantCheckOthersRecords":"你不能查看别人的记录哟\n"
        }
        # 当月份参数位置为QQ号时
        if (
            "月" not in month
            and user_id is None
        ):
            if (
                month.isdigit()
                and (6 <= len(month) <= 15)
            ):
                user_id = month
                month = None

                # 非管理员无法查询他人记录
                if (
                    isNotAdmin
                    and str(event.get_sender_id()) != user_id
                ):
                    prefix_str = perfix_dict['CantCheckOthersRecords']
                    user_id = None # 后续直接赋值为触发者qq
                    month = None

            elif month == "" :
                user_id = None # 后续直接赋值为触发者qq
                month = None

        # 如果在上面没有获取到QQ号，则在这处理
        if not user_id:
            user_id = str(event.get_sender_id())
        elif user_id != str(event.get_sender_id()) and isNotAdmin:
            prefix_str = perfix_dict['CantCheckOthersRecords']
            user_id = str(event.get_sender_id())


        # 获取日期
        date = None
        if month:
            # 获取当前年份
            now = datetime.datetime.now()
            year = now.year
            month = month.replace('月', '')
            date = f"{year}-0{month}" if len(month) == 1 else f"{year}-{month}"

        # sqllite实例
        db_path = Path(f"{StarTools.get_data_dir(self.plugin_name)}/db")
        db_path.mkdir(parents=True, exist_ok=True)
        results = None
        with DatabaseQuery(Path(f"{db_path}/cars.db")) as db:
            # 引入SQL实例
            if date:
                sql_statement = f"select * from oncars where date = ? and user_id = ?"
                results = db.query(sql_statement, (date, user_id))
            else:
                sql_statement = f"select * from oncars where user_id = ?"
                results = db.query(sql_statement, (user_id,))
            logger.debug(f"【上车记录】执行查询 {user_id} | {date} | {sql_statement} | {results}")
        if not results:
            yield event.plain_result(f"{prefix_str}{user_id}的({date if date is not None else '全部记录'})查不到上车记录呀")
            return

        # 输出结果
        if date:
            send_msg = f"{prefix_str}{user_id}的({date})上车记录\n日期\t车名\n"
        else:
            send_msg = f"{prefix_str}{user_id}的上车记录\n日期\t车名\n"

        for row in results:
            msg_date = row.get('date')
            send_msg += f"{msg_date[2:4] + msg_date[5:7]}\t{row.get('car_name')}\n"

        yield event.plain_result(send_msg)
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("下车", alias={'xc'})
    async def DeleteCar(self, event: AstrMessageEvent, car_name:str):
        '''删除车群数据'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                logger.info(f"【下车记录】已开启测试模式，本群不是测试群，调用已停止")
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            logger.info(f"【下车记录】权限不足")
            return

        # 处理输入
        car_name = car_name.strip()

        # sqllite实例
        db_path = Path(f"{StarTools.get_data_dir(self.plugin_name)}/db")
        db_path.mkdir(parents=True, exist_ok=True)
        results = None
        try:
            with DatabaseQuery(Path(f"{db_path}/cars.db")) as db:
                # 引入SQL实例
                sql_statement = "DELETE FROM oncars WHERE car_name LIKE '%' || ? || '%'"
                results = db.execute_sql(sql_statement, (car_name,))
                logger.info(f"【下车记录】尝试删除 {car_name}，受影响行数: {results}")

            if results is None:
                yield event.plain_result("【下车记录】数据库操作异常")
                return
            elif results == 0:
                yield event.plain_result(f"【下车记录】未找到名为 {car_name} 的记录")
                return
            else:
                yield event.plain_result(f"【下车记录】成功下车，删除了 {results} 条记录")
        except Exception as e:
            logger.error(f"【下车记录】逻辑出错: {e}")
            yield event.plain_result(f"【下车记录】发生错误，详情请移步控制台")
            return
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("查车", alias={'cc'})
    async def CheckAllCars(self, event: AstrMessageEvent):
        '''查询所有车群数据'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                logger.info(f"【查车记录】已开启测试模式，本群不是测试群，调用已停止")
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            logger.info(f"【查车记录】权限不足")
            return

        # sqllite实例
        db_path = Path(f"{StarTools.get_data_dir(self.plugin_name)}/db")
        db_path.mkdir(parents=True, exist_ok=True)
        results = None
        try:
            with DatabaseQuery(Path(f"{db_path}/cars.db")) as db:
                # 引入SQL实例
                sql_statement = "SELECT car_name,date,group_id FROM oncars GROUP BY car_name;"
                results = db.query(sql_statement)
                logger.info(f"【查车记录】尝试查询记录")

            if results is None:
                yield event.plain_result("【查车记录】数据库操作异常")
                return
            else:
                send_msg = "群号\t日期\t车名\n"
                for row in results:
                    msg_date = row.get('date')
                    send_msg += f"{row.get('group_id')}\t{msg_date[2:4] + msg_date[5:7]}\t{row.get('car_name')}\n"
                yield event.plain_result(f"【查车记录】成功查询：\n"+send_msg)
        except Exception as e:
            logger.error(f"【查车记录】逻辑出错: {e}")
            yield event.plain_result(f"【查车记录】发生错误，详情请移步控制台")
            return
        return

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("乌拉大点兵", alias={})
    async def CallByKeywords(self, event: AstrMessageEvent,Key_word:str=""):
        '''艾特符合关键词的所有人'''
        if self.config['TestMode']:
            if str(event.get_group_id()) != self.config['TestGroupID']:
                logger.info(f"【乌拉大点兵】已开启测试模式，本群不是测试群，调用已停止")
                return

        admin_list = [item["user_id"] for item in self.config['adminList']]
        if str(event.get_sender_id()) not in admin_list:
            logger.info(f"【乌拉大点兵】权限不足")
            return

        if Key_word == "":
            logger.error("【乌拉大点兵】缺少参数")
            return

        call_list_chain = [
            Comp.Plain(f"乌拉大点兵！\n")
        ]

        # 获取全部群成员信息
        client = event.bot
        params = {
            "group_id": event.get_group_id(),
            "no_cache": True,
        }
        group_mem_list = (await client.api.call_action("get_group_member_list", **params))
        for mem_data in group_mem_list:
            # 规避bot自身和管理员
            user_id = mem_data.get('user_id')
            user_card = mem_data.get('card')

            if Key_word in user_card:
                call_list_chain.append(Comp.At(qq=str(user_id)))

        try:
            yield event.chain_result(call_list_chain)
            return
        except Exception as e:
            logger.error(f"【乌拉大点兵】发生错误：{e}")


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

