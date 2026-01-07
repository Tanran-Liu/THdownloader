#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备数据下载器 - 主入口
"""

import sys
import logging
import os
from tui_app import DownloadManagerApp


def main():
    """主函数"""
    # 设置系统编码
    import locale

    # 设置环境变量以支持中文
    if sys.platform.startswith('linux'):
        try:
            locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_ALL, 'C.UTF-8')
            except locale.Error:
                pass
        os.environ['LANG'] = 'zh_CN.UTF-8'
        os.environ['LC_ALL'] = 'zh_CN.UTF-8'
        os.environ['PYTHONIOENCODING'] = 'utf-8'

    # 强制设置标准输出编码
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('download.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # 启动Tkinter GUI应用
    try:
        app = DownloadManagerApp()
        app.run()
    except Exception as e:
        logging.error(f"应用启动失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
