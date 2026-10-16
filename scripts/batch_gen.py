"""批量出图（并发跑号池，自动在多个窗口间分配）

用法
----
    # 每行一个提示词（# 开头是注释）
    python scripts/batch_gen.py prompts.txt --outdir out --concurrency 4

    # 同一个提示词出 N 张
    python scripts/batch_gen.py --prompt "极简风格的咖啡杯" -n 6 --outdir out

    # 风格/比例/分辨率对所有任务生效
    python scripts/batch_gen.py prompts.txt --style cyberpunk --ratio 16:9 --res 2k

输出
----
    成功：out/<序号>_<时间戳>.png
    结束打印汇总表，并生成 out/_batch_report.json

退出码：0 = 全部成功；1 = 有失败（部分成功也算 1，便于 CI/脚本判断）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402
import gen_image as G  # noqa: E402


def read_prompts(path: Path) -> list[str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    else:
        raise SystemExit(f"无法识别文件编码：{path}")
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="批量出图（号池并发）")
    ap.add_argument("prompts_file", nargs="?", default="", help="提示词文件（每行一条）")
    ap.add_argument("--prompt", default="", help="单条提示词（与 -n 搭配出多张）")
    ap.add_argument("-n", "--count", type=int, default=1, help="--prompt 模式下生成张数")
    ap.add_argument("--outdir", default="output", help="输出目录")
    ap.add_argument("--concurrency", type=int, default=3, help="并发数（建议 ≤ 窗口数）")
    ap.add_argument("--ratio", default="1:1")
    ap.add_argument("--res", default="1k", choices=["1k", "2k", "4k"])
    ap.add_argument("--style", default="concept_art")
    ap.add_argument("--raw-prompt", action="store_true")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--fpb-url", default="")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--retry-failed", action="store_true", help="只重跑上次报告里失败的条目（免费号偶发，很好用）")
    ap.add_argument("--report", default="", help="报告文件路径（默认 <outdir>/_batch_report.json）")
    args = ap.parse_args()

    C.ensure_stdout_encoding()

    outdir = Path(args.outdir)
    report = Path(args.report) if args.report else outdir / "_batch_report.json"
    prompts: list[str] = []

    if args.retry_failed:
        if not report.exists():
            C.fail(f"找不到上次的报告：{report}（先正常跑一次 batch，再用 --retry-failed）")
            return 1
        prev = json.loads(report.read_text(encoding="utf-8"))
        failed_items = [x for x in (prev.get("items") or []) if not x.get("ok")]
        if not failed_items:
            C.ok("上次没有失败条目，无需重跑")
            return 0
        prompts = [str(x.get("prompt") or "") for x in failed_items]
        prompts = [x for x in prompts if x]
        C.info(f"重跑上次失败的 {len(prompts)} 个任务")

    if args.prompt:
        prompts = [args.prompt] * max(1, args.count)
    elif args.prompts_file:
        prompts = read_prompts(Path(args.prompts_file))
    elif not prompts:
        C.fail("请给出提示词文件，或用 --prompt \"...\" -n 3，或加 --retry-failed")
        return 1
    if not prompts:
        C.fail("没有解析到任何提示词")
        return 1

    p = C.Paths.discover()
    api_url = args.fpb_url.rstrip("/") if args.fpb_url else p.fpb_api_url
    api_key = G.resolve_api_key(p, args.api_key)
    outdir.mkdir(parents=True, exist_ok=True)

    if not C.tcp_listening(p.fpb_port) and "127.0.0.1" in api_url:
        C.fail(f"FPBrowser2API 未运行（{p.fpb_port}）→ python scripts/start_all.py")
        return 1

    C.title(f"批量出图：{len(prompts)} 个任务，并发 {args.concurrency}")
    C.log(f"  输出目录：{outdir.resolve()}")
    C.log("")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    t0 = time.time()
    results: list[dict] = []

    def run(idx: int, prompt: str) -> dict:
        out = outdir / f"{idx:03d}_{stamp}.png"
        try:
            r = G.generate_one(
                p=p, api_url=api_url, api_key=api_key, prompt=prompt, out_path=out,
                ratio=args.ratio, res=args.res, style=args.style,
                raw_prompt=args.raw_prompt, timeout=args.timeout, poll=6.0, quiet=True,
            )
            r["index"] = idx
            r["prompt"] = prompt
            return r
        except Exception as e:
            return {"index": idx, "prompt": prompt, "ok": False, "error": str(e)}

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(run, i, pr): i for i, pr in enumerate(prompts, 1)}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            done += 1
            flag = "OK  " if r.get("ok") else "FAIL"
            detail = (r.get("saved_path") or r.get("error") or "")[:70]
            C.log(f"  [{done:2d}/{len(prompts)}] {flag} #{r['index']:<3} {detail}")
            results.append(r)

    ok = sum(1 for r in results if r.get("ok"))
    fail = len(results) - ok
    cost = time.time() - t0

    report = report  # 已在参数阶段解析
    report.write_text(json.dumps(
        {"total": len(prompts), "ok": ok, "failed": fail, "seconds": round(cost, 1),
         "ratio": args.ratio, "res": args.res, "style": args.style, "items": results},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")

    C.log("")
    C.log("-" * 68)
    C.log(f"  成功 {ok}/{len(prompts)}，失败 {fail}，耗时 {cost:.0f}s（平均 {cost / max(1, len(prompts)):.0f}s/张）")
    C.info(f"报告：{report}")
    if fail:
        C.log(f"  失败明细（可直接重跑失败的：pool.bat batch --outdir {outdir} --retry-failed）：")
        for r in results:
            if not r.get("ok"):
                msg = str(r.get("error") or "")
                hint = G.diagnose(msg)
                C.log(f"    #{r['index']}: {msg[:100]}" + (f"  → {hint}" if hint else ""))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
