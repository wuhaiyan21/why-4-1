#!/usr/bin/env python3
import argparse
import csv
import json
import math
import sys
from pathlib import Path

G = 6.67430e-11
MIN_DT = 1e-6


class Body:
    def __init__(self, mass, x, y, vx, vy):
        self.mass = mass
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy


def compute_force(b1, b2):
    dx = b2.x - b1.x
    dy = b2.y - b1.y
    r2 = dx * dx + dy * dy
    r = math.sqrt(r2)
    if r == 0:
        return 0.0, 0.0, 0.0
    f = G * b1.mass * b2.mass / r2
    fx = f * dx / r
    fy = f * dy / r
    return fx, fy, r


def compute_acceleration(b, other):
    fx, fy, r = compute_force(b, other)
    ax = fx / b.mass
    ay = fy / b.mass
    return ax, ay, r


def compute_energy(b1, b2):
    v1_sq = b1.vx ** 2 + b1.vy ** 2
    v2_sq = b2.vx ** 2 + b2.vy ** 2
    ke = 0.5 * b1.mass * v1_sq + 0.5 * b2.mass * v2_sq
    dx = b2.x - b1.x
    dy = b2.y - b1.y
    r = math.sqrt(dx * dx + dy * dy)
    if r == 0:
        pe = 0.0
    else:
        pe = -G * b1.mass * b2.mass / r
    return ke + pe


def adaptive_dt(dt, dt_init, r_current, initial_distance):
    threshold = initial_distance / 10.0
    if r_current < threshold:
        n = 0
        r = threshold
        while r_current < r / 2 and dt_init / (2 ** (n + 2)) >= MIN_DT:
            r /= 2
            n += 1
        target_dt = dt_init / (2 ** (n + 1))
        if target_dt < dt:
            return target_dt, True
    else:
        if dt < dt_init:
            n = 1
            r = threshold
            while r_current >= r * 2 and dt_init / (2 ** (n - 1)) <= dt_init:
                r *= 2
                n -= 1
            target_dt = dt_init / (2 ** max(0, n))
            if target_dt > dt:
                return target_dt, False
    return dt, False


