#!/usr/bin/env python3
"""Read experiment artifacts without changing the running worker or model."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path

try:
    from .deployment_paths import storage_path
except ImportError:
    from deployment_paths import storage_path
import statistics
import subprocess
import time

ROOT = storage_path('iclr-s4/experiments/repro500_qwen38_27b_q3_medium_64k_v2')
METHODS = ['taxoadapt', 'context', 'lisa', 'itl']


def worker_state():
    result = subprocess.run(['systemctl', '--user', 'show', 'iclr-s4-repro500-qwen38.service',
        '-p', 'ActiveState', '-p', 'SubState', '-p', 'ExecMainStatus', '-p', 'FreezerState'], capture_output=True, text=True)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def stage_forecast(root, groups, latest, now, config, state):
    if state.get('ActiveState') != 'active' or state.get('FreezerState') == 'frozen':
        return ['- 本阶段预计完成时间：任务未运行，恢复运行后重新估算。']
    events = []
    for line in (root / 'runtime/run.log').read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('event') in ('request_batch_start', 'request_progress', 'taxoadapt_node', 'method_complete'):
            events.append(event)
    progress = events[-1] if events else {}
    # The same schema is reused across recursive batches; never use its cumulative count.
    if progress.get('event') in ('request_batch_start', 'request_progress') and progress.get('task') == latest:
        total, completed = progress['total'], progress['completed']
        boundary = config.get('production_resumed_at', '')
        following = progress
        for event in reversed(events[:-1]):
            if (event.get('event') != 'request_progress' or event.get('task') != latest
                    or event.get('total') != total or event['completed'] >= following['completed']):
                boundary = max(boundary, event['time'])
                break
            following = event
    elif latest == 'taxoadapt_TypeClsSchema' and not any(
            e.get('task') == latest for e in events):
        total, completed = 500, 0
        boundary = config.get('production_resumed_at', '')
    else:
        return ['- 本阶段预计完成时间：等待当前批次总量或处理速率，下一次刷新自动更新。']
    rows = sorted([r for r in groups.get(latest, []) if r['ok'] and r['created_at'] >= boundary],
                  key=lambda r: r['created_at'])
    completed = min(total, max(completed, len(rows)))
    remaining = total - completed
    if not remaining:
        return [f'- 本阶段进度：{latest}，**{completed}/{total}**；本批次已完成，等待下一阶段。']
    recent = rows[-20:]
    concurrency = config['client_concurrency']
    if len(recent) >= max(4, concurrency):
        start = min(datetime.fromisoformat(r['created_at']) for r in recent)
        end = max(datetime.fromisoformat(r['created_at']) + timedelta(seconds=r['seconds']) for r in recent)
        seconds_each = (end - start).total_seconds() / len(recent)
        basis = f'本批次最近 {len(recent)} 个成功请求的实际处理速率'
    else:
        return [f'- 本阶段进度：{latest}，**{completed}/{total}**；预计完成时间：采样中。']
    seconds_left = remaining * seconds_each
    estimate = now + timedelta(seconds=seconds_left)
    return [f'- 本阶段进度：{latest}，**{completed}/{total}**；剩余 {remaining} 个请求。',
            f'- 本阶段预计完成时间：**{estimate:%Y-%m-%d %H:%M %Z}**；预计剩余 **{seconds_left / 60:.0f} 分钟**。',
            f'- 估算依据：{basis}；每 60 秒校准，仅涵盖本批次。']


def render(root, cache):
    groups = defaultdict(list)
    for path in (root / 'requests').glob('*/*.json'):
        if '.attempt' in path.name:
            continue
        signature = path.stat().st_mtime_ns
        if path not in cache or cache[path][0] != signature:
            data = json.loads(path.read_text())
            cache[path] = (signature, {'ok': data.get('ok', False), 'seconds': data.get('seconds', 0),
                                      'created_at': data.get('created_at', '')})
        groups[path.parent.name].append(cache[path][1])
    state = worker_state()
    outcome_path = root / 'runtime/workflow_status.json'
    outcome = json.loads(outcome_path.read_text()) if outcome_path.exists() else {}
    now = datetime.now().astimezone()
    config = json.loads((root / 'runtime/selected_config.json').read_text())
    concurrency = config['client_concurrency']
    done = [m for m in METHODS if (root / 'methods' / m / 'result.json').exists()]
    current = next((m for m in METHODS if m not in done), 'evaluation')
    related = [(task, max(v['created_at'] for v in rows)) for task, rows in groups.items()
               if task.startswith(current + '_')]
    latest = max(related, key=lambda x: x[1])[0] if related else '准备数据、向量或训练'
    lines = ['# 500 篇论文实验进度', '', f'更新时间：{now:%Y-%m-%d %H:%M:%S %Z}（每 60 秒更新；重新打开或刷新此文件）', '',
        f'- 任务状态：{state.get("ActiveState", "unknown")} / {state.get("SubState", "unknown")}，退出码 {state.get("ExecMainStatus", "unknown")}',
        f'- 调度状态：{state.get("FreezerState", "unknown")}；请求并发：{concurrency}',
        f'- 四方法完成：{len(done)}/4；当前方法：{current}；最近请求阶段：{latest}']
    lines += stage_forecast(root, groups, latest, now, config, state)
    if outcome.get('state') == 'failed':
        lines += [f'- 实验异常退出：{outcome.get("finished_at")}，实际退出码 {outcome.get("exit_code")}；详见运行日志。']
    lines += [
        '- 模型：Qwen3.8-27B UD-Q3_K_XL；K/V Q8_0；单请求上限 64K；medium 思考。',
        '- 多请求共享 64K KV 池，按输入 token 与最大生成预算控制准入；长请求自动排队。', '',
        '| 方法 | 完成状态 |', '|---|---|']
    running = state.get('ActiveState') in ('active', 'activating', 'reloading')
    lines += [f'| {m} | {"已完成" if m in done else ("进行中" if running else "已中断，未完成") if m == current else "等待"} |' for m in METHODS]
    lines += ['', '| 请求阶段 | 成功请求 | 失败请求 | 请求耗时中位数 |', '|---|---:|---:|---:|']
    for task, rows in sorted(groups.items()):
        good = [r for r in rows if r['ok']]
        seconds = statistics.median(r['seconds'] for r in good) if good else 0
        lines.append(f'| {task} | {len(good)} | {len(rows) - len(good)} | {seconds:.1f} 秒 |')
    lines += ['', '递归扩展会动态增加请求，当前无法给出可信的全流程百分比或准确结束时刻；阶段估计按正式并发速度持续校准。', '',
              f'[详细运行日志]({root}/runtime/run.log) · [服务日志]({root}/runtime/server.log) · [实验协议]({root}/PROTOCOL.md)',
              '', '成功请求数包含不同阶段对同一论文的多次处理，不能直接除以 500 当作全流程完成率。']
    return '\n'.join(lines) + '\n', state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    cache = {}
    while True:
        content, state = render(args.root, cache)
        target = args.root / 'PROGRESS.md'
        temporary = target.with_suffix('.md.tmp')
        temporary.write_text(content)
        temporary.replace(target)
        if not args.watch:
            print(content)
            return
        if state.get('ActiveState') not in ('active', 'activating', 'reloading'):
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
