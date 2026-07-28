#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件下载器
支持从给定的URL下载文件，使用YAML配置文件管理下载参数
"""

import os
import sys
import time
import logging
import requests
import yaml
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import Dict


class FileDownloader:
    """文件下载器类"""
    
    def __init__(self, config_path: str = None):
        """
        初始化下载器
        
        Args:
            config_path: 配置文件路径，默认为 ../config/download_config.yaml
        """
        if config_path is None:
            # 获取当前文件的目录，然后找到config文件夹
            current_dir = Path(__file__).parent
            config_path = current_dir.parent / "config" / "download_config.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._setup_logging()
        self.session = self._setup_session()
    
    def _load_config(self) -> Dict:
        """加载YAML配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
                logging.info(f"成功加载配置文件: {self.config_path}")
                return config
        except FileNotFoundError:
            logging.error(f"配置文件未找到: {self.config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logging.error(f"配置文件格式错误: {e}")
            sys.exit(1)
    
    def _setup_logging(self):
        """设置日志"""
        log_config = self.config.get('logging', {})
        log_level = getattr(logging, log_config.get('level', 'INFO').upper())
        log_format = log_config.get('log_format', '%(asctime)s - %(levelname)s - %(message)s')
        log_file = log_config.get('log_file', 'download.log')
        
        # 创建日志目录
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 配置日志
        logging.basicConfig(
            level=log_level,
            format=log_format,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
    
    def _setup_session(self) -> requests.Session:
        """设置请求会话"""
        session = requests.Session()
        download_config = self.config.get('download', {})
        
        # 设置用户代理
        headers = {
            'User-Agent': download_config.get('user_agent', 
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        }
        session.headers.update(headers)
        
        return session
    
    def _get_filename_from_url(self, url: str) -> str:
        """从URL中提取文件名"""
        parsed_url = urlparse(url)
        filename = os.path.basename(unquote(parsed_url.path))
        
        # 如果URL中没有文件名，生成一个默认文件名
        if not filename or '.' not in filename:
            timestamp = int(time.time())
            filename = f"download_{timestamp}"
        
        return filename
    
    def _is_allowed_file_type(self, filename: str) -> bool:
        """检查文件类型是否被允许"""
        download_config = self.config.get('download', {})
        allowed_extensions = download_config.get('allowed_extensions', [])
        
        # 如果没有限制，允许所有文件类型
        if not allowed_extensions:
            return True
        
        file_extension = Path(filename).suffix.lower()
        return file_extension in allowed_extensions
    
    def _check_file_size(self, response: requests.Response) -> bool:
        """检查文件大小是否超过限制"""
        download_config = self.config.get('download', {})
        max_size_mb = download_config.get('max_file_size_mb', 0)
        
        # 0表示无限制
        if max_size_mb == 0:
            return True
        
        content_length = response.headers.get('content-length')
        if content_length:
            file_size_mb = int(content_length) / (1024 * 1024)
            return file_size_mb <= max_size_mb
        
        return True  # 如果无法获取文件大小，允许下载
    
    def download_file(self, url: str, filename: str = None, download_dir: str = None) -> bool:
        """
        下载单个文件
        
        Args:
            url: 文件下载链接
            filename: 保存的文件名，如果为None则从URL中提取
            download_dir: 下载目录，如果为None则使用默认目录
        
        Returns:
            bool: 下载是否成功
        """
        download_config = self.config.get('download', {})
        
        # 设置下载目录
        if download_dir is None:
            download_dir = download_config.get('default_download_dir', 'downloads')
        
        # 设置文件名
        if filename is None or filename == "":
            filename = self._get_filename_from_url(url)
        
        # 检查文件类型
        if not self._is_allowed_file_type(filename):
            logging.warning(f"文件类型不被允许: {filename}")
            return False
        
        # 创建下载目录
        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)
        
        # 完整的文件路径
        file_path = download_path / filename
        
        # 如果文件已存在，跳过下载
        if file_path.exists():
            logging.info(f"文件已存在，跳过下载: {file_path}")
            return True
        
        try:
            logging.info(f"开始下载: {url}")
            
            # 发送请求
            timeout = download_config.get('timeout', 30)
            verify_ssl = download_config.get('verify_ssl', True)
            
            response = self.session.get(url, timeout=timeout, verify=verify_ssl, stream=True)
            response.raise_for_status()
            
            # 检查文件大小
            if not self._check_file_size(response):
                logging.error(f"文件大小超过限制: {url}")
                return False
            
            # 获取文件大小用于进度显示
            total_size = int(response.headers.get('content-length', 0))
            
            # 下载文件
            chunk_size = download_config.get('chunk_size', 8192)
            downloaded_size = 0
            
            with open(file_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 显示下载进度
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            print(f"\r下载进度: {progress:.1f}% ({downloaded_size}/{total_size} bytes)", end='')
            
            print()  # 换行
            logging.info(f"下载完成: {file_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logging.error(f"下载失败: {url}, 错误: {e}")
            return False
        except Exception as e:
            logging.error(f"下载过程中发生未知错误: {e}")
            return False
    
    def download_from_config(self) -> Dict[str, bool]:
        """
        从配置文件中读取下载任务并执行
        
        Returns:
            Dict[str, bool]: 下载结果，键为URL，值为是否成功
        """
        download_tasks = self.config.get('download_tasks', [])
        results = {}
        
        for task in download_tasks:
            url = task.get('url')
            filename = task.get('filename', '')
            download_dir = task.get('download_dir')
            
            if not url:
                logging.warning("跳过无效任务：缺少URL")
                continue
            
            success = self.download_file(url, filename, download_dir)
            results[url] = success
        
        return results
    
    def download_with_retry(self, url: str, filename: str = None, download_dir: str = None) -> bool:
        """
        带重试机制的文件下载
        
        Args:
            url: 文件下载链接
            filename: 保存的文件名
            download_dir: 下载目录
        
        Returns:
            bool: 下载是否成功
        """
        download_config = self.config.get('download', {})
        max_retries = download_config.get('max_retries', 3)
        
        for attempt in range(max_retries + 1):
            if attempt > 0:
                logging.info(f"重试下载 ({attempt}/{max_retries}): {url}")
                time.sleep(2 ** attempt)  # 指数退避
            
            if self.download_file(url, filename, download_dir):
                return True
        
        logging.error(f"下载失败，已达到最大重试次数: {url}")
        return False


def main():
    """主函数，提供命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='文件下载器')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--url', '-u', help='要下载的文件URL')
    parser.add_argument('--filename', '-f', help='保存的文件名')
    parser.add_argument('--dir', '-d', help='下载目录')
    parser.add_argument('--from-config', action='store_true', help='从配置文件中读取下载任务')
    
    args = parser.parse_args()
    
    # 创建下载器实例
    downloader = FileDownloader(args.config)
    
    if args.from_config:
        # 从配置文件下载
        results = downloader.download_from_config()
        success_count = sum(results.values())
        total_count = len(results)
        print(f"下载完成: {success_count}/{total_count} 个文件成功")
    elif args.url:
        # 下载单个文件
        success = downloader.download_with_retry(args.url, args.filename, args.dir)
        if success:
            print("文件下载成功")
        else:
            print("文件下载失败")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
