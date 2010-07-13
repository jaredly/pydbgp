#!/usr/bin/env python
# Copyright (c) 2005-2006 ActiveState Software Inc.
#
# The MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is furnished
# to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# Authors:
#    Shane Caraveo <ShaneC@ActiveState.com>
#    Trent Mick <TrentM@ActiveState.com>

"""
    dbg -- command-line front-end to the DBGP debugger protocol and system

    Usage:
        dbg [<options>...] [<invocation of app to test>]
    
    Options:
        -h, --help          Print this help and exit.
        -V, --version       Print dbg's version and exit.
        -l, --log-level <level>
            Set the logging level (default INFO). Valid values are:
            CRITICAL, ERROR, WARN, INFO, DEBUG.

        -d, --daemon [<hostname>:]<port>
            Specify a hostname and port on which to listen for DBGP
            connections. Specify port 0 to have the system select a free
            port.

        --perl, --php, --python, --tcl, --xslt
            Specify the language of the application to debug. Only
            necessary if the language cannot be determined automatically.

    Debug applications implemented in languages supported by the DBGP
    protocol (currently Perl, PHP, Python, Tcl and XSLT). Note that there
    the graphical front-end to DBGP provided in Komodo may be more to your
    taste (http://www.activestate.com/Products/Komodo/).

    If not invocation is given, then the DBG shell is enter, from which one
    can listen for remote DBGP connections and/or start debugging apps.

    Examples:
        $ dbg foo.py
        dbg> ...
        
        $ dbg c:\python24\python.exe foo.py arg1 arg2 ...
        dbg> ...

        $ dbg --perl /usr/local/ActivePerl-5.8/bin/GET
        dbg> ...

    More infomation:
        http://specs.tl.activestate.com/komodo30/func/debugger_protocol.html
"""

import os
import sys
import getopt
import cmd
import socket
import pprint
import re
import dbgp.server
from dbgp.common import *
try:
    import logging
except ImportError:
    from dbgp import _logging as logging
import dbgp.listcmd as listcmd


#---- globals

__revision__ = "$Revision: #6 $ $Change: 259693 $"
__version__ = (0, 3, 0)
log = logging.getLogger("dbg")


#---- internal support stuff

# override line2argv to catch -- data sections
def line2argv(line):
    if line.find(' -- ') > -1:
        parts = line.split(' -- ', 1)
        return listcmd._line2argv(parts[0]) + ['--',parts[1]]
    return listcmd._line2argv(line)

listcmd._line2argv = listcmd.line2argv
listcmd.line2argv = line2argv


def _parsePortString(portString, defaultHostname="127.0.0.1"):
    """Parse a user-specified port string and return the appropriate
    hostname and port.
    """
    if ':' in portString:
        hostname, port = portString.split(':', 1)
    else:
        hostname, port = defaultHostname, portString
    try:
        port = int(port)
    except ValueError, ex:
        raise ValueError("illegal port: it must be a number: %r" % port)
    return (hostname, port)

def _getopts(args, options):
    # options is an array of option arrays:
    # [['i','transaction_id',int,1,-1, func],...]
    # [short_arg, long_arg, type_handler, required, default, validat_func]
    # returns values for all requested options
    short = ''
    longopt = []
    shortopt = []
    found = []
    for opt in options:
        short = short + opt[0]+':'
        shortopt.append('-'+opt[0])
        longopt.append(opt[1])
    try:
        opts, args = getopt.getopt(args, short, longopt)
    except getopt.GetoptError, e:
        raise DBGPError('invalid argument supplied: %s' % (str(e)))
    # get the default values
    result = [o[4] for o in options]
    # override defaults with provided arg values
    for o, a in opts:
        found.append(o)
        if o in shortopt:
            i = shortopt.index(o)
            result[i] = options[i][2](a.strip())
            if options[i][5]:
                options[i][5](result[i])
        elif o in longopt:
            i = longopt.index(o)
            result[i] = options[i][2](a.strip())
            if options[i][5]:
                options[i][5](result[i])
    # check for required arguments
    for o in options:
        i = options.index(o)
        if o[3] and not (shortopt[i] in found or longopt[i] in found):
            raise DBGPError('required argument [%s:%s] missing' % (o[0],o[1]))
    return result
    
