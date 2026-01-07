#!/usr/bin/env python3
"""
异步设备数据下载器
"""

import asyncio
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple
import logging

import oss2
import pandas as pd
from download.db import database_resource
from config.config import THCPN_DB_CONFIG


class DownloadError(Exception):
    """下载过程中的自定义异常"""
    pass


class AsyncDeviceDataDownloader:
    """异步设备数据下载器"""
    
    def __init__(self, root_path: str = './tmp/', logger: Optional[logging.Logger] = None):
        self.root_path = Path(root_path)
        self.logger = logger or logging.getLogger(__name__)
        
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
    
    def set_progress_callback(self, callback: Callable[[str, float], None]):
        """设置进度回调函数"""
        self._progress_callback = callback
    
    def cancel(self):
        """取消下载任务"""
        self._cancelled = True
        self.logger.info("下载任务已取消")
    
    def _update_progress(self, message: str, progress: float):
        """更新进度"""
        if self._cancelled:
            raise DownloadError("下载任务已取消")
        
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
            
            total_devices = len(devices)
            results = {
                "success": True,
                "processed_devices": 0,
                "failed_devices": [],
                "download_path": str(work_dir),
                "zip_path": None,
                "errors": []
            }
            
            # 处理每个设备
            for i, device_id in enumerate(devices):
                if self._cancelled:
                    break
                    
                self._update_progress(
                    f"downloading: {device_id} ({i+1}/{total_devices})", 
                    0.1 + (i / total_devices) * 0.7
                )
                
                try:
                    await self._process_single_device(
                        device_id, contents, start_time, end_time,
                        data_table_start, data_table_end, work_dir,
                        thumbnail, rename_images, rename_format
                    )
                    results["processed_devices"] += 1
                    
                except Exception as e:
                    error_msg = f"设备 {device_id} 处理失败: {str(e)}"
                    self.logger.error(error_msg)
                    results["failed_devices"].append(device_id)
                    results["errors"].append(error_msg)
            
            if self._cancelled:
                results["success"] = False
                results["errors"].append("下载任务被用户取消")
                return results
            
            # 打包ZIP文件（如果需要）
            if is_zip and results["processed_devices"] > 0:
                self._update_progress("正在打包ZIP文件...", 0.9)
                zip_path = await self._create_zip_async(work_dir)
                results["zip_path"] = str(zip_path)
                self.logger.info(f"ZIP文件已创建: {zip_path}")
            
            self._update_progress("Download completed", 1.0)
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
    
    async def _download_device_images_async(
        self, device_id: int, start_time: datetime, end_time: datetime,
        table_infos: List[Tuple], config_image: Dict[str, str], device_path: Path,
        thumbnail: bool, rename_images: bool, rename_format: Optional[str]
    ):
        """异步下载设备图片"""
        images = []

        # 从所有相关表中查询图片数据
        for table_info in table_infos:
            table_name = table_info[3]
            sql = (
                "SELECT * FROM `{}` WHERE `ts` BETWEEN %s AND %s "
                "AND `device_id` = %s AND `type` = 'image'"
            ).format(table_name)

            try:
                with database_resource() as cursor:
                    cursor.execute(sql, (start_time, end_time, device_id))
                    images.extend(cursor.fetchall())
            except Exception as e:
                self.logger.warning(f"查询图片表 {table_name} 失败: {str(e)}")

        # 并行下载图片
        if images:
            tasks = []
            for image in images:
                task = self._download_single_image_async(
                    image, config_image, device_path, thumbnail, rename_images, rename_format
                )
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _download_single_image_async(
        self, image: Tuple, config_image: Dict[str, str], device_path: Path,
        thumbnail: bool, rename_images: bool, rename_format: Optional[str]
    ):
        """异步下载单张图片"""
        try:
            image_data = json.loads(image[3])

            for key, value in image_data.items():
                if key in config_image:
                    key_dir = device_path / config_image[key]
                else:
                    key_dir = device_path / key

                key_dir.mkdir(exist_ok=True)

                image_path = value["value"]
                if image_path.startswith("/"):
                    image_path = image_path[1:]

                # 原始文件名与扩展名
                raw_filename = Path(image_path).name
                suffix = Path(raw_filename).suffix  # 包含点

                # 计算重命名文件名
                target_filename = raw_filename
                if rename_images:
                    # 取原始名中的第二个时间戳
                    parts = Path(raw_filename).stem.split("_")
                    timestamp_str = None
                    if len(parts) >= 2 and parts[1].isdigit():
                        timestamp_str = parts[1]
                        # 将UNIX时间戳转换为datetime对象
                        try:
                            timestamp = int(timestamp_str)
                            dt = datetime.fromtimestamp(timestamp)
                            
                            if rename_format:
                                # 使用提供的格式将时间戳格式化为人类可读的字符串
                                base = dt.strftime(rename_format)
                                # 替换Windows文件系统中的非法字符
                                base = self._sanitize_filename(base)
                            else:
                                # 如果没有提供格式，就使用时间戳
                                base = timestamp_str
                        except (ValueError, OverflowError):
                            # 如果时间戳无效，回退到使用原始文件名
                            base = Path(raw_filename).stem
                    else:
                        # 如果找不到时间戳部分，使用原始文件名
                        base = Path(raw_filename).stem
                        
                    target_filename = f"{base}{suffix}"

                # 如果同名存在，自动加序号避免覆盖
                local_path = key_dir / target_filename
                if local_path.exists():
                    idx = 1
                    while True:
                        alt = key_dir / f"{Path(target_filename).stem}_{idx}{suffix}"
                        if not alt.exists():
                            local_path = alt
                            break
                        idx += 1

                # 避免重复下载（如果同名文件已经存在则跳过）
                if not local_path.exists():
                    loop = asyncio.get_event_loop()
                    if thumbnail:
                        # 使用 process 参数下载缩略图
                        def _download_thumb():
                            obj = self.bucket.get_object(image_path, process='style/small')
                            with open(local_path, 'wb') as f:
                                data = obj.read()
                                if data:
                                    f.write(data)
                        await loop.run_in_executor(None, _download_thumb)
                    else:
                        await loop.run_in_executor(
                            None, self.bucket.get_object_to_file, image_path, str(local_path)
                        )

        except Exception as e:
            self.logger.warning(f"下载图片失败: {str(e)}")
    
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
        
        # 构建数据结构
        data_dict = {"time": [row[4] for row in datas]}
        
        # 初始化数据列
        for desc in config_data.values():
            data_dict[desc] = [None] * len(datas)
        
        # 填充数据
        for i, row in enumerate(datas):
            try:
                row_data = json.loads(row[3])
                for key, value in row_data.items():
                    if key in config_data:
                        data_dict[config_data[key]][i] = value.get("value")
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 创建DataFrame
        df = pd.DataFrame(data_dict)
        
        # 根据config_data动态定义列顺序
        # 确保"时间"列始终是第一列
        columns = ["time"]
        
        # 将config_data中的所有值添加到列中（如果在DataFrame中存在）
        config_columns = list(config_data.values())
        existing_config_columns = [col for col in config_columns if col in df.columns]
        columns.extend(existing_config_columns)
        
        # 如果有任何在DataFrame中但不在columns列表中的列，将它们添加到末尾
        remaining_columns = [col for col in df.columns if col not in columns]
        columns.extend(remaining_columns)
        
        # 只保留存在于DataFrame的列
        final_columns = [col for col in columns if col in df.columns]
        df = df[final_columns]
        
        # 去除空列
        df = df.dropna(axis=1, how='all')
        
        # 生成文件名
        filename = f"data_{start_time.strftime('%Y%m%d')}_to_{end_time.strftime('%Y%m%d')}.xlsx"
        file_path = device_path / filename
        
        # 处理已存在的文件
        if file_path.exists():
            try:
                existing_df = pd.read_excel(file_path)
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=['时间']).sort_values('时间')
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
