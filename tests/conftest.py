"""pytest 共享配置：把 scripts/ 加入 import 路径。

所有测试都是**离线纯逻辑**测试（不联网、不依赖指纹浏览器/服务），
所以在任意机器与 CI 上都能直接跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for p in (str(SCRIPTS), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
