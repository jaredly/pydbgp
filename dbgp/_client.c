

#include "Python.h"
#include "compile.h"
#include "eval.h"
#include "frameobject.h"
#include "structmember.h"

#include "osdefs.h"

#ifdef MS_WINDOWS
#define WIN32_LEAN_AND_MEAN
#include "windows.h"
#endif /* MS_WINDOWS */

/* The following defines were introduced in Python 2.3 only, but we want
 * to support Python 2.2. Do the same macro-magic as does Python 2.3's
 * pyexpat.c for compatibility
 */
#ifndef PyDoc_STRVAR
#define PyDoc_STR(str)         str
#define PyDoc_VAR(name)        static char name[]
#define PyDoc_STRVAR(name,str) PyDoc_VAR(name) = PyDoc_STR(str)
#endif /* !PyDoc_STRVAR */

#ifndef PyMODINIT_FUNC
#   ifdef MS_WINDOWS
#       define PyMODINIT_FUNC __declspec(dllexport) void
#   else
#       define PyMODINIT_FUNC void
#   endif
#endif


//#define DEBUG_PRINT 1

#define BOTFRAME_STEP        0x00
#define BOTFRAME_CONTINUE    0x01

static PyObject *__adb_ignoreModules = NULL;
static PyObject *__adb_debugAll = NULL;
static PyObject *__adb_canonicCache = NULL;
static PyObject *__adb_breakpointFileList = NULL;
static PyObject *__adb_breakpointList = NULL;
static PyObject *__dbgpClientModule = NULL;
static PyObject *PyExc_DBGPQuit;

typedef struct {
    PyObject_HEAD
    PyObject *botframe;
    PyObject *stopframe;
    PyObject *returnframe;
    
    long breakOnFirstCall;
    long interrupt;
    long quitting;
    long botframeBehaviour;
} AdbObject;


static long _adbobj_stop_here(AdbObject *self, PyFrameObject *frame)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_stop_here...\n");
#endif

    if ((PyObject *)frame == self->stopframe) {
#ifdef DEBUG_PRINT
        fprintf(stderr, "..._adbobj_stop_here at stopframe\n");
#endif
        return 1;
    }

    // while frame is not None and frame is not self.stopframe:
    while (frame != NULL && (PyObject *)frame != Py_None && (PyObject *)frame != self->stopframe) {
        
        if ((PyObject *)frame == self->botframe) {
#ifdef DEBUG_PRINT
            fprintf(stderr, "..._adbobj_stop_here at botframe\n");
#endif
            return self->botframeBehaviour == BOTFRAME_STEP;
        }
        frame = frame->f_back;
    }
#ifdef DEBUG_PRINT
    fprintf(stderr, "..._adbobj_stop_here\n");
#endif
    return 0;
}

static long _adbobj_trace_skip(AdbObject *self, PyFrameObject *frame)
{
    unsigned long ignoreSize;
    int result;
    unsigned int i;
    PyObject *__obj;

#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_trace_skip...\n");
#endif
    // super debugger.  If we need to debug the debugger, then this var
    // gets set, and we never skip a frame
    if (PyInt_AsLong(__adb_debugAll) != 0) {
        return 0;
    }

    // if no frame or line number we skip the frame
    if (frame == NULL || frame->f_lineno == 0) {
        return 1;
    }

    // if this frame is explicitly hidden, skip it
    if (PyDict_GetItemString(frame->f_globals,"DBGPHide") != NULL) {
        return 1;
    }
    
    // if the module this frame is in is in our ignore list, the skip it
    /*
      if self._ignoreModules and \
        frame.f_globals.has_key('__name__') and \
        frame.f_globals['__name__'] in self._ignoreModules:
        return 1;
    */
    ignoreSize = PyList_Size(__adb_ignoreModules);
    if (ignoreSize > 0) {
        __obj = PyDict_GetItemString(frame->f_globals,"__name__");
        if (__obj != NULL) {
            for (i=0; i < ignoreSize; i++) {
                PyObject *item = PyList_GetItem(__adb_ignoreModules, i);
                if (item != NULL && PyString_Check(item) &&
                    PyObject_Cmp(__obj, item, &result) != -1 &&
                    result == 0) {
                        return 1;
                }
            }
        }
    }

    /*
        if frame and frame.f_back and frame.f_back.f_globals.has_key('DBGPHideChildren'):
            frame.f_globals['DBGPHideChildren'] = frame.f_back.f_globals['DBGPHideChildren']
    */
    if (frame->f_back) {
        __obj = PyDict_GetItemString(frame->f_back->f_globals,"DBGPHideChildren");
        if (__obj != NULL && PyInt_Check(__obj)) {
            PyDict_SetItemString(frame->f_globals,"DBGPHideChildren", __obj);
            return PyInt_AsLong(__obj);
        }
    }
    
    // now we have to look through the frame stack, and see if this is
    // a frame we need to ignore, because it is a child of a frame that .
    // we want to bypass (eg. stdout redirection in the dbgp module).
    // this is a bit of a perf hit, but that is prevented somewhat by the
    // block above.  see _pyclient.py trace_skip for some comments or refer
    // to bugs 35933 and 44620
    while (frame != NULL) {
        __obj = PyDict_GetItemString(frame->f_globals,"DBGPHideChildren");
        if (__obj != NULL && PyInt_Check(__obj) && PyInt_AsLong(__obj) != 0) {
            return PyInt_AsLong(__obj);
        }
        frame = frame->f_back;
    }
    return 0;
}

