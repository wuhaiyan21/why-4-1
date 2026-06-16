#!/usr/bin/env python3
import argparse
import csv
import json
import sys
import traceback
from pathlib import Path

from two_body_sim import simulate


def format_sci(val, decimals=4):
    if val == '' or val is None:
        return '-'
    try:
        v = float(val)
        return f'{v:.{decimals}g}'
    except (ValueError, TypeError):
        return str(val)


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


def run_single(cfg, parent_dir, verbose=False):
    name = cfg['name']
    dir_name = sanitize_dirname(name)
    run_dir = parent_dir / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = run_dir / 'trajectory.csv'
    json_path = run_dir / 'summary.json'

    if verbose:
        print(f'\n{"="*70}')
        print(f'[>] 开始运行配置: {name}')
        print(f'    输出目录: {run_dir}')
        print(f'{"="*70}')
    else:
        print(f'[{cfg.get("_index", "?")}/{cfg.get("_total", "?")}] 运行中: {name:<30} ', end='', flush=True)
    sys.stdout.flush()

    summary = simulate(
        m1=cfg['m1'], m2=cfg['m2'],
        x1=cfg['x1'], y1=cfg['y1'],
        x2=cfg['x2'], y2=cfg['y2'],
        vx1=cfg['vx1'], vy1=cfg['vy1'],
        vx2=cfg['vx2'], vy2=cfg['vy2'],
        total_time=cfg['time'], dt_init=cfg['dt'],
        csv_path=csv_path, json_path=json_path,
        sample_interval=cfg.get('sample_interval', 1),
        verbose=verbose
    )

    if verbose:
        print(f'\n[OK] 配置 [{name}] 运行完成')
    else:
        dev = summary.get('energy', {}).get('deviation_percent', '')
        dev_str = format_sci(dev)
        steps = summary.get('actual_steps', '')
        print(f'[OK] 成功 | 偏差={dev_str}% | 步数={steps}')
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


def read_trajectory_csv(csv_path):
    points1 = []
    points2 = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    x1 = float(row['x1'])
                    y1 = float(row['y1'])
                    x2 = float(row['x2'])
                    y2 = float(row['y2'])
                    points1.append((x1, y1))
                    points2.append((x2, y2))
                except (ValueError, KeyError):
                    continue
    except Exception:
        pass
    return points1, points2


def generate_svg(points1, points2, width=400, height=300, margin=20):
    if not points1 and not points2:
        return '<svg width="400" height="300" xmlns="http://www.w3.org/2000/svg"><text x="200" y="150" text-anchor="middle" fill="#999">无轨迹数据</text></svg>'

    all_points = points1 + points2
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    range_x = max_x - min_x if max_x != min_x else 1.0
    range_y = max_y - min_y if max_y != min_y else 1.0

    plot_width = width - 2 * margin
    plot_height = height - 2 * margin

    def to_svg(x, y):
        sx = margin + (x - min_x) / range_x * plot_width
        sy = margin + (1.0 - (y - min_y) / range_y) * plot_height
        return sx, sy

    def path_data(points):
        if not points:
            return ''
        d = []
        for i, (x, y) in enumerate(points):
            sx, sy = to_svg(x, y)
            if i == 0:
                d.append(f'M {sx:.2f} {sy:.2f}')
            else:
                d.append(f'L {sx:.2f} {sy:.2f}')
        return ' '.join(d)

    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="border:1px solid #ddd; border-radius:4px;">',
        f'<rect width="100%" height="100%" fill="#fafafa"/>',
    ]

    for i in range(5):
        gx = margin + i * plot_width / 4
        gy = margin + i * plot_height / 4
        svg_parts.append(f'<line x1="{gx}" y1="{margin}" x2="{gx}" y2="{height-margin}" stroke="#eee" stroke-width="1"/>')
        svg_parts.append(f'<line x1="{margin}" y1="{gy}" x2="{width-margin}" y2="{gy}" stroke="#eee" stroke-width="1"/>')

    path1 = path_data(points1)
    if path1:
        svg_parts.append(f'<path d="{path1}" fill="none" stroke="#3498db" stroke-width="1.5" opacity="0.8"/>')

    path2 = path_data(points2)
    if path2:
        svg_parts.append(f'<path d="{path2}" fill="none" stroke="#e74c3c" stroke-width="1.5" opacity="0.8"/>')

    if points1:
        sx1, sy1 = to_svg(points1[0][0], points1[0][1])
        ex1, ey1 = to_svg(points1[-1][0], points1[-1][1])
        svg_parts.append(f'<circle cx="{sx1:.2f}" cy="{sy1:.2f}" r="4" fill="#3498db" stroke="#fff" stroke-width="1"/>')
        svg_parts.append(f'<circle cx="{ex1:.2f}" cy="{ey1:.2f}" r="4" fill="#3498db" stroke="#fff" stroke-width="2"/>')

    if points2:
        sx2, sy2 = to_svg(points2[0][0], points2[0][1])
        ex2, ey2 = to_svg(points2[-1][0], points2[-1][1])
        svg_parts.append(f'<circle cx="{sx2:.2f}" cy="{sy2:.2f}" r="4" fill="#e74c3c" stroke="#fff" stroke-width="1"/>')
        svg_parts.append(f'<circle cx="{ex2:.2f}" cy="{ey2:.2f}" r="4" fill="#e74c3c" stroke="#fff" stroke-width="2"/>')

    svg_parts.append(f'<text x="{margin}" y="{height-5}" font-size="10" fill="#999">天体1 (蓝) · 天体2 (红) · 实心=起点 · 空心=终点</text>')
    svg_parts.append('</svg>')

    return '\n'.join(svg_parts)


