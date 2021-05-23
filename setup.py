#!/usr/bin/env python3

from os import environ
from os.path import join, abspath, dirname
from codecs import open
from setuptools import setup, find_packages
from subprocess import check_output


def long_description():
    with open('README.md', 'r') as fh:
        return fh.read()


def version():
    with open(join(abspath(dirname(__file__)), 'gerber/__init__.py')) as fh:
        for line in fh:
            if line.startswith('__version__'):
                ver = line.split("'")[1]
                if environ.get('CI_COMMIT_SHA', '') != '' and environ.get('CI_COMMIT_TAG', '') == '':
                    # attach commit hash to non tagged test uploads from CI
                    commits = check_output(['/usr/bin/env', 'git', 'rev-list', '--count', 'HEAD'], text=True)
                    return f'{ ver }.dev{ commits.strip() }'
                return ver

    raise RuntimeError('Unable to find version string.')


setup(
    name='gerbonara',
    version=version(),
    author='XenGi, Jaseg',
    author_email='contact@gerbonara.io',
    description='Tools to handle Gerber and Excellon files in Python',
    long_description=long_description(),
    long_description_content_type='text/markdown',
    url='https://gitlab.com/gerbonara/gerbonara',
    project_urls={
        # 'Documentation': 'https://packaging.python.org/tutorials/distributing-packages/',
        # 'Funding': 'https://donate.pypi.org',
        # 'Say Thanks!': 'http://saythanks.io/to/example',
        'Source': 'https://gitlab.com/gerbonara/gerbonara',
        'Tracker': 'https://gitlab.com/gerbonara/gerbonara/issues',
    },
    packages=find_packages(exclude=['tests']),
    install_requires=[],
    classifiers=[
        'Development Status :: 1 - Planning',
        #'Development Status :: 3 - Alpha',
        #'Development Status :: 4 - Beta',
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
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
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
    python_requires='>=3.6',
)