class SessionShell(listcmd.ListCmd):
    """
    dbg -- command-line front end to the DBGP debugger protocol

    Session Layer
    
    Help:
        help                Print this help and exit.
        help <command>      Print help on the given command.
    
    Session Commands:
        threads             list attached threads
        thread              select a thread to debug
        stop                end script execution
        detach              detach debugger from current thread
        quit, exit, q       exit to server shell (does not stop session)
        
    Debugging Commands:
        run                 continue running until breakpoint or end
        step                step to next command
        step_over           step over function
        step_into           step into function
        feature_get         get a feature value
        feature_set         set a feature value
        break               break now (while running)
        status              get current status
        stack_depth         get the stack depth
        stack_get           get the stack
        context_names       get context names and id's
        context_get         get the context
        type_map            get type mapping from language to protocol
        eval                evaluate source code
        source              get the current source code
        property_get        get a variable
        property_set        set a variable
        property_value      get the value of a variable
        breakpoint_set      set a breakpoint
        breakpoint_get      get a breakpoint
        breakpoint_enable   enable a breakpoint
        breakpoint_disable  disable a breakpoint
        breakpoint_remove   remove a breakpoint
        spawnpoint_set      set a spawnpoint
        spawnpoint_get      get a spawnpoint
        spawnpoint_enable   enable a spawnpoint
        spawnpoint_disable  disable a spawnpoint
        spawnpoint_remove   remove a spawnpoint
        interact            execute an interactive prompt line
        interactive         full interactive mode
    """

    _prompt = "[dbgp-%s:%s] "

    def __init__(self, dbgapp, dbgShell):
        listcmd.ListCmd.__init__(self)
        self._app = dbgapp
        self.prompt = self._prompt % (self._app.currentSession.applicationId,
                                      self._app.currentSession.threadId)
        self._bpManager = self._app.currentSession._sessionHost.breakpointManager
        self.dbgShell = dbgShell
    
    def onecmd(self, argv):
        try:
            return listcmd.ListCmd.onecmd(self, argv)
        except DBGPError, e:
            print str(e)

    def do_quit(self, argv):
        """
    quit, exit, q -- exit the DBG Session layer
        """
        return 1
    do_q = do_quit
    do_exit = do_quit
    do_EOF = do_quit  # allow EOF to terminate session as well

    def do_threads(self, argv):
        """
    threads -- list threads attached to application
        """
        threads = self._app.getSessionList()
        for thread in threads:
            print "%s:%r" % (thread.threadId, thread)

    def do_thread(self, argv):
        """
    thread [<thread id>] -- select a thread to debug
        """
        # Parse arguments.
        args = argv[1:]
        if len(args) == 0:
            threadId = None
        elif len(args) == 1:
            threadId = args[0]
        else:
            log.error("thread: incorrect number of arguments: %s" % args)
            log.error("thread: Try 'help thread'.")
            return

        threads = self._app.getSessionList()
        for thread in threads:
            if thread.threadId == threadId:
                self._app.currentSession = thread
                log.info("Selected thread '%s'." % threadId)
                break

        self.prompt = self._prompt % (self._app.currentSession.applicationId,
                                      self._app.currentSession.threadId)

    def do_select(self, argv):
        log.warn("'select' is deprecated. Use 'thread' instead.")
        return self.do_thread(argv)

    _feature_get_optlist = [['n', 'feature_name', str, 1, None, None]]
    def do_feature_get(self, argv):
        """
    feature_get -- get a feature value from the client
    
    feature_get -n <name>
        """
        (name,) = _getopts(argv[1:], self._feature_get_optlist)
        self._app.currentSession.featureGet(name)
    
    _feature_set_optlist = [['n', 'feature_name', str, 1, None, None],
                            ['v', 'feature_value', str, 1, None, None]]
    def do_feature_set(self, argv):
        """
    feature_set -- set a feature value on the client
    
    feature_set -n <name> -v <value>
        """
        (name, value,) = _getopts(argv[1:], self._feature_set_optlist)
        print "feature %s set to %s" % (name, value)
        ok = self._app.currentSession.featureSet(name, value)
        print "result: success: %d " % ok

    def do_stop(self, argv):
        """
    stop -- end script execution
        """
        self._app.currentSession.stop()
        return 1
        
    def do_detach(self, argv):
        """
    detach -- detach current thread from debugger (thread continues execution)
        """
        self._app.currentSession.detach()
        return self._app.sessionCount() == 0
    
    def do_run(self, argv):
        """
    run -- continue execution until breakpoint or finish
        """
        self._app.currentSession.resume(RESUME_GO)

    def do_step(self, argv):
        """
    step -- execute next command
        """
        self._app.currentSession.resume(RESUME_STEP_IN)

    def do_step_over(self, argv):
        """
    step_out -- execute next line
        """
        self._app.currentSession.resume(RESUME_STEP_OVER)
    
    def do_step_out(self, argv):
        """
    step_out -- execute next line in caller
        """
        self._app.currentSession.resume(RESUME_STEP_OUT)
    
    def do_break(self, argv):
        """
    break -- stop execution now
        """
        self._app.currentSession.breakNow()
    
    def do_status(self, argv):
        """
    status -- print the current state of execution
        """
        self._app.currentSession.updateStatus()
        print "Current Status: status [%s] reason[%s]" % \
            (self._app.currentSession.statusName, self._app.currentSession.reason)

    def do_stack_depth(self, argv):
        """
    stack_depth -- show the depth of the execution stack
        """
        print "Stack Depth: %s" % self._app.currentSession.stackDepth()

    _stack_get_optlist = [['d', 'depth', int, 0, 0, None]]
    def do_stack_get(self, argv):
        """
    stack_get -- print the stack

    stack_get [-d <depth>] 
        """
        (depth,) = _getopts(argv[1:], self._stack_get_optlist)
        if depth:
            frame = self._app.currentSession.stackGet(depth)
            frames = [frame]
        else:
            frames = self._app.currentSession.stackFramesGet()
        for frame in frames:
            print repr(frame)
   
    def do_context_names(self, argv):
        """
    context_names -- print the context names
        """
        contexts = self._app.currentSession.contextNames()
        for c in contexts:
            print repr(c)

    _context_get_optlist = [['d','depth', int, 0, 0, None],
                            ['c','context_id', int, 0, 0, None]]
    def do_context_get(self, argv):
        """
    context_get -- print the context values
    
    context_get [-c <context_id>] [-d <context_depth>]
        """
        (depth, context_id,) = _getopts(argv[1:], self._context_get_optlist)
        properties = self._app.currentSession.contextGet(context_id, depth)
        for p in properties:
            print repr(p)

    def do_type_map(self, argv):
        """
    type_map -- print the data type map
        """
        types = self._app.currentSession.getTypeMap()
        for t in types:
            print repr(t)

    def do_eval(self, argv):
        """
    eval -- print the result of an evalution
    
    eval code to eval
        """
        code = ''.join(argv[1:])
        result = self._app.currentSession.evalString(code)
        print repr(result)

    _source_optlist =  [['f','filename', str, 0, None, None],
                        ['b','startline', int, 0, 0, None],
                        ['e','endline', int, 0, 0, None]]
    def do_source(self, argv):
        """
    source -- print the source code of a given file
    
    source [-f filename] [-b start line] [-e end line]
    
        if no arguments are provided, the file for the current
        stack is returned.
        """
        (filename, begin, end,) = _getopts(argv[1:], self._source_optlist)
        result = self._app.currentSession.getSourceCode(filename, begin, end)
        print result

    _property_get_optlist = [
               ['d', 'depth', int, 0, 0, None],
               ['c', 'context_id', int, 0, 0, None],
               ['n', 'fullname', str, 1, None, None],
               ['m', 'maxdata', int, 0, 0, None],
               ['t', 'datatype', str, 0, None, None],
               ['p', 'datapage', int, 0, 0, None]]
    def do_property_get(self, argv):
        """
    property_get -- print the specified property
    
    property_get -n fullname [-d stack_depth] [-c context_id]
                 [-m maxdata] [-t datatype] [-p datapage]
        """
        (depth, context_id, fullname,
         maxdata, datatype, datapage,) = \
            _getopts(argv[1:], self._property_get_optlist)
        # not all options used yet, see propertyGetEx
        property = self._app.currentSession.propertyGetEx(context_id, depth, fullname, maxdata, datatype, datapage)
        print repr(property)

    _property_set_optlist = [
                   ['d', 'depth', int, 0, 0, None],
                   ['c', 'context_id', int, 0, 0, None],
                   ['n', 'fullname', str, 1, None, None]]
    def do_property_set(self, argv):
        """
    property_set -- set the specified property value
    
    property_set -n fullname [-d stack_depth] [-c context_id] value 
        """
        (depth, context_id, fullname,) = \
            _getopts(argv[1:], self._property_set_optlist)
        value = argv[1:][-1]
        response = self._app.currentSession.propertySetEx(context_id, depth, fullname, value)
        print repr(response)

    _property_value_optlist = [
               ['d', 'depth', int, 0, 0, None],
               ['c', 'context_id', int, 0, 0, None],
               ['n', 'fullname', str, 1, None, None]]
    def do_property_value(self, argv):
        """
    property_value -- get the value of a property
    
    property_value -n fullname [-d stack_depth] [-c context_id]
        """
        (depth, context_id, fullname,) = \
            _getopts(argv[1:], self._property_value_optlist)
        # not all options used yet, see propertyValueEx
        response = self._app.currentSession.propertyValueEx(context_id, depth, fullname)
        print response

    _breakpoint_set_optlist = [
               ['t','type', str, 1, None, None],
               ['s','state', str, 0, 'enabled', None],
               ['n','lineno', int, 0, 0, None],
               ['f','filename', str, 0, '', None],
               ['m','function', str, 0, None, None],
               ['x','exception', str, 0, None, None],
               ['c','expression', str, 0, None, None],
               ['h','hit_value', int, 0, None, None],
               ['o','hit_condition', str, 0, None, None],
               ['r','temporary', int, 0, 0, None]]
    def do_breakpoint_set(self, argv):
        """
    breakpoint_set -- set a breakpoint
    
    breakpoint_set -t type
                  [-s state]
                  [-f filename]
                  [-n lineno]
                  [-m function]
                  [-x exception]
                  [-c expression]
                  [-r temporary 0|1]
                  [-h hit-value]
                  [-o hit-condition]
                  
    Depending on the breakpoint type, other options will be
    required.  See the protocol documentation for details.
        """
        (type, state, lineno,
         filename, function, exceptionName,
         expression, hitValue, hitCondition, temporary) = _getopts(argv[1:], self._breakpoint_set_optlist)
        
        # getting language this way is a bit of cheating
        lang = self._app.currentSession.languageName
        
        if type == 'line':
            bp = self._bpManager.addBreakpointLine(lang, filename, lineno,
                                                   state, temporary, hitValue,
                                                   hitCondition)
        elif type == 'conditional':
            bp = self._bpManager.addBreakpointConditional(lang, expression,
                                                          filename, lineno,
                                                          state, temporary,
                                                          hitValue,
                                                          hitCondition)
        elif type == 'watch':
            bp = self._bpManager.addBreakpointWatch(lang, expression,
                                                          filename, lineno,
                                                          state, temporary,
                                                          hitValue,
                                                          hitCondition)
        elif type == 'exception':
            bp = self._bpManager.addBreakpointException(lang, exceptionName,
                                                        state, temporary,
                                                        hitValue,
                                                        hitCondition)
        elif type == 'call':
            bp = self._bpManager.addBreakpointCall(lang, function, filename,
                                                   state, temporary, hitValue,
                                                   hitCondition)
        elif type == 'return':
            bp = self._bpManager.addBreakpointReturn(lang, function, filename,
                                                     state, temporary,
                                                     hitValue, hitCondition)
        print repr(bp)

    _breakpoint_info_optlist = [['d','id', int, 1, 0, None]]
    def do_breakpoint_get(self, argv):
        """
    breakpoint_get -- print a breakpoint
    
    breakpoint_get -d breakpoint_id
        """
        (bpid,) = _getopts(argv[1:], self._breakpoint_info_optlist)
        bp = self._app.currentSession.breakpointGet(bpid)
        print repr(bp)

    def do_breakpoint_remove(self, argv):
        """
    breakpoint_remove -- remove a breakpoint
    
    breakpoint_remove -d breakpoint_id
        """
        (bpid,) = _getopts(argv[1:], self._breakpoint_info_optlist)
        self._app.currentSession.breakpointRemove(bpid)
        print "breakpoint removed"

    def do_breakpoint_enable(self, argv):
        """
    breakpoint_enable -- enable a breakpoint
    
    breakpoint_enable -d breakpoint_id
        """
        (bpid,) = _getopts(argv[1:], self._breakpoint_info_optlist)
        self._app.currentSession.breakpointEnable(bpid)
        print "breakpoint enabled"

    def do_breakpoint_disable(self, argv):
        """
    breakpoint_disable -- disable a breakpoint
    
    breakpoint_disable -d breakpoint_id
        """
        (bpid,) = _getopts(argv[1:], self._breakpoint_info_optlist)
        self._app.currentSession.breakpointDisable(bpid)
        print "breakpoint disabled"

    def do_breakpoint_list(self, argv):
        """
    breakpoint_list -- list current breakpoints
        """
        bplist = self._app.currentSession.breakpointList()
        for bp in bplist:
            print repr(bplist[bp])

    _spawnpoint_set_optlist = [
               ['s','state', str, 0, 'enabled', None],
               ['n','lineno', int, 1, 0, None],
               ['f','filename', str, 0, '', None]]
    def do_spawnpoint_set(self, argv):
        """
    spawnpoint_set -- set a spawnpoint
    
    spawnpoint_set -n lineno
                   -f filename
                  [-s state]
                  
                  
    Depending on the spawnpoint type, other options will be
    required.  See the protocol documentation for details.
        """
        (state, lineno, filename, ) = _getopts(argv[1:], self._spawnpoint_set_optlist)
        
        # getting language this way is a bit of cheating
        lang = self._app.currentSession.languageName
        
        sp = self._bpManager.addSpawnpoint(lang, filename, lineno, state)
        sp = self._app.currentSession.spawnpointSet(sp)
        print repr(sp)

    _spawnpoint_info_optlist = [['d','id', int, 1, 0, None]]
    def do_spawnpoint_get(self, argv):
        """
    spawnpoint_get -- print a spawnpoint
    
    spawnpoint_get -d spawnpoint_id
        """
        (spid,) = _getopts(argv[1:], self._spawnpoint_info_optlist)
        sp = self._app.currentSession.spawnpointGet(spid)
        print repr(sp)

    def do_spawnpoint_remove(self, argv):
        """
    spawnpoint_remove -- remove a spawnpoint
    
    spawnpoint_remove -d spawnpoint_id
        """
        (spid,) = _getopts(argv[1:], self._spawnpoint_info_optlist)
        self._app.currentSession.spawnpointRemove(spid)
        print "spawnpoint removed"

    def do_spawnpoint_enable(self, argv):
        """
    spawnpoint_enable -- enable a spawnpoint
    
    spawnpoint_enable -d spawnpoint_id
        """
        (spid,) = _getopts(argv[1:], self._spawnpoint_info_optlist)
        self._app.currentSession.spawnpointEnable(spid)
        print "spawnpoint enabled"

    def do_spawnpoint_disable(self, argv):
        """
    spawnpoint_disable -- disable a spawnpoint
    
    spawnpoint_disable -d spawnpoint_id
        """
        (spid,) = _getopts(argv[1:], self._spawnpoint_info_optlist)
        self._app.currentSession.spawnpointDisable(spid)
        print "spawnpoint disabled"

    def do_spawnpoint_list(self, argv):
        """
    spawnpoint_list -- list current spawnpoints
        """
        splist = self._app.currentSession.getSpawnpointList()
        for sp in splist:
            print repr(splist[sp])
            
    def do_stdout(self, argv):
        """
    stdout -- redirect stdout from the client
        """
        self._app.setStdoutHandler(sys.stdout, 1)

    def do_stderr(self, argv):
        """
    stdout -- redirect stdout from the client
        """
        self._app.setStderrHandler(sys.stderr, 1)

    def do_interact(self, argv):
        """
    interact -- single step of interactive mode.  You must use '--' in the
                command line as shown below.
    
    interact -- code
    
        """
        self._app.currentSession.interact(' '.join(argv[2:]))

    def do_interactive(self, argv):
        """
    interactive -- enter interactive mode.  No further dbgp commands can be
                   executed until interactive mode is finished (ctrl-d)
        """
        tid = self._app.currentSession.interact('') # start interact
        node = self._app.currentSession.waitResponse(tid, 0)
        prompt = node.getAttribute('prompt')
        while 1:
            try:
                line = raw_input(prompt)
                tid = self._app.currentSession.interact(line)
                node = self._app.currentSession.waitResponse(tid, 0)
                prompt = node.getAttribute('prompt')
            except EOFError:
                tid = self._app.currentSession.interact(None) # stop interact
                print "\n"
                break;
            except Exception, e:
                log.exception(e)
                break;


