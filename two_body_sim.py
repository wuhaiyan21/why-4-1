#!/usr/bin/env python3
import argparse
import csv
import json
import math
import sys
from pathlib import Path

G = 6.67430e-11


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


def simulate(m1, m2, x1, y1, x2, y2, vx1, vy1, vx2, vy2, total_time, dt_init,
             csv_path, json_path):
    b1 = Body(m1, x1, y1, vx1, vy1)
    b2 = Body(m2, x2, y2, vx2, vy2)

    _, _, r0 = compute_force(b1, b2)
    initial_distance = r0 if r0 > 0 else 1.0
    threshold_distance = initial_distance / 10.0

    initial_energy = compute_energy(b1, b2)

    t = 0.0
    dt = dt_init
    actual_steps = 0
    records = []
    track1 = []
    track2 = []

    records.append((t, b1.x, b1.y, b2.x, b2.y))
    track1.append((b1.x, b1.y))
    track2.append((b2.x, b2.y))

    while t < total_time:
        if t + dt > total_time:
            dt = total_time - t

        _, _, r_current = compute_force(b1, b2)
        if r_current < threshold_distance and dt >= dt_init:
            dt = dt_init / 2.0
        elif r_current >= threshold_distance and dt < dt_init:
            dt = dt_init

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

        records.append((t, b1.x, b1.y, b2.x, b2.y))
        track1.append((b1.x, b1.y))
        track2.append((b2.x, b2.y))

    final_energy = compute_energy(b1, b2)
    if initial_energy != 0:
        energy_deviation_pct = abs((final_energy - initial_energy) / initial_energy) * 100.0
    else:
        energy_deviation_pct = 0.0

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time', 'x1', 'y1', 'x2', 'y2'])
        for row in records:
            writer.writerow([f'{row[0]:.10g}', f'{row[1]:.10g}', f'{row[2]:.10g}',
                             f'{row[3]:.10g}', f'{row[4]:.10g}'])

    summary = {
        'initial_conditions': {
            'body1': {'mass': m1, 'position': [x1, y1], 'velocity': [vx1, vy1]},
            'body2': {'mass': m2, 'position': [x2, y2], 'velocity': [vx2, vy2]},
            'total_time': total_time,
            'initial_dt': dt_init
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
        'actual_steps': actual_steps
    }

    with open(json_path, 'w') as f:
        json.dump(summary, f, indent=2)

    if energy_deviation_pct > 1.0:
        print(f'警告: 能量相对偏差为 {energy_deviation_pct:.4f}%，超过1%阈值！', file=sys.stderr)

    print(f'初始能量: {initial_energy:.10g} J')
    print(f'最终能量: {final_energy:.10g} J')
    print(f'能量相对偏差: {energy_deviation_pct:.6f}%')
    print(f'实际步数: {actual_steps}')
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

    grid = [[' ' for _ in range(width)] for _ in range(height)]

    def project(x, y):
        cx = int((x - min_x) / range_x * (width - 1))
        cy = int((1.0 - (y - min_y) / range_y) * (height - 1))
        cx = max(0, min(width - 1, cx))
        cy = max(0, min(height - 1, cy))
        return cx, cy

    for i, (x, y) in enumerate(track1):
        cx, cy = project(x, y)
        if grid[cy][cx] == ' ':
            grid[cy][cx] = 'o'
        elif grid[cy][cx] == '*':
            grid[cy][cx] = '#'
        else:
            grid[cy][cx] = 'o'

    for i, (x, y) in enumerate(track2):
        cx, cy = project(x, y)
        if grid[cy][cx] == ' ':
            grid[cy][cx] = '*'
        elif grid[cy][cx] == 'o':
            grid[cy][cx] = '#'
        else:
            grid[cy][cx] = '*'

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
    print('图例: o=天体1  *=天体2  #=交汇  S/s=起点  E/e=终点')


def main():
    parser = argparse.ArgumentParser(
        description='双体轨道仿真工具 - 基于牛顿万有引力的N=2体数值仿真',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''示例:
  %(prog)s --m1 5.972e24 --x1 0 --y1 0 --vx1 0 --vy1 0 \\
           --m2 7.342e22 --x2 3.844e8 --y2 0 --vx2 0 --vy2 1022 \\
           --time 2.36e6 --dt 600
  上述参数近似模拟地月系统一个月的轨道运动。'''
    )
    parser.add_argument('--m1', type=float, required=True, help='天体1的质量 (kg)')
    parser.add_argument('--x1', type=float, required=True, help='天体1初始x坐标 (m)')
    parser.add_argument('--y1', type=float, required=True, help='天体1初始y坐标 (m)')
    parser.add_argument('--vx1', type=float, required=True, help='天体1初始x方向速度 (m/s)')
    parser.add_argument('--vy1', type=float, required=True, help='天体1初始y方向速度 (m/s)')
    parser.add_argument('--m2', type=float, required=True, help='天体2的质量 (kg)')
    parser.add_argument('--x2', type=float, required=True, help='天体2初始x坐标 (m)')
    parser.add_argument('--y2', type=float, required=True, help='天体2初始y坐标 (m)')
    parser.add_argument('--vx2', type=float, required=True, help='天体2初始x方向速度 (m/s)')
    parser.add_argument('--vy2', type=float, required=True, help='天体2初始y方向速度 (m/s)')
    parser.add_argument('--time', type=float, required=True, help='仿真总时长 (秒)')
    parser.add_argument('--dt', type=float, required=True, help='初始时间步长 (秒)')
    parser.add_argument('--csv', type=str, default='trajectory.csv', help='CSV输出文件路径 (默认: trajectory.csv)')
    parser.add_argument('--json', type=str, default='summary.json', help='JSON摘要输出路径 (默认: summary.json)')
    parser.add_argument('--output-dir', type=str, default='.', help='输出文件所在目录 (默认: 当前目录)')

    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / args.csv
    json_path = out_dir / args.json

    simulate(
        m1=args.m1, m2=args.m2,
        x1=args.x1, y1=args.y1,
        x2=args.x2, y2=args.y2,
        vx1=args.vx1, vy1=args.vy1,
        vx2=args.vx2, vy2=args.vy2,
        total_time=args.time, dt_init=args.dt,
        csv_path=csv_path, json_path=json_path
    )


if __name__ == '__main__':
    main()
