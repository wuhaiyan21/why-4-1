#!/usr/bin/env python3
import argparse
import csv
import json
import sys
import traceback
from pathlib import Path

from two_body_sim import simulate


def load_batch_config(batch_config_path):
    with open(batch_config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_single_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError('配置项必须是 JSON 对象')
    if 'name' not in cfg or not isinstance(cfg['name'], str) or not cfg['name'].strip():
        raise ValueError('配置项缺少有效 name 字段')

    required_keys = ['m1', 'x1', 'y1', 'vx1', 'vy1', 'm2', 'x2', 'y2', 'vx2', 'vy2', 'time', 'dt']
    missing = []
    for k in required_keys:
        if k not in cfg:
            missing.append(k)
    if missing:
        raise ValueError(f'缺少必要参数: {", ".join(missing)}')

    for k in required_keys:
        if not isinstance(cfg[k], (int, float)):
            raise ValueError(f'参数 {k} 必须是数值类型')

    if cfg['time'] <= 0:
        raise ValueError('仿真总时长 time 必须 > 0')
    if cfg['dt'] <= 0:
        raise ValueError('初始步长 dt 必须 > 0')
    if cfg['m1'] <= 0 or cfg['m2'] <= 0:
        raise ValueError('天体质量必须 > 0')

    sample_interval = cfg.get('sample_interval', 1)
    if not isinstance(sample_interval, int) or sample_interval < 1:
        raise ValueError('sample_interval 必须是 >= 1 的整数')


def sanitize_dirname(name):
    invalid = '<>:"/\\|?*'
    safe = ''.join('_' if c in invalid else c for c in name)
    return safe.strip() or 'unnamed'


def run_single(cfg, parent_dir):
    name = cfg['name']
    dir_name = sanitize_dirname(name)
    run_dir = parent_dir / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = run_dir / 'trajectory.csv'
    json_path = run_dir / 'summary.json'

    print(f'\n{"="*70}')
    print(f'[>] 开始运行配置: {name}')
    print(f'    输出目录: {run_dir}')
    print(f'{"="*70}')
    sys.stdout.flush()

    summary = simulate(
        m1=cfg['m1'], m2=cfg['m2'],
        x1=cfg['x1'], y1=cfg['y1'],
        x2=cfg['x2'], y2=cfg['y2'],
        vx1=cfg['vx1'], vy1=cfg['vy1'],
        vx2=cfg['vx2'], vy2=cfg['vy2'],
        total_time=cfg['time'], dt_init=cfg['dt'],
        csv_path=csv_path, json_path=json_path,
        sample_interval=cfg.get('sample_interval', 1)
    )

    print(f'\n[OK] 配置 [{name}] 运行完成')
    sys.stdout.flush()
    return summary


def flatten_config(cfg):
    flat = {'name': cfg['name']}
    for key in ['m1', 'x1', 'y1', 'vx1', 'vy1', 'm2', 'x2', 'y2', 'vx2', 'vy2', 'time', 'dt', 'sample_interval']:
        if key in cfg:
            flat[key] = cfg[key]
    return flat


def build_summary_rows(results):
    rows = []
    for item in results:
        cfg = item['config']
        status = item['status']
        row = {
            'name': cfg['name'],
            'status': status,
            'actual_steps': '',
            'energy_deviation_percent': '',
            'min_distance': '',
            'max_distance': '',
            'eccentricity': '',
            'error_reason': item.get('error', '')
        }
        if status == 'success' and 'summary' in item:
            s = item['summary']
            row['actual_steps'] = s.get('actual_steps', '')
            row['energy_deviation_percent'] = s.get('energy', {}).get('deviation_percent', '')
            row['min_distance'] = s.get('orbit_geometry', {}).get('min_distance', '')
            row['max_distance'] = s.get('orbit_geometry', {}).get('max_distance', '')
            row['eccentricity'] = s.get('orbit_geometry', {}).get('eccentricity', '')
        rows.append(row)
    return rows


def sort_rows(rows):
    def sort_key(r):
        dev = r['energy_deviation_percent']
        if r['status'] != 'success' or dev == '':
            return (1, 0, r['name'])
        return (0, float(dev), r['name'])
    return sorted(rows, key=sort_key)


def write_comparison_csv(rows, csv_path):
    fieldnames = [
        'name', 'status', 'actual_steps', 'energy_deviation_percent',
        'min_distance', 'max_distance', 'eccentricity', 'error_reason'
    ]
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def print_header_explanation():
    print('\n' + '='*70)
    print('[*] 汇总对比表列说明:')
    print('-'*70)
    print('  name                       配置名称标识')
    print('  status                     运行状态: success / failed')
    print('  actual_steps               实际积分步数')
    print('  energy_deviation_percent   能量相对偏差 (%)')
    print('  min_distance               全程最小距离 (m)')
    print('  max_distance               全程最大距离 (m)')
    print('  eccentricity               轨道偏心率')
    print('  error_reason               失败原因 (成功时为空)')
    print('='*70)
    print()


def main():
    parser = argparse.ArgumentParser(
        description='双体仿真批量对比工具 - 顺序执行多组配置并生成汇总对比表',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''示例:
  %(prog)s --batch-config batch_config_example.json --output-dir ./batch_results

输出目录结构:
  <output-dir>/
    ├── <config-name-1>/
    │   ├── trajectory.csv
    │   └── summary.json
    ├── <config-name-2>/
    │   ├── trajectory.csv
    │   └── summary.json
    └── comparison_summary.csv
'''
    )
    parser.add_argument('--batch-config', type=str, required=True,
                        help='批量配置文件路径 (JSON 数组格式，每项含 name 和仿真参数)')
    parser.add_argument('--output-dir', type=str, default='./batch_results',
                        help='批量结果输出父目录 (默认: ./batch_results)')

    args = parser.parse_args()

    batch_config_path = Path(args.batch_config)
    if not batch_config_path.is_file():
        print(f'错误: 批量配置文件不存在: {batch_config_path}', file=sys.stderr)
        sys.exit(1)

    try:
        batch_config = load_batch_config(batch_config_path)
    except Exception as e:
        print(f'错误: 读取批量配置文件失败: {e}', file=sys.stderr)
        sys.exit(1)

    if not isinstance(batch_config, list):
        print('错误: 批量配置文件根节点必须是 JSON 数组', file=sys.stderr)
        sys.exit(1)

    if len(batch_config) == 0:
        print('错误: 批量配置数组为空', file=sys.stderr)
        sys.exit(1)

    parent_dir = Path(args.output_dir)
    parent_dir.mkdir(parents=True, exist_ok=True)

    print('\n' + '#'*70)
    print(f'# 双体仿真批量对比工具')
    print(f'# 配置文件: {batch_config_path.resolve()}')
    print(f'# 输出目录: {parent_dir.resolve()}')
    print(f'# 配置组数: {len(batch_config)}')
    print('#'*70)
    sys.stdout.flush()

    results = []
    for idx, cfg in enumerate(batch_config, 1):
        item = {'index': idx, 'config': cfg if isinstance(cfg, dict) else {}, 'status': 'pending'}

        try:
            validate_single_config(cfg)
            item['config'] = cfg
        except Exception as e:
            item['status'] = 'failed'
            item['error'] = f'配置不合法: {e}'
            name = cfg.get('name', f'<第{idx}组>') if isinstance(cfg, dict) else f'<第{idx}组>'
            item['config']['name'] = name
            print(f'\n[FAIL] 配置 [{name}] 参数校验失败: {e}', file=sys.stderr)
            results.append(item)
            continue

        try:
            summary = run_single(cfg, parent_dir)
            item['status'] = 'success'
            item['summary'] = summary
        except Exception as e:
            item['status'] = 'failed'
            item['error'] = f'运行时错误: {e}'
            print(f'\n[FAIL] 配置 [{cfg["name"]}] 运行出错: {e}', file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)

        results.append(item)

    rows = build_summary_rows(results)
    sorted_rows = sort_rows(rows)

    comparison_csv = parent_dir / 'comparison_summary.csv'
    write_comparison_csv(sorted_rows, comparison_csv)

    print_header_explanation()

    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = len(results) - success_count
    print(f'[=] 批量运行汇总: 成功 {success_count} 组, 失败 {failed_count} 组, 共 {len(results)} 组')
    print(f'[=] 对比表已保存至: {comparison_csv.resolve()}')
    print()

    print('排名预览 (按能量偏差升序):')
    print('-'*70)
    header = f'{"排名":>4}  {"名称":<24}  {"状态":<8}  {"偏差(%)":>12}  {"步数":>10}'
    print(header)
    print('-'*70)
    for i, r in enumerate(sorted_rows, 1):
        dev = r['energy_deviation_percent'] if r['energy_deviation_percent'] != '' else '-'
        steps = r['actual_steps'] if r['actual_steps'] != '' else '-'
        print(f'{i:>4}  {str(r["name"]):<24}  {r["status"]:<8}  {str(dev):>12}  {str(steps):>10}')
    print()


if __name__ == '__main__':
    main()
