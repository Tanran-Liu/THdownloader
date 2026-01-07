#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build Simple Downloader with PyInstaller
"""

import os
import shutil
import sys
from pathlib import Path
import PyInstaller.__main__

def clean_build_dirs():
    """Clean build directories"""
    dirs_to_clean = ['build', 'dist', '__pycache__', 'config/__pycache__', 'download/__pycache__']

    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            try:
                print(f"Cleaning directory: {dir_name}")
                shutil.rmtree(dir_name)
            except PermissionError:
                print(f"Warning: Cannot delete {dir_name} (file might be in use)")
            except Exception as e:
                print(f"Warning: Error cleaning {dir_name}: {e}")

def build_app():
    """Build the application"""
    print("Starting to build Simple Downloader...")
    
    # Clean previous build files
    clean_build_dirs()
    
    # PyInstaller arguments
    args = [
        'simple_downloader.py',
        '--onefile',
        '--windowed',
        '--name=Tashigang Data Downloader',
        
        # Add data files
        '--add-data=config;config',
        '--add-data=download;download',

        # Add necessary files from third-party libraries
        '--add-data=.venv/Lib/site-packages/mysql;mysql',
        '--add-data=.venv/Lib/site-packages/ttkthemes;ttkthemes',
        
        # Project modules
        '--hidden-import=config',
        '--hidden-import=config.config',
        '--hidden-import=download',
        '--hidden-import=download.async_downloader',
        '--hidden-import=download.db',
        
        # Tkinter related
        '--hidden-import=tkinter.font',
        '--hidden-import=tkinter.scrolledtext',
        
        # MySQL connector related - simplified version because it's already included via add-data
        '--hidden-import=mysql.connector',
        '--hidden-import=mysql.connector.errorcode',
        '--hidden-import=mysql.connector.errors',

        # Exclude C extensions, force use of pure Python version
        '--exclude-module=_mysql_connector',
        
        # OSS2 related
        '--hidden-import=oss2',
        '--hidden-import=oss2.auth',
        '--hidden-import=oss2.api',
        '--hidden-import=oss2.models',
        '--hidden-import=oss2.exceptions',
        '--hidden-import=oss2.utils',
        '--hidden-import=oss2.http',
        '--hidden-import=oss2.compat',
        '--hidden-import=oss2.iterators',
        
        # Data processing related
        '--hidden-import=pandas',
        '--hidden-import=pandas._libs.tslibs',
        '--hidden-import=pandas.io.formats.style',
        '--hidden-import=openpyxl',
        '--hidden-import=openpyxl.workbook',
        '--hidden-import=openpyxl.worksheet',
        
        # Image processing
        '--hidden-import=PIL',
        '--hidden-import=PIL._imaging',
        '--hidden-import=PIL.Image',
        '--hidden-import=PIL.ImageTk',
        
        # ttkthemes - simplified version because it's already included via add-data
        '--hidden-import=ttkthemes',
        
        # Other necessary modules
        '--hidden-import=cryptography.hazmat.backends.openssl',
        '--hidden-import=dateutil.parser',
        '--hidden-import=dateutil.tz',
        
        # Exclude unnecessary modules
        '--exclude-module=matplotlib',
        '--exclude-module=scipy',
        '--exclude-module=IPython',
        '--exclude-module=jupyter',
        '--exclude-module=notebook',
        '--exclude-module=pytest',
        '--exclude-module=test',
        '--exclude-module=tests',
        '--exclude-module=unittest',
        
        # Other options
        '--clean',
        '--noconfirm',
    ]
    
    print("PyInstaller arguments:")
    for arg in args:
        print(f"  {arg}")
    print()
    
    try:
        # Run PyInstaller
        PyInstaller.__main__.run(args)
        
        # Check result
        exe_path = Path('dist/Tashigang Data Downloader.exe')
        if exe_path.exists():
            print(f"\n✓ Build successful!")
            print(f"Executable location: {exe_path.absolute()}")
            print(f"File size: {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
            return True
        else:
            print("\n✗ Build failed: Could not find generated exe file")
            return False
            
    except Exception as e:
        print(f"\n✗ Error during build process: {e}")
        return False

def main():
    """Main function"""
    print("Tashigang Data Downloader - PyInstaller Build Tool")
    print("=" * 50)
    
    if build_app():
        print("\nBuild completed!")
        
        # Ask whether to run a test
        try:
            response = input("\nRun the generated exe file for testing? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                exe_path = Path('dist/Tashigang Data Downloader.exe')
                if exe_path.exists():
                    print("Starting application...")
                    os.startfile(str(exe_path))
        except KeyboardInterrupt:
            print("\nUser cancelled")
    else:
        print("\nBuild failed!")
        print("Check the error messages, you might need to:")
        print("1. Check if dependencies are correctly installed")
        print("2. Look at warning files in the build directory")
        print("3. Add missing hidden-imports")

if __name__ == "__main__":
    main()
