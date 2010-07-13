#!/usr/bin/env python
# Copyright (c) 2003-2006 ActiveState Software Inc.
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
#
# Authors:
#    Shane Caraveo <ShaneC@ActiveState.com>
#    Trent Mick <TrentM@ActiveState.com>

"""
    pydbgpshell -- command-line front-end interface to the DBGP
                   debugger protocol

    Usage:
        dbgp [<options>...]
    
    Options:
        -h, --help          Print this help and exit.
        -V, --version       Print this script's version and exit.
        -v, --verbose       More verbose output.

    This command-line interface is intended primarily for development and
    testing of the DBGP protocol. It is intended that a proper graphical
    front-end be provided for this interface (e.g. in Komodo).
    
    Relevant documentation:
    http://specs.activestate.com/Komodo_3.0/func/debugger_protocol.html
    http://specs.activestate.com/Komodo_3.0/func/debugger_protocol_clients.html
    http://specs.activestate.com/Komodo_3.0/func/debugger_ui.html
"""

import os
import sys
import getopt
import cmd
import socket
import string

import dbgp.serverBase
from dbgp.common import *

try:
    import logging
except ImportError:
    from dbgp import _logging as logging
import dbgp.listcmd as listcmd


#---- globals

__version__ = "$Revision: #1 $ $Change: 118914 $"
_version_ = (0,2,0)
log = logging.getLogger("dbgp.server")


#---- internal support stuff

def _parsePortString(portString, defaultHostName="127.0.0.1"):
    """Parse a user-specified port string and return the appropriate
    hostname and port.
    """
    if ':' in portString:
        hostname, port = portString.split(':', 1)
    else:
        hostname, port = defaultHostName, portString
    try:
        port = int(port)
    except ValueError, ex:
        raise DBGPError("illegal port number: it must be a "
                        "number: '%s'" % port)
    return (hostname, port)

# override line2argv to catch -- data sections

def line2argv(line):
    if line.find(' -- ') > -1:
        parts = line.split(' -- ', 1)
        return listcmd._line2argv(parts[0]) + ['--',parts[1]]
    return listcmd._line2argv(line)

listcmd._line2argv = listcmd.line2argv
listcmd.line2argv = line2argv

#---- the main shell implementation

