#from oelite.meta import *
from oebakery import die, err, warn, info, debug

import oelite.meta
import oelite.recipe
import oelite.util
import oelite.path

import os
import cPickle

class MetaCache:

    def __init__(self, cachefile, recipes=None, baker=None):
        if recipes is None:
            try:
                self.cachefile = cachefile
                self.file = open(cachefile)
                self.abi = cPickle.load(self.file)
                self.env_signature = cPickle.load(self.file)
                self.mtimes = cPickle.load(self.file)
            finally:
                return

        if os.path.exists(cachefile):
            os.unlink(cachefile)
        oelite.util.makedirs(os.path.dirname(cachefile))
        self.abi = pickle_abi()
        self.env_signature = baker.config.env_signature()
        self.mtimes = set()
        self.meta = {}
        self.expand_cache = {}
        for type in recipes:
            for mtime in recipes[type].meta.get_input_mtimes():
                self.mtimes.add(mtime)
        self.file = open(cachefile, "w")
        cPickle.dump(self.abi, self.file, 2)
        cPickle.dump(self.env_signature, self.file, 2)
        cPickle.dump(self.mtimes, self.file, 2)
        cPickle.dump(len(recipes), self.file, 2)
        for type in recipes:
            recipes[type].pickle(self.file)
        return


    def is_current(self, baker):
        try:
            if pickle_abi() != self.abi:
                return False
            if baker.config.env_signature() != self.env_signature:
                return False
            if not isinstance(self.mtimes, set):
                return False
        except AttributeError:
            return False
        if not self.mtimes:
            warn("Cachefile (%s) with no file(s) reference(s) loaded, broken cache generation?"%(self.cachefile))
            return False
        for (fn, oepath, old_mtime) in list(self.mtimes):
            if oepath is not None:
                filepath = oelite.path.which(oepath, fn)
            else:
                filepath = fn
            if os.path.exists(filepath):
                cur_mtime = os.path.getmtime(filepath)
            else:
                cur_mtime = None
            if cur_mtime != old_mtime:
                return False
        return True


    def load(self, filename, cookbook):
        recipes = {}
        for i in xrange(cPickle.load(self.file)):
            recipe = oelite.recipe.unpickle(
                self.file, filename, cookbook)
            recipes[recipe.type] = recipe
        return recipes


    def __repr__(self):
        return '%s()'%(self.__class__.__name__)


    def __iter__(self):
        return self.meta.keys().__iter__()


PICKLE_ABI = None

PICKLE_ABI_MODULES = [
    "oelite",
    "oelite.arch",
    "oelite.baker",
    "oelite.cookbook",
    "oelite.dbutil",
    "oelite.fetch",
    "oelite.fetch.fetch",
    "oelite.fetch.git",
    "oelite.fetch.local",
    "oelite.fetch.sigfile",
    "oelite.fetch.svn",
    "oelite.fetch.url",
    "oelite.function",
    "oelite.item",
    "oelite.meta",
    "oelite.meta.cache",
    "oelite.meta.dict",
    "oelite.meta.meta",
    "oelite.package",
    "oelite.parse",
    "oelite.parse.confparse",
    "oelite.parse.expandlex",
    "oelite.parse.expandparse",
    "oelite.parse.oelex",
    "oelite.parse.oeparse",
    "oelite.pyexec",
    "oelite.recipe",
    "oelite.runq",
    "oelite.task",
    "oelite.util",
    ]

def pickle_abi():
    global PICKLE_ABI
    if not PICKLE_ABI:
        import inspect
        import hashlib
        srcfiles = []
        for module in PICKLE_ABI_MODULES:
            exec "import %s"%(module)
            srcfiles.append(inspect.getsourcefile(eval(module)))
        m = hashlib.md5()
        for srcfile in srcfiles:
            with open(srcfile) as _srcfile:
                m.update(_srcfile.read())
        PICKLE_ABI = m.digest()
    return PICKLE_ABI
