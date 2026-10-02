#!/usr/bin/env python3
"""Compare production Python/Rust HTTP servers on one Linux host, without printing.

Uses isolated data copies, loopback HTTP, alternating order, repeated warm requests,
and /proc memory/CPU accounting. Requires the retained Python release for comparison.
"""
import argparse
import concurrent.futures
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location('checks', Path(__file__).with_name('check_rust_api.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def stats(values):
    ordered = sorted(values)
    return {'n': len(values), 'median': statistics.median(values),
            'p95': ordered[math.ceil(len(ordered) * .95) - 1],
            'min': min(values), 'max': max(values)}


def request(connection, path, payload=None):
    connection.request('GET' if payload is None else 'POST', path, payload,
                       {'Content-Type': 'application/json'} if payload is not None else {})
    response = connection.getresponse()
    body = response.read()
    if response.status != 200:
        raise RuntimeError(f'{path}: HTTP {response.status}: {body[:300]!r}')
    if path.endswith('/preview'):
        return {'pngSize': checks.png_size(body), 'bytes': len(body)}
    data = json.loads(body)
    if path.endswith('/prepare'):
        assert len(data['rows']) == 100 and all(row['kind'] == 'ready' for row in data['rows'])
    return data


def memory(pid):
    values = {}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key, amount, _ = line.split()
            values[key.rstrip(':')] = int(amount) / 1024
    for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
        if line.startswith('Pss:'):
            values['Pss'] = int(line.split()[1]) / 1024
    return values


def cpu(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


def temperature():
    path = Path('/sys/class/thermal/thermal_zone0/temp')
    return int(path.read_text()) / 1000 if path.exists() else None


def throttling():
    if shutil.which('vcgencmd'):
        return subprocess.check_output(['vcgencmd', 'get_throttled'], text=True).strip()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-release', type=Path, required=True)
    parser.add_argument('--rust-release', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--samples', type=int, default=8)
    parser.add_argument('--port', type=int, default=8026)
    args = parser.parse_args()
    assert args.rounds > 0 and args.samples > 0
    args.work.mkdir(parents=True, exist_ok=False)
    python_source = args.work / 'python'
    python_source.mkdir()
    shutil.copytree(args.python_release / 'app', python_source / 'app', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['config.py', 'serve.py']:
        shutil.copy2(args.python_release / name, python_source / name)
    (python_source / 'instance').mkdir()
    for backend in ['python', 'rust']:
        shutil.copytree(args.data, args.work / backend / 'data',
                        ignore=shutil.ignore_patterns('classic-labels', 'simulated_labels', 'bulk-jobs', 'printer.lock'))
    pydata = python_source / 'data'
    (python_source / 'instance/application.py').write_text('\n'.join([
        "PRINTER_PRINTER = 'simulation'", "PRINTER_MODEL = 'QL-800'",
        f'STUDIO_DATA_DIR = {str(pydata)!r}', f'STUDIO_LABELS_DIR = {str(pydata / "labels")!r}',
        f'STUDIO_PRINTER_LOCK = {str(pydata / "printer.lock")!r}',
        "LABEL_DEFAULT_FONT_FAMILY = 'DejaVu Sans'", "LABEL_DEFAULT_FONT_STYLE = 'Book'",
    ]) + '\n')
    rust_config = args.work / 'rust/config.json'
    rust_config.write_text(json.dumps({'printer': 'simulation', 'model': 'QL-800',
        'dataDir': str(args.work / 'rust/data'), 'seedSamples': False,
        'staticDir': str(args.rust_release / 'app/static/studio'),
        'defaults': {'font': 'DejaVu Sans,Book'}}))
    commands = {'python': [str(args.python_release / '.venv/bin/python'), str(python_source / 'serve.py')],
                'rust': [str(args.rust_release / 'label-studio-server')]}
    cases = list(checks.reference_cases('DejaVu Sans,Book'))
    chosen = ['62-standard-False-plain', '62-standard-False-rich', '62-standard-False-qr',
              '62-standard-False-barcode', '62-standard-False-image', '62x100-standard-True-rich']
    workloads = [('config', '/studio/api/config', None), ('library', '/studio/api/labels', None)]
    for name, draft in cases:
        if name in chosen:
            workloads.append((name, '/studio/api/preview', json.dumps(draft).encode()))
    assert len(workloads) == 8
    template = checks.draft('DejaVu Sans,Book', {'kind': 'text', 'text': '{{Name}}\nSKU {{SKU}}'})
    bulk = {'template': template, 'csv': 'Name,SKU\n' + '\n'.join(f'Item {i},SKU-{i:04d}' for i in range(100)), 'timezone': 'UTC'}
    workloads.append(('prepare-100-csv-rows', '/studio/api/bulk/prepare', json.dumps(bulk).encode()))
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'device': Path('/proc/device-tree/model').read_text().rstrip('\0') if Path('/proc/device-tree/model').exists() else platform.machine(),
              'pythonCommit': (args.python_release / 'DEPLOYED_COMMIT').read_text().strip(),
              'rustCommit': (args.rust_release / 'DEPLOYED_COMMIT').read_text().strip(),
              'rounds': args.rounds, 'samplesPerRound': args.samples, 'runs': []}
    expected_fonts = None
    expected_defaults = None
    expected_geometry = {}
    for round_index in range(args.rounds):
        for backend in (['python', 'rust'] if round_index % 2 == 0 else ['rust', 'python']):
            env = {**os.environ, 'SERVER_HOST': '127.0.0.1', 'SERVER_PORT': str(args.port),
                   'PRINTER_PRINTER': 'simulation', 'LABEL_STUDIO_CONFIG': str(rust_config)}
            log = (args.work / f'{backend}-{round_index}.log').open('w')
            run = {'backend': backend, 'round': round_index + 1, 'temperatureBeforeC': temperature(),
                   'throttledBefore': throttling(), 'loadBefore': os.getloadavg(), 'workloads': {}}
            start = time.perf_counter()
            process = subprocess.Popen(commands[backend], cwd=python_source if backend == 'python' else args.rust_release,
                                       env=env, stdout=log, stderr=log)
            connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=30)
            try:
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'{backend} exited; inspect {log.name}')
                    try:
                        configuration = request(connection, '/studio/api/config')
                        break
                    except OSError:
                        connection.close()
                        if time.perf_counter() - start > 30:
                            raise RuntimeError('Startup timed out')
                        time.sleep(.005)
                run['startupMs'] = (time.perf_counter() - start) * 1000
                assert configuration['mode'] == 'simulation'
                assert request(connection, '/studio/api/status')['state'] == 'simulation'
                fonts = sorted(f['id'] for f in configuration['fonts'])
                if expected_fonts is None:
                    expected_fonts, expected_defaults = fonts, configuration['defaults']
                assert fonts == expected_fonts and configuration['defaults'] == expected_defaults
                run['idleMiB'] = memory(process.pid)
                for name, path, body in workloads:
                    for _ in range(2):
                        value = request(connection, path, body)
                    if path.endswith('/preview'):
                        expected_geometry.setdefault(name, value['pngSize'])
                        assert value['pngSize'] == expected_geometry[name]
                    before_cpu = cpu(process.pid)
                    durations = []
                    for _ in range(args.samples):
                        began = time.perf_counter()
                        value = request(connection, path, body)
                        durations.append((time.perf_counter() - began) * 1000)
                    run['workloads'][name] = {'latencyMs': durations,
                        'cpuMsPerRequest': (cpu(process.pid) - before_cpu) * 1000 / args.samples,
                        'responseBytes': value.get('bytes') if path.endswith('/preview') else None}
                parallel_body = next(body for name, _, body in workloads if name.endswith('-rich') and name.startswith('62-'))
                def client_batch(_):
                    client = http.client.HTTPConnection('127.0.0.1', args.port, timeout=30)
                    try:
                        for _ in range(20):
                            request(client, '/studio/api/preview', parallel_body)
                    finally:
                        client.close()
                began = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(client_batch, range(2)))
                run['twoClientRichPreviewsPerSecond'] = 40 / (time.perf_counter() - began)
                run['loadedMiB'] = memory(process.pid)
                run['temperatureAfterC'] = temperature()
                run['throttledAfter'] = throttling()
                report['runs'].append(run)
                (args.work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
                print(f'{backend} round {round_index + 1}: startup {run["startupMs"]:.1f} ms, idle RSS {run["idleMiB"]["VmRSS"]:.1f} MiB, loaded RSS {run["loadedMiB"]["VmRSS"]:.1f} MiB', flush=True)
            finally:
                connection.close()
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.close()
    report['summary'] = {}
    for backend in ['python', 'rust']:
        runs = [r for r in report['runs'] if r['backend'] == backend]
        report['summary'][backend] = {
            'startupMs': stats([r['startupMs'] for r in runs]),
            'idleRssMiB': stats([r['idleMiB']['VmRSS'] for r in runs]),
            'idlePssMiB': stats([r['idleMiB']['Pss'] for r in runs]),
            'loadedRssMiB': stats([r['loadedMiB']['VmRSS'] for r in runs]),
            'peakRssMiB': stats([r['loadedMiB']['VmHWM'] for r in runs]),
            'twoClientRichPreviewsPerSecond': stats([r['twoClientRichPreviewsPerSecond'] for r in runs]),
            'workloads': {name: stats([t for r in runs for t in r['workloads'][name]['latencyMs']]) for name, _, _ in workloads}}
    (args.work / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Completed. All requests used simulation servers on loopback; no print endpoint was called.', flush=True)


if __name__ == '__main__':
    main()