static long _adbobj_have_possible_break(AdbObject *self, PyFrameObject *frame)
{
    PyObject *filename;
    PyObject *tuple;
    int haveFileBP;

#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_have_possible_break...\n");
#endif
    if (PyDict_Size(__adb_breakpointList) < 1) {
        // no breakpoints, no possible break
        return 0;
    }
    
    if (PyMapping_HasKey(__adb_canonicCache, frame->f_code->co_filename)==0) {
        // filename has not been mapped, so force a call to effective
        return 1;
    }

    filename = PyDict_GetItem(__adb_canonicCache, frame->f_code->co_filename);
    if (PyMapping_HasKey(__adb_breakpointFileList, filename)==1) {
        // we have breakpoints for this file, do we have one for this line
        // or a file global breakpoint?

        tuple = Py_BuildValue("(Oi)", filename, frame->f_lineno);
        haveFileBP = PyDict_GetItem(__adb_breakpointList, tuple) != NULL;
        Py_DECREF(tuple);
        if (haveFileBP) {
            return 1;
        }

        // check for file global breakpoints
        tuple = Py_BuildValue("(Oi)", filename, 0);
        haveFileBP = PyDict_GetItem(__adb_breakpointList, tuple) != NULL;
        Py_DECREF(tuple);
        if (haveFileBP) {
            return 1;
        }
    }
    // check for global breakpoints
    return PyMapping_HasKeyString(__adb_breakpointFileList, "");
}

static long _adbobj_break_here(AdbObject *self, PyFrameObject *frame,
                               PyObject *arg, char *type)
{
    PyObject *tuple;
    PyObject *bp;
    PyObject *flag;

#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_break_here...\n");
#endif
    // do a basic fast test to see if we have possible breakpoints, if we do
    // then we will go the slow road and call effective.
    if (_adbobj_have_possible_break(self, frame) == 0) {
        return 0;
    }
    
    // flag says ok to delete temp. bp
    tuple = PyObject_CallMethod(__dbgpClientModule, "effective", "OOs",
                                (PyObject *)frame, arg, type);
    bp   = PyTuple_GetItem(tuple, 0);
    flag = PyTuple_GetItem(tuple, 1);
    
    if (bp != NULL && bp != Py_None) {
        PyObject *tmp = PyObject_GetAttrString(bp, "temporary");
        if (PyLong_AsLong(flag) && PyLong_AsLong(tmp)) {
            PyObject *r = PyObject_CallMethod(bp, "deleteMe", NULL);
            Py_DECREF(r);
        }
        Py_DECREF(tmp);
        Py_DECREF(tuple);
        return 1;
    }
    Py_DECREF(tuple);
    return 0;
}

