#!/usr/bin/env python3
"""Provide HTTPS Git credentials to scheduled jobs without storing them in Git config."""

import os
import sys


prompt = " ".join(sys.argv[1:]).lower()
if "username" in prompt:
    print("x-access-token")
elif "password" in prompt:
    print(os.environ.get("ICLR_GITHUB_TOKEN", ""))
else:
    print("")
