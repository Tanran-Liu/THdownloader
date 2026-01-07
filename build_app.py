#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用PyInstaller打包应用
"""

import os
import shutil
import sys
from pathlib import Path
import PyInstaller.__main__

def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__', 'config/__pycache__', 'download/__pycache__']

    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            try:
                print(f"清理目录: {dir_name}")
                shutil.rmtree(dir_name)
            except PermissionError:
                print(f"警告: 无法删除 {dir_name} (文件可能正在使用中)")
            except Exception as e:
                print(f"警告: 清理 {dir_name} 时出错: {e}")

def build_app():
    """打包应用"""
    print("开始打包设备数据下载器...")
    
    # 清理之前的构建文件
    clean_build_dirs()
    
    # PyInstaller参数
    args = [
        'main.py',
        '--onefile',
        '--windowed',
        '--name=设备数据下载器',
        
        # 添加数据文件
        '--add-data=config;config',
        '--add-data=download;download',

        # 添加第三方库的必要文件
        '--add-data=.venv/Lib/site-packages/mysql;mysql',
        '--add-data=.venv/Lib/site-packages/ttkthemes;ttkthemes',
        
        # 项目模块
        '--hidden-import=config',
        '--hidden-import=config.config',
        '--hidden-import=download',
        '--hidden-import=download.async_downloader',
        '--hidden-import=download.db',
        '--hidden-import=tui_app',
        
        # Tkinter相关
        '--hidden-import=tkinter.font',
        '--hidden-import=tkinter.scrolledtext',
        
        # MySQL connector相关 - 简化版本，因为已通过add-data包含
        '--hidden-import=mysql.connector',
        '--hidden-import=mysql.connector.errorcode',
        '--hidden-import=mysql.connector.errors',

        # 排除C扩展，强制使用纯Python版本
        '--exclude-module=_mysql_connector',
        
        # OSS2相关
        '--hidden-import=oss2',
        '--hidden-import=oss2.auth',
        '--hidden-import=oss2.api',
        '--hidden-import=oss2.models',
        '--hidden-import=oss2.exceptions',
        '--hidden-import=oss2.utils',
        '--hidden-import=oss2.http',
        '--hidden-import=oss2.compat',
        '--hidden-import=oss2.iterators',
        
        # 数据处理相关
        '--hidden-import=pandas',
        '--hidden-import=pandas._libs.tslibs',
        '--hidden-import=pandas.io.formats.style',
        '--hidden-import=openpyxl',
        '--hidden-import=openpyxl.workbook',
        '--hidden-import=openpyxl.worksheet',
        
        # 图像处理
        '--hidden-import=PIL',
        '--hidden-import=PIL._imaging',
        '--hidden-import=PIL.Image',
        '--hidden-import=PIL.ImageTk',
        
        # ttkthemes - 简化版本，因为已通过add-data包含
        '--hidden-import=ttkthemes',
        
        # 其他必要模块
        '--hidden-import=cryptography.hazmat.backends.openssl',
        '--hidden-import=dateutil.parser',
        '--hidden-import=dateutil.tz',
        
        # 排除不需要的模块
        '--exclude-module=matplotlib',
        '--exclude-module=scipy',
        '--exclude-module=IPython',
        '--exclude-module=jupyter',
        '--exclude-module=notebook',
        '--exclude-module=pytest',
        '--exclude-module=test',
        '--exclude-module=tests',
        '--exclude-module=unittest',
        
        # 其他选项
        '--clean',
        '--noconfirm',
    ]
    
    print("PyInstaller参数:")
    for arg in args:
        print(f"  {arg}")
    print()
    
    try:
        # 运行PyInstaller
        PyInstaller.__main__.run(args)
        
        # 检查结果
        exe_path = Path('dist/设备数据下载器.exe')
        if exe_path.exists():
            print(f"\n✓ 打包成功!")
            print(f"可执行文件位置: {exe_path.absolute()}")
            print(f"文件大小: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
            return True
        else:
            print("\n✗ 打包失败: 未找到生成的exe文件")
            return False
            
    except Exception as e:
        print(f"\n✗ 打包过程中出现错误: {e}")
        return False

def main():
    """主函数"""
    print("设备数据下载器 - PyInstaller打包工具")
    print("=" * 50)
    
    if build_app():
        print("\n打包完成!")
        
        # 询问是否运行测试
        try:
            response = input("\n是否运行生成的exe文件进行测试? (y/n): ").strip().lower()
            if response in ['y', 'yes', '是']:
                exe_path = Path('dist/设备数据下载器.exe')
                if exe_path.exists():
                    print("启动应用...")
                    os.startfile(str(exe_path))
        except KeyboardInterrupt:
            print("\n用户取消")
    else:
        print("\n打包失败!")
        print("请检查错误信息，可能需要:")
        print("1. 检查依赖是否正确安装")
        print("2. 查看build目录下的警告文件")
        print("3. 添加缺失的hidden-import")

if __name__ == "__main__":
    main()
