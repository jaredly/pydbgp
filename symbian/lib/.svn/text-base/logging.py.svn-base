# Comments and DocStrings stripped for space savings
# Copyright 2001-2002 by Vinay Sajip. All Rights Reserved.
# This file is part of the Python logging distribution. See
# http://www.red-dove.com/python_logging.html

import sys, os, types, time, string, struct

try:
	import cStringIO as StringIO
except ImportError:
	import StringIO

try:
	import thread
	import threading
except ImportError:
	thread = None
try:
	import inspect
except ImportError:
	inspect = None

__author__  = "Vinay Sajip <vinay_sajip@red-dove.com>"
__status__  = "alpha"
__version__ = "0.4.7"
__date__    = "15 November 2002"

if __name__ == "__main__":
	_srcfile = None
else:
	if string.lower(__file__[-4:]) in ['.pyc', '.pyo']:
		_srcfile = __file__[:-4] + '.py'
	else:
		_srcfile = __file__
	_srcfile = os.path.normcase(_srcfile)

_startTime = time.time()
raiseExceptions = 1
CRITICAL = 50
FATAL = CRITICAL
ERROR = 40
WARN = 30
INFO = 20
DEBUG = 10
NOTSET = 0

_levelNames = {
	CRITICAL : 'CRITICAL',
	ERROR : 'ERROR',
	WARN : 'WARN',
	INFO : 'INFO',
	DEBUG : 'DEBUG',
	NOTSET : 'NOTSET',
	'CRITICAL' : CRITICAL,
	'ERROR' : ERROR,
	'WARN' : WARN,
	'INFO' : INFO,
	'DEBUG' : DEBUG,
	'NOTSET' : NOTSET,
}

def getLevelName(level):
	return _levelNames.get(level, ("Level %s" % level))

def addLevelName(level, levelName):
	_acquireLock()
	try:
		_levelNames[level] = levelName
		_levelNames[levelName] = level
	finally:
		_releaseLock()

_lock = None

def _acquireLock():
	global _lock
	if (not _lock) and thread:
		_lock = threading.RLock()
	if _lock:
		_lock.acquire()

def _releaseLock():
	if _lock:
		_lock.release()

class LogRecord:
	def __init__(self, name, level, pathname, lineno, msg, args, exc_info):
		ct = time.time()
		self.name = name
		self.msg = msg
		self.args = args
		self.levelname = getLevelName(level)
		self.levelno = level
		self.pathname = pathname
		try:
			self.filename = os.path.basename(pathname)
			self.module = os.path.splitext(self.filename)[0]
		except:
			self.filename = pathname
			self.module = "Unknown module"
		self.exc_info = exc_info
		self.lineno = lineno
		self.created = ct
		self.msecs = (ct - long(ct)) * 1000
		self.relativeCreated = (self.created - _startTime) * 1000
		if thread:
			self.thread = thread.get_ident()
		else:
			self.thread = None

	def __str__(self):
		return '<LogRecord: %s, %s, %s, %s, "%s">'%(self.name, self.levelno,
			self.pathname, self.lineno, self.msg)

	def getMessage(self):
		msg = str(self.msg)
		if self.args:
			msg = msg % self.args
		return msg

class Formatter:
	converter = time.localtime

	def __init__(self, fmt=None, datefmt=None):
		if fmt:
			self._fmt = fmt
		else:
			self._fmt = "%(message)s"
		self.datefmt = datefmt

	def formatTime(self, record, datefmt=None):
		ct = self.converter(record.created)
		if datefmt:
			s = time.strftime(datefmt, ct)
		else:
			t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
			s = "%s,%03d" % (t, record.msecs)
		return s

	def formatException(self, ei):
		import traceback
		sio = StringIO.StringIO()
		traceback.print_exception(ei[0], ei[1], ei[2], None, sio)
		s = sio.getvalue()
		sio.close()
		if s[-1] == "\n":
			s = s[:-1]
		return s

	def format(self, record):
		record.message = record.getMessage()
		if string.find(self._fmt,"%(asctime)") >= 0:
			record.asctime = self.formatTime(record, self.datefmt)
		s = self._fmt % record.__dict__
		if record.exc_info:
			if s[-1] != "\n":
				s = s + "\n"
			s = s + self.formatException(record.exc_info)
		return s

_defaultFormatter = Formatter()

class BufferingFormatter:
	def __init__(self, linefmt=None):
		if linefmt:
			self.linefmt = linefmt
		else:
			self.linefmt = _defaultFormatter

	def formatHeader(self, records):
		return ""

	def formatFooter(self, records):
		return ""

	def format(self, records):
		rv = ""
		if len(records) > 0:
			rv = rv + self.formatHeader(records)
			for record in records:
				rv = rv + self.linefmt.format(record)
			rv = rv + self.formatFooter(records)
		return rv

class Filter:
	def __init__(self, name=''):
		self.name = name
		self.nlen = len(name)

	def filter(self, record):
		if self.nlen == 0:
			return 1
		elif self.name == record.name:
			return 1
		elif string.find(record.name, self.name, 0, self.nlen) != 0:
			return 0
		return (record.name[self.nlen] == ".")