static int
_adbobj_dispatch_line(AdbObject *self, PyFrameObject *frame, PyObject *arg)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_dispatch_line...\n");
#endif
    //if self.stop_here(frame) or self.break_here(frame):
    //    self.dispatch_interaction(frame)
    if (_adbobj_stop_here(self, frame) ||
        _adbobj_break_here(self, frame, arg, "")) {
#ifdef DEBUG_PRINT
        fprintf(stderr, "    _adbobj_dispatch_line dispatch_interaction...\n");
#endif
        PyObject *r = PyObject_CallMethod((PyObject *)self,
                                          "dispatch_interaction",
                                          "O", (PyObject *)frame);
#ifdef DEBUG_PRINT
        fprintf(stderr, "    _adbobj_dispatch_line ...dispatch_interaction\n");
#endif
        if (r != NULL) {Py_DECREF(r);}
    
        // if self.quitting: raise DBGPQuit
        if (self->quitting) {
#ifdef DEBUG_PRINT
            fprintf(stderr, "..._adbobj_dispatch_line quiting\n");
#endif
            PyErr_SetObject(PyExc_DBGPQuit, 0);
            return -1;
        }
    }
    //return self.trace_dispatch
#ifdef DEBUG_PRINT
    fprintf(stderr, "..._adbobj_dispatch_line\n");
#endif
    return 0;
}

static int
_adbobj_dispatch_call(AdbObject *self, PyFrameObject *frame, PyObject *arg)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_dispatch_call...\n");
#endif
    //if self.botframe is None:
    //    # First call of dispatch since reset()
    //    self.botframe = frame.f_back # (CT) Note that this may also be None!
    //    return self.trace_dispatch
    if (!self->botframe || self->botframe == Py_None) {
        Py_DECREF(self->botframe);
        if (frame->f_back != NULL) {
            self->botframe = (PyObject *)frame->f_back;
        } else {
            self->botframe = Py_None;
        }
        Py_INCREF(self->botframe);
        return 0;
    }
    
    //if self.stop_here(frame) or self.break_here(frame, arg, 'call'):
    //    self.dispatch_interaction(frame)
    if (_adbobj_stop_here(self, frame) ||
        _adbobj_break_here(self, frame, arg, "call")) {
        PyObject *r = PyObject_CallMethod((PyObject *)self,
                                          "dispatch_interaction",
                                          "O", (PyObject *)frame);
        Py_DECREF(r);
        // if self.quitting: raise DBGPQuit
        if (self->quitting) {
            PyErr_SetObject(PyExc_DBGPQuit, 0);
            return -1;
        }
    }
    //return self.trace_dispatch
    return 0;
}

static int
_adbobj_dispatch_return(AdbObject *self, PyFrameObject *frame, PyObject *arg)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_dispatch_return...\n");
#endif
    /*if self.stop_here(frame) or frame == self.returnframe or \
     *   self.break_here(frame, arg, 'return'):
     *    self.dispatch_interaction(frame, arg)
     */
    if ((PyObject *)frame == self->returnframe ||
        _adbobj_stop_here(self, frame) ||
        _adbobj_break_here(self, frame, arg, "return")) {
        PyObject *r = PyObject_CallMethod((PyObject *)self,
                                          "dispatch_interaction",
                                          "O", (PyObject *)frame);
        Py_DECREF(r);
        /* if self.quitting: raise DBGPQuit */
        if (self->quitting) {
            PyErr_SetObject(PyExc_DBGPQuit, 0);
            return -1;
        }
    }
    /* return self.trace_dispatch */
    return 0;
}

static int
_adbobj_dispatch_exception(AdbObject *self, PyFrameObject *frame, PyObject *arg)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_dispatch_exception...\n");
#endif
    //if self.stop_here(frame) or self.break_here(frame, arg, 'exception'):
    //    self.dispatch_interaction(frame)
    if (_adbobj_stop_here(self, frame) ||
        _adbobj_break_here(self, frame, arg, "exception")) {
        PyObject *r = PyObject_CallMethod((PyObject *)self, "dispatch_interaction",
                                          "O", (PyObject *)frame);
        Py_DECREF(r);
        // if self.quitting: raise DBGPQuit
        if (self->quitting) {
            PyErr_SetObject(PyExc_DBGPQuit, 0);
            return -1;
        }
    }
    //return self.trace_dispatch
    return 0;
}


