import asyncio
import logging
from datetime import datetime
from pathlib import Path
from download.async_downloader import AsyncDeviceDataDownloader, DownloadError

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

async def test_download():
    """测试下载函数"""
    # 设置下载参数
    device_id = 2594  # Tashigang Quinoa GIES Station (Bhutan)
    
    # 创建下载目录
    download_dir = Path("./tmp/test_download")
    download_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建下载器实例
    downloader = AsyncDeviceDataDownloader(root_path=str(download_dir))
    
    # 设置进度回调
    def progress_callback(message, progress):
        print(f"[{progress:.1%}] {message}")
    
    downloader.set_progress_callback(progress_callback)
    
    # 设置时间范围（下载一个月的数据）
    # 格式化为：YYYY-MM-DD HH:MM:SS
    year = 2025
    month = 8
    start_time = f"{year}-{month:02d}-01 00:00:00"
    end_time = f"{year}-{month:02d}-31 23:59:59"
    
    print(f"开始下载 设备ID: {device_id}")
    print(f"时间范围: {start_time} 到 {end_time}")
    print(f"下载目录: {download_dir}")
    
    try:
        # 测试连接
        print("测试连接...")
        connection_results = await downloader.test_connections()
        print(f"数据库连接: {'成功' if connection_results['database'] else '失败'}")
        print(f"OSS连接: {'成功' if connection_results['oss'] else '失败'}")
        
        if not (connection_results['database'] and connection_results['oss']):
            print("连接测试失败，无法继续下载")
            return
            
        # 开始下载
        results = await downloader.download_device_data(
            devices=[device_id],
            contents=["data","image"],  # 下载数据和图片
            start_at=start_time,
            end_at=end_time,
            is_zip=True,  # 打包为ZIP
            thumbnail=False,  # 不下载缩略图
            rename_images=True,  # 重命名图片
            rename_format=None  # 使用默认命名格式
        )
        
        # 处理结果
        if results["success"]:
            print("下载成功!")
            print(f"下载路径: {results['download_path']}")
            if results["zip_path"]:
                print(f"ZIP文件: {results['zip_path']}")
        else:
            print("下载失败!")
            for error in results["errors"]:
                print(f"错误: {error}")
                
    except DownloadError as e:
        print(f"下载错误: {e}")
    except Exception as e:
        print(f"未知错误: {e}")
        import traceback
        traceback.print_exc()

def main():
    """主函数"""
    # 运行异步测试函数
    asyncio.run(test_download())

if __name__ == '__main__':  # 注意这里修正为 '__main__'
    main()
