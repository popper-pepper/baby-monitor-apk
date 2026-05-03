[app]

# 应用信息
title = 婴儿看护系统
package.name = baby_monitor
package.domain = org.baby

# 版本
version = 1.0.0
version.regex = __version__\s*=\s*['"](.*)['"]
version.filename = %(source.dir)s/main.py

# Python 需求
requirements = python3,kivy,flask,requests,pyyaml,Pillow,numpy

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
android.ndk = 23b
android.sdk = 31
android.minapi = 21
android.gradle_dependencies = 'androidx.core:core:1.9.0'

# 权限
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, FOREGROUND_SERVICE, WAKE_LOCK

android.manifest = <manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.baby.monitor">
    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE"/>
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
    <uses-permission android:name="android.permission.WAKE_LOCK"/>
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED"/>
    <application android:allowBackup="true" android:usesCleartextTraffic="true" android:supportsRtl="true">
    </application>
</manifest>

# 屏幕方向
android.orientation = portrait

# 允许 HTTP 明文（IP Webcam 是 HTTP）
android.add_src =  # 额外 Java 源码目录（可选）

# ARM 架构（兼容性更好）
android.arch = arm64-v8a, armeabi-v7a

# 启用日志
android.logcat_filters = *:S python:D

# ── iOS 配置（暂不启用）──
ios.codesign.allowed = false

# ── 构建后处理 ──

# 签名
android.akeystore = %(source.dir)s/keystore.keystore
android.keystore_alias = baby_monitor

# 输出文件名
android.filename = baby_monitor

# 构建完成后复制 APK 到当前目录
android.copy_libs = True

# 构建方式（使用 Docker 或本地）
# 0=自动, 1=Docker, 2=本地
android.build_tool = gradle
docker.image = default

# p4a 额外参数
android.add_package_name = org.baby.monitor
android.gradle_dependencies += 'com.android.support:support-annotations:28.0.0'