// here we do some extra thinking about whether we want to call into the
// python layer of dbgp
static int
_adbobj_trace_dispatch(AdbObject* self, PyFrameObject *frame,
                      int what, PyObject *arg)
{
    int result = 0;
    
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_trace_dispatch...\n");
#endif
    if (self->quitting != 0) {
#ifdef DEBUG_PRINT
        fprintf(stderr, "..._adbobj_trace_dispatch quiting\n");
#endif
        PyErr_SetObject(PyExc_DBGPQuit, 0);
        return -1;
    }
    
    if (_adbobj_trace_skip(self, frame) == 1) {
#ifdef DEBUG_PRINT
        fprintf(stderr, "..._adbobj_trace_dispatch skip\n");
#endif
        return 0;
    }
    
    // have we been flagged to do an interraction?  If so, then interact
    
    // XXX one logic flaw here is that we used to call poll(), which would
    // check more than just having a command waiting in queue, it would also
    // check to see what our run state was, and whether we support async.
    // this only matters on startup, after which it is fine to handle interact
    // here, so we're taking a shortcut and relying on breakOnFirstCall
    // to bypass interact until after the first 'call' into our script.
    if (self->interrupt != 0 && !self->breakOnFirstCall) {
        PyObject *r;
        self->interrupt = 0;
#ifdef DEBUG_PRINT
        fprintf(stderr, "  _adbobj_trace_dispatch calling interraction\n");
#endif
        r = PyObject_CallMethod((PyObject *)self, "interaction",
                                          "OOi", (PyObject *)frame, Py_None, 1);
        // discard the result
        Py_DECREF(r);
#ifdef DEBUG_PRINT
        fprintf(stderr, "..._adbobj_trace_dispatch called interraction\n");
#endif
        return 0;
    }

    switch (what) {
    case PyTrace_LINE:
        result = _adbobj_dispatch_line(self, frame, arg);
        break;
    case PyTrace_CALL:
        result = _adbobj_dispatch_call(self, frame, arg);
        if (self->breakOnFirstCall) {
            self->breakOnFirstCall = 0;
            result = _adbobj_dispatch_line(self, frame, arg);
        }
        break;
    case PyTrace_RETURN:
        result = _adbobj_dispatch_return(self, frame, arg);
        break;
    case PyTrace_EXCEPTION:
        result = _adbobj_dispatch_exception(self, frame, arg);
        break;
    }
#ifdef DEBUG_PRINT
    fprintf(stderr, "..._adbobj_trace_dispatch return %d\n", result);
#endif
    return result;
}

/* XXX the following code has been copied from sysmodule.c
 */

static int
_adbobj_trace_trampoline(AdbObject *self, PyFrameObject *frame, int what,
                PyObject *arg)
{
    int result;
#ifdef DEBUG_PRINT
    fprintf(stderr, "_adbobj_trace_trampoline...\n");
#endif
    PyFrame_FastToLocals(frame);
    result = _adbobj_trace_dispatch(self, frame, what, arg);
    PyFrame_LocalsToFast(frame, 1);
    if (result == -1) {
        PyTraceBack_Here(frame);
        PyEval_SetTrace(NULL, NULL);
        Py_XDECREF(frame->f_trace);
        frame->f_trace = NULL;
#ifdef DEBUG_PRINT
        fprintf(stderr, "..._adbobj_trace_trampoline NULL result\n");
#endif
    }
#ifdef DEBUG_PRINT
    fprintf(stderr, "..._adbobj_trace_trampoline %d\n", result);
#endif
    return result;
}


PyDoc_STRVAR(adbobj_starttrace__doc__,
"starttrace()\n\
\n\
Start tracing."
);

static PyObject *
adbobj_starttrace(AdbObject *self, PyObject *args)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "adbobj_starttrace\n");
#endif
    PyEval_SetTrace((Py_tracefunc)_adbobj_trace_trampoline, (PyObject *)self);
    Py_INCREF(Py_None);
    return Py_None;
}

PyDoc_STRVAR(adbobj_stoptrace__doc__,
"stoptrace()\n\
\n\
Stop tracing."
);

static PyObject *
adbobj_stoptrace(AdbObject *self, PyObject *args)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "adbobj_stoptrace\n");
#endif
    PyEval_SetTrace(NULL, NULL);
    Py_INCREF(Py_None);
    return Py_None;
}

static void
adbobj_dealloc(AdbObject *self)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "adbobj_dealloc...\n");
#endif
    Py_DECREF(self->stopframe);
    Py_DECREF(self->botframe);
    Py_DECREF(self->returnframe);
    Py_DECREF(__dbgpClientModule);
    PyObject_Del((PyObject *)self);
