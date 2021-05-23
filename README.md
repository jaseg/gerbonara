[![pipeline status](https://gitlab.com/gerbonara/gerbonara/badges/master/pipeline.svg)](https://gitlab.com/gerbonara/gerbonara/commits/master)
[![coverage report](https://gitlab.com/gerbonara/gerbonara/badges/master/coverage.svg)](https://gitlab.com/gerbonara/gerbonara/commits/master)
[![pypi](https://img.shields.io/pypi/v/gerbonara)](https://pypi.org/project/gerbonara/)
[![aur](https://img.shields.io/aur/version/python-gerbonara)](https://aur.archlinux.org/packages/python-gerbonara/)

# gerbonara

Tools to handle Gerber and Excellon files in Python.

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
