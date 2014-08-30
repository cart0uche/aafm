#!/bin/bash

python setup.py --command-packages=stdeb.command bdist_deb
# TODO: automate debuild -S -sa in source dir
# TODO: automate dput ppa:tslocum/aafm <*_source>.changes
