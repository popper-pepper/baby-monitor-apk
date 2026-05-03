[app]

# 应用信息
title = 婴儿看护系统
package.name = baby_monitor
package.domain = org.baby

# 版本
version = 1.0.0

# Python 需求（注意：p4a 上的 Pillow 需要用 pillow）
requirements = python3,kivy,flask,requests,pyyaml,pillow,numpy

# 源码
source.dir = .
source.include_exts = py,png,jpg,jpeg,gif,txt,yaml,yml
source.exclude_exts = spec

# 导出 __init__.py 中的符号
export_symbols = False

# 编译选项
presplash.color = #0f0f1a
icon = data/icon.png

# ── Android 配置 ──

android.api = 31
android.ndk = 25b
android.sdk = 31
android.minapi = 21
android.gradle_dependencies = androidx.core:core:1.9.0

# 权限
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, FOREGROUND_SERVICE, WAKE_LOCK, RECEIVE_BOOT_COMPLETED

# 屏幕方向
android.orientation = portrait

# 允许 HTTP 明文（IP Webcam 是 HTTP）
android.add_src =

# ARM 架构（兼容性更好）
android.archs = arm64-v8a,armeabi-v7a

# 启用日志
android.logcat_filters = *:S python:D

# ── iOS 配置（暂不启用）──
ios.codesign.allowed = false

# ── 构建后处理 ──

# 调试模式自动生成 debug keystore，无需手动设置
# android.akeystore = %(source.dir)s/keystore.keystore
# android.keystore_alias = baby_monitor

# 输出文件名
android.filename = baby_monitor

# 构建完成后复制 APK 到当前目录
android.copy_libs = True

# 构建方式（使用 Docker）
android.build_tool = gradle
docker.image = default
