#!/usr/bin/env bash
# 在当前服务器上，以配置网站服务的用户（yhr）运行，无需 sudo。
set -euo pipefail

systemctl --user stop iclr-web-lan.service
printf '网站已关闭（5173 跳转入口及 8443 网站服务）。\n'