#ifdef DEBUG_PRINT
    fprintf(stderr, "...adbobj_dealloc\n");
#endif
}

static PyObject *
adbobj_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    AdbObject *self;

#ifdef DEBUG_PRINT
    fprintf(stderr, "adbobj_new...\n");
#endif
    self = (AdbObject *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->breakOnFirstCall = 1;
        self->interrupt = 0;
        self->quitting = 0;
        self->botframeBehaviour = BOTFRAME_STEP;
    
        Py_INCREF(Py_None);
        self->botframe = Py_None;
        Py_INCREF(Py_None);
        self->stopframe = Py_None;
        Py_INCREF(Py_None);
        self->returnframe = Py_None;
    }
    // only import dbgpClient when the first object is created
    if (__dbgpClientModule == NULL) {
        // import the module so we can call some module level functions
        __dbgpClientModule = PyImport_ImportModule("dbgp.client");
    }
    if (PyExc_DBGPQuit == NULL) {
        PyObject *mod = PyImport_ImportModule("dbgp.common");
        PyExc_DBGPQuit = PyObject_GetAttrString(mod, "DBGPQuit");
    }
    Py_INCREF(__dbgpClientModule);
    return (PyObject *)self;
}

static int
adbobj_init(AdbObject *self, PyObject *args, PyObject *kwds)
{
#ifdef DEBUG_PRINT
    fprintf(stderr, "adbobj_init...\n");
#endif
    return 0;
}

static PyMethodDef adbobj_methods[] = {
    {"starttrace", (PyCFunction)adbobj_starttrace, METH_VARARGS, adbobj_starttrace__doc__},
    {"stoptrace", (PyCFunction)adbobj_stoptrace, METH_VARARGS, adbobj_stoptrace__doc__},
    {NULL, NULL}
};

static PyMemberDef adbobj_members[] = {
    {"breakOnFirstCall", T_LONG, offsetof(AdbObject, breakOnFirstCall), 0, ""},
    {"interrupt", T_LONG, offsetof(AdbObject, interrupt), 0, ""},
    {"quitting",   T_LONG, offsetof(AdbObject, quitting), 0, ""},
    {"botframeBehaviour",  T_LONG, offsetof(AdbObject, botframeBehaviour), 0, ""},
    {"botframe", T_OBJECT_EX, offsetof(AdbObject, botframe), 0, ""},
    {"stopframe",   T_OBJECT_EX, offsetof(AdbObject, stopframe), 0, ""},
    {"returnframe",  T_OBJECT_EX, offsetof(AdbObject, returnframe), 0, ""},
    {NULL}
};


PyDoc_STRVAR(adbobj__doc__,
"High-performance debugger object.\n\
\n\
Methods:\n\
\n\
\n\
Attributes (read-only):\n\
\n\
");

static PyTypeObject AdbType = {
    PyObject_HEAD_INIT(NULL)
    0,					/* ob_size		*/
    "Adb.Adb",		                /* tp_name		*/
    (int) sizeof(AdbObject),	        /* tp_basicsize		*/
    0,					/* tp_itemsize		*/
    (destructor)adbobj_dealloc,	        /* tp_dealloc		*/
    0,					/* tp_print		*/
    0,	                                /* tp_getattr           */
    0,					/* tp_setattr		*/
    0,					/* tp_compare		*/
    0,					/* tp_repr		*/
    0,					/* tp_as_number		*/
    0,					/* tp_as_sequence	*/
    0,					/* tp_as_mapping	*/
    0,					/* tp_hash		*/
    0,					/* tp_call		*/
    0,					/* tp_str		*/
    PyObject_GenericGetAttr,		/* tp_getattro		*/
    0,					/* tp_setattro		*/
    0,					/* tp_as_buffer		*/
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags	*/
    adbobj__doc__,		        /* tp_doc		*/
    0,					/* tp_traverse		*/
    0,					/* tp_clear		*/
    0,					/* tp_richcompare	*/
    0,					/* tp_weaklistoffset	*/
    0,					/* tp_iter		*/
    0,					/* tp_iternext		*/
    adbobj_methods,			/* tp_methods		*/
    adbobj_members,			/* tp_members		*/
    0,          			/* tp_getset		*/
    0,					/* tp_base		*/
    0,					/* tp_dict		*/
    0,					/* tp_descr_get		*/
    0,					/* tp_descr_set		*/
    0,                                  /* tp_dictoffset        */
    (initproc)adbobj_init,              /* tp_init              */
    0,                                  /* tp_alloc             */
    adbobj_new,                         /* tp_new               */
};

