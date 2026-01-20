#!/usr/bin/env python3
"""
异步设备数据下载器
"""

import asyncio
import json
import shutil
import zipfile

# v2.2.4
import socket
import ssl
import errno
import oss2
# v2.2.4
from datetime import datetime
from pathlib import Path

# v2.2.3
import time
from typing import List, Dict, Any, Optional, Callable, Tuple, Awaitable
import logging

import oss2
import pandas as pd
from download.db import database_resource
from config.config import THCPN_DB_CONFIG


class DownloadError(Exception):
    """下载过程中的自定义异常"""
    pass

# v2.2.3 添加新功能限制并行下载请求数量
class _AsyncThrottle:
    """最小间隔限速：保证两次请求启动之间至少间隔 min_interval 秒"""
    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, float(min_interval))
        self._lock: Optional[asyncio.Lock] = None
        self._next_time = 0.0

    async def wait(self):
        if self.min_interval <= 0:
            return
        # 这里延迟创建 Lock，避免跨 event loop 绑定问题
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            now = time.monotonic()
            if now < self._next_time:
                await asyncio.sleep(self._next_time - now)
            self._next_time = time.monotonic() + self.min_interval

class AsyncDeviceDataDownloader:
    """异步设备数据下载器"""
    
    def __init__(self, root_path: str = './tmp/', logger: Optional[logging.Logger] = None):
        self.root_path = Path(root_path)
        self.logger = logger or logging.getLogger(__name__)
        # v2.2.2 添加功能Excel列名使用原始Key（不映射）
        self.export_raw_keys = False
        # v2.2.3 图片下载：并发/限速/重试（可按需调）
        self.image_concurrency = 10  # 同时下载“图片记录”的worker数量（等价于并发数）
        self.image_min_interval = 0.02  # 每次OSS请求最小间隔(秒)，0=不限速；建议 0.02~0.1
        self.image_max_retries = 2  # 临时失败重试次数

        # 初始化OSS客户端
        try:
            self.auth = oss2.Auth(
                THCPN_DB_CONFIG["OSS_ACCESSKEYID"], 
                THCPN_DB_CONFIG["OSS_ACCESSKEYSECRET"]
            )
            self.bucket = oss2.Bucket(
                self.auth, 
                THCPN_DB_CONFIG["OSS_ENDPOINTURI"], 
                THCPN_DB_CONFIG["OSS_BUCKET"]
            )
            
            # 测试OSS连接
            self.bucket.get_bucket_info()
            self.logger.info("OSS连接成功")
            
        except Exception as e:
            raise DownloadError(f"OSS连接失败: {str(e)}")
        
        # 确保根目录存在
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.zipfile_path = self.root_path / "device_data.zip"
        
        # 进度回调
        self._progress_callback: Optional[Callable[[str, float], None]] = None
        self._cancelled = False

    def _raise_if_cancelled(self):
        if self._cancelled:
            raise asyncio.CancelledError()

    def set_progress_callback(self, callback: Callable[[str, float], None]):
        """设置进度回调函数"""
        self._progress_callback = callback

    def cancel(self):
        """取消下载任务（幂等：只记录一次）"""
        if not self._cancelled:
            self._cancelled = True
            self.logger.info("下载任务已取消")

    def _update_progress(self, message: str, progress: float):
        # v2.2.5-
        # """更新进度"""
        # if self._cancelled:
        #     raise DownloadError("下载任务已取消")

        # v2.2.5+
        self._raise_if_cancelled()

        if self._progress_callback:
            self._progress_callback(message, progress)

        self.logger.info(f"[{progress:.1%}] {message}")

    async def download_device_data(
        self,
        devices: List[int],
        contents: List[str],
        start_at: str,
        end_at: str,
        is_zip: bool = False,
        thumbnail: bool = False,
        rename_images: bool = True,
        rename_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        异步下载设备数据

        Args:
            devices: 设备ID列表
            contents: 内容类型 ['data', 'image'] 或 ['data'] 或 ['image']
            start_at: 开始时间字符串
            end_at: 结束时间字符串
            is_zip: 是否打包为ZIP
            thumbnail: 图片是否下载缩略图（style/small）
            rename_images: 是否对图片进行重命名
            rename_format: 重命名格式（若提供，则所有图片统一用该名字，自动去重）

        Returns:
            Dict包含下载结果信息
        """
        work_dir = None
        results = {
            "success": True,
            "processed_devices": 0,
            "failed_devices": [],
            "download_path": None,
            "zip_path": None,
            "errors": []
        }

        try:
            self._cancelled = False
            start_time = datetime.strptime(start_at, "%Y-%m-%d %H:%M:%S")
            end_time = datetime.strptime(end_at, "%Y-%m-%d %H:%M:%S")
            
            if start_time >= end_time:
                raise DownloadError("开始时间必须早于结束时间")
            
            # 计算数据表时间范围
            data_table_start = start_time.replace(day=1, hour=0, minute=0, second=0)
            last_day = self._get_last_day_of_month(end_time.year, end_time.month)
            data_table_end = end_time.replace(day=last_day, hour=23, minute=59, second=59)
            
            self.logger.info(f"数据表时间范围: {data_table_start} 到 {data_table_end}")
            
            # 创建临时工作目录
            work_dir = self.root_path / f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            work_dir.mkdir(exist_ok=True)

            # v2.2.5+
            results["download_path"] = str(work_dir)

            total_devices = len(devices)

            # v2.2.5-
            # results = {
            #     "success": True,
            #     "processed_devices": 0,
            #     "failed_devices": [],
            #     "download_path": str(work_dir),
            #     "zip_path": None,
            #     "errors": []
            # }

            # v2.2.4+
            # 处理每个设备
            for i, device_id in enumerate(devices):
                # 这里一旦取消，就立刻抛 CancelledError，走到下面 except asyncio.CancelledError
                self._raise_if_cancelled()

                self._update_progress(
                    f"downloading: {device_id} ({i + 1}/{total_devices})",
                    0.1 + (i / total_devices) * 0.7
                )

                try:
                    await self._process_single_device(
                        device_id, contents, start_time, end_time,
                        data_table_start, data_table_end, work_dir,
                        thumbnail, rename_images, rename_format
                    )
                    results["processed_devices"] += 1

                except DownloadError as e:
                    # 致命错误（例如网络断开）——直接停止
                    msg = f"致命错误，停止下载: {str(e)}"
                    self.logger.error(msg)
                    results["success"] = False
                    results["errors"].append(msg)
                    break

                except Exception as e:
                    error_msg = f"设备 {device_id} 处理失败: {str(e)}"
                    self.logger.error(error_msg)
                    results["failed_devices"].append(device_id)
                    results["errors"].append(error_msg)

                    # v2.2.5-
                    # # 如果是致命错误导致 cancel，则立刻停止整个下载
                    # if self._cancelled:
                    #     results["success"] = False
                    #     return results

            # v2.2.5+
            # 循环结束后再检查一次是否取消
            self._raise_if_cancelled()


            # v2.2.4-
            # for i, device_id in enumerate(devices):
            #     if self._cancelled:
            #         break
            #
            #     self._update_progress(
            #         f"downloading: {device_id} ({i+1}/{total_devices})",
            #         0.1 + (i / total_devices) * 0.7
            #     )
            #
            #     try:
            #         await self._process_single_device(
            #             device_id, contents, start_time, end_time,
            #             data_table_start, data_table_end, work_dir,
            #             thumbnail, rename_images, rename_format
            #         )
            #         results["processed_devices"] += 1
            #
            #     except Exception as e:
            #         error_msg = f"设备 {device_id} 处理失败: {str(e)}"
            #         self.logger.error(error_msg)
            #         results["failed_devices"].append(device_id)
            #         results["errors"].append(error_msg)

            # v2.2.5-
            # if self._cancelled:
            #     results["success"] = False
            #     results["errors"].append("下载任务被用户取消")
            #     self._update_progress("Download cancelled", 1.0)
            #     return results

            # 打包ZIP文件（如果需要）
            if is_zip and results["processed_devices"] > 0 and results["success"]:

                # v2.2.5-
                # # v2.2.4-
                # # self._update_progress("正在打包ZIP文件...", 0.9)
                # # v2.2.4+
                # # 根据结果决定最终提示，避免失败/致命错误时误报 completed
                # final_msg = "Download completed" if results.get("success") else "Download failed"
                # self._update_progress(final_msg, 1.0)

                zip_path = await self._create_zip_async(work_dir)
                results["zip_path"] = str(zip_path)
                self.logger.info(f"ZIP文件已创建: {zip_path}")
            
            self._update_progress("Download completed", 1.0)
            return results

        # v2.2.5+
        except asyncio.CancelledError:
            # 取消下载：这里直接返回，不要再 _update_progress
            results["success"] = False
            results["errors"].append("下载任务被用户取消")
            # download_path 已经写了就保留
            if work_dir is not None:
                results["download_path"] = str(work_dir)
            return results

        except Exception as e:
            self.logger.error(f"下载失败: {str(e)}")
            return {
                "success": False,
                "processed_devices": 0,
                "failed_devices": devices,
                "download_path": None,
                "zip_path": None,
                "errors": [str(e)]
            }
    
    async def _process_single_device(
        self,
        device_id: int,
        contents: List[str],
        start_time: datetime,
        end_time: datetime,
        data_table_start: datetime,
        data_table_end: datetime,
        work_dir: Path,
        thumbnail: bool,
        rename_images: bool,
        rename_format: Optional[str],
    ):
        """处理单个设备的数据下载"""
        device_path = work_dir / str(device_id)
        device_path.mkdir(exist_ok=True)

        # 获取设备配置
        config = await self._get_device_config_async(device_id)
        if not config:
            raise DownloadError(f"无法获取设备 {device_id} 的配置")

        config_data, config_image = self._parse_config(config)

        # 获取数据表信息
        table_infos = await self._get_table_infos_async(data_table_start, data_table_end)

        # 处理数据
        if "data" in contents:
            await self._download_device_data_async(
                device_id, start_time, end_time, table_infos,
                config_data, device_path
            )

        # 处理图片
        if "image" in contents:
            await self._download_device_images_async(
                device_id, start_time, end_time, table_infos,
                config_image, device_path, thumbnail, rename_images, rename_format
            )
    
    async def _get_device_config_async(self, device_id: int) -> Optional[Tuple]:
        """异步获取设备配置"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_device_config_sync, device_id)
    
    def _get_device_config_sync(self, device_id: int) -> Optional[Tuple]:
        """同步获取设备配置"""
        sql = (
            "SELECT * FROM `device_config` WHERE `device_id` = %s "
            "ORDER BY created_at DESC LIMIT 1"
        )
        try:
            with database_resource() as cursor:
                cursor.execute(sql, (device_id,))
                return cursor.fetchone()
        except Exception as e:
            raise DownloadError(f"获取设备配置失败: {str(e)}")
    
    async def _get_table_infos_async(self, start_dt: datetime, end_dt: datetime) -> List[Tuple]:
        """异步获取数据表信息"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_table_infos_sync, start_dt, end_dt)
    
    def _get_table_infos_sync(self, start_dt: datetime, end_dt: datetime) -> List[Tuple]:
        """同步获取数据表信息"""
        sql = (
            "SELECT * FROM `device_data_index` "
            "WHERE `start_at` >= %s AND `end_at` <= %s"
        )
        try:
            with database_resource() as cursor:
                cursor.execute(sql, (start_dt, end_dt))
                return cursor.fetchall()
        except Exception as e:
            raise DownloadError(f"获取数据表信息失败: {str(e)}")
    
    async def _download_device_data_async(
        self, device_id: int, start_time: datetime, end_time: datetime,
        table_infos: List[Tuple], config_data: Dict[str, str], device_path: Path
    ):
        """异步下载设备数据"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._download_device_data_sync,
            device_id, start_time, end_time, table_infos, config_data, device_path
        )
    
    def _download_device_data_sync(
        self, device_id: int, start_time: datetime, end_time: datetime,
        table_infos: List[Tuple], config_data: Dict[str, str], device_path: Path
    ):
        """同步下载设备数据"""
        datas = []
        
        # 从所有相关表中查询数据
        for table_info in table_infos:
            table_name = table_info[3]
            sql = (
                "SELECT * FROM `{}` WHERE `ts` BETWEEN %s AND %s "
                "AND `device_id` = %s AND `type` = 'data'"
            ).format(table_name)
            
            try:
                with database_resource() as cursor:
                    cursor.execute(sql, (start_time, end_time, device_id))
                    datas.extend(cursor.fetchall())
            except Exception as e:
                self.logger.warning(f"查询表 {table_name} 失败: {str(e)}")
        
        if datas:
            self._save_data_to_excel(datas, config_data, device_path, start_time, end_time)

    # v2.2.4+
    async def _download_device_images_async(
            self, device_id: int, start_time: datetime, end_time: datetime,
            table_infos: List[Tuple], config_image: Dict[str, str], device_path: Path,
            thumbnail: bool, rename_images: bool, rename_format: Optional[str]
    ):
        """异步下载设备图片（队列 + 限并发 + 可选限速 + fatal 后立刻停止请求但继续清队列）"""

        # 查询图片数据：丢到线程里，避免卡死 event loop（关键）
        self._raise_if_cancelled()
        loop = asyncio.get_running_loop()

        # v2.2.5+
        def _query_images_sync(table_infos, start_time, end_time, device_id):
            imgs = []
            for table_info in table_infos:
                if self._cancelled:
                    break
                table_name = table_info[3]
                sql = (
                    "SELECT * FROM `{}` WHERE `ts` BETWEEN %s AND %s "
                    "AND `device_id` = %s AND `type` = 'image'"
                ).format(table_name)
                try:
                    with database_resource() as cursor:
                        cursor.execute(sql, (start_time, end_time, device_id))
                        imgs.extend(cursor.fetchall())
                except Exception as e:
                    self.logger.warning(f"查询图片表 {table_name} 失败: {str(e)}")
            return imgs

        images = await loop.run_in_executor(
            None, _query_images_sync, table_infos, start_time, end_time, device_id
        )
        self._raise_if_cancelled()

        if not images:
            return

        concurrency = max(1, int(getattr(self, "image_concurrency", 10)))
        qmax = max(50, concurrency * 5)
        queue: asyncio.Queue = asyncio.Queue(maxsize=qmax)

        throttler = _AsyncThrottle(getattr(self, "image_min_interval", 0.0))
        max_retries = int(getattr(self, "image_max_retries", 0))

        fatal_event = asyncio.Event()
        first_fatal_msg: Dict[str, Optional[str]] = {"msg": None}

        def _image_paths_from_row(img_row: Tuple) -> str:
            """从一条 image 记录里提取所有 value['value'] 路径，方便日志定位"""
            try:
                d = json.loads(img_row[3]) if img_row[3] else {}
                if isinstance(d, dict):
                    paths = []
                    for _, v in d.items():
                        if isinstance(v, dict) and "value" in v:
                            paths.append(str(v["value"]))
                    return ", ".join(paths) if paths else "<unknown>"
            except Exception:
                pass
            return "<unknown>"

        async def worker(worker_id: int):
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return

                    if fatal_event.is_set():
                        # fatal 已发生：不再发请求，但给“每个图片”打一条 FATAL（跳过日志）
                        self.logger.error(
                            f"[FATAL] 已停止下载，跳过图片: {_image_paths_from_row(item)}；原因: {first_fatal_msg['msg']}"
                        )
                        continue

                    # fatal/取消后不要 return，要继续 drain 队列直到拿到 None
                    if self._cancelled:
                        # 用户取消：不再发请求，但把队列清掉
                        continue

                    try:
                        await self._download_single_image_async(
                            item, config_image, device_path,
                            thumbnail, rename_images, rename_format,
                            throttler=throttler,
                            max_retries=max_retries,
                        )
                    except DownloadError as e:
                        # 第一次致命错误：记录原因 + 触发停止
                        if not fatal_event.is_set():
                            first_fatal_msg["msg"] = str(e)
                            fatal_event.set()

                        # 你要“每个图片一条 fatal”：这里对当前失败图片也打一条
                        self.logger.error(
                            f"[FATAL] 图片下载失败: {_image_paths_from_row(item)}；原因: {e}"
                        )
                        # 不 return，继续 drain
                        continue

                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker(i)) for i in range(concurrency)]

        # producer：fatal/取消后停止继续塞任务
        for img in images:
            if self._cancelled or fatal_event.is_set():
                break
            await queue.put(img)

        # 发送退出信号
        for _ in range(concurrency):
            await queue.put(None)

        # 等待队列完全处理完（fatal 后 worker 会快速 drain，所以这里会很快结束）
        await queue.join()

        # 回收 workers
        await asyncio.gather(*workers, return_exceptions=True)

        # 如果是 fatal 导致的停止：向上抛，确保上层立刻停止整次下载
        if fatal_event.is_set() and first_fatal_msg["msg"]:
            raise DownloadError(first_fatal_msg["msg"])


    # v2.2.4-
    # # v2.2.3-
    # async def _download_device_images_async(
    #     self, device_id: int, start_time: datetime, end_time: datetime,
    #     table_infos: List[Tuple], config_image: Dict[str, str], device_path: Path,
    #     thumbnail: bool, rename_images: bool, rename_format: Optional[str]
    # ):
    #     """异步下载设备图片"""
    #     images = []
    #
    #     # 从所有相关表中查询图片数据
    #     for table_info in table_infos:
    #         table_name = table_info[3]
    #         sql = (
    #             "SELECT * FROM `{}` WHERE `ts` BETWEEN %s AND %s "
    #             "AND `device_id` = %s AND `type` = 'image'"
    #         ).format(table_name)
    #
    #         try:
    #             with database_resource() as cursor:
    #                 cursor.execute(sql, (start_time, end_time, device_id))
    #                 images.extend(cursor.fetchall())
    #         except Exception as e:
    #             self.logger.warning(f"查询图片表 {table_name} 失败: {str(e)}")
    #
    #     # 并行下载图片
    #     if images:
    #         tasks = []
    #         for image in images:
    #             task = self._download_single_image_async(
    #                 image, config_image, device_path, thumbnail, rename_images, rename_format
    #             )
    #             tasks.append(task)
    #
    #         if tasks:
    #             await asyncio.gather(*tasks, return_exceptions=True)

    # v2.2.3+"_download_single_image_async"
    async def _download_single_image_async(
            self, image: Tuple, config_image: Dict[str, str], device_path: Path,
            thumbnail: bool, rename_images: bool, rename_format: Optional[str],
            throttler: Optional[_AsyncThrottle] = None,
            max_retries: int = 0,
    ):
        """异步下载单张图片（受队列worker控制并发；内部可限速/重试）"""

        def _should_retry(e: Exception) -> bool:
            s = str(e).lower()
            return any(x in s for x in [
                "429", "too many", "throttle", "rate", "503", "timeout",
                "temporarily", "connection", "reset", "closed", "busy", "servererror"
            ])

        async def _run_oss_call(callable_fn, *args):
            loop = asyncio.get_running_loop()
            retries = max(0, int(max_retries))
            for attempt in range(retries + 1):
                try:
                    if throttler is not None:
                        await throttler.wait()
                    return await loop.run_in_executor(None, callable_fn, *args)
                except Exception as e:
                    if attempt >= retries or not _should_retry(e):
                        raise
                    await asyncio.sleep(0.5 * (2 ** attempt))

        current_object = "<unknown>"

        try:
            image_data = json.loads(image[3]) if image[3] else {}

            if not isinstance(image_data, dict):
                return

            for key, value in image_data.items():
                if key in config_image:
                    key_dir = device_path / config_image[key]
                else:
                    key_dir = device_path / key

                key_dir.mkdir(exist_ok=True)

                image_path = value["value"]
                if image_path.startswith("/"):
                    image_path = image_path[1:]
                current_object = image_path  # 记录当前对象，方便报错定位

                raw_filename = Path(image_path).name
                suffix = Path(raw_filename).suffix

                target_filename = raw_filename
                if rename_images:
                    parts = Path(raw_filename).stem.split("_")
                    if len(parts) >= 2 and parts[1].isdigit():
                        try:
                            timestamp = int(parts[1])
                            dt = datetime.fromtimestamp(timestamp)
                            if rename_format:
                                base = self._sanitize_filename(dt.strftime(rename_format))
                            else:
                                base = parts[1]
                        except (ValueError, OverflowError):
                            base = Path(raw_filename).stem
                    else:
                        base = Path(raw_filename).stem
                    target_filename = f"{base}{suffix}"

                local_path = key_dir / target_filename
                if local_path.exists():
                    idx = 1
                    while True:
                        alt = key_dir / f"{Path(target_filename).stem}_{idx}{suffix}"
                        if not alt.exists():
                            local_path = alt
                            break
                        idx += 1

                if local_path.exists():
                    continue

                if thumbnail:
                    def _download_thumb():
                        obj = self.bucket.get_object(image_path, process='style/small')
                        with open(local_path, 'wb') as f:
                            data = obj.read()
                            if data:
                                f.write(data)

                    await _run_oss_call(_download_thumb)
                else:
                    await _run_oss_call(self.bucket.get_object_to_file, image_path, str(local_path))

        except Exception as e:
            msg, fatal = self._classify_error(e)
            if fatal:
                # 这里不要 self.cancel()，也不要疯狂打印 N 次 FATAL
                # fatal 的“停止整个下载”和“每条图片日志”交给 worker 去做
                raise DownloadError(f"{msg} (object={current_object})")
            else:
                self.logger.warning(f"下载图片失败(可忽略): {msg} (object={current_object})")
        # v2.2.4-
        # # v2.2.4-
        # # except Exception as e:
        # #     self.logger.warning(f"下载图片失败: {str(e)}")
        #
        # # v2.2.4+
        # except Exception as e:
        #     msg, fatal = self._classify_error(e)
        #     if fatal:
        #         # 标记取消，尽量让其它协程尽快停止
        #         self.cancel()
        #         self.logger.error(f"[FATAL] {msg}")
        #         raise DownloadError(msg)
        #     else:
        #         self.logger.warning(f"下载图片失败(可忽略): {msg}")

    # v2.2.3-
    # async def _download_single_image_async(
    #     self, image: Tuple, config_image: Dict[str, str], device_path: Path,
    #     thumbnail: bool, rename_images: bool, rename_format: Optional[str]
    # ):
    #     """异步下载单张图片"""
    #     try:
    #         image_data = json.loads(image[3])
    #
    #         for key, value in image_data.items():
    #             if key in config_image:
    #                 key_dir = device_path / config_image[key]
    #             else:
    #                 key_dir = device_path / key
    #
    #             key_dir.mkdir(exist_ok=True)
    #
    #             image_path = value["value"]
    #             if image_path.startswith("/"):
    #                 image_path = image_path[1:]
    #
    #             # 原始文件名与扩展名
    #             raw_filename = Path(image_path).name
    #             suffix = Path(raw_filename).suffix  # 包含点
    #
    #             # 计算重命名文件名
    #             target_filename = raw_filename
    #             if rename_images:
    #                 # 取原始名中的第二个时间戳
    #                 parts = Path(raw_filename).stem.split("_")
    #                 timestamp_str = None
    #                 if len(parts) >= 2 and parts[1].isdigit():
    #                     timestamp_str = parts[1]
    #                     # 将UNIX时间戳转换为datetime对象
    #                     try:
    #                         timestamp = int(timestamp_str)
    #                         dt = datetime.fromtimestamp(timestamp)
    #
    #                         if rename_format:
    #                             # 使用提供的格式将时间戳格式化为人类可读的字符串
    #                             base = dt.strftime(rename_format)
    #                             # 替换Windows文件系统中的非法字符
    #                             base = self._sanitize_filename(base)
    #                         else:
    #                             # 如果没有提供格式，就使用时间戳
    #                             base = timestamp_str
    #                     except (ValueError, OverflowError):
    #                         # 如果时间戳无效，回退到使用原始文件名
    #                         base = Path(raw_filename).stem
    #                 else:
    #                     # 如果找不到时间戳部分，使用原始文件名
    #                     base = Path(raw_filename).stem
    #
    #                 target_filename = f"{base}{suffix}"
    #
    #             # 如果同名存在，自动加序号避免覆盖
    #             local_path = key_dir / target_filename
    #             if local_path.exists():
    #                 idx = 1
    #                 while True:
    #                     alt = key_dir / f"{Path(target_filename).stem}_{idx}{suffix}"
    #                     if not alt.exists():
    #                         local_path = alt
    #                         break
    #                     idx += 1
    #
    #             # 避免重复下载（如果同名文件已经存在则跳过）
    #             if not local_path.exists():
    #                 loop = asyncio.get_event_loop()
    #                 if thumbnail:
    #                     # 使用 process 参数下载缩略图
    #                     def _download_thumb():
    #                         obj = self.bucket.get_object(image_path, process='style/small')
    #                         with open(local_path, 'wb') as f:
    #                             data = obj.read()
    #                             if data:
    #                                 f.write(data)
    #                     await loop.run_in_executor(None, _download_thumb)
    #                 else:
    #                     await loop.run_in_executor(
    #                         None, self.bucket.get_object_to_file, image_path, str(local_path)
    #                     )
    #
    #     except Exception as e:
    #         self.logger.warning(f"下载图片失败: {str(e)}")

    def _parse_config(self, config: Tuple) -> Tuple[Dict[str, str], Dict[str, str]]:
        """解析设备配置"""
        config_dict_data = {}
        config_dict_image = {}
        
        try:
            if config[-3] == "2.0":
                # 版本2.0配置格式
                data_config = json.loads(config[2])
                image_config = json.loads(config[3])
                
                for data_sensor in data_config:
                    contents = data_sensor["params"]["contents"]
                    for item in contents:
                        config_dict_data[item["key"]] = (
                            item["info"]["name"] + "(" + item["info"]["unit"] + ")"
                        )
                
                for item in image_config:
                    config_dict_image[item["key"]] = item["name"]
            
            elif config[-3] == "1.0":
                # 版本1.0配置格式
                data_config = json.loads(config[2])
                for k, v in data_config.items():
                    if v["type"] == "image":
                        config_dict_image[k] = v["desc"]
                    else:
                        config_dict_data[k] = v["desc"]
            
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            self.logger.error(f"解析配置失败: {str(e)}")
            raise DownloadError(f"设备配置格式错误: {str(e)}")
        
        return config_dict_data, config_dict_image

    def _save_data_to_excel(
            self, datas: List[Tuple], config_data: Dict[str, str],
            device_path: Path, start_time: datetime, end_time: datetime
    ):
        """保存数据到Excel文件"""
        if not datas:
            return

        # ===== 新功能：按 JSON 原始 key 输出（不映射、不过滤）=====
        if getattr(self, "export_raw_keys", False):
            rows = []
            seen_keys = []
            seen_set = set()

            for row in datas:
                one = {"time": row[4]}
                try:
                    row_data = json.loads(row[3]) if row[3] else {}
                except json.JSONDecodeError:
                    row_data = {}

                if isinstance(row_data, dict):
                    for k, v in row_data.items():
                        if isinstance(v, dict):
                            one[k] = v.get("value")
                        else:
                            one[k] = v

                        if k not in seen_set:
                            seen_set.add(k)
                            seen_keys.append(k)

                rows.append(one)

            df = pd.DataFrame(rows)

            cols = ["time"] + [k for k in seen_keys if k in df.columns]
            cols += [c for c in df.columns if c not in cols]
            df = df[cols].dropna(axis=1, how="all")

            filename = f"data_rawkeys_{start_time.strftime('%Y%m%d')}_to_{end_time.strftime('%Y%m%d')}.xlsx"
            file_path = device_path / filename

            if file_path.exists():
                try:
                    existing_df = pd.read_excel(file_path)
                    combined_df = pd.concat([existing_df, df], ignore_index=True)
                    if "time" in combined_df.columns:
                        combined_df = combined_df.drop_duplicates(subset=["time"]).sort_values("time")
                    combined_df.to_excel(file_path, index=False)
                except Exception as e:
                    self.logger.warning(f"合并现有文件失败: {str(e)}")
                    df.to_excel(file_path, index=False)
            else:
                df.to_excel(file_path, index=False)

            return  # 新功能写完直接返回，不走旧逻辑

        # ===== 旧逻辑：原来使用 config_data 映射列名的代码（保持不变）=====
        data_dict = {"time": [row[4] for row in datas]}

        for desc in config_data.values():
            data_dict[desc] = [None] * len(datas)

        for i, row in enumerate(datas):
            try:
                row_data = json.loads(row[3])
                for key, value in row_data.items():
                    if key in config_data:
                        data_dict[config_data[key]][i] = value.get("value")
            except (json.JSONDecodeError, KeyError):
                continue

        df = pd.DataFrame(data_dict)

        columns = ["time"]
        config_columns = list(config_data.values())
        existing_config_columns = [col for col in config_columns if col in df.columns]
        columns.extend(existing_config_columns)

        remaining_columns = [col for col in df.columns if col not in columns]
        columns.extend(remaining_columns)

        final_columns = [col for col in columns if col in df.columns]
        df = df[final_columns]

        df = df.dropna(axis=1, how='all')

        filename = f"data_{start_time.strftime('%Y%m%d')}_to_{end_time.strftime('%Y%m%d')}.xlsx"
        file_path = device_path / filename

        if file_path.exists():
            try:
                existing_df = pd.read_excel(file_path)
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=['time']).sort_values('time')
                combined_df.to_excel(file_path, index=False)
            except Exception as e:
                self.logger.warning(f"合并现有文件失败: {str(e)}")
                df.to_excel(file_path, index=False)
        else:
            df.to_excel(file_path, index=False)

    async def _create_zip_async(self, source_dir: Path) -> Path:
        """异步创建ZIP文件"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._create_zip_sync, source_dir)
    
    def _create_zip_sync(self, source_dir: Path) -> Path:
        """同步创建ZIP文件"""
        zip_path = self.root_path / f"device_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob('*'):
                if file_path.is_file():
                    arc_path = file_path.relative_to(source_dir)
                    zf.write(file_path, arc_path)
        
        return zip_path
    
    @staticmethod
    def _get_last_day_of_month(year: int, month: int) -> int:
        """获取月份的最后一天"""
        if month == 2:
            if year % 400 == 0 or (year % 100 != 0 and year % 4 == 0):
                return 29
            return 28
        elif month in [1, 3, 5, 7, 8, 10, 12]:
            return 31
        else:
            return 30
    
    async def test_connections(self) -> Dict[str, bool]:
        """测试数据库和OSS连接"""
        results = {"database": False, "oss": False}
        
        # 测试数据库连接
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._test_database_connection)
            results["database"] = True
        except Exception as e:
            self.logger.error(f"数据库连接测试失败: {str(e)}")
        
        # 测试OSS连接
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.bucket.get_bucket_info
            )
            results["oss"] = True
        except Exception as e:
            self.logger.error(f"OSS连接测试失败: {str(e)}")
        
        return results
    
    def _test_database_connection(self):
        """测试数据库连接"""
        try:
            with database_resource() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as e:
            raise DownloadError(f"数据库连接失败: {str(e)}")
    # v2.2.4
    def _classify_error(self, e: Exception) -> tuple[str, bool]:
        """
        返回 (人类可读错误信息, 是否致命fatal)
        fatal=True 表示：网络/连接中断/被拒绝/超时等 -> 应停止整个下载
        """
        # oss2 常见网络错误
        if isinstance(e, (oss2.exceptions.RequestError, oss2.exceptions.ServerError)):
            return f"网络/OSS请求失败: {e}", True

        # 常见 socket/SSL/超时/连接错误
        if isinstance(e, (socket.timeout, TimeoutError)):
            return f"网络超时: {e}", True
        if isinstance(e, (ConnectionError, BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return f"网络连接中断: {e}", True
        if isinstance(e, ssl.SSLError):
            return f"SSL连接错误: {e}", True

        # OSError 类：WinError 10054/10053/10060 等也会落到这里
        if isinstance(e, OSError):
            # Windows 常见：10054 连接被远程重置；10060 连接超时；10053 软件导致连接中止
            win_err = getattr(e, "winerror", None)
            if win_err in (10054, 10053, 10060, 10061):
                return f"网络连接异常(WinError {win_err}): {e}", True
            # Linux/mac 常见 errno
            if getattr(e, "errno", None) in (errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNREFUSED, errno.ENETUNREACH):
                return f"网络连接异常(errno {e.errno}): {e}", True

        # 其他默认：非致命（按设备失败继续）
        return f"{type(e).__name__}: {e}", False

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        # Windows文件系统中的非法字符
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        
        # 替换非法字符
        for char in illegal_chars:
            if char in filename:
                # 替换冒号为连字符，其他字符为下划线
                replacement = '-' if char == ':' else '_'
                filename = filename.replace(char, replacement)
        
        # 确保文件名不超过255字符（Windows限制）
        if len(filename) > 255:
            filename = filename[:255]
            
        return filename
    
    def cleanup(self):
        """清理临时文件"""
        try:
            if self.zipfile_path.exists():
                self.zipfile_path.unlink()
            
            # 清理空目录
            for item in self.root_path.iterdir():
                if item.is_dir() and not any(item.iterdir()):
                    shutil.rmtree(item)
                    
        except Exception as e:
            self.logger.warning(f"清理文件失败: {str(e)}")

    # v2.2.7+
    async def get_latest_device_data_async(self, device_id: int) -> Optional[Dict[str, Any]]:
        """
        查询某设备最新一条 data 记录（跨最近的分表）。
        返回：None 或 {"table": table_name, "row": raw_row_tuple}
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_latest_device_data_sync, device_id)

    # v2.2.7+
    def _get_latest_device_data_sync(self, device_id: int) -> Optional[Dict[str, Any]]:
        """
        同步版本：按 device_data_index 的 end_at 倒序找最近分表，
        每张表查 device_id 最新一条 type='data' 记录。
        """
        try:
            with database_resource() as cursor:
                cursor.execute("SELECT * FROM device_data_index ORDER BY end_at DESC LIMIT 30")
                index_rows = cursor.fetchall()
        except Exception as e:
            self.logger.error(f"查询 device_data_index 失败: {e}")
            return None

        for info in index_rows:
            table_name = info[3]
            sql = f"SELECT * FROM `{table_name}` WHERE device_id=%s AND `type`='data' ORDER BY ts DESC LIMIT 1"
            try:
                with database_resource() as cursor:
                    cursor.execute(sql, (device_id,))
                    row = cursor.fetchone()
                if row:
                    return {"table": table_name, "row": row}
            except Exception:
                # 某张表查不了就跳过继续
                continue

        return None