#!/usr/bin/env python3
"""agent-vision: 为纯文本模型提供图片理解能力（图片描述 / 问答 / OCR）。

通过 OpenAI-compatible 视觉 API 将图片转为文字描述，供 Agent 在回答中使用。
本脚本自包含：无需安装任何第三方依赖，复制到任意位置即可使用。

用法:
  python vision.py <图片路径|data URL|http(s) URL>
  python vision.py <图片> -q "这张图片里有什么？"
  python vision.py <图片> --ocr
  python vision.py <图片1> <图片2> ...   # 多图逐张描述（并发）

配置加载顺序（从高到低）:
  1. 环境变量 VISION_API_KEY / VISION_BASE_URL / VISION_MODEL / LANG
  2. env 文件（可通过 --env-file 指定，或默认在脚本同目录 .env）
  3. Windows: %LOCALAPPDATA%\\codex-deepseek-vision\\env（与 Codex 视觉代理共用）
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
import urllib.error
import urllib.request

DEFAULT_PROMPT = "请详细描述这张图片中的内容。"

# 深度结构化描述(默认):不仅说出"有什么",还给出位置、布局、细节与推理,
# 使下游主模型(如 DeepSeek)能基于高质量描述完成推理工作。
DETAILED_PROMPT = """请对这张图片进行专业、细致的视觉分析,输出结构化中文描述。请按以下层次组织(不适用的小节可省略,但位置信息必须尽量具体):

1.【整体概览】图片类型(照片/截图/海报/UI界面/文档/图表等)、主题、风格、色调、明暗与清晰度,用一句话概括画面。
2.【空间布局】用九宫格区域(左上/上中/右上/左中/中央/右中/左下/下中/右下)描述画面结构:主体在哪个区域、前景/中景/背景分别是什么、各元素之间的相对位置关系(如"标题在上方居中,操作按钮在右下角,配图占左下四分之一")。
3.【对象与细节】逐项列出每个重要对象:是什么、所在区域、在画面中的大致占比(如占画面1/3)、颜色、形状、材质/纹理、大小对比、状态或动作。同类对象要说明数量与分布方式。
4.【文字与UI】(有文字时必答)逐条提取所有文字内容,并标注每条文字的位置区域、相对大小与颜色。若是UI/截图/网页,额外描述界面结构:导航栏、按钮、输入框、弹窗、列表等各自的位置与作用。
5.【数据与数字】(有时必答)精确读出数字、时间、百分比、价格、标签、型号等,并注明在画面中的位置。
6.【隐含信息】基于可见内容做合理的视觉推理(场景判断、人物状态/情绪、物体用途、可能的上下文),并明确区分"可见事实"与"推测"。
7.【易漏细节】背景文字、角标、水印、logo、阴影、边缘被裁切的物体等容易被忽略但可能有用的细节。

要求:全面、精确、不遗漏;位置描述优先用九宫格区域+相对关系,能给出大致坐标(如"距左边缘约1/4处")更好;不要编造看不清的内容,看不清就说明"此处不清晰"。请使用简体中文。"""

# 针对性追问时:围绕问题细化,同时保留结构化骨架
QUESTION_PROMPT = """请对这张图片进行专业、细致的视觉分析。用户有具体问题,请以该问题为核心,先详细回答并给足位置、细节与推理依据;然后再按以下层次补充画面其余部分:
1.【整体概览】图片类型、主题、风格、色调,一句话概括。
2.【空间布局】九宫格区域描述主体与元素位置、相对关系。
3.【对象与细节】重要对象逐项列出:是什么、所在区域、占比、颜色、形状、状态。
4.【文字与UI】(有文字时必答)逐条提取文字内容并标注位置区域、相对大小与颜色;UI/截图则描述界面结构及各元素位置与作用。
5.【数据与数字】(有时必答)精确读出数字并注明位置。
6.【隐含信息】合理视觉推理,区分"可见事实"与"推测"。
7.【易漏细节】背景文字、角标、水印、logo、边缘裁切等。
要求:位置信息尽量具体(九宫格区域+相对关系);看不清就说明,不编造。请使用简体中文。

