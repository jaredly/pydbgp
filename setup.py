#!/usr/bin/env python

from setuptools import setup
import os

setup(
    name='dbgp',
    author="Shane Caraveo, Trent Mick",
    author_email="komodo-feedback@ActiveState.com",
    maintainer='Jared Forsyth',
    maintainer_email='jared@jaredforsyth.com',
    version='1.1',
    url='http://jabapyth.github.com/pydbgp/',
    packages=['dbgp'],
    description='a python debug server that is complient with DBGP',
    scripts=['bin/pydbgp.py', 'bin/pydbgpproxy.py'],
)




# vim: et sw=4 sts=4