PyDoc_STRVAR(adb_Adb__doc__,
"_client() -> _client\n\
Create a new Adb object.");

static PyObject *
adb_Adb(PyObject *unused, PyObject *args)
{
    AdbObject *self = PyObject_New(AdbObject, &AdbType);
#ifdef DEBUG_PRINT
    fprintf(stderr, "adb_Adb...\n");
#endif
    return (PyObject *) self;
}

PyDoc_STRVAR(adb_setLocal__doc__,
"setLocal(frame, varname, value)\n\
set a local variable in a frame.");

#ifndef Py_DEBUG
#define GETITEM(v, i) PyTuple_GET_ITEM((PyTupleObject *)(v), (i))
#define GETITEMNAME(v, i) \
	PyString_AS_STRING((PyStringObject *)GETITEM((v), (i)))
#else
#define GETITEM(v, i) PyTuple_GetItem((v), (i))
#define GETITEMNAME(v, i) PyString_AsString(GETITEM(v, i))
#endif

static PyObject* adb_setLocal(PyObject* unused, PyObject* args) {
    PyFrameObject* frame = NULL;
    PyObject* value = NULL;
    char *name;
    int i;

    if (!PyArg_ParseTuple(args, "OsO:setlocal", &frame, &name, &value)) {
        return NULL;
    }
    if (!PyFrame_Check(frame)) {
        return NULL;
    }
    for(i=0; i < PySequence_Length(frame->f_locals); ++i) {
        if ( strcmp(GETITEMNAME(frame->f_code->co_varnames,i),name) == 0 ) {
            Py_XDECREF(frame->f_localsplus[i]);
            Py_INCREF(value);
            frame->f_localsplus[i] = value;
        }
    }
    Py_INCREF(Py_None);
    return Py_None;
}

static struct PyMethodDef __adb_methods[] = {
    {"_client", adb_Adb,  METH_VARARGS, adb_Adb__doc__},
    {"setlocal", adb_setLocal,  METH_VARARGS, adb_setLocal__doc__},
    {0, 0, 0, 0}
};

PyDoc_STRVAR(adb_doc,
"Adb - Advanced Debugger\n\
\n\
This module provides fast optimizations for the DBGP debugger module.");

PyMODINIT_FUNC
init_client(void)
{
    PyObject *m;

#ifdef DEBUG_PRINT
    fprintf(stderr, "init_client...\n");
#endif
    AdbType.ob_type = &PyType_Type;
    m = Py_InitModule3("_client", __adb_methods, adb_doc);

    Py_INCREF(&AdbType);
    PyModule_AddObject(m, "clientBase", (PyObject *)&AdbType);
    
    __adb_ignoreModules = PyList_New(0);
    Py_INCREF(__adb_ignoreModules);
    PyModule_AddObject(m, "ignoreModules", __adb_ignoreModules);
    
    __adb_debugAll = PyInt_FromLong(0);
    Py_INCREF(__adb_debugAll);
    PyModule_AddObject(m, "debugAll", __adb_debugAll);

    __adb_canonicCache = PyDict_New();
    Py_INCREF(__adb_canonicCache);
    PyModule_AddObject(m, "canonicCache", __adb_canonicCache);

    __adb_breakpointFileList = PyDict_New();
    Py_INCREF(__adb_breakpointFileList);
    PyModule_AddObject(m, "breakpointsByFile", __adb_breakpointFileList);

    __adb_breakpointList = PyDict_New();
    Py_INCREF(__adb_breakpointList);
    PyModule_AddObject(m, "breakpointList", __adb_breakpointList);

    PyModule_AddIntConstant(m, "BOTFRAME_STEP", BOTFRAME_STEP);
    PyModule_AddIntConstant(m, "BOTFRAME_CONTINUE", BOTFRAME_CONTINUE);
#ifdef DEBUG_PRINT
    fprintf(stderr, "...init_client\n");
#endif
}


