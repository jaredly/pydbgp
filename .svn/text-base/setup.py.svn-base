#!/usr/bin/env python

# Setup script for Python DBGP package. DBGP is a cross-platform,
# cross-language debugging protocol and system.

import sys
import os
import re
from distutils.core import setup
from distutils.extension import Extension
from distutils.command import build_py, build_scripts

if "py2exe" in sys.argv:
    import py2exe
    py2exe_setup_args = dict(
        zipfile=None,  # don't want a separate library.zip
        console=[os.path.join("bin", "pydbgpproxy.py")],
    )
else:
    py2exe_setup_args = {}



#---- internal support

def _get_python_version_info():
    major = sys.hexversion >> 24
    minor = (sys.hexversion & 0x00ff0000) >> 16
    return (major, minor)


# HACK override required, because distutils in Python 2.2 otherwise dies
# with:
#   error: build_py: supplying both 'packages' and 'py_modules' options is not allowed
class _HackBuildPy(build_py.build_py):
    def run(self):
        if not self.py_modules and not self.packages:
            return
        if self.py_modules:
            self.build_modules()
        if self.packages:
            self.build_packages()
        self.byte_compile(self.get_outputs(include_bytecode=0))


class _DropPyScriptExtOnUnix(build_scripts.build_scripts):
    """build_scripts command override to drop the .py from Python scripts
    on build
    """
    def run(self):
        if not self.scripts:
            return
        # If on a Unix platform, drop the .py in the scripts and pass on
        # to base class' implementation.
        if not sys.platform.startswith("win"):
            newscripts = []
            for script in self.scripts:
                dst, ext = os.path.splitext(script)
                if ext == ".py":
                    self.announce("drop script ext %s -> %s" % (script, dst))
                    self.copy_file(script, dst)
                    newscripts.append(dst)
                else:
                    newscripts.append(script)
            self.scripts = newscripts
        build_scripts.build_scripts.run(self)


def _get_version():
    from dbgp.common import DBGP_VERSION
    return DBGP_VERSION


#---- package definition

# Only build the _clientXY extension for Python >= 2.2.
ext_modules = []
pyver = _get_python_version_info()
if pyver >= (2,2):
    # Name the extension after the current Python version so can have
    # one lib dir that supports multiple Python versions.
    modname = "_client%s%s" % pyver
    # Need to s/_client/_clientXY/ in _client.c.
    template = os.path.join("dbgp", "_client.c")
    versioned = os.path.join("dbgp", "_client%s%s.c" % pyver)
    content = open(template, 'r').read()
    content = re.sub(r"_client\b", "_client%s%s" % pyver, content)
    open(versioned, 'w').write(content)
    _client_ext = Extension("dbgp."+modname,
                            [versioned],
                            define_macros=[("PYTHON_VER", "%s.%s" % pyver)])
    ext_modules.append(_client_ext)

scripts = [
    "bin/pydbgp.py",
    "bin/pydbgpproxy.py"
    # Don't install these by default. They are primarily of interest only
    # to DBGP backend developers at this point.
    #"bin/pydbgpd.py",
    #"bin/pydbgpshell.py",
]


# Hack fix for bug 45479.
# The Problem:
#   Distutil's build_scripts command does you the "favour" of rewriting
#   the shebang line without the option to decline the favour.
# The Solution:
#   Change the regex use to discover the shebang line to something that
#   won't match.
from distutils.command import build_scripts
build_scripts.first_line_re = re.compile("^womba womba womba$")


setup(
      name="dbgp", 
      version=_get_version(),
      url="http://www.ActiveState.com/Products/Komodo/",
      author="Shane Caraveo, Trent Mick",
      author_email="komodo-feedback@ActiveState.com",
      cmdclass={"build_py": _HackBuildPy,
                "build_scripts": _DropPyScriptExtOnUnix},
      scripts=scripts,
      packages=["dbgp", "dbgp._logging"],
      py_modules=["dbgpClient"],
      ext_modules=ext_modules,

      # py2exe setup for pydbgpproxy.exe on Windows
      **py2exe_setup_args
)

