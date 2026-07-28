#!/usr/bin/env python3
"""
数据集更新管理器

两文件架构：
  config/update.json   — 外部发放的更新通知（只读，不修改）
  config/config.yaml   — 本地持久化缓存（版本号 + 密码），由程序自动维护

流程：
  1. 对比 update.json 与 config.yaml 的 version
  2. 版本相同 → 跳过更新
  3. 版本不同 → 下载 ZIP（已有且 SHA256 匹配则跳过）
  4. 尝试用 config.yaml 中缓存的密码解压
  5. 解压失败 → 提示用户手动获取密码（仅一次）→ 写入 config.yaml
"""

import hashlib
import json
import math
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, List
from urllib.parse import urlparse, unquote


class UpdateManager:
    """数据集更新管理器"""

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent
        self.project_root = project_root

        # 关键路径
        self.update_json_path = project_root / "config" / "update.json"
        self.cache_yaml_path = project_root / "config" / "config.yaml"
        self.download_config_path = project_root / "config" / "download_config.yaml"
        self.extract_config_path = project_root / "config" / "extract_config.yaml"

        self.download_dir = project_root / "comment"
        self.extract_dir = project_root / "comment" / "extracted"
        self.logs_dir = project_root / "logs"

        # 确保目录存在
        for d in [self.download_dir, self.extract_dir, self.logs_dir,
                  self.update_json_path.parent]:
            d.mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════
    #  工具方法
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def compute_sha256(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_file_sha256(filepath: Path) -> str:
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def compute_quick_jump_url(topic_id: str, floor_id: str) -> str:
        """快速跳转网址: ceil(floor_id / 10)"""
        page_id = math.ceil(int(floor_id) / 10)
        return f"https://www.cc98.org/topic/{topic_id}/{page_id}"

    @staticmethod
    def compute_forum_url(topic_id: str) -> str:
        return f"https://www.cc98.org/topic/{topic_id}/"

    @staticmethod
    def get_filename_from_url(url: str) -> str:
        return os.path.basename(unquote(urlparse(url).path))

    # ══════════════════════════════════════════════════════════
    #  update.json 读取
    # ══════════════════════════════════════════════════════════

    def load_update_json(self) -> Optional[Dict]:
        """加载 config/update.json。不存在则返回 None（无更新）。"""
        if not self.update_json_path.exists():
            return None
        try:
            with open(self.update_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"  ⚠️  update.json 格式错误: {e}")
            return None

    def validate_update_json(self, data: Dict) -> Optional[str]:
        """校验 update.json 必要字段，返回错误信息或 None"""
        for field in ["update_package_url", "check", "password"]:
            if field not in data:
                return f"缺少字段: {field}"
        check = data["check"]
        if check.get("type") != "sha256" or not check.get("value"):
            return "check 格式错误（需 type=sha256 + value）"
        pwd = data["password"]
        if pwd.get("type") != "sha256":
            return "password.type 必须为 sha256"
        for f in ["topic_id", "floor_id", "hint"]:
            if not pwd.get(f):
                return f"缺少 password.{f}"
        return None

    # ══════════════════════════════════════════════════════════
    #  config.yaml 缓存读写
    # ══════════════════════════════════════════════════════════

    def load_cache(self) -> Dict:
        """加载 config/config.yaml，不存在返回空 dict"""
        if self.cache_yaml_path.exists():
            with open(self.cache_yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_cache(self, data: Dict) -> None:
        """保存到 config/config.yaml"""
        self.cache_yaml_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def get_cached_password(self, filename: str) -> Optional[str]:
        """从 config.yaml 中查找已缓存的密码"""
        cache = self.load_cache()
        datasets = cache.get("datasets", {})
        ds = datasets.get(filename, {})
        return ds.get("password_raw")

    def set_cached_dataset(self, version: str, filename: str, url: str,
                           sha256: str, password_raw: str) -> None:
        """将数据集信息（含密码）写入 config.yaml"""
        cache = self.load_cache()
        cache["version"] = version

        datasets = cache.setdefault("datasets", {})
        datasets[filename] = {
            "url": url,
            "sha256": sha256,
            "password_raw": password_raw,
        }

        self.save_cache(cache)

    # ══════════════════════════════════════════════════════════
    #  用户交互：获取密码
    # ══════════════════════════════════════════════════════════

    def _verify_hint(self, content: str, hint: str) -> bool:
        """
        验证用户输入内容的 SHA256 是否匹配 hint。

        hint 格式为截断 SHA256: "0c4a1...c0d7fb"（前缀...后缀）
        完整 SHA256 需以 hint 前缀开头、以 hint 后缀结尾。
        """
        full_hash = self.compute_sha256(content)

        # 解析 hint: "prefix...suffix"
        if "..." not in hint:
            # 向后兼容：hint 可能是完整的 SHA256
            return full_hash == hint

        prefix, suffix = hint.split("...", 1)
        return full_hash.startswith(prefix) and full_hash.endswith(suffix)

    def prompt_password(self, topic_id: str, floor_id: str,
                        hint: str) -> Optional[str]:
        """提示用户手动获取楼层内容，验证 SHA256 后返回原始内容"""
        quick_jump_url = self.compute_quick_jump_url(topic_id, floor_id)
        forum_url = self.compute_forum_url(topic_id)

        print()
        print(f"  {'=' * 50}")
        print(f"  🔐 需要手动获取解压密码")
        print(f"  {'=' * 50}")
        print(f"  论坛帖子 : {forum_url}")
        print(f"  快速跳转 : {quick_jump_url}")
        print(f"  目标楼层 : 第 {floor_id} 楼")
        print(f"  SHA256   : {hint}")
        print(f"  {'=' * 50}")
        print(f"  ⚠️  论坛对爬虫有严格管控，无法自动获取。")
        print(f"  请手动打开 [快速跳转网址]，复制第 {floor_id} 楼的内容。")
        print()

        try:
            content = input("  请粘贴楼层内容: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  ❌ 用户取消输入")
            return None

        if not content:
            print("  ❌ 输入内容为空")
            return None

        if not self._verify_hint(content, hint):
            full_hash = self.compute_sha256(content)
            print(f"\n  ❌ SHA256 不匹配！请检查是否复制了正确楼层的内容。")
            print(f"  hint  : {hint}")
            print(f"  实际值: {full_hash}")
            return None

        print(f"  ✅ 密码 SHA256 验证通过")
        return content

    # ══════════════════════════════════════════════════════════
    #  下载 & 解压
    # ══════════════════════════════════════════════════════════

    def download_if_needed(self, url: str, expected_sha256: str) -> Optional[Path]:
        """下载 ZIP，若本地已有且 SHA256 匹配则跳过"""
        from src.file_downloader import FileDownloader

        filename = self.get_filename_from_url(url)
        filepath = self.download_dir / filename

        if filepath.exists():
            actual = self.compute_file_sha256(filepath)
            if actual == expected_sha256:
                print(f"  ✅ ZIP 已存在且 SHA256 匹配，跳过下载")
                return filepath
            else:
                print(f"  ⚠️  ZIP 已存在但 SHA256 不匹配，重新下载")

        print(f"  ⬇️  下载: {filename}")
        downloader = FileDownloader()
        if not downloader.download_file(url, filename, str(self.download_dir)):
            print(f"  ❌ 下载失败")
            return None

        actual = self.compute_file_sha256(filepath)
        if actual != expected_sha256:
            print(f"  ❌ ZIP SHA256 校验失败！")
            print(f"  预期: {expected_sha256}")
            print(f"  实际: {actual}")
            return None

        print(f"  ✅ ZIP SHA256 校验通过")
        return filepath

    def _ensure_config_files(self) -> None:
        """确保 download_config.yaml 和 extract_config.yaml 存在（含最小默认配置）"""
        defaults = {
            self.download_config_path: {
                "download": {
                    "default_download_dir": "comment",
                    "timeout": 30,
                    "max_retries": 3,
                    "chunk_size": 8192,
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "verify_ssl": True,
                    "allowed_extensions": [".zip"],
                    "max_file_size_mb": 0,
                },
                "download_tasks": [],
                "logging": {
                    "level": "INFO",
                    "log_file": "logs/download.log",
                    "log_format": "%(asctime)s - %(levelname)s - %(message)s",
                },
            },
            self.extract_config_path: {
                "extract": {
                    "default_extract_dir": "comment/extracted",
                    "keep_archive": True,
                    "overwrite_existing": True,
                    "supported_formats": [".zip"],
                    "encoding": "utf-8",
                },
                "passwords": {
                    "default_passwords": [""],
                    "file_passwords": {},
                },
                "extract_tasks": [],
                "logging": {
                    "level": "INFO",
                    "log_file": "logs/extract.log",
                    "log_format": "%(asctime)s - %(levelname)s - %(message)s",
                },
            },
        }
        for path, data in defaults.items():
            if not path.exists():
                self._save_yaml(path, data)

    def try_extract(self, archive_path: Path, password_raw: str) -> bool:
        """尝试用给定密码解压，返回是否成功"""
        from src.file_extractor import FileExtractor

        self._ensure_config_files()

        print(f"  📦 解压: {archive_path.name}")

        extractor = FileExtractor()
        if "passwords" not in extractor.config:
            extractor.config["passwords"] = {}
        if "file_passwords" not in extractor.config["passwords"]:
            extractor.config["passwords"]["file_passwords"] = {}

        extractor.config["passwords"]["file_passwords"][archive_path.name] = [
            {"type": "raw", "content": password_raw}
        ]

        return extractor.extract_file(str(archive_path), str(self.extract_dir))

    # ══════════════════════════════════════════════════════════
    #  写入 download / extract 的 YAML 配置（向后兼容）
    # ══════════════════════════════════════════════════════════

    def _load_yaml(self, path: Path) -> Dict:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _save_yaml(self, path: Path, data: Dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                      sort_keys=False)

    def sync_to_download_config(self, url: str, filename: str) -> None:
        """将下载任务同步到 download_config.yaml（去重）"""
        config = self._load_yaml(self.download_config_path)
        tasks = config.setdefault("download_tasks", [])
        if not any(t.get("url") == url for t in tasks):
            tasks.append({"url": url, "filename": filename, "download_dir": "comment"})
            self._save_yaml(self.download_config_path, config)

    def sync_to_extract_config(self, filename: str, password_raw: str) -> None:
        """将密码和解压任务同步到 extract_config.yaml（去重）"""
        config = self._load_yaml(self.extract_config_path)
        passwords = config.setdefault("passwords", {})
        fp = passwords.setdefault("file_passwords", {})
        if filename not in fp:
            fp[filename] = [{"type": "raw", "content": password_raw}]

        tasks = config.setdefault("extract_tasks", [])
        archive_path = f"comment/{filename}"
        if not any(t.get("archive_path") == archive_path for t in tasks):
            tasks.append({
                "archive_path": archive_path,
                "extract_dir": "comment/extracted",
                "password": "",
            })

        self._save_yaml(self.extract_config_path, config)

    # ══════════════════════════════════════════════════════════
    #  主入口：检查并应用更新
    # ══════════════════════════════════════════════════════════

    def check_and_apply(self) -> bool:
        """
        对比 update.json 与 config.yaml，执行更新。

        Returns:
            True  — 无更新 或 更新成功
            False — 更新失败（不应继续后续构建步骤）
        """
        # ── 0. 确保依赖的配置文件存在 ──
        self._ensure_config_files()

        # ── 1. 加载 update.json ──
        update_data = self.load_update_json()
        if update_data is None:
            print("  ℹ️  未找到 config/update.json，跳过更新检查")
            return True

        # ── 2. 校验 update.json ──
        error = self.validate_update_json(update_data)
        if error:
            print(f"  ⚠️  update.json 格式错误: {error}，跳过更新")
            return True  # 格式错误不阻塞构建

        new_version = update_data.get("version", "?")
        release_date = update_data.get("release_date", "?")
        url = update_data["update_package_url"]
        sha256_expected = update_data["check"]["value"]
        topic_id = update_data["password"]["topic_id"]
        floor_id = update_data["password"]["floor_id"]
        hint = update_data["password"]["hint"]
        filename = self.get_filename_from_url(url)

        print(f"\n  📋 数据集更新")
        print(f"  版本: {new_version}  日期: {release_date}")
        print(f"  文件: {filename}")

        # ── 3. 对比版本 ──
        cache = self.load_cache()
        cached_version = cache.get("version", "")
        if cached_version == new_version:
            print(f"  ✅ 已是最新版本 (v{new_version})，无需更新")
            return True

        # ── 4. 下载 ZIP ──
        archive_path = self.download_if_needed(url, sha256_expected)
        if archive_path is None:
            return False

        # ── 5. 尝试用缓存密码解压 ──
        password_raw = self.get_cached_password(filename)
        if password_raw:
            print(f"  🔑 使用本地缓存密码解压...")
            if self.try_extract(archive_path, password_raw):
                print(f"  ✅ 使用缓存密码解压成功")
                # 版本可能更新了但密码没变
                cache["version"] = new_version
                self.save_cache(cache)
                self._sync_configs(url, filename, password_raw)
                self._show_result()
                return True
            else:
                print(f"  ⚠️  缓存密码解压失败，需要重新获取密码")

        # ── 6. 提示用户输入密码 ──
        password_raw = self.prompt_password(topic_id, floor_id, hint)
        if password_raw is None:
            return False

        if not self.try_extract(archive_path, password_raw):
            print(f"  ❌ 解压仍然失败，请检查密码是否正确")
            return False

        # ── 7. 写入缓存 + 同步到 YAML 配置 ──
        self.set_cached_dataset(new_version, filename, url, sha256_expected,
                                password_raw)
        self._sync_configs(url, filename, password_raw)

        self._show_result()
        return True

    def _sync_configs(self, url: str, filename: str, password_raw: str) -> None:
        """同步到 download_config.yaml 和 extract_config.yaml"""
        self.sync_to_download_config(url, filename)
        self.sync_to_extract_config(filename, password_raw)
        print(f"  📝 已同步到 download_config.yaml / extract_config.yaml")

    def _show_result(self) -> None:
        csv_files = list(self.extract_dir.glob("*.csv"))
        print(f"  📊 当前解压数据: {len(csv_files)} 个 CSV 文件")
        print(f"  🎉 数据集更新完成！")
