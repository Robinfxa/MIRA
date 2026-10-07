"""One local entry for the selected MIRA subscription preset or offline rehearsal.

Auth-store and ADC contents are never read here. The selected .env is parsed
without logging secrets. Existing runtime/configuration/authentication tools
retain their own checks. Starting never installs packages or signs into accounts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "subscription-google-voice-story-images-v1"
PROFILE_FIELDS = {
    "MIRAAPP_PROVIDER": (None, None),
    "MIRAAPP_MODEL": ("model", "--model"),
    "MIRAAPP_SERVICE_TIER": ("service_tier", "--service-tier"),
    "MIRAAPP_VOICE": ("no_voice", "--voice"),
    "MIRAAPP_STORY": ("no_story", "--story"),
    "MIRAAPP_STORY_IMAGES": ("no_story_images", "--story-images"),
    "MIRAAPP_IMAGE_REVIEW_MODEL": ("story_image_review_model", "--story-image-review-model"),
    "MIRAAPP_ADC_FILE": ("adc_file", "--adc-file"),
    "MIRAAPP_AUTH_STORE": ("auth_store", "--auth-store"),
}
EXTRA_FLAGS = {"--loopback-only", "--require-device-pairing", "--allow-private-http-text"}
EXTRA_VALUES = {
    "--generation-requests", "--turns", "--stt-requests", "--tts-requests",
    "--stt-max-seconds", "--tts-max-seconds", "--turn-timeout-seconds",
    "--listen-silence-ms", "--listen-grace-seconds", "--listen-drain-seconds",
    "--listen-max-recognition-streams", "--listen-max-seconds", "--listen-max-utterances",
    "--listen-max-session-starts", "--listen-max-total-starts",
    "--story-image-max-attempts", "--story-image-max-output-bytes", "--story-image-max-total-bytes",
    "--story-image-timeout-seconds", "--story-image-generation-timeout-seconds",
    "--story-image-review-timeout-seconds", "--story-image-max-wire-bytes",
    "--story-image-review-max-wire-bytes", "--character-renderer",
    "--private-bind", "--device-origin", "--device-pairing-dir", "--tls-cert-file", "--tls-key-file",
}
DISCLOSURE = (
    "真实预设：ChatGPT 订阅 / gpt-6.1-sol / Fast；对话与受控工具上下文发送给 OpenAI。\n"
    "启用 Google STT/TTS：麦克风音频及待合成文字发送给 Google，可能产生费用。\n"
    "启用临时剧情与生图：虚构环境/静物描述、生成图和审核信息发送给 OpenAI；"
    "允许本轮可变描述并消耗订阅用量，审核模型 gpt-6-luna。\n"
    "文字与连续 STT 默认无本机次数上限；TTS 20 次/每次30秒；图片1个任务。"
    "这些不是金额上限。默认同一可信 Wi-Fi 可访问文字/图片并共享这些额度。\n"
    "账号、Google 项目及其服务权限须由你自行准备；不会自动登录或切付费 API。"
)


class StartError(ValueError):
    """Fixed, credential-free startup guidance."""


def home_path() -> Path:
    return Path.home()


def local_path(value: str) -> Path:
    # Expand only the requested HOME forms. Never shell-expand/source/evaluate.
    for prefix in ("${HOME}", "$HOME", "~"):
        if value == prefix or value.startswith(prefix + "/"):
            value = str(home_path()) + value[len(prefix):]
            break
    path = Path(value)
    return path.absolute() if path.is_absolute() else (ROOT / path).absolute()


def default_auth_path() -> Path:
    # Same public path contract as openai_codex.default_session_path(), without
    # importing runtime dependencies or opening the session at preflight time.
    if os.name == "nt":
        return home_path() / "AppData/Local/MIRA/auth/openai-codex-session.json"
    if sys.platform == "darwin":
        return home_path() / "Library/Application Support/MIRA/auth/openai-codex-session.json"
    return home_path() / ".local/share/mira/auth/openai-codex-session.json"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
        epilog="默认真实预设包含数据外传及用量许可；首次需选择。"
               " -- 后仅接受现有预算、设备网络和 renderer 选项。")
    parser.add_argument("--preset", choices=("live", "offline"))
    parser.add_argument("--accept-live-profile", action="store_true", help=DISCLOSURE)
    parser.add_argument("--python", help="复用已有 Python 3.11–3.13 及项目依赖")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--adc-file", default="$HOME/.config/gcloud/application_default_credentials.json")
    parser.add_argument("--auth-store", help="只允许 MIRA 自己的登录文件")
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--service-tier", choices=("fast", "standard"), default="fast")
    parser.add_argument("--story-image-review-model", default="gpt-6-luna")
    parser.add_argument("--port", type=int)
    for feature in ("voice", "story", "story-images"):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--" + feature, dest="no_" + feature.replace("-", "_"), action="store_false")
        group.add_argument("--no-" + feature, dest="no_" + feature.replace("-", "_"), action="store_true")
        parser.set_defaults(**{"no_" + feature.replace("-", "_"): False})
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--dry-run", action="store_true", help="只显示参数，不写入或启动")
    operations.add_argument("--check", action="store_true", help="只做本地预检，不代表服务可用")
    operations.add_argument("--setup", action="store_true", help="仅安装项目内锁定依赖后退出")
    values = list(sys.argv[1:] if argv is None else argv)
    split = values.index("--") if "--" in values else len(values)
    args = parser.parse_args(values[:split])
    args.explicit_options = {value.split("=", 1)[0] for value in values[:split] if value.startswith("--")}
    extra = values[split + 1:] if split < len(values) else []
    index = 0
    while index < len(extra):
        flag = extra[index]
        if flag in EXTRA_FLAGS:
            index += 1
        elif flag in EXTRA_VALUES and index + 1 < len(extra) and not extra[index + 1].startswith("--"):
            index += 2
        else:
            raise StartError("不支持的透传参数。完整高级选项请用 tools/live_provider.py；"
                             "官方 API 必须明确选择并提供 --authorize-api-billing，绝不自动回退。")
    if args.port is not None and not 1024 <= args.port <= 65535:
        raise StartError("--port 必须在 1024–65535 之间。")
    if args.preset == "offline" and args.accept_live_profile:
        raise StartError("--preset offline 与 --accept-live-profile 不能同时使用。")
    return args, extra


def apply_profile(args) -> None:
    """Read only a closed public launch-field set with the installed dotenv parser.

    The separate interpreter supports a system Python without project packages.
    The file is never rewritten, shell-sourced, or passed into an auth client.
    Service fields remain the unchanged runtime loader's responsibility.
    """
    path = local_path(args.env_file)
    if not path.exists() and not path.is_symlink():
        return
    private_metadata(path, ".env", "请选择已有私密配置。")
    python = args.python or str(ROOT / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"))
    if not args.python and not Path(python).is_file():
        python = sys.executable
    code = ("import json, sys; from dotenv import dotenv_values; "
            "values=dotenv_values(sys.argv[1], interpolate=False); "
            "print(json.dumps({k:v for k,v in values.items() if k.startswith('MIRAAPP_')}))")
    try:
        result = subprocess.run([python, "-I", "-c", code, str(path)], cwd=ROOT,
                                env=child_environment(), capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise StartError("无法安全读取启动预设；检查 --python、.env 权限及 FIRST-RUN.md。未显示配置值。") from None
    if result.returncode:
        raise StartError("读取启动预设需要项目内 python-dotenv。先运行 sh scripts/start --setup，"
                         "或用 --python /absolute/path/to/ready/python；未显示配置值。")
    try:
        values = json.loads(result.stdout)
    except ValueError:
        raise StartError("无法安全读取启动预设；未显示配置值。") from None
    if not isinstance(values, dict) or values.keys() - PROFILE_FIELDS.keys():
        raise StartError(".env 包含不支持的 MIRAAPP_ 字段；仅使用 .env.example 列出的启动字段。"
                         "数据/计费许可不能通过 .env 授予。")
    for key, value in values.items():
        if value is None or value == "":
            continue
        destination, option = PROFILE_FIELDS[key]
        if key == "MIRAAPP_PROVIDER":
            if value != "chatgpt_subscription":
                raise StartError("此预设只使用 chatgpt_subscription。官方 API 请用 tools/live_provider.py "
                                 "明确选择 --provider openai_api 并提供 --authorize-api-billing。")
            continue
        if option in args.explicit_options or option.replace("--", "--no-", 1) in args.explicit_options:
            continue
        if destination in {"no_voice", "no_story", "no_story_images"}:
            if value not in {"true", "false"}:
                raise StartError("MIRAAPP_VOICE / STORY / STORY_IMAGES 只接受 true 或 false；未显示配置值。")
            value = value == "false"
        elif destination == "service_tier":
            if value not in {"fast", "standard"}:
                raise StartError("MIRAAPP_SERVICE_TIER 只接受 fast 或 standard；未显示配置值。")
        elif destination in {"model", "story_image_review_model"}:
            if re.fullmatch(r"(?:gpt-|o[1-9])[A-Za-z0-9._-]{0,80}", value) is None:
                raise StartError("MIRAAPP 模型字段须为 OpenAI 模型标识，不可填写密钥；未显示配置值。")
        elif not isinstance(value, str) or len(value) > 4096 or any(ord(char) < 32 for char in value):
            raise StartError("MIRAAPP 路径字段无效；未显示配置值。")
        setattr(args, destination, value)


def command(python: str, args, extra: list[str], preset: str, *, check=False) -> list[str]:
    if preset == "offline":
        return [python, str(ROOT / "tools/dev.py"), "--python", python, "--profile", "rehearsal",
                *(["--port", str(args.port)] if args.port is not None else [])]
    result = [python, str(ROOT / "tools/live_provider.py"), "check" if check else "serve",
              "--provider", "chatgpt_subscription", "--model", args.model,
              "--service-tier", args.service_tier, "--env-file", str(local_path(args.env_file)),
              "--authorize-provider-data"]
    if not args.no_voice:
        result += ["--voice", "--adc-file", str(local_path(args.adc_file)),
                   "--authorize-google-voice-data-and-spend"]
    if not args.no_story:
        result += ["--story"]
        if not args.no_story_images:
            result += ["--story-images", "--authorize-story-image-data-to-openai",
                       "--authorize-story-image-subscription-usage", "--authorize-story-image-custom-brief",
                       "--story-image-review-model", args.story_image_review_model]
    if args.auth_store:
        result += ["--auth-store", str(local_path(args.auth_store))]
    if args.port is not None:
        result += ["--port", str(args.port)]
    return result + extra


def private_metadata(path: Path, label: str, recovery: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise StartError(f"缺少或无法访问 {label}。{recovery}") from None
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise StartError(f"{label} 必须是本人拥有、仅本人可读写的普通文件（0600）。"
                         "请在本机检查权限；未读取内容，也未自动修改权限。")


def ensure_env(path: Path, *, default_path: bool) -> None:
    if path.exists() or path.is_symlink():
        return
    if not default_path:
        raise StartError("所选 --env-file 不存在；请指定已有私密配置，或移除该参数来创建默认 .env。")
    contents = (ROOT / ".env.example").read_bytes()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as file:
        file.write(contents)
    print("已从公开模板创建 .env（0600）；请在本机填写 GOOGLE_CLOUD_PROJECT，quota project 可选。")


def local_identity() -> str:
    identity = f"{ROOT.resolve()}\0{home_path()}\0{platform.node()}\0{getattr(os, 'getuid', lambda: 0)()}"
    return hashlib.sha256(identity.encode()).hexdigest()


def saved_choice() -> str | None:
    path = ROOT / "var/launcher/choice.json"
    try:
        private_metadata(path, "本机启动选择", "")
        if path.stat().st_size > 4096:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if (type(data) is dict and data.get("profile") == PROFILE
                and data.get("local_identity") == local_identity()
                and data.get("preset") in ("live", "offline")):
            return data["preset"]
    except (StartError, OSError, ValueError):
        pass
    return None


def save_choice(preset: str) -> None:
    for folder in (ROOT / "var", ROOT / "var/launcher"):
        if folder.is_symlink():
            raise StartError("本机启动选择目录不能是符号链接；未写入选择。")
        folder.mkdir(mode=0o700, exist_ok=True)
    path = ROOT / "var/launcher/choice.json"
    if path.exists() or path.is_symlink():
        private_metadata(path, "本机启动选择", "")
    data = {"profile": PROFILE, "local_identity": local_identity(), "preset": preset}
    # Do not follow an existing symlink or persist env/arguments/credential paths.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(data, file)
        file.write("\n")


def child_environment() -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.dev import child_environment as clean_environment
    result = clean_environment()
    result["PYTHONPATH"] = str(ROOT / "apps/api/src")
    return result


def python_ready(python: str) -> bool:
    code = ("import sys, importlib; "
            "assert (3, 11) <= sys.version_info[:2] < (3, 14); "
            "[importlib.import_module(m) for m in "
            "('fastapi','pydantic','uvicorn','dotenv','httpx','google.cloud.speech',"
            "'google.auth','jwt','PIL')]")
    try:
        return subprocess.run([python, "-I", "-c", code], cwd=ROOT, env=child_environment(),
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def select_python(explicit: str | None) -> str:
    if explicit:
        explicit = (str(local_path(explicit)) if "/" in explicit or "\\" in explicit
                    else shutil.which(explicit) or explicit)
    candidates = [explicit] if explicit else [str(ROOT / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python")), sys.executable]
    for python in dict.fromkeys(candidates):
        if python_ready(python):
            return python
    raise StartError("缺少兼容的 Python 3.11–3.13 或项目依赖。运行 sh scripts/start --setup，"
                     "或用 --python /absolute/path/to/ready/python 复用已有环境。没有安装任何依赖。")


def check_web() -> None:
    from tools.dev import StartupError, web_build_command
    try:
        web_build_command()  # checks local Node and declared deps; does not build/install
    except StartupError:
        raise StartError("缺少 Node.js 22.12+、npm 或项目内前端依赖。先准备 Node/npm，再运行 "
                         "sh scripts/start --setup。没有安装或构建任何依赖。") from None


def preflight(python: str, args, extra: list[str]) -> None:
    private_metadata(local_path(args.env_file), ".env", "首次运行 sh scripts/start 可创建默认模板。")
    auth = local_path(args.auth_store) if args.auth_store else default_auth_path()
    private_metadata(auth, "MIRA 登录文件", "先用所选 Python 运行 tools/provider_login.py login；"
                     "若使用自选存储，放在子命令前：--auth-store /absolute/private/session.json login。")
    if not args.no_voice:
        private_metadata(local_path(args.adc_file), "Google ADC", "在本机运行 "
                         "gcloud auth application-default login，并检查该文件权限；详见 FIRST-RUN.md。")
    check_web()
    result = subprocess.run(command(python, args, extra, "live", check=True), cwd=ROOT,
                            env=child_environment(), capture_output=True, timeout=45)
    if result.returncode:
        # Never replay loader stdout/stderr: even allowed fields may contain
        # user-selected private strings. Existing CLI check remains available.
        raise StartError("本地配置校验未通过。请在所选 .env 填写 GOOGLE_CLOUD_PROJECT，"
                         "核对 Google voice 字段（TTS_LOCATION=global、TTS_VOICE=Gacrux）"
                         "及显式预算/网络参数；完整检查方式见 FIRST-RUN.md。未显示配置值。")


def choose_preset(args) -> str | None:
    if args.accept_live_profile:
        return "live"
    existing = saved_choice()
    if args.preset == "offline":
        return "offline"
    if existing == "live" and args.preset != "offline":
        return "live"
    if existing == "offline" and args.preset is None:
        return "offline"
    if not sys.stdin.isatty():
        raise StartError("首次启动需要明确选择。交互运行 sh scripts/start，或选择 --preset offline；"
                         "已同意真实数据/用量范围时使用 --accept-live-profile（详情见 --help）。")
    print(DISCLOSURE)
    choice = input("选择：1 接受并使用真实预设 / 2 无密钥离线排练 / 0 取消 [0]：").strip()
    return {"1": "live", "2": "offline"}.get(choice)


def main(argv=None) -> int:
    try:
        args, extra = parse_args(argv)
        if args.dry_run:
            preset = args.preset or ("live" if args.accept_live_profile else saved_choice() or "live")
            if preset == "offline" and extra:
                raise StartError("离线入口不接收真实服务透传参数；高级离线选项请用 sh scripts/dev。")
            if preset == "live":
                apply_profile(args)
            python = args.python or str(ROOT / ".venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"))
            print(json.dumps({"argv": command(python, args, extra, preset),
                              "network": "not_run", "consent": "not_granted_by_preview"}, ensure_ascii=False))
            return 0
        if args.setup:
            if args.python:
                raise StartError("--setup 只准备本项目 .venv/node_modules；复用环境请直接用 --python 启动。")
            return subprocess.run([sys.executable, str(ROOT / "tools/bootstrap.py")],
                                  cwd=ROOT, env=child_environment()).returncode
        if args.check:
            preset = args.preset or ("live" if args.accept_live_profile else saved_choice() or "live")
            if preset == "live":
                apply_profile(args)
            python = select_python(args.python)
            if preset == "offline":
                if extra:
                    raise StartError("离线入口不接收真实服务透传参数；高级离线选项请用 sh scripts/dev。")
                check_web()
            else:
                preflight(python, args, extra)
            print("本地预检通过；not_live_verified。未登录、未刷新凭据、未调用服务，也未写入选择。")
            return 0
        preset = choose_preset(args)
        if preset is None:
            print("已取消；没有写入配置、安装依赖或启动服务。")
            return 0
        if preset == "offline" and extra:
            raise StartError("离线入口不接收真实服务透传参数；高级离线选项请用 sh scripts/dev。")
        if preset == "live":
            ensure_env(local_path(args.env_file), default_path=args.env_file == ".env")
        save_choice(preset)
        if preset == "live":
            apply_profile(args)
        python = select_python(args.python)
        if preset == "live":
            preflight(python, args, extra)
        else:
            check_web()
        print(f"正在启动 MIRA {'真实预设' if preset == 'live' else '离线排练'}；"
              f"本机 http://127.0.0.1:{args.port or 8000}，按 Ctrl+C 停止。", flush=True)
        os.chdir(ROOT)
        os.execve(python, command(python, args, extra, preset), child_environment())
        return 0
    except (KeyboardInterrupt, EOFError):
        print("已取消；没有启动服务。", file=sys.stderr)
        return 130
    except StartError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, subprocess.TimeoutExpired):
        print("本机文件/依赖检查未完成；请检查文件权限及 FIRST-RUN.md。未显示私密值。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
