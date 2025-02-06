import os
import re
import time
import json
import logging
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from http.cookies import SimpleCookie, CookieError
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_session_with_retries(timeout: int = 60, retries: int = 5) -> requests.Session:
    """
    创建一个带重试机制的 Session，设置默认超时时间
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.request_timeout = timeout
    return session

# ===================== 配置类 =====================
@dataclass
class Config:
    """程序配置项"""
    cookies: str
    save_path: Path = Path("./downloads")
    ffmpeg_path: str = "ffmpeg"
    request_interval: float = 1.5
    max_retries: int = 3
    history_file: Path = Path("./download_history.json")
    temp_dir: Path = Path("./temp")

    def __post_init__(self):
        self.save_path.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2, ensure_ascii=False)

# ===================== 核心下载器类 =====================
class BilibiliDownloader:
    def __init__(self, config: Config):
        self.config = config
        self.session = get_session_with_retries(timeout=60, retries=5)
        self._init_session()
        self.logger = self._setup_logger()
        self.downloaded = self._load_download_history()

    def _init_session(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
            "Cookie": self.config.cookies
        }
        self.session.headers.update(headers)

    def _setup_logger(self):
        logger = logging.getLogger("BiliDownloader")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        return logger

    # ------------------- 下载记录管理 -------------------
    def _load_download_history(self) -> Set[Tuple[str, int, int]]:
        try:
            if self.config.history_file.exists():
                if self.config.history_file.stat().st_size == 0:
                    return set()
                with open(self.config.history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
                    return {(item["bvid"], item["cid"], item["quality"]) for item in records}
            return set()
        except json.JSONDecodeError:
            self.logger.error("历史记录文件损坏，已重置")
            return set()
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {str(e)}")
            return set()

    def _save_download_entry(self, bvid: str, cid: int, quality: int, title: str, up_name: str):
        try:
            records = []
            if self.config.history_file.exists():
                with open(self.config.history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append({
                "bvid": bvid,
                "cid": cid,
                "quality": quality,
                "title": title,
                "up": up_name,
                "timestamp": int(time.time())
            })
            with open(self.config.history_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存记录失败: {str(e)}")

    # ------------------- 收藏夹获取 -------------------
    def get_user_folders(self) -> List[Dict]:
        try:
            cookies = SimpleCookie()
            try:
                cookies.load(self.config.cookies.strip())
            except CookieError as e:
                self.logger.error(f"Cookie解析失败: {str(e)}")
                return []
            dede_userid = cookies.get("DedeUserID")
            if not dede_userid or not dede_userid.value.isdigit():
                self.logger.error("无效的用户身份凭证，请检查Cookie中的DedeUserID")
                return []
            created = self._get_paginated_data(
                "https://api.bilibili.com/x/v3/fav/folder/created/list",
                {"up_mid": dede_userid.value},
                data_key="list"
            )
            collected = self._get_paginated_data(
                "https://api.bilibili.com/x/v3/fav/folder/collected/list",
                data_key="list"
            )
            return created + collected
        except Exception as e:
            self.logger.error(f"获取收藏夹失败: {str(e)}")
            return []

    def _get_paginated_data(self, url: str, params: dict = None, data_key: str = "medias") -> List[Dict]:
        results = []
        page = 1
        while True:
            try:
                resp = self.session.get(url, params={"pn": page, "ps": 20, **(params or {})}, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                if data["code"] != 0:
                    self.logger.error(f"API错误[{url}]: {data.get('message')}")
                    break
                items = data["data"].get(data_key, [])
                results.extend(items)
                if len(items) < 20:
                    break
                page += 1
                time.sleep(self.config.request_interval)
            except Exception as e:
                self.logger.error(f"请求失败: {str(e)}")
                break
        return results

    # ------------------- 视频处理 -------------------
    def get_video_info(self, bvid: str) -> Optional[Dict]:
        try:
            resp = self.session.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                self.logger.error(f"视频信息获取失败: {data.get('message')}")
                return None
            return data["data"]
        except Exception as e:
            self.logger.error(f"请求异常: {str(e)}")
            return None

    def get_available_qualities(self, bvid: str, cid: int) -> Dict[int, str]:
        """
        获取视频可选清晰度列表，支持4K、HDR、8K等
        """
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": 0,
                    "fnval": 4048,
                    "fourk": 1,
                    "fnver": 0
                },
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                self.logger.error(f"清晰度接口错误: {data.get('message')}")
                return {}
            qualities = {}
            for qn, desc in zip(data["data"]["accept_quality"], data["data"]["accept_description"]):
                if ":" in desc:
                    _, desc_part = desc.split(":", 1)
                    qualities[qn] = desc_part.strip()
                else:
                    qualities[qn] = desc.strip()
            return qualities
        except Exception as e:
            self.logger.error(f"清晰度获取失败: {str(e)}")
            return {}

    def _download_media(self, url: str, path: Path) -> bool:
        for retry in range(self.config.max_retries):
            try:
                with self.session.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get("content-length", 0))
                    with open(path, "wb") as f, tqdm(
                        desc=f"下载 {path.name}",
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as bar:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                return True
            except Exception as e:
                self.logger.warning(f"下载失败（重试 {retry+1}/{self.config.max_retries}）: {str(e)}")
                if path.exists():
                    path.unlink()
                time.sleep(2)
        return False

    def _merge_files(self, video_path: Path, audio_path: Path, output_path: Path) -> bool:
        try:
            subprocess.run(
                [
                    self.config.ffmpeg_path,
                    "-y",
                    "-loglevel", "error",
                    "-i", str(video_path),
                    "-i", str(audio_path),
                    "-c", "copy",
                    str(output_path)
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"合并失败: {e.stderr.decode()}")
            return False
        except Exception as e:
            self.logger.error(f"FFmpeg异常: {str(e)}")
            return False

    def download_video(self, bvid: str, cid: int, quality: int, dest_dir: Optional[Path] = None, suffix: str = "") -> bool:
        """
        完整的下载流程
        参数:
          bvid: 视频 bvid
          cid: 分P对应的 cid
          quality: 清晰度码
          dest_dir: 视频保存目录，若为 None 则保存在配置中的 save_path 下
          suffix: 输出文件名后缀（例如"-hdr"）
        """
        try:
            if (bvid, cid, quality) in self.downloaded:
                self.logger.info(f"跳过已下载内容: {bvid}-{cid}")
                return True

            video_info = self.get_video_info(bvid)
            if not video_info:
                return False

            title = re.sub(r'[\\/:*?"<>|]', "", video_info["title"]).strip()[:100]
            page_info = next((p for p in video_info["pages"] if p["cid"] == cid), None)
            if not page_info:
                self.logger.error(f"未找到分P信息: {bvid}-{cid}")
                return False

            owner = video_info.get("owner", {})
            up_name = owner.get("name", "unknown")
            up_name = re.sub(r'[\\/:*?"<>|]', "", up_name).strip()

            output_name = f"{title}_{re.sub(r'[\\/:*?\"<>|]', '', page_info['part']).strip()}-{up_name}{suffix}.mp4"
            if dest_dir is None:
                dest_dir = self.config.save_path
            dest_dir.mkdir(parents=True, exist_ok=True)
            output_path = dest_dir / output_name

            video_url, audio_url = self._get_media_urls(bvid, cid, quality)
            if not video_url or not audio_url:
                return False

            temp_video = self.config.temp_dir / f"{bvid}_{cid}_video.m4s"
            temp_audio = self.config.temp_dir / f"{bvid}_{cid}_audio.m4s"

            success = (
                self._download_media(video_url, temp_video) and
                self._download_media(audio_url, temp_audio) and
                self._merge_files(temp_video, temp_audio, output_path)
            )

            if success:
                self._save_download_entry(bvid, cid, quality, title, up_name)
                self.downloaded.add((bvid, cid, quality))
            temp_video.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)
            return success
        except Exception as e:
            self.logger.error(f"下载流程异常: {str(e)}")
            return False

    def _get_media_urls(self, bvid: str, cid: int, quality: int) -> Tuple[Optional[str], Optional[str]]:
        """
        获取媒体文件地址，传入支持高画质参数，
        并优先选取 hi-res（id==30251）的音频
        """
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": quality,
                    "fnval": 4048,
                    "fourk": 1,
                    "fnver": 0
                },
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                return None, None
            dash = data["data"].get("dash")
            if not dash:
                return None, None
            video_stream = max((v for v in dash["video"] if v["id"] == quality),
                               key=lambda x: x["bandwidth"],
                               default=None)
            hi_res_audio = next((a for a in dash["audio"] if a.get("id") == 30251), None)
            if hi_res_audio is not None:
                audio_stream = hi_res_audio
            else:
                audio_stream = max(dash["audio"], key=lambda x: x["bandwidth"], default=None)
            if video_stream and audio_stream:
                video_url = video_stream.get("baseUrl") or video_stream.get("base_url")
                audio_url = audio_stream.get("baseUrl") or audio_stream.get("base_url")
                return video_url, audio_url
            return None, None
        except Exception as e:
            self.logger.error(f"媒体地址获取失败: {str(e)}")
            return None, None

# ===================== 用户交互类 =====================
class InteractiveManager:
    @staticmethod
    def select_quality(qualities: Dict[int, str]) -> int:
        """交互式选择清晰度"""
        print("\n可用清晰度:")
        sorted_qn = sorted(qualities.items(), key=lambda x: x[0], reverse=True)
        for idx, (qn, desc) in enumerate(sorted_qn, 1):
            print(f"  {idx}. {qn} - {desc}")
        default_qn = sorted_qn[0][0]
        while True:
            choice = input(f"请输入清晰度（默认 {default_qn}）: ").strip()
            if not choice:
                return default_qn
            try:
                selected_idx = int(choice) - 1
                if 0 <= selected_idx < len(sorted_qn):
                    return sorted_qn[selected_idx][0]
                print(f"请输入1~{len(sorted_qn)}之间的数字")
            except ValueError:
                print("输入无效，请输入数字")

    @staticmethod
    def select_folders(folders: List[Dict]) -> List[str]:
        """选择收藏夹，返回收藏夹的 id 列表"""
        print("\n发现收藏夹:")
        for idx, folder in enumerate(folders, 1):
            print(f"  {idx}. {folder['title']} ({folder['media_count']}个视频)")
        while True:
            selection = input("\n请选择要下载的序号（多个用逗号分隔，q退出）: ").strip()
            if selection.lower() == "q":
                return []
            try:
                selected = [int(s.strip()) for s in selection.split(",")]
                if all(1 <= num <= len(folders) for num in selected):
                    return [folders[num-1]["id"] for num in selected]
                print(f"请输入1~{len(folders)}之间的有效数字")
            except ValueError:
                print("输入格式错误，示例：1,3")

# ===================== 主程序 =====================
def main():
    try:
        with open("config.json", encoding="utf-8") as f:
            config_data = json.load(f)
    except FileNotFoundError:
        print("错误：缺少配置文件 config.json")
        return
    except json.JSONDecodeError:
        print("错误：配置文件格式不正确")
        return

    config = Config(
        cookies=config_data.get("cookies", ""),
        save_path=Path(config_data.get("save_path", "./downloads")),
        ffmpeg_path=config_data.get("ffmpeg_path", "ffmpeg"),
        request_interval=config_data.get("request_interval", 1.5),
        max_retries=config_data.get("max_retries", 3)
    )

    downloader = BilibiliDownloader(config)
    print(f"已加载历史记录：{len(downloader.downloaded)} 条")

    use_highest_quality = False
    choice = input("是否以最高画质下载所有视频？(Y/n): ").strip().lower()
    if choice in ("", "y", "yes"):
        use_highest_quality = True

    folders = downloader.get_user_folders()
    if not folders:
        print("错误：无法获取收藏夹，请检查Cookie或网络连接")
        return

    selected_ids = InteractiveManager.select_folders(folders)
    if not selected_ids:
        print("下载已取消")
        return

    for folder_id in selected_ids:
        folder_info = next((f for f in folders if f["id"] == folder_id), None)
        if folder_info is None:
            print(f"未找到收藏夹信息: {folder_id}")
            continue

        folder_title = re.sub(r'[\\/:*?"<>|]', "", folder_info["title"]).strip() or folder_id
        folder_dir = config.save_path / folder_title
        folder_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n正在处理收藏夹: {folder_title} (ID: {folder_id})")

        medias = downloader._get_paginated_data(
            "https://api.bilibili.com/medialist/gateway/base/spaceDetail",
            {"media_id": folder_id, "keyword": "", "order": "mtime", "type": 0, "tid": 0, "jsonp": "jsonp"},
            data_key="medias"
        )

        for media in medias:
            bvid = media.get("bvid")
            if not bvid:
                continue

            video_info = downloader.get_video_info(bvid)
            if not video_info:
                print(f"跳过无效视频: {bvid}")
                continue

            for page in video_info.get("pages", []):
                cid = page.get("cid")
                if not cid:
                    continue

                qualities = downloader.get_available_qualities(bvid, cid)
                if not qualities:
                    print(f"视频可能受地区限制或需要登录: {video_info['title']}")
                    continue

                if use_highest_quality:
                    allowed = {16, 32, 64, 80, 112, 116, 120, 125, 127}
                    avail = allowed.intersection(set(qualities.keys()))
                    if avail:
                        selected_quality = max(avail)
                    else:
                        selected_quality = max(qualities.keys())
                else:
                    selected_quality = InteractiveManager.select_quality(qualities)

                # 下载最高画质版本（下载结果放在收藏夹目录下）
                if downloader.download_video(bvid, cid, selected_quality, dest_dir=folder_dir):
                    print(f"✓ 成功下载: {video_info['title']} - {page['part']}")
                else:
                    print(f"✗ 下载失败: {video_info['title']} - {page['part']}")

                # 检查是否支持HDR：根据描述中包含 "HDR" 或 "杜比视界"
                hdr_candidates = [q for q, desc in qualities.items() if "HDR" in desc or "杜比视界" in desc]
                if hdr_candidates:
                    hdr_quality = max(hdr_candidates)
                    hdr_dir = folder_dir / "hdr"
                    hdr_dir.mkdir(parents=True, exist_ok=True)
                    if downloader.download_video(bvid, cid, hdr_quality, dest_dir=hdr_dir, suffix="-hdr"):
                        print(f"✓ HDR版本下载成功: {video_info['title']} - {page['part']}")
                    else:
                        print(f"✗ HDR版本下载失败: {video_info['title']} - {page['part']}")

if __name__ == "__main__":
    main()
