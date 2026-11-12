#!/usr/bin/env bash
# Control an existing user service; fresh deployments use run_website.sh.
set -euo pipefail

systemctl --user start iclr-web-lan.service
systemctl --user is-active --quiet iclr-web-lan.service
printf '网站服务已启动。查看配置：systemctl --user cat iclr-web-lan.service\n'