#---- the main management shell

class ServerShell(listcmd.ListCmd):
    """
    dbgp -- command-line front end to the DBGP debugger protocol

    Help:
        help                Print this help and exit.
        help <command>      Print help on the given command.
    
    Commands:
        key                 set a server key
        loglevel            set the logging level
        listen              start/stop listening for debugger connections
        proxyinit           connect to debugging proxy server
        proxystop           stop the current proxy server
        quit, exit, q       quit the DBG shell
        session             switch to the given debugger session
        sessions            list all active debugger sessions
        start               start a debug session and select it
        stop                stop the current (or all) debugging session(s)
    """
    intro = "DBGP Command Line Debugger. Type 'help' for help."
    prompt = "dbg> "

    def __init__(self):
        listcmd.ListCmd.__init__(self)
        self._manager = dbgp.server.manager()
        self._currentApp = None

    def logerror(self, msg):
        log.error(msg)
    def onerror(self):
        self._manager.shutdown()
    def postloop(self):
        listcmd.ListCmd.postloop(self)
        self._manager.shutdown()

    def do_quit(self, argv):
        """
    quit, exit, q -- exit the DBG shell
        """
        self._manager.shutdown() # stop the host listener
        return 1
    do_q = do_quit
    do_exit = do_quit
    do_EOF = do_quit  # allow EOF to terminate session as well

    def do_key(self, argv):
        """
    key -- set a server key

    key <value>
    
        <value> is the string to use for a server key.
        
        The server key is an arbitrary string that, if set, is used to
        deny or allow debugger client connections.
        """
        args = argv[1:]
        if len(args) != 1:
            log.error("key: incorrect number of arguments: %s" % args)
            log.error("key: Try 'help key'.")
            return
        
        self._manager.setKey(args[0])
        log.info("Set server key to '%s'." % args[0])

    def do_listen(self, argv):
        """
    listen -- start/stop listening for debugger connections on given port
    
    listen [-p [<hostname>:]<port>] start       # start listening
    listen stop                                 # stop listening  
        
        <hostname> and <port> specify the port on which to listen. If not
            specified a free port will be selected.

    Examples:
        listen start                    # start listening on a free port
        listen -p 9010 start            # start listening on port 9010
        listen -p 127.0.0.1:9010 start
        """
        # Parse options.
        try:
            optlist, args = getopt.getopt(argv[1:], "hp:", ["help"])
        except getopt.GetoptError, msg:
            log.error("%s: %s", msg, argv)
            log.error("Try 'help listen'.")
            return 0
        portOption = None
        for opt, optarg in optlist:
            if opt in ("-h", "--help"):
                sys.stdout.write(self.do_listen.__doc__)
                return
            elif opt in ("-p",):
                portOption = optarg  # parse later if necessary

        # Parse arguments.
        if len(args) != 1:
            log.error("listen: incorrect number of arguments: %s" % args)
            log.error("listen: Try 'help listen'.")
            return
        action = args[0]
        
        if action == "start":
            # Determine the port to use.
            port = 0 # tells system to pick a free port
            hostname = "" # tells system to listen on all ip addresses
            if portOption:
                try:
                    hostname, port = _parsePortString(portOption, "")
                except ValueError, ex:
                    log.error("listen: %s", ex)
                    return
            _address, _port = self._manager.listen(hostname, port)
            log.info("Listening on %s:%s.", _address or "127.0.0.1", _port)
        elif action == "stop":
            self._manager.stop()
        else:
            log.error("listen: unknown action: '%s'" % action)
            log.error("listen: Try 'help listen'.")
            return

    def do_sessions(self, argv):
        """
    sessions -- list all active debugger sessions
        """
        #XXX Can do prettier output that than. Copy talbe printing stuff
        #    from relic.py.
        #    - mark the current one
        apps = self._manager.getApplicationList()
        for app in apps:
            print "%s:%r" % (app.currentSession.applicationId, app)

    def do_session(self, argv):
        """
    session -- switch to the given debugging session
    
    session [<session id>]
    
        <session id> is the id string of an active debugging session. Use
            the 'sessions' command to list active sessions. If not
            specified then the first active sessions is selected.
        """
        # Parse arguments.
        args = argv[1:]
        if len(args) == 0:
            sessionId = None
        elif len(args) == 1:
            sessionId = args[0]
        else:
            log.error("session: incorrect number of arguments: %s" % args)
            log.error("session: Try 'help session'.")
            return

        apps = self._manager.getApplicationList()
        if len(apps) < 1:
            log.error("There are no active sessions.")
            return
        if not sessionId:
            self._currentApp = apps[0]
        else:
            for app in apps:
                if app.currentSession.applicationId == sessionId:
                    self._currentApp = app
                    log.info("Selected session '%s'." % sessionId)
                    break
        appShell(self._currentApp, self).cmdloop()
        if self._currentApp.sessionCount() < 1:
            self._currentApp = None

    def do_select(self, argv):
        log.warn("'select' is deprecated. Use 'session' instead.")
        return self.do_session(argv)

    def do_stop(self, argv):
        """
    stop -- stop the current (or all) debugging session(s)
    
    stop [all]
    
        If 'all' is specified then all active debugging sessions are stopped.
        Otherwise the current debugging session is stopped.
        """
        #XXX I would also like to have the option of specifying a session_id
        #    to stop.
        args = argv[1:]
        if len(args) == 0:
            # Stop the current session.
            if self._currentApp is None:
                log.error("stop: There is no current session set.")
                return
            else:
                self._currentApp.currentSession.stop()
                self._currentApp = None
        elif len(args) == 1:
            if args[0] == "all":
                apps = self._manager.getApplicationList()
                for session in apps:
                    session.stop()
                self._currentApp = None
            else:
                log.error("stop: illegal argument: '%s'" % args[0])
                log.error("stop: Try 'help stop'.")
                return
        else:
            log.error("stop: incorrect number of arguments: %s" % args)
            log.error("stop: Try 'help stop'.")
            return

    # quick-n-dirty proxy support
    def do_proxyinit(self, argv):
        """
    proxyinit -- start a proxy server for debugging on the given port

    proxyinit [<options>] [<hostname>:]<port>
        
        Options:
            -M, --multiple-sessions   Proxy server supports multiple sessions.
        
        <hostname> and <port> specify the port on which the proxy should
            run.
        """
        # Parse options.
        if not self._manager._server_key:
            idekey = getenv('USER', getenv('USERNAME', ''))
            self._manager.setKey(idekey)

        try:
            optlist, args = getopt.getopt(argv[1:], "hM",
                ["help", "multiple-sessions"])
        except getopt.GetoptError, msg:
            log.error("%s. Your invocation was: %s", msg, argv)
            log.error("Try 'help proxyinit'.")
            return 0
        multi = 0
        for opt, optarg in optlist:
            if opt in ("-h", "--help"):
                sys.stdout.write(self.do_proxyinit.__doc__)
                return
            elif opt in ("-M", "--multiple-sessions"):
                multi = 1

        # Parse args.
        if len(args) != 1:
            log.error("proxyinit: incorrect number of arguments: %s" % args)
            log.error("proxyinit: Try 'help proxyinit'.")
            return
        try:
            addr = _parsePortString(args[0])
        except ValueError, ex:
            log.error("proxyinit: %s", ex)
            return
        self._manager.setProxy(addr[0],addr[1])

    def do_proxystop(self, argv):
        """
    proxystop -- stop the current proxy server
        """
        self._manager.setProxy(None,None)

    def do_errorlevel(self, argv):
        """
    errorlevel -- Change the logging error level for debugging
    
    errorlevel [<level>]
    
    level may be one of: debug, info, warn, error
    Default error level is warn.
    errorlevel called without the level arg will print the current
    logging level.
        """
        args = argv[1:]
        if not args:
            print "Error Level is ",logging.getLevelName(log.level)
            return
        level = logging.getLevelName(args[0].upper())
        log.setLevel(level)