def simulate(m1, m2, x1, y1, x2, y2, vx1, vy1, vx2, vy2, total_time, dt_init,
             csv_path, json_path, sample_interval=1):
    b1 = Body(m1, x1, y1, vx1, vy1)
    b2 = Body(m2, x2, y2, vx2, vy2)

    _, _, r0 = compute_force(b1, b2)
    initial_distance = r0 if r0 > 0 else 1.0
    threshold_distance = initial_distance / 10.0

    initial_energy = compute_energy(b1, b2)

    t = 0.0
    dt = dt_init
    actual_steps = 0
    adaptive_trigger_count = 0
    records = []
    track1 = []
    track2 = []
    dt_history = []

    initial_state = (b1.x, b1.y, b1.vx, b1.vy, b2.x, b2.y, b2.vx, b2.vy)

    _, _, r0 = compute_force(b1, b2)
    min_distance = r0
    max_distance = r0

    records.append((t, b1.x, b1.y, b2.x, b2.y, dt))
    track1.append((b1.x, b1.y))
    track2.append((b2.x, b2.y))
    dt_history.append(dt)

    print_interval = max(1, int(total_time / dt_init / 20))
    step_counter = 0
    warned = False

    print(f'===== 仿真开始 =====')
    print(f'初始能量: {initial_energy:.10g} J')
    print(f'初始距离: {initial_distance:.4g} m, 近距阈值: {threshold_distance:.4g} m')
    print(f'初始时间步长: {dt_init} s')
    print(f'进度每 {print_interval} 步输出一次')
    print(f'{"="*60}')
    print(f'{"时间(s)":>12}  {"距离(m)":>14}  {"步长(s)":>10}  {"能量(J)":>16}  {"偏差(%)":>10}')
    print(f'{"-"*60}')
    sys.stdout.flush()

    while t < total_time:
        if t + dt > total_time:
            dt = total_time - t

        _, _, r_current = compute_force(b1, b2)
        if r_current < min_distance:
            min_distance = r_current
        if r_current > max_distance:
            max_distance = r_current
        new_dt, triggered = adaptive_dt(dt, dt_init, r_current, initial_distance)
        if triggered:
            adaptive_trigger_count += 1
        dt = new_dt

        ax1, ay1, _ = compute_acceleration(b1, b2)
        ax2, ay2, _ = compute_acceleration(b2, b1)

        b1.x += b1.vx * dt + 0.5 * ax1 * dt * dt
        b1.y += b1.vy * dt + 0.5 * ay1 * dt * dt
        b2.x += b2.vx * dt + 0.5 * ax2 * dt * dt
        b2.y += b2.vy * dt + 0.5 * ay2 * dt * dt

        ax1_new, ay1_new, _ = compute_acceleration(b1, b2)
        ax2_new, ay2_new, _ = compute_acceleration(b2, b1)

        b1.vx += 0.5 * (ax1 + ax1_new) * dt
        b1.vy += 0.5 * (ay1 + ay1_new) * dt
        b2.vx += 0.5 * (ax2 + ax2_new) * dt
        b2.vy += 0.5 * (ay2 + ay2_new) * dt

        t += dt
        actual_steps += 1
        step_counter += 1

        current_energy = compute_energy(b1, b2)
        if initial_energy != 0:
            current_deviation = abs((current_energy - initial_energy) / initial_energy) * 100.0
        else:
            current_deviation = 0.0

        if current_deviation > 1.0 and not warned:
            print(f'[WARN] 警告: t={t:.4g}s 时能量相对偏差已达 {current_deviation:.4f}%，超过1%阈值！', file=sys.stderr)
            warned = True
        elif current_deviation > 1.0 and step_counter % max(1, print_interval // 2) == 0:
            print(f'[WARN] 持续警告: t={t:.4g}s 能量偏差 {current_deviation:.4f}%', file=sys.stderr)

        if step_counter % print_interval == 0 or step_counter == 1:
            _, _, r = compute_force(b1, b2)
            print(f'{t:>12.4g}  {r:>14.4g}  {dt:>10.3g}  {current_energy:>16.4e}  {current_deviation:>10.4f}')
            sys.stdout.flush()

        dt_history.append(dt)
        track1.append((b1.x, b1.y))
        track2.append((b2.x, b2.y))

        if actual_steps % sample_interval == 0:
            records.append((t, b1.x, b1.y, b2.x, b2.y, dt))

    _, _, r_final = compute_force(b1, b2)
    if r_final < min_distance:
        min_distance = r_final
    if r_final > max_distance:
        max_distance = r_final

    final_state = (b1.x, b1.y, b1.vx, b1.vy, b2.x, b2.y, b2.vx, b2.vy)

    def compute_eccentricity(state):
        x1, y1, vx1, vy1, x2, y2, vx2, vy2 = state
        total_mass = m1 + m2
        dx = x2 - x1
        dy = y2 - y1
        dvx = vx2 - vx1
        dvy = vy2 - vy1
        r = math.sqrt(dx * dx + dy * dy)
        v_sq = dvx * dvx + dvy * dvy
        h = dx * dvy - dy * dvx
        h_sq = h * h
        mu = G * total_mass
        if mu == 0 or r == 0:
            return 0.0
        e_x = (v_sq / mu - 1.0 / r) * dx - (dvx * (dx * dvx + dy * dvy)) / mu
        e_y = (v_sq / mu - 1.0 / r) * dy - (dvy * (dx * dvx + dy * dvy)) / mu
        eccentricity = math.sqrt(e_x * e_x + e_y * e_y)
        return eccentricity

    ecc_initial = compute_eccentricity(initial_state)
    ecc_final = compute_eccentricity(final_state)
    eccentricity = (ecc_initial + ecc_final) / 2.0

    final_energy = compute_energy(b1, b2)
    if initial_energy != 0:
        energy_deviation_pct = abs((final_energy - initial_energy) / initial_energy) * 100.0
    else:
        energy_deviation_pct = 0.0

    print(f'{"-"*60}')

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'x1', 'y1', 'x2', 'y2', 'dt'])
        for row in records:
            writer.writerow([f'{row[0]:.10g}', f'{row[1]:.10g}', f'{row[2]:.10g}',
                             f'{row[3]:.10g}', f'{row[4]:.10g}', f'{row[5]:.10g}'])

    summary = {
        'initial_conditions': {
            'body1': {'mass': m1, 'position': [x1, y1], 'velocity': [vx1, vy1]},
            'body2': {'mass': m2, 'position': [x2, y2], 'velocity': [vx2, vy2]},
            'total_time': total_time,
            'initial_dt': dt_init,
            'sample_interval': sample_interval
        },
        'final_positions': {
            'body1': [b1.x, b1.y],
            'body2': [b2.x, b2.y]
        },
        'energy': {
            'initial': initial_energy,
            'final': final_energy,
            'deviation_percent': energy_deviation_pct
        },
        'orbit_geometry': {
            'min_distance': min_distance,
            'max_distance': max_distance,
            'eccentricity': eccentricity
        },
        'actual_steps': actual_steps,
        'csv_rows': len(records),
        'adaptive_trigger_count': adaptive_trigger_count,
        'min_dt_used': min(dt_history),
        'max_dt_used': max(dt_history)
    }

    with open(json_path, 'w') as f:
        json.dump(summary, f, indent=2)

    if energy_deviation_pct > 1.0:
        print(f'[WARN] 最终警告: 能量相对偏差为 {energy_deviation_pct:.4f}%，超过1%阈值！', file=sys.stderr)

    print(f'最终能量: {final_energy:.10g} J')
    print(f'能量相对偏差: {energy_deviation_pct:.6f}%')
    print(f'实际步数: {actual_steps}')
    print(f'自适应步长触发次数: {adaptive_trigger_count}')
    print(f'使用步长范围: {min(dt_history):.3g} ~ {max(dt_history):.3g} s')
    print(f'CSV轨迹已保存至: {csv_path}')
    print(f'JSON摘要已保存至: {json_path}')

    print('\n二维轨迹俯瞰图:')
    draw_ascii_track(track1, track2)

    return summary


