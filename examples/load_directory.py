#!/usr/bin/env python3

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('input', help='Input Gerber directory')
    args = parser.parse_args()

    import gerbonara
    print(gerbonara.LayerStack.from_directory(args.input))

