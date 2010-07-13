#!/usr/bin/env python

# based on tcp_serial_redirect.py from pyserial
# http://pyserial.sourceforge.net/

"""USAGE: serial_tcp_redirect.py [options]
Simple Serial to Network (TCP/IP) redirector.

This redirector waits for data from the serial port, then connects
to the remote host/port and relays data back and forth.  If either
the COM port or the socket is closed, it restarts and waits for a
new connection on the COM port.

Options:
  -p, --port=PORT   serial port, a number, defualt = 0 or a device name
  -b, --baud=BAUD   baudrate, default 9600
  -r, --rtscts      enable RTS/CTS flow control (default off)
  -x, --xonxoff     enable software flow control (default off)
  -H, --iphost      Remote TCP/IP host (default 127.0.0.1)
  -P, --ipport      Remote TCP/IP port (default 9000)

Note: Only one connection at once is supported. If the connection is terminaed
it waits for the next connect.
"""

import sys, os, threading, getopt, socket

try:
    import serial
except:
    print "Running serial_tcp_redirect requries pyserial"
    print "available at http://pyserial.sourceforge.net/"
    sys.exit(1)

try:
    True
except NameError:
    True = 1
    False = 0

class SerialRedirector:
    def __init__(self, tcp_addr, com_port, baudrate=9600, rtscts=False,
                 xonxoff=False, timeout=1):
        print "address is %r" % (tcp_addr)
        self.addr = tcp_addr
        self.socket = None
        self.thread_write = None
        self.alive = False
        
        # create the serial connection
        ser = serial.Serial()
        ser.port    = com_port
        ser.baudrate = baudrate
        ser.rtscts  = rtscts
        ser.xonxoff = xonxoff
        ser.timeout = timeout     #required so that the reader thread can exit
        try:
            ser.open()
        except serial.SerialException, e:
            print "Could not open serial port %s: %s" % (ser.portstr, e)
            sys.exit(1)
        self.serial = ser

    def go(self):
        """wait for incoming com data, then redirect
            to the tcp port"""
        self.alive = True
        self.reader()
    
    def socketStart(self):
        print "Connecting to IDE at %r" % self.addr
        # create the socket connection
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.addr[0], self.addr[1]))
        except socket.error, details:
            self.socket = None
            raise
        
        # start redirecting from serial to tcpip
        self.thread_write = threading.Thread(target=self.writer)
        self.thread_write.setDaemon(1)
        self.thread_write.start()
        
    def reader(self):
        """loop forever and copy serial->socket"""
        print "Waiting for serial data on %s" % self.serial.portstr
        data = None
        while not data:
            data = self.serial.read(1)              #read one, blocking
            n = self.serial.inWaiting()             #look if there is more
        print "Received serial data on %s" % self.serial.portstr
        print "data [%r]" %data
        while self.alive:
            try:
                if n:
                    data = data + self.serial.read(n)   #and get as much as possible
                if data:
                    print "serial data [%r]" %data
                    if not self.socket:
                        self.socketStart()
                    self.socket.sendall(data)           #send it over TCP
                data = self.serial.read(1)              #read one, blocking
                n = self.serial.inWaiting()             #look if there is more
            except socket.error, msg:
                print msg
                #probably got disconnected
                break
        self.alive = False
        self.serial.close()
        if self.thread_write:
            self.thread_write.join()
    
    def writer(self):
        """loop forever and copy socket->serial"""
        while self.alive:
            try:
                data = self.socket.recv(1024)
                if not data:
                    break
                print "socket data [%r]" % data
                self.serial.write(data)                 #get a bunch of bytes and send them
            except socket.error, msg:
                print msg
                #probably got disconnected
                break
        self.alive = False
        # close the socket
        try:
            self.socket.close()
        except socket.error, details:
            pass #we quiting, dont care about the error
        self.socket = None

    def stop(self):
        """Stop copying"""
        if self.alive:
            self.alive = False
            self.thread_write.join()

if __name__ == '__main__':
    
    #parse command line options
    try:
        opts, args = getopt.getopt(sys.argv[1:],
                "hp:b:rxP:H:",
                ["help", "port=", "baud=", "rtscts", "xonxoff", "ipport=", "iphost="])
    except getopt.GetoptError:
        # print help information and exit:
        print >>sys.stderr, __doc__
        sys.exit(2)
    
    ser_port = 0
    baudrate = 9600
    rtscts = False
    xonxoff = False
    iphost = '127.0.0.1'
    ipport = 9000
    for o, a in opts:
        if o in ("-h", "--help"):   #help text
            usage()
            sys.exit()
        elif o in ("-p", "--port"):   #specified port
            try:
                ser_port = int(a)
            except ValueError:
                ser_port = a
        elif o in ("-b", "--baud"):   #specified baudrate
            try:
                baudrate = int(a)
            except ValueError:
                raise ValueError, "Baudrate must be a integer number"
        elif o in ("-r", "--rtscts"):
            rtscts = True
        elif o in ("-x", "--xonxoff"):
            xonxoff = True
        elif o in ("-H", "--iphost"):
            iphost = a
        elif o in ("-P", "--ipport"):
            try:
                ipport = int(a)
            except ValueError:
                raise ValueError, "Local port must be an integer number"

    print "--- Serial to TCP/IP redirector --- type Ctrl-C / BREAK to quit"


    while 1:
        try:
            #enter console->serial loop
            r = SerialRedirector([iphost, ipport],
                                 ser_port, baudrate, rtscts, xonxoff)
            r.go()
        except socket.error, msg:
            print msg

    print "\n--- exit ---"