#---- mainline

def main(argv):
    logging.basicConfig()
    log.setLevel(logging.INFO)

    hostname = None
    port = None
    appLanguage = None
    try:
        optlist, args = getopt.getopt(argv[1:], "hVl:d:",
            ["help", "version", "log-level", "daemon",
             "perl", "php", "python", "tcl", "xslt"])
    except getopt.GetoptError, msg:
        log.error("%s. Your invocation was: %s", msg, argv)
        log.error("Try 'dbg --help'.")
        return 1
    for opt, optarg in optlist:
        if opt in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        elif opt in ("-V", "--version"):
            version = "dbg %s" % ('.'.join([str(i) for i in __version__]))
            hits = re.findall('\$(\w+):\s(.*?)\s\$', __revision__)
            extra = ["%s %s" % hit for hit in hits]
            if extra: version += " (%s)" % (', '.join(extra))
            sys.stderr.write(version)
            return 0
        elif opt in ("-d", "--deamon"):
            try:
                hostname, port = _parsePortString(optarg, "")
            except ValueError, ex:
                log.error(str(ex))
        elif opt in ("-l", "--log-level"):
            try:
                level = logging._levelNames[optarg.upper()]
            except KeyError:
                log.error("invalid log level: %r" % optarg)
                log.error("Try 'dbg --help'.")
                return 1
            log.setLevel(level)
        elif opt == "perl":
            appLanguage = "Perl"
        elif opt == "php":
            appLanguage = "PHP"
        elif opt == "python":
            appLanguage = "Python"
        elif opt == "tcl":
            appLanguage = "Tcl"
        elif opt == "xslt":
            appLanguage = "XSLT"

    sh = ServerShell()
    if port is not None:
        hp = hostname and ("%s:%s" % (hostname, port)) or str(port)
        sh.do_listen(["listen", "-p", hp, "start"])
    return sh.cmdloop()


if __name__ == "__main__":
    try:
        retval = main(sys.argv)
    except KeyboardInterrupt, ex:
        log.debug("user interrupt")
        retval = 1
    except Exception, ex:
        log.error(str(ex))
        if log.isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exception(*sys.exc_info())
        retval = 1
    sys.exit(retval)

