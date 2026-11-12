"""Regression check for ETA when recursive batches reuse the same request schema."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile

from s4_reproduce500_status import stage_forecast


def test_recursive_batch_eta():
    task = 'taxoadapt_ClassifySchema'
    start = datetime.fromisoformat('2026-10-27T12:00:00+08:00')
    config = {'client_concurrency': 4, 'production_resumed_at': ''}
    active = {'ActiveState': 'active', 'FreezerState': 'running'}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'runtime').mkdir()
        events = [
            dict(event='request_progress', task=task, completed=50, total=50,
                 time=start.isoformat()),
            dict(event='request_progress', task=task, completed=20, total=50,
                 time=(start + timedelta(minutes=4)).isoformat()),
        ]
        (root / 'runtime/run.log').write_text('ordinary log\n' + '\n'.join(map(json.dumps, events)))
        rows = [dict(ok=True, seconds=40,
                     created_at=(start + timedelta(seconds=i * 10)).isoformat())
                for i in range(-50, 20)]
        now = start + timedelta(minutes=4)
        report = '\n'.join(stage_forecast(root, {task: rows}, task, now, config, active))
        assert '**20/50**' in report, report
        assert '2026-10-27 12:09' in report, report
        assert '剩余 30 个请求' in report, report
        paused = dict(active, FreezerState='frozen')
        assert '恢复运行后重新估算' in stage_forecast(root, {}, task, now, config, paused)[0]
        assert '等待当前批次' in stage_forecast(root, {}, 'new_task', now, config, active)[0]
        events[-1]['completed'] = 50
        (root / 'runtime/run.log').write_text('\n'.join(map(json.dumps, events)))
        assert '本批次已完成' in stage_forecast(root, {task: rows}, task, now, config, active)[0]


if __name__ == '__main__':
    test_recursive_batch_eta()
    print('Stage ETA regression check passed.')
