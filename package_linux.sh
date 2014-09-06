#!/bin/bash

python setup.py --command-packages=stdeb.command sdist_dsc
# TODO: automate debuild -S -sa in source dir
# TODO: automate dput ppa:tslocum/aafm <*_source>.changes
