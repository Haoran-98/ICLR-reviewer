#!/usr/bin/env bash
# 在当前服务器上，以配置网站服务的用户（yhr）运行，无需 sudo。
set -euo pipefail

systemctl --user start iclr-web-lan.service
systemctl --user is-active --quiet iclr-web-lan.service
printf '网站已启动：http://172.24.246.231:5173/\n关闭终端后仍会运行。\n'