def draw_ascii_track(track1, track2, width=80, height=24):
    all_points = track1 + track2
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    range_x = max_x - min_x if max_x != min_x else 1.0
    range_y = max_y - min_y if max_y != min_y else 1.0

    count1 = [[0 for _ in range(width)] for _ in range(height)]
    count2 = [[0 for _ in range(width)] for _ in range(height)]

    def project(x, y):
        cx = int((x - min_x) / range_x * (width - 1))
        cy = int((1.0 - (y - min_y) / range_y) * (height - 1))
        cx = max(0, min(width - 1, cx))
        cy = max(0, min(height - 1, cy))
        return cx, cy

    for x, y in track1:
        cx, cy = project(x, y)
        count1[cy][cx] += 1

    for x, y in track2:
        cx, cy = project(x, y)
        count2[cy][cx] += 1

    def density_char_b1(cnt):
        if cnt == 0:
            return ' '
        elif cnt == 1:
            return 'o'
        elif cnt <= 3:
            return 'O'
        elif cnt <= 6:
            return '0'
        else:
            return '@'

    def density_char_b2(cnt):
        if cnt == 0:
            return ' '
        elif cnt == 1:
            return '*'
        elif cnt <= 3:
            return 'x'
        elif cnt <= 6:
            return 'X'
        else:
            return '%'

    grid = [[' ' for _ in range(width)] for _ in range(height)]
    for cy in range(height):
        for cx in range(width):
            c1 = count1[cy][cx]
            c2 = count2[cy][cx]
            if c1 > 0 and c2 > 0:
                total = c1 + c2
                if total <= 2:
                    grid[cy][cx] = '#'
                elif total <= 6:
                    grid[cy][cx] = '&'
                else:
                    grid[cy][cx] = '8'
            elif c1 > 0:
                grid[cy][cx] = density_char_b1(c1)
            elif c2 > 0:
                grid[cy][cx] = density_char_b2(c2)

    sx1, sy1 = project(track1[0][0], track1[0][1])
    sx2, sy2 = project(track2[0][0], track2[0][1])
    ex1, ey1 = project(track1[-1][0], track1[-1][1])
    ex2, ey2 = project(track2[-1][0], track2[-1][1])
    grid[sy1][sx1] = 'S'
    grid[sy2][sx2] = 's'
    grid[ey1][ex1] = 'E'
    grid[ey2][ex2] = 'e'

    print('+' + '-' * width + '+')
    for row in grid:
        print('|' + ''.join(row) + '|')
    print('+' + '-' * width + '+')
    print('图例: 天体1: o/O/0/@ (密度递增)  天体2: */x/X/% (密度递增)')
    print('       交汇: #(轻) &(中) 8(重)  S/s=起点  E/e=终点')


def load_config(config_path):
    with open(config_path, 'r') as f:
        return json.load(f)