用户的针对性问题(重点详细回答):{question}"""
LANG_INSTRUCTIONS = {
    "zh": "请使用简体中文回答。",
    "en": "Please respond in English.",
}

# 保险丝：只允许用户配置的视觉 API，防止误用其他付费模型
ALLOWED_BASE_URLS = ["nayutoai.xyz", "agnes-ai.com"]
ALLOWED_MODELS = ["gpt-5.6-luna", "agnes"]


class VisionError(RuntimeError):
    pass


def load_env_file(path):
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_default_env(args_env=None):
    candidates = []
    if args_env:
        candidates.append(Path(args_env).expanduser())
    candidates.extend([
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
    ])
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "codex-deepseek-vision" / "env")
    for path in candidates:
        load_env_file(path)


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise VisionError(f"缺少配置 {name}；请设置环境变量或创建 .env 文件")
    return value


def image_path_to_data_url(path):
    image_path = Path(path).expanduser()
    if not image_path.is_file():
        raise VisionError(f"图片不存在: {image_path}")
    mime, _ = mimetypes.guess_type(image_path.name)
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}:
        raise VisionError(f"不支持的图片格式: {image_path.name}（支持 PNG/JPEG/GIF/WebP/BMP）")
    return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode()}"


def _config_sites():
    """按优先级返回视觉站点列表：主站点(VISION_*) + 可选备用站点(VISION2_*、VISION3_* ...)。

    备用站点编号依次后延，某编号的 BASE_URL / API_KEY / MODEL 任一缺失则跳过该编号；
    一个都不配时抛错提示（与旧版仅主站点的行为一致）。
    """
    sites = []
    primary = {
        "base_url": os.environ.get("VISION_BASE_URL", "").strip(),
        "api_key": os.environ.get("VISION_API_KEY", "").strip(),
        "model": os.environ.get("VISION_MODEL", "").strip(),
    }
    if all(primary.values()):
        sites.append(primary)
    index = 2
    while True:
        site = {
            "base_url": os.environ.get(f"VISION{index}_BASE_URL", "").strip(),
            "api_key": os.environ.get(f"VISION{index}_API_KEY", "").strip(),
            "model": os.environ.get(f"VISION{index}_MODEL", "").strip(),
        }
        if not any(site.values()):
            break  # 该编号未配置，停止查找
        if all(site.values()):
            sites.append(site)
        index += 1
    if not sites:
        _required("VISION_API_KEY")
    return sites


def describe_image(image_url, prompt=None, max_tokens=16384, apply_lang=True):
    """Describe an image via OpenAI-compatible /chat/completions.

    多站点故障切换：主站点(VISION_*)重试耗尽后自动切换到备用站点
    (VISION2_* / VISION3_* ...)，全部失败才抛错。
    """
    if not image_url.startswith(("data:", "http://", "https://")):
        raise VisionError("只支持 data URL 或 http(s) 图片 URL")
    sites = _config_sites()
    text = prompt or DEFAULT_PROMPT
    if apply_lang:
        instruction = LANG_INSTRUCTIONS.get(os.environ.get("LANG", "zh").strip().lower())
        if instruction:
            text = f"{instruction}\n\n{text}"
    last_err = None
    for site_index, site in enumerate(sites):
        base_url = site["base_url"].rstrip("/")
        api_key = site["api_key"]
        model = site["model"]
        # 保险丝：只允许配置好的视觉 API
        if not any(allowed in base_url for allowed in ALLOWED_BASE_URLS):
            raise VisionError(f"配置拒绝：VISION_BASE_URL 必须是已配置的 API（{' / '.join(ALLOWED_BASE_URLS)}），当前为 {base_url}")
        if not any(allowed in model for allowed in ALLOWED_MODELS):
            raise VisionError(f"配置拒绝：VISION_MODEL 必须是已配置的模型（{' / '.join(ALLOWED_MODELS)}），当前为 {model}")
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}],
        }
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        )
        # 强制直连，绕过系统代理（Windows 系统代理可能导致连接重置/SSL EOF）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(5):
            try:
                with opener.open(request, timeout=240) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
                if content.strip():
                    if site_index:
                        print(f"[vision] 主站点失败，已切换到备用站点 {base_url}: {last_err}", file=sys.stderr)
                    return content
                last_err = VisionError("视觉 API 返回空内容（推理模型可能需更多 max_tokens）")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                # 4xx/5xx 中属于服务端抖动的状态码，重试
                if exc.code in (404, 429, 500, 502, 503, 504):
                    last_err = VisionError(f"视觉 API HTTP {exc.code}: {body}")
                    time.sleep(3 * (attempt + 1))
                    continue
                raise VisionError(f"视觉 API HTTP {exc.code}: {body}") from exc
            except urllib.error.URLError as exc:
                last_err = VisionError(f"视觉 API 网络错误: {exc.reason}")
                time.sleep(3 * (attempt + 1))
            except ConnectionResetError as exc:
                last_err = VisionError(f"视觉 API 连接重置: {exc}")
                time.sleep(3 * (attempt + 1))
            except (KeyError, IndexError, TypeError) as exc:
                raise VisionError(f"视觉 API 响应格式异常: {json.dumps(data, ensure_ascii=False)[:500]}") from exc
        if site_index < len(sites) - 1:
            print(f"[vision] 站点 {base_url} 失败，切换到备用站点: {last_err}", file=sys.stderr)
    raise last_err


def build_prompt(args):
    if args.ocr:
        return "请提取这张图片中的全部文字内容，按阅读顺序输出，并为每条文字标注其在图片中的位置区域(如左上角/顶部居中/右下角等)。只输出提取到的文字和位置，不要额外解释。"
    if args.question:
        return QUESTION_PROMPT.format(question=args.question)
    if args.simple:
        return DEFAULT_PROMPT
    return DETAILED_PROMPT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", help="图片路径或 URL（可多个，并发描述）")
    parser.add_argument("-q", "--question", default="", help="针对图片的提问")
    parser.add_argument("--ocr", action="store_true", help="OCR 模式：提取图片文字(带位置标注)")
    parser.add_argument("--simple", action="store_true", help="简短描述模式(仅基础描述，不启用深度结构化描述)")
    parser.add_argument("--lang", default="", help="输出语言 zh/en，覆盖 env 的 LANG")
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--env-file", default="", help="指定 env 配置文件路径")
    args = parser.parse_args()
    if args.lang:
        os.environ["LANG"] = args.lang
    load_default_env(args.env_file)
    try:
        _required("VISION_API_KEY")
        _required("VISION_BASE_URL")
        _required("VISION_MODEL")
    except VisionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(2)

    prompt = build_prompt(args)
    urls = []
    for img in args.images:
        if img.startswith(("data:", "http://", "https://")):
            urls.append(img)
        else:
            urls.append(image_path_to_data_url(img))

    if len(urls) == 1:
        try:
            print(describe_image(urls[0], prompt, args.max_tokens))
        except VisionError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
        futures = [pool.submit(describe_image, u, prompt, args.max_tokens) for u in urls]
        for i, fut in enumerate(futures, 1):
            try:
                result = fut.result()
                if len(urls) > 1:
                    print(f"--- 图片 {i} ---")
                print(result)
            except VisionError as exc:
                print(f"--- 图片 {i} 失败 ---", file=sys.stderr)
                print(f"错误: {exc}", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
