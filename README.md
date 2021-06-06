[![pipeline status](https://gitlab.com/gerbonara/gerbonara/badges/master/pipeline.svg)](https://gitlab.com/gerbonara/gerbonara/commits/master)
[![coverage report](https://gitlab.com/gerbonara/gerbonara/badges/master/coverage.svg)](https://gitlab.com/gerbonara/gerbonara/commits/master)
[![pypi](https://img.shields.io/pypi/v/gerbonara)](https://pypi.org/project/gerbonara/)
[![aur](https://img.shields.io/aur/version/python-gerbonara)](https://aur.archlinux.org/packages/python-gerbonara/)

# gerbonara

Tools to handle Gerber and Excellon files in Python.

This repository is a friendly fork of [phsilva's pcb-tools](https://github.com/curtacircuitos/pcb-tools) with
[extensions from opiopan](https://github.com/opiopan/pcb-tools-extension) integrated. We decided to fork pcb-tools since
we need it as a dependency for [gerbolyze](https://gitlab.com/gerbolyze/gerbolyze) and pcb-tools was sometimes very
behind on bug fixes.

# Installation

Arch Linux:

```
yay -S python-gerbonara
```

Python:

```
pip install gerbonara
```

# Usage

Here's a simple example:

```python
import gerbonara
from gerbonara.render import GerberCairoContext

# Read gerber and Excellon files
top_copper = gerbonara.read('example.GTL')
nc_drill = gerbonara.read('example.txt')

# Rendering context
ctx = GerberCairoContext()

# Create SVG image
top_copper.render(ctx)
nc_drill.render(ctx, 'composite.svg')
```

---

Made with ❤️ and 🐍.
