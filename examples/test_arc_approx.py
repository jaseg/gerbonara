#!/usr/bin/env python3

import math

from gerbonara.graphic_objects import Arc
from gerbonara.graphic_objects import rotate_point


def approx_test():
    print('<?xml version="1.0" encoding="utf-8"?>')
    print('<svg width="300mm" height="300mm" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">')
    n = 16
    eps = 1/n*2*math.pi
    cx, cy = 0, 0
    for clockwise in False, True:
        for start_angle in range(n):
            cx, cy = 0, cy+2.5
            for sweep_angle in range(n):
                for color, max_error in zip(['black', 'red', 'blue', 'magenta'], [0.1, 0.3, 1, 3]):
                    cx = cx+2.5

                    x1, y1 = rotate_point(0, -1, start_angle*eps)
                    x2, y2 = rotate_point(x1, y1, sweep_angle*eps*(-1 if clockwise else 1))
                    
                    arc = Arc(x1+cx, y1+cy, x2+cx, y2+cy, -x1, -y1, clockwise=clockwise, aperture=None, polarity_dark=True)
                    lines = arc.approximate(max_error=max_error)

                    print(f'<path style="fill: {color}; stroke: none;" d="M {cx} {cy} L {lines[0].x1} {lines[0].y1}', end=' ')
                    for line in lines:
                        print(f'L {line.x2} {line.y2}', end=' ')
                    print('"/>')
    print('</svg>')


if __name__ == '__main__':
    approx_test()