class Filterer:
	def __init__(self):
		self.filters = []

	def addFilter(self, filter):
		if not (filter in self.filters):
			self.filters.append(filter)

	def removeFilter(self, filter):
		if filter in self.filters:
			self.filters.remove(filter)

	def filter(self, record):
		rv = 1
		for f in self.filters:
			if not f.filter(record):
				rv = 0
				break
		return rv

_handlers = {}

class Handler(Filterer):
	def __init__(self, level=NOTSET):
		Filterer.__init__(self)
		self.level = level
		self.formatter = None
		_acquireLock()
		try:
			_handlers[self] = 1
		finally:
			_releaseLock()
		self.createLock()

	def createLock(self):
		if thread:
			self.lock = thread.allocate_lock()
		else:
			self.lock = None

	def acquire(self):
		if self.lock:
			self.lock.acquire()

	def release(self):
		if self.lock:
			self.lock.release()

	def setLevel(self, level):
		self.level = level

	def format(self, record):
		if self.formatter:
			fmt = self.formatter
		else:
			fmt = _defaultFormatter
		return fmt.format(record)

	def emit(self, record):
		raise NotImplementedError, 'emit must be implemented '\
									'by Handler subclasses'

	def handle(self, record):
		if self.filter(record):
			self.acquire()
			try:
				self.emit(record)
			finally:
				self.release()

	def setFormatter(self, fmt):
		self.formatter = fmt

	def flush(self):
		pass

	def close(self):
		pass

	def handleError(self):
		if raiseExceptions:
			import traceback
			ei = sys.exc_info()
			traceback.print_exception(ei[0], ei[1], ei[2], None, sys.stderr)
			del ei

class StreamHandler(Handler):
	def __init__(self, strm=None):
		Handler.__init__(self)
		if not strm:
			strm = sys.stderr
		self.stream = strm
		self.formatter = None

	def flush(self):
		self.stream.flush()

	def emit(self, record):
		try:
			msg = self.format(record)
			self.stream.write("%s\n" % msg)
			self.flush()
		except:
			self.handleError()

class FileHandler(StreamHandler):
	def __init__(self, filename, mode="a"):
		StreamHandler.__init__(self, open(filename, mode))
		self.baseFilename = filename
		self.mode = mode

	def close(self):
		self.stream.close()

class PlaceHolder:
	def __init__(self, alogger):
		self.loggers = [alogger]

	def append(self, alogger):
		if alogger not in self.loggers:
			self.loggers.append(alogger)

_loggerClass = None

def setLoggerClass(klass):
	if klass != Logger:
		if type(klass) != types.ClassType:
			raise TypeError, "setLoggerClass is expecting a class"
		if not issubclass(klass, Logger):
			raise TypeError, "logger not derived from logging.Logger: " + \
							klass.__name__
	global _loggerClass
	_loggerClass = klass
	global root
	root = RootLogger(WARN)
	Logger.root = root
	Logger.manager = Manager(Logger.root)

class Manager:
	def __init__(self, root):
		self.root = root
		self.disable = 0
		self.emittedNoHandlerWarning = 0
		self.loggerDict = {}
		
	def getLoggerNames(self):
		names = self.loggerDict.keys()
		names.sort()
		return [''] + names

	def getLogger(self, name):
		rv = None
		_acquireLock()
		try:
			if self.loggerDict.has_key(name):
				rv = self.loggerDict[name]
				if isinstance(rv, PlaceHolder):
					ph = rv
					rv = _loggerClass(name)
					rv.manager = self
					self.loggerDict[name] = rv
					self._fixupChildren(ph, rv)
					self._fixupParents(rv)
			else:
				rv = _loggerClass(name)
				rv.manager = self
				self.loggerDict[name] = rv
				self._fixupParents(rv)
		finally:
			_releaseLock()
		return rv

	def _fixupParents(self, alogger):
		name = alogger.name
		i = string.rfind(name, ".")
		rv = None
		while (i > 0) and not rv:
			substr = name[:i]
			if not self.loggerDict.has_key(substr):
				self.loggerDict[substr] = PlaceHolder(alogger)
			else:
				obj = self.loggerDict[substr]
				if isinstance(obj, Logger):
					rv = obj
				else:
					assert isinstance(obj, PlaceHolder)
					obj.append(alogger)
			i = string.rfind(name, ".", 0, i - 1)
		if not rv:
			rv = self.root
		alogger.parent = rv

	def _fixupChildren(self, ph, alogger):
		for c in ph.loggers:
			if string.find(c.parent.name, alogger.name) <> 0:
				alogger.parent = c.parent
				c.parent = alogger

