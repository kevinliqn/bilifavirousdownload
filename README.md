---

# Bilibili 收藏夹视频下载器

本项目是一个用于下载 Bilibili 账户下收藏夹内视频的 Python 程序。程序支持自动获取收藏夹列表、选择要下载的收藏夹、选择下载清晰度（支持自动以最高画质下载）、记录下载历史（包括视频标题）等功能，同时使用 FFmpeg 合并 DASH 格式的音视频文件。

## 特性

- **收藏夹支持**  
  自动获取用户在 Bilibili 上的创建与收藏的收藏夹列表，支持批量选择下载。

- **自动选择最高画质**  
  启动时可选择是否自动以最高画质下载所有视频，避免手动选择清晰度。

- **多 P 视频支持**  
  对于分 P 的视频，程序会逐个处理并下载所有视频分P。

- **断点续传**  
  程序会记录已下载的视频，避免重复下载。

- **日志与进度条**  
  使用日志记录下载过程，并借助 tqdm 显示下载进度条。

- **跨平台支持**  
  基于 Python 开发，可在 Windows、Linux、macOS 等系统上运行（需配置 FFmpeg）。

## 环境依赖

- Python 3.6+
- [requests](https://pypi.org/project/requests/)
- [tqdm](https://pypi.org/project/tqdm/)

此外，还需要安装 [FFmpeg](https://ffmpeg.org/) 并确保其在系统 PATH 中，或在配置文件中指定 FFmpeg 的路径。

## 安装

1. **克隆仓库**

   ```bash
   git clone https://github.com/kevinliqn/bilifavirousdownload.git
   cd bilibili-downloader
   ```

2. **创建虚拟环境并安装依赖**

   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/macOS
   venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

   如果没有提供 `requirements.txt`，请手动安装依赖：

   ```bash
   pip install requests tqdm
   ```

3. **安装 FFmpeg**

   请参考 [FFmpeg 官网](https://ffmpeg.org/) 下载并安装 FFmpeg。

## 配置

在项目根目录下创建一个 `config.json` 文件，示例如下：

```json
{
  "cookies": "YOUR_BILIBILI_COOKIES_STRING",
  "save_path": "./bili_videos",
  "ffmpeg_path": "ffmpeg",
  "request_interval": 1.5,
  "max_retries": 3
}
```

- **cookies**  
  必须填写有效的 Bilibili Cookie，其中需包含 `DedeUserID` 字段，用于验证用户身份和获取收藏夹信息。

- **save_path**  
  下载的视频将保存在此路径下。

- **ffmpeg_path**  
  FFmpeg 的可执行文件路径。如果已将 FFmpeg 添加到系统 PATH，此项可保持默认值。

- **request_interval**  
  请求间隔，防止请求过于频繁。

- **max_retries**  
  下载过程中重试的最大次数。

## 使用方法

在命令行下运行：

```bash
python bilifavirousdownload.py
```

程序启动后将会进行以下步骤：

1. 读取 `config.json` 配置文件。
2. 获取用户收藏夹列表，并展示可选项。
3. 提示是否以最高画质下载所有视频。输入 `Y`（或直接回车）表示使用最高画质下载，否则手动选择清晰度。
4. 逐个下载选择的收藏夹内的视频，并自动合并音视频文件到最终的 MP4 文件。
5. 下载成功后会在 `download_history.json` 中记录下载信息，包括视频的 bvid、cid、清晰度、视频名称及下载时间戳。

## 注意事项

- **Cookie 有效性**  
  请确保 `config.json` 中的 Cookie 信息有效且包含 `DedeUserID` 字段，否则程序无法正常获取收藏夹数据。

- **网络环境**  
  程序依赖 Bilibili 的 API，请确保网络连接正常。

- **FFmpeg**  
  如果合并音视频失败，请检查 FFmpeg 是否正确安装以及配置是否正确。

## 许可证

本项目遵循 [MIT 许可证](LICENSE)。

---
