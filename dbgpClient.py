#!/usr/bin/env python
if __name__ == "__main__":
    print("""
dbgpClient.py has been replaced with pydbgp.  pydbgp uses the same
command line arguments that dbgpClient supported.
""")
else:
    import warnings
    warnings.warn("dbgpClient is deprecated, use 'import dbgp.client'",
                  DeprecationWarning)
    from dbgp.client import *