class Logger(Filterer):
	def __init__(self, name, level=NOTSET):
		Filterer.__init__(self)
		self.name = name
		self.level = level
		self.parent = None
		self.propagate = 1
		self.handlers = []
		self.disabled = 0

	def setLevel(self, level):
		self.level = level

	def debug(self, msg, *args, **kwargs):
		if self.manager.disable >= DEBUG:
			return
		if DEBUG >= self.getEffectiveLevel():
			apply(self._log, (DEBUG, msg, args), kwargs)

	def info(self, msg, *args, **kwargs):
		if self.manager.disable >= INFO:
			return
		if INFO >= self.getEffectiveLevel():
			apply(self._log, (INFO, msg, args), kwargs)

	def warn(self, msg, *args, **kwargs):
		if self.manager.disable >= WARN:
			return
		if self.isEnabledFor(WARN):
			apply(self._log, (WARN, msg, args), kwargs)

	def error(self, msg, *args, **kwargs):
		if self.manager.disable >= ERROR:
			return
		if self.isEnabledFor(ERROR):
			apply(self._log, (ERROR, msg, args), kwargs)

	def exception(self, msg, *args):
		apply(self.error, (msg,) + args, {'exc_info': 1})

	def critical(self, msg, *args, **kwargs):
		if self.manager.disable >= CRITICAL:
			return
		if CRITICAL >= self.getEffectiveLevel():
			apply(self._log, (CRITICAL, msg, args), kwargs)

	fatal = critical

	def log(self, level, msg, *args, **kwargs):
		if self.manager.disable >= level:
			return
		if self.isEnabledFor(level):
			apply(self._log, (level, msg, args), kwargs)

	def findCaller(self):
		rv = (None, None)
		frame = inspect.currentframe().f_back
		while frame:
			sfn = inspect.getsourcefile(frame)
			if sfn:
				sfn = os.path.normcase(sfn)
			if sfn != _srcfile:
				lineno = inspect.getlineno(frame)
				rv = (sfn, lineno)
				break
			frame = frame.f_back
		return rv

	def makeRecord(self, name, level, fn, lno, msg, args, exc_info):
		return LogRecord(name, level, fn, lno, msg, args, exc_info)

	def _log(self, level, msg, args, exc_info=None):
		if inspect and _srcfile:
			_acquireLock()
			try:
				fn, lno = self.findCaller()
			finally:
				_releaseLock()
		else:
			fn, lno = "<unknown file>", 0
		if exc_info:
			exc_info = sys.exc_info()
		record = self.makeRecord(self.name, level, fn, lno, msg, args, exc_info)
		self.handle(record)

	def handle(self, record):
		if (not self.disabled) and self.filter(record):
			self.callHandlers(record)

	def addHandler(self, hdlr):
		if not (hdlr in self.handlers):
			self.handlers.append(hdlr)

	def removeHandler(self, hdlr):
		if hdlr in self.handlers:
			hdlr.close()
			self.handlers.remove(hdlr)

	def callHandlers(self, record):
		c = self
		found = 0
		while c:
			for hdlr in c.handlers:
				found = found + 1
				if record.levelno >= hdlr.level:
					hdlr.handle(record)
			if not c.propagate:
				c = None
			else:
				c = c.parent
		if (found == 0) and not self.manager.emittedNoHandlerWarning:
			sys.stderr.write("No handlers could be found for logger"
							 " \"%s\"\n" % self.name)
			self.manager.emittedNoHandlerWarning = 1

	def getEffectiveLevel(self):
		logger = self
		while logger:
			if logger.level:
				return logger.level
			logger = logger.parent
		return NOTSET

	def isEnabledFor(self, level):
		if self.manager.disable >= level:
			return 0
		return level >= self.getEffectiveLevel()

class RootLogger(Logger):
	def __init__(self, level):
		Logger.__init__(self, "root", level)

_loggerClass = Logger

root = RootLogger(WARN)
Logger.root = root
Logger.manager = Manager(Logger.root)

BASIC_FORMAT = "%(levelname)s:%(name)s:%(message)s"

def basicConfig():
	if len(root.handlers) == 0:
		hdlr = StreamHandler()
		fmt = Formatter(BASIC_FORMAT)
		hdlr.setFormatter(fmt)
		root.addHandler(hdlr)

def getLogger(name=None):
	if name:
		return Logger.manager.getLogger(name)
	else:
		return root

def critical(msg, *args, **kwargs):
	if len(root.handlers) == 0:
		basicConfig()
	apply(root.critical, (msg,)+args, kwargs)

fatal = critical

def error(msg, *args, **kwargs):
	if len(root.handlers) == 0:
		basicConfig()
	apply(root.error, (msg,)+args, kwargs)

def exception(msg, *args):
	apply(error, (msg,)+args, {'exc_info': 1})

def warn(msg, *args, **kwargs):
	if len(root.handlers) == 0:
		basicConfig()
	apply(root.warn, (msg,)+args, kwargs)

def info(msg, *args, **kwargs):
	if len(root.handlers) == 0:
		basicConfig()
	apply(root.info, (msg,)+args, kwargs)

def debug(msg, *args, **kwargs):
	if len(root.handlers) == 0:
		basicConfig()
	apply(root.debug, (msg,)+args, kwargs)

def disable(level):
	root.manager.disable = level

def shutdown():
	for h in _handlers.keys():
		h.flush()
		h.close()

if __name__ == "__main__":
	print __doc__