def merge_config_and_args(config, args):
    result = {}
    arg_map = {
        'm1': ('body1', 'mass'),
        'x1': ('body1', 'position', 0),
        'y1': ('body1', 'position', 1),
        'vx1': ('body1', 'velocity', 0),
        'vy1': ('body1', 'velocity', 1),
        'm2': ('body2', 'mass'),
        'x2': ('body2', 'position', 0),
        'y2': ('body2', 'position', 1),
        'vx2': ('body2', 'velocity', 0),
        'vy2': ('body2', 'velocity', 1),
        'time': ('total_time',),
        'dt': ('initial_dt',),
        'sample_interval': ('sample_interval',),
        'csv': ('csv_output',),
        'json': ('json_output',),
        'output_dir': ('output_dir',),
    }

    def get_nested(d, keys):
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            elif isinstance(d, list) and isinstance(k, int) and k < len(d):
                d = d[k]
            else:
                return None
        return d

    for arg_name, config_keys in arg_map.items():
        arg_val = getattr(args, arg_name, None)
        if arg_val is not None:
            result[arg_name] = arg_val
        elif config is not None:
            config_val = get_nested(config, config_keys)
            if config_val is not None:
                result[arg_name] = config_val

    return result


def main():
    parser = argparse.ArgumentParser(
        description='双体轨道仿真工具 - 基于牛顿万有引力的N=2体数值仿真',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''示例:
  %(prog)s --m1 5.972e24 --x1 0 --y1 0 --vx1 0 --vy1 0 \\
           --m2 7.342e22 --x2 3.844e8 --y2 0 --vx2 0 --vy2 1022 \\
           --time 2.36e6 --dt 600
  上述参数近似模拟地月系统一个月的轨道运动。

  使用配置文件:
  %(prog)s --config earth_moon_config.json'''
    )
    parser.add_argument('--config', type=str, help='JSON配置文件路径')
    parser.add_argument('--m1', type=float, help='天体1的质量 (kg)')
    parser.add_argument('--x1', type=float, help='天体1初始x坐标 (m)')
    parser.add_argument('--y1', type=float, help='天体1初始y坐标 (m)')
    parser.add_argument('--vx1', type=float, help='天体1初始x方向速度 (m/s)')
    parser.add_argument('--vy1', type=float, help='天体1初始y方向速度 (m/s)')
    parser.add_argument('--m2', type=float, help='天体2的质量 (kg)')
    parser.add_argument('--x2', type=float, help='天体2初始x坐标 (m)')
    parser.add_argument('--y2', type=float, help='天体2初始y坐标 (m)')
    parser.add_argument('--vx2', type=float, help='天体2初始x方向速度 (m/s)')
    parser.add_argument('--vy2', type=float, help='天体2初始y方向速度 (m/s)')
    parser.add_argument('--time', type=float, help='仿真总时长 (秒)')
    parser.add_argument('--dt', type=float, help='初始时间步长 (秒)')
    parser.add_argument('--sample-interval', type=int, dest='sample_interval', help='CSV采样间隔，每N步写一行 (默认: 1)')
    parser.add_argument('--csv', type=str, help='CSV输出文件路径 (默认: trajectory.csv)')
    parser.add_argument('--json', type=str, help='JSON摘要输出路径 (默认: summary.json)')
    parser.add_argument('--output-dir', type=str, dest='output_dir', help='输出文件所在目录 (默认: 当前目录)')

    args = parser.parse_args()

    config = None
    if args.config:
        config = load_config(args.config)

    merged = merge_config_and_args(config, args)

    required_params = ['m1', 'x1', 'y1', 'vx1', 'vy1', 'm2', 'x2', 'y2', 'vx2', 'vy2', 'time', 'dt']
    missing = [p for p in required_params if p not in merged]
    if missing:
        print(f'错误: 缺少必要参数: {", ".join(missing)}', file=sys.stderr)
        print('请通过命令行参数或配置文件提供这些参数。', file=sys.stderr)
        sys.exit(1)

    sample_interval = merged.get('sample_interval', 1)
    if sample_interval < 1:
        print(f'错误: 采样间隔必须 >= 1，当前值: {sample_interval}', file=sys.stderr)
        sys.exit(1)

    out_dir = Path(merged.get('output_dir', '.'))
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / merged.get('csv', 'trajectory.csv')
    json_path = out_dir / merged.get('json', 'summary.json')

    simulate(
        m1=merged['m1'], m2=merged['m2'],
        x1=merged['x1'], y1=merged['y1'],
        x2=merged['x2'], y2=merged['y2'],
        vx1=merged['vx1'], vy1=merged['vy1'],
        vx2=merged['vx2'], vy2=merged['vy2'],
        total_time=merged['time'], dt_init=merged['dt'],
        csv_path=csv_path, json_path=json_path,
        sample_interval=sample_interval
    )


if __name__ == '__main__':
    main()
