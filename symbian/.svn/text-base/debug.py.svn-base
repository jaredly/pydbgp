#
# default.py
#
# The default script run by the "Python" application in Series 60 Python
# environment. Offers menu options for running scripts that are found in
# application's directory, or in the \my -directory below it (this is
# where the application manager copies the plain Python scripts sent to
# device's inbox), as well as for launching interactive Python console. 
#     
# Copyright (c) 2004 Nokia. All rights reserved.
#

import sys
import os, socket
import appuifw
import series60_console

def select_script():
    appuifw.app.title = u"Select Script"
    def is_py(x):
        return os.path.splitext(x)[1] == '.py'

    my_script_dir = os.path.join(this_dir,'my')
    script_list = []

    if os.path.exists(my_script_dir):
        script_list = map(lambda x: os.path.join('my',x),\
                          filter(is_py, os.listdir(my_script_dir)))

    script_list += filter(is_py, os.listdir(this_dir))
    index = appuifw.selection_list(map(unicode, script_list))
    return os.path.join(this_dir, script_list[index])
    
def select_btdevice():
    appuifw.app.title = u"Select Device"
    target='' #('00:20:e0:76:c3:52',1)
    if not target:
        address,services=socket.bt_discover()
        print "Discovered: %s, %s"%(address,services)
        if len(services)>1:
            choices=services.keys()
            choices.sort()
            choice=appuifw.popup_menu(
                [unicode(services[x])+": "+x for x in choices],u'Choose port:')
            target=(address,services[choices[choice]])
        else:
            target=(address,services.values()[0])
    return target
   
def myexit():
    print "exiting main thread!!!!!!!!!!!!!!!!!!!!!!!"
    
def query_and_debug():
    import atexit
    atexit.register(myexit)

    fn = select_script()
    host, port = select_btdevice()
    
    appuifw.app.title = u"Connecting..."
    import dbgp.client
    import logging
    dbgp.client.configureLogging(dbgp.client.log, logging.WARN)
    client = dbgp.client.backendCmd(module=dbgp.client.h_main())
    args=[fn]
    try:
        client.connect(host, port, '__main__', args,
                       socket_type=socket.AF_BT)
        print "connected to client."
    except socket.error, e:
        appuifw.note(u"Unable to Connect to IDE", 'error')
        appuifw.app.title = u""
        return 1
    appuifw.app.title = u"Running..."
    print "start script %r" % args
    try:
        client.runMain(args)
    except Exception, e:
        print e

this_dir = os.path.split(appuifw.app.full_name())[0]
print this_dir
my_console = series60_console.Console()
appuifw.app.body = my_console.text
sys.stderr = sys.stdout = my_console
from e32 import _stdo
_stdo(u'c:\\python_error.log')         # low-level error output
query_and_debug()