class shell(listcmd.ListCmd):
    """
    dbgp -- command-line front end to the DBGP debugger protocol

    Help:
        help                Print this help and exit.
        help <command>      Print help on the given command.
        rhelp               Get help from the current debugger session.
    
    Commands:
        key                 set a server key
        listen              start/stop listening for debugger connections
        sessions            list all active debugger sessions
        select              switch to the given debugger session
        stop                stop the current (or all) debugging session(s)
        proxyinit           connect to debugging proxy server
        proxystop           stop the current proxy server
        quit, exit, q       exit the DBGP shell
    """
    intro = "DBGP Command Line Debugger. Type 'help' for help."
    prompt = "[dbgp] "

    def __init__(self):
        listcmd.ListCmd.__init__(self)
        #XXX listener should be Listener
        self._listener = dbgp.serverBase.listener(self)
        self._currentSess = None
        self._sessions = {} # session id -> dbgp.serverBase.session instance
        self._session_id_base = 0
        self._server_key = None
        self._proxyaddr = None

    def logerror(self, msg):
        log.error(msg)

    def default(self, argv):
        #XXX Would rather do a separate shell for a selected session.
        try:
            if self._currentSess:
                data = None
                if '--' in argv:
                    i = argv.index('--')
                    c = argv[:i]
                    data = argv[i+1]
                    argv = c
                print "sending %r -- %r" % (argv, data)
                tid = self._currentSess.sendCommand(argv, data)
                log.debug("session command '%r': tid=%s", argv, tid)
            else:
                listcmd.ListCmd.default(self, argv)
        except Exception, e:
            print "default command handler recieved exception %r", e

    #---- shell commands

    def do_quit(self, argv):
        """
    quit, exit, q -- exit the DBGP shell
        """
        self._listener.stop() # stop the host listener
        for session in self._sessions.values(): # stop all sessions
            session.stop()
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
        
        self._server_key = args[0]
        log.info("Set server key to '%s'." % self._server_key)

    def do_listen(self, argv):
        """
    listen -- start/stop listening for debugger connections on given port
    
    listen [-p <port>] start        # start listening
    listen stop                     # stop listening  
        
        <port> specifies which hostname and port to listen on. It may simply
            be a port number or a <hostname>:<port>. See examples below.
            If not specified an open port will be selected.

    Examples:
        listen start                    # start listening on a free port
        listen -p 9010 start            # start listening on port 9010
        listen -p 127.0.0.1:9010 start
        """
        # Parse options.
        try:
            optlist, args = getopt.getopt(argv[1:], "hp:", ["help"])
        except getopt.GetoptError, msg:
            log.error("%s. Your invocation was: %s", msg, argv)
            log.error("Try 'help listen'.")
            return 1
        try:
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
                    except DBGPError, ex:
                        log.error("listen: %s", ex)
                        return
                _address, _port = self._listener.start(hostname, port)
                log.info("Start listening on %s:%d.",
                         _address or "127.0.0.1", _port)
            elif action == "stop":
                self._listener.stop()
            else:
                log.error("listen: unknown action: '%s'" % action)
                log.error("listen: Try 'help listen'.")
                return
        except Exception, e:
            print "listen caused exception: %r", e

    def do_sessions(self, argv):
        """
    sessions -- list all active debugger sessions
        """
        #XXX Can do prettier output that than. Copy talbe printing stuff
        #    from relic.py.
        #    - mark the current one
        print repr(self._sessions)

    def do_list(self, argv):
        log.warn("'list' is deprecated. Use 'sessions' instead.")

    def do_select(self, argv):
        """
    select -- switch to the given debugger session
    
    select [<session_id>]
    
        <session_id> is the id string of an active debugger sessions. Use
            the 'sessions' command to list active sessions. If not specified
            then the first active session is selected.
        """
        # Parse arguments.
        args = argv[1:]
        if len(args) == 0:
            sessionId = None
        elif len(args) == 1:
            sessionId = args[0]
            try:
                sessionId = long(sessionId)
            except ValueError:
                pass
        else:
            log.error("select: incorrect number of arguments: %s" % args)
            log.error("select: Try 'help select'.")
            return

        if not self._sessions:
            log.error("select: There are no active sessions.")
            return
        if sessionId is None:
            sessionIds = self._sessions.keys()
            sessionIds.sort()
            sessionId = sessionIds[0]
        try:
            session = self._sessions[sessionId]
        except KeyError:
            log.error("select: There is no active session with id '%s'."
                      % sessionId)
            return
        self._currentSess = session
        log.info("Selected session '%s'." % sessionId)

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
            if self._currentSess is None:
                log.error("stop: There is no current session set.")
                return
            else:
                self._currentSess.stop()
                self.remove_session(self._currentSess)
                self._currentSess = None
        elif len(args) == 1:
            if args[0] == "all":
                for session in self._sessions.values():
                    session.stop()
                    self.remove_session(session)
                    self._currentSession = None
            else:
                log.error("stop: illegal argument: '%s'" % args[0])
                log.error("stop: Try 'help stop'.")
                return
        else:
            log.error("stop: incorrect number of arguments: %s" % args)
            log.error("stop: Try 'help stop'.")
            return


    def do_rhelp(self, argv):
        """
    rhelp -- remote help, list commands available for the current session
        """
        if self._currentSess is None:
            log.error("rhelp: There is no current session set.")
            return
        
        tid = self._currentSess.sendCommand(["help"])

    # quick-n-dirty proxy support
    def do_proxyinit(self, argv):
        """
    proxyinit -- start a proxy server for debugging on the given port

    proxyinit [<options>] <port>
        
        Options:
            -M, --multiple-sessions   Proxy server supports multiple sessions.
        
        <port> specifies the hostname and port on which the proxy should run.
            It may simply be a port number (in which case the hostname is
            presumed to be localhost) or <hostname>:<port>.
        """
        # Parse options.
        try:
            optlist, args = getopt.getopt(argv[1:], "hM",
                ["help", "multiple-sessions"])
        except getopt.GetoptError, msg:
            log.error("%s. Your invocation was: %s", msg, argv)
            log.error("Try 'help proxyinit'.")
            return 1
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
        except DBGPError, ex:
            log.error("proxyinit: %s", ex)
            return

        proxySocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            proxySocket.connect(addr)
        except socket.error, ex:
            log.error("proxyinit: %s: %s" % ex.args)
            return
        
        command = "proxyinit -p %d -k %s -m %d"\
                  % (self._listener._port, self._server_key, multi)
        proxySocket.send(command)
        print proxySocket.recv(1024)  #XXX Huh? --TM
        proxySocket.close()
        self._proxyaddr = addr

    def do_proxystop(self, argv):
        """
    proxystop -- stop the current proxy server
        """
        if self._proxyaddr is None:
            log.error("proxystop: No proxy server is running.")
            return

        proxySocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxySocket.connect(self._proxyaddr)
        command = 'proxystop -k %s' % self._server_key
        proxySocket.send(command)
        print proxySocket.recv(1024)  #XXX Huh? --TM
        proxySocket.close()


    #---- session list handling
    
    def remove_session(self, session):
        #XXX Whoa! Redo this to not be so painful.
        _sess = {}
        for sess_id in self._sessions:
            if session != self._sessions[sess_id]:
                _sess[sess_id] = self._sessions[sess_id]
        self._sessions = _sess


    #---- listener callback functions
    #XXX Where is the interface documentation for this?

    def onConnect(self, session, client, addr):
        # before any communication, we can decide if we want
        # to allow the connection here.  return 0 to deny
        log.info("Listener received connection from %s:%s: session %s started.",
                 client, addr, self._session_id_base)
        self._sessions[self._session_id_base] = session
        self._session_id_base = self._session_id_base + 1
        return 1
    
    def initHandler(self, session, init):
        # this is called once during a session, after the connection
        # to provide initialization information.  initNode is a
        # minidom node
        if self._server_key:
            idekey = init.getAttribute('idekey')
            if idekey != self._server_key:
                session.stop()
                self.remove_session(session)
                print "Session stopped, incorrect key [%s]", idekey
        print
        print init.ownerDocument.toprettyxml()
    
    def outputHandler(self, session, stream, text):
        # this is called any time stdout or stderr data is provided
        # to us from the debugger client
        print
        print "[%s] %s" % (stream, text)

    def responseHandler(self, session, response):
        # when we send commands to the session, we get our
        # responses here in the form of a minidom node
        print
        print response.ownerDocument.toprettyxml()


#---- mainline

def main(argv):
    configureLogging(log, logging.INFO)
    try:
        optlist, args = getopt.getopt(argv[1:], "hVv",
            ["help", "version", "verbose"])
    except getopt.GetoptError, msg:
        log.error("%s. Your invocation was: %s", msg, argv)
        log.error("Try 'dbgp --help'.")
        return 1
    for opt, optarg in optlist:
        if opt in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        elif opt in ("-V", "--version"):
            import re
            kw = re.findall('\$(\w+):\s(.*?)\s\$', __version__)
            
            sys.stderr.write("dbgp Version %s %s %s %s %s\n"\
                             % ('.'.join([str(i) for i in _version_]),
                                kw[0][0], kw[0][1], kw[1][0], kw[1][1]))
            return 0
        elif opt in ("-v", "--verbose"):
            log.setLevel(logging.DEBUG)

    s = shell()
    try:
        return s.cmdloop()
    except KeyboardInterrupt, ex:
        pass
    except Exception, ex:
        log.error(str(ex))
        if log.isEnabledFor(logging.DEBUG):
            import traceback
            traceback.print_exception(*sys.exc_info())
        return 1


if __name__ == "__main__":
    sys.exit( main(sys.argv) )
