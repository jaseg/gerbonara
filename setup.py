#!/usr/bin/env python3

from pathlib import Path
from setuptools import setup, find_packages
import subprocess

def version():
    try:
        res = subprocess.run(['git', 'describe', '--tags', '--match', 'v*'], capture_output=True, check=True, text=True)
        version, _, _rest = res.stdout.strip()[1:].partition('-')
        return version
    except:
        subprocess.run(['git', 'describe', '--tags', '--match', 'v*'])
        raise

setup(
    name='gerbonara',
    version=version(),
    author='jaseg, XenGi',
    author_email='gerbonara@jaseg.de',
    description='Tools to handle Gerber and Excellon files in Python',
    long_description=Path('README.md').read_text(),
    long_description_content_type='text/markdown',
    url='https://gitlab.com/gerbolyze/gerbonara',
    project_urls={
        'Documentation': 'https://gerbolyze.gitlab.io/gerbonara/',
        # 'Funding': 'https://donate.pypi.org',
        # 'Say Thanks!': 'http://saythanks.io/to/example',
        'Source': 'https://gitlab.com/gerbolyze/gerbonara',
        'Tracker': 'https://gitlab.com/gerbolyze/gerbonara/issues',
    },
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    install_requires=['click', 'rtree', 'quart'],
    entry_points={
        'console_scripts': [
            'gerbonara = gerbonara.cli:cli',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        #'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Manufacturing',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Artistic Software',
        'Topic :: Multimedia :: Graphics',
        'Topic :: Printing',
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)',
        'Topic :: Scientific/Engineering :: Image Processing',
        'Topic :: Utilities',
        'Typing :: Typed',
    ],
    keywords='gerber excellon pcb',
    python_requires='>=3.10',
)