def generate_html_report(rows, results, parent_dir, sorted_results):
    html_path = parent_dir / 'comparison_report.html'

    def fmt(v, suffix=''):
        if v == '' or v is None:
            return '<span style="color:#999">-</span>'
        try:
            fv = float(v)
            return f'{fv:.4g}{suffix}'
        except (ValueError, TypeError):
            return str(v)

    def status_class(s):
        return 'status-success' if s == 'success' else 'status-failed'

    html_content = []
    html_content.append('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>双体仿真批量对比报告</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f7fa; color: #333; }
  h1 { font-size: 24px; margin-bottom: 8px; color: #2c3e50; }
  .subtitle { color: #7f8c8d; margin-bottom: 24px; font-size: 14px; }
  .summary-card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .summary-stats { display: flex; gap: 20px; margin-bottom: 16px; }
  .stat { flex: 1; text-align: center; padding: 12px; border-radius: 6px; }
  .stat-success { background: #d4edda; color: #155724; }
  .stat-failed { background: #f8d7da; color: #721c24; }
  .stat-total { background: #d1ecf1; color: #0c5460; }
  .stat-value { font-size: 28px; font-weight: bold; }
  .stat-label { font-size: 12px; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }
  th { background: #f8f9fa; font-weight: 600; color: #495057; position: sticky; top: 0; }
  tr:hover { background: #f8f9fa; }
  .status-success { color: #28a745; font-weight: 500; }
  .status-failed { color: #dc3545; font-weight: 500; }
  .section { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .section-failed { border-left: 4px solid #dc3545; }
  .section h2 { font-size: 18px; margin-bottom: 16px; color: #2c3e50; display: flex; align-items: center; gap: 10px; }
  .section-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
  .badge-success { background: #d4edda; color: #155724; }
  .badge-failed { background: #f8d7da; color: #721c24; }
  .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .metric { background: #f8f9fa; padding: 12px; border-radius: 6px; }
  .metric-label { font-size: 11px; color: #6c757d; margin-bottom: 4px; }
  .metric-value { font-size: 16px; font-weight: 600; color: #2c3e50; }
  .metric-unit { font-size: 11px; color: #6c757d; font-weight: normal; }
  .svg-container { display: flex; justify-content: center; padding: 10px; background: #fafafa; border-radius: 6px; }
  .error-box { background: #f8d7da; color: #721c24; padding: 12px; border-radius: 6px; font-family: monospace; font-size: 13px; }
  a { color: #0066cc; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
''')

    success_count = sum(1 for r in rows if r['status'] == 'success')
    failed_count = len(rows) - success_count
    total_count = len(rows)

    html_content.append(f'''
<h1>双体仿真批量对比报告</h1>
<p class="subtitle">共 {total_count} 组配置 · 成功 {success_count} 组 · 失败 {failed_count} 组</p>

<div class="summary-card">
  <div class="summary-stats">
    <div class="stat stat-total"><div class="stat-value">{total_count}</div><div class="stat-label">总组数</div></div>
    <div class="stat stat-success"><div class="stat-value">{success_count}</div><div class="stat-label">成功</div></div>
    <div class="stat stat-failed"><div class="stat-value">{failed_count}</div><div class="stat-label">失败</div></div>
  </div>
  <h3 style="margin-bottom:12px; font-size:16px; color:#495057;">汇总对比表</h3>
  <div style="overflow-x:auto;">
  <table>
    <thead>
      <tr>
        <th>排名</th>
        <th>名称</th>
        <th>状态</th>
        <th>实际步数</th>
        <th>能量偏差(%)</th>
        <th>最小距离(m)</th>
        <th>最大距离(m)</th>
        <th>偏心率</th>
        <th>失败原因</th>
      </tr>
    </thead>
    <tbody>
''')

    for i, row in enumerate(rows, 1):
        html_content.append(f'''
      <tr>
        <td>{i}</td>
        <td><a href="#sec-{i}">{row['name']}</a></td>
        <td class="{status_class(row['status'])}">{row['status']}</td>
        <td>{fmt(row['actual_steps'])}</td>
        <td>{fmt(row['energy_deviation_percent'])}</td>
        <td>{fmt(row['min_distance'])}</td>
        <td>{fmt(row['max_distance'])}</td>
        <td>{fmt(row['eccentricity'])}</td>
        <td style="font-family:monospace; font-size:12px;">{fmt(row['error_reason'])}</td>
      </tr>
''')

    html_content.append('''
    </tbody>
  </table>
  </div>
</div>
''')

    for i, (row, item) in enumerate(zip(rows, sorted_results), 1):
        html_content.append(f'<div id="sec-{i}" class="section {"section-failed" if row["status"] == "failed" else ""}">')
        html_content.append(f'<h2>{i}. {row["name"]} <span class="section-badge {"badge-success" if row["status"] == "success" else "badge-failed"}">{row["status"]}</span></h2>')

        if row['status'] == 'failed':
            html_content.append(f'<div class="error-box">失败原因: {row["error_reason"]}</div>')
        else:
            html_content.append('<div class="metrics-grid">')
            html_content.append(f'<div class="metric"><div class="metric-label">能量偏差</div><div class="metric-value">{fmt(row["energy_deviation_percent"])}<span class="metric-unit">%</span></div></div>')
            html_content.append(f'<div class="metric"><div class="metric-label">最小距离</div><div class="metric-value">{fmt(row["min_distance"])}<span class="metric-unit">m</span></div></div>')
            html_content.append(f'<div class="metric"><div class="metric-label">最大距离</div><div class="metric-value">{fmt(row["max_distance"])}<span class="metric-unit">m</span></div></div>')
            html_content.append(f'<div class="metric"><div class="metric-label">偏心率</div><div class="metric-value">{fmt(row["eccentricity"])}</div></div>')
            html_content.append(f'<div class="metric"><div class="metric-label">实际步数</div><div class="metric-value">{fmt(row["actual_steps"])}</div></div>')
            html_content.append('</div>')

            cfg = item['config']
            dir_name = sanitize_dirname(cfg['name'])
            csv_path = parent_dir / dir_name / 'trajectory.csv'
            points1, points2 = read_trajectory_csv(csv_path)
            svg = generate_svg(points1, points2)
            html_content.append(f'<div class="svg-container">{svg}</div>')

        html_content.append('</div>')

    html_content.append('''
<footer style="text-align:center; color:#999; font-size:12px; margin-top:30px; padding:20px;">
  双体仿真批量对比报告 · 由 batch_compare.py 自动生成
</footer>
</body>
</html>
''')

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))

    return html_path


def main():
    parser = argparse.ArgumentParser(
        description='双体仿真批量对比工具 - 顺序执行多组配置并生成汇总对比表',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''示例:
  %(prog)s --batch-config batch_config_example.json --output-dir ./batch_results
  %(prog)s --batch-config batch_config_example.json --verbose
  %(prog)s --batch-config batch_config_example.json --no-html

输出目录结构:
  <output-dir>/
    ├── <config-name-1>/
    │   ├── trajectory.csv
    │   └── summary.json
    ├── <config-name-2>/
    │   ├── trajectory.csv
    │   └── summary.json
    ├── comparison_summary.csv
    └── comparison_report.html
'''
    )
    parser.add_argument('--batch-config', type=str, required=True,
                        help='批量配置文件路径 (JSON 数组格式，每项含 name 和仿真参数)')
    parser.add_argument('--output-dir', type=str, default='./batch_results',
                        help='批量结果输出父目录 (默认: ./batch_results)')
    parser.add_argument('--verbose', action='store_true',
                        help='显示每组完整的仿真日志 (积分进度、ASCII轨迹图)')
    parser.add_argument('--no-html', action='store_true',
                        help='不生成 HTML 对比报告')

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

    total = len(batch_config)
    verbose = args.verbose

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
            if verbose:
                print(f'\n[FAIL] 配置 [{name}] 参数校验失败: {e}', file=sys.stderr)
            else:
                print(f'[{idx}/{total}] 校验中: {name:<30} [FAIL] 失败 | 原因: 配置不合法')
            results.append(item)
            continue

        cfg['_index'] = idx
        cfg['_total'] = total

        try:
            summary = run_single(cfg, parent_dir, verbose=verbose)
            item['status'] = 'success'
            item['summary'] = summary
        except Exception as e:
            item['status'] = 'failed'
            item['error'] = f'运行时错误: {e}'
            if verbose:
                print(f'\n[FAIL] 配置 [{cfg["name"]}] 运行出错: {e}', file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
            else:
                print(f'[FAIL] 失败 | 原因: 运行时错误')

        results.append(item)

    rows = build_summary_rows(results)
    sorted_rows = sort_rows(rows)

    name_to_result = {r['config']['name']: r for r in results}
    sorted_results = [name_to_result[row['name']] for row in sorted_rows]

    comparison_csv = parent_dir / 'comparison_summary.csv'
    write_comparison_csv(sorted_rows, comparison_csv)

    html_path = None
    if not args.no_html:
        try:
            html_path = generate_html_report(sorted_rows, results, parent_dir, sorted_results)
        except Exception as e:
            print(f'\n[WARN] 生成 HTML 报告失败: {e}', file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)

    print_header_explanation()

    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = len(results) - success_count
    print(f'[=] 批量运行汇总: 成功 {success_count} 组, 失败 {failed_count} 组, 共 {len(results)} 组')
    print(f'[=] 对比表已保存至: {comparison_csv.resolve()}')
    if html_path:
        print(f'[=] HTML报告已保存至: {html_path.resolve()}')
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
