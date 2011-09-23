import re
import os
import hashlib
import shutil

import bb.utils
import oe.process

import oelite.fetch
import local
import url
import git
import hg

FETCHERS = {
    "file"	: local.LocalFetcher,
    "http"	: url.UrlFetcher,
    "https"	: url.UrlFetcher,
    "ftp"	: url.UrlFetcher,
    "git"	: git.GitFetcher,
    "hg"	: hg.HgFetcher,
}

uri_pattern = re.compile("(?P<scheme>[^:]*)://(?P<location>[^;]+)(;(?P<params>.*))?")

unpack_ext = (
    ("tar_gz",	(".tar.gz", ".tgz", ".tar.Z")), 
    ("tar_bz2",	(".tar.bz2", ".tbz", ".tbz2")),
    ("tar_xz",	(".tar.xz", ".txz")),
    ("tar_lz",	(".tar.lz", ".tlz")),
    ("zip",	(".zip", ".jar")),
    ("gz",	(".gz", ".Z", ".z")),
    ("bz2",	(".bz2",)),
    ("xz",	(".xz",)),
    ("lz",	(".lz",)),
    )

class OEliteUri:

    def __init__(self, uri, d):
        # Note, do not store reference to meta
        self.srcdir = d.get("SRCDIR")
        self.patchsubdir = d.get("PATCHSUBDIR")
        self.patchdir = d.get("PATCHDIR")
        self.quiltrc = d.get("QUILTRC")
        self.ingredients = d.get("INGREDIENTS")
        self.isubdir = (d.get("INGREDIENTS_SUBDIR") or
                        os.path.basename(d.get("FILE_DIRNAME")))
        self.strict = d.get("SRC_URI_STRICT") or False
        if self.strict == "0":
            self.strict = False
        m = uri_pattern.match(uri)
        if not m:
            raise oelite.fetch.InvalidURI(uri, "not an URI at all")
        self.scheme = m.group("scheme")
        self.location = m.group("location")
        if not self.scheme:
            raise oelite.fetch.InvalidURI(uri, "no URI scheme")
        if not self.location:
            raise oelite.fetch.InvalidURI(uri, "no URI location")
        self.params = {}
        if m.group("params"):
            for param in (m.group("params") or "").split(";"):
                try:
                    name, value = param.split("=")
                except ValueError:
                    raise oelite.fetch.InvalidURI(
                        uri, "bad parameter: %s"%param)
                self.params[name] = value
        if not self.scheme in FETCHERS:
            raise oelite.fetch.InvalidURI(
                uri, "unsupported URI scheme: %s"%(self.scheme))
        self.fetcher = FETCHERS[self.scheme](self, d)
        self.init_unpack_params()
        self.init_patch_params()
        return

    def __str__(self):
        return "%s://%s"%(self.scheme, self.location)

    def init_unpack_params(self):
        if not "localpath" in dir(self.fetcher):
            return
        if not "unpack" in self.params:
            for (unpack, exts) in unpack_ext:
                assert isinstance(exts, tuple)
                for ext in exts:
                    if self.fetcher.localpath.endswith(ext):
                        self.params["unpack"] = unpack
                        return
        elif self.params["unpack"] == "0":
            del self.params["unpack"]
        if "unpack" in self.params and self.params["unpack"] == "zip":
            if "dos" in self.params and self.params["dos"] != "0":
                self.params["unpack"] += "_dos"
        return

    def init_patch_params(self):
        if not "localpath" in dir(self.fetcher):
            return
        if not "apply" in self.params:
            patchfile = self.fetcher.localpath
            try:
                unpack = self.params["unpack"] or None
                if unpack == "0":
                    unpack = None
            except KeyError:
                unpack = None
            if unpack and self.fetcher.localpath.endswith(unpack):
                patchfile = self.fetcher.localpath[-len(unpack):]
            if patchfile.endswith(".patch") or patchfile.endswith(".diff"):
                self.params["apply"] = "yes"
        elif not self.params["apply"] in ["yes", "y", "1"]:
            del self.params["apply"]
        if "apply" in self.params:
            if "subdir" in self.params:
                subdir = self.params["subdir"]
                if (subdir != self.patchsubdir and
                    not subdir.startswith(self.patchsubdir + "")):
                    subdir = os.path.join(self.patchsubdir, subdir)
            else:
                subdir = self.patchsubdir
            self.params["subdir"] = subdir
        if not "striplevel" in self.params:
            self.params["striplevel"] = 1
        if "patchdir" in self.params:
            raise Exception("patchdir URI parameter support not implemented")
        return

    def signature(self):
        try:
            return self.fetcher.signature()
        except oelite.fetch.NoSignature as e:
            if self.strict:
                raise e
            print "warning: no checksum known for", self.location
            return ""

    def cache(self):
        if not "cache" in dir(self.fetcher):
            return True
        return self.fetcher.cache()

    def write_checksum(self, filepath):
        md5path = filepath + ".md5"
        checksum = hashlib.md5()
        with open(filepath) as f:
            checksum.update(f.read())
        with open(md5path, "w") as f:
            f.write(checksum.digest())

    def verify_checksum(self, filepath):
        md5path = filepath + ".md5"
        if not os.path.exists(md5path):
            return None
        checksum = hashlib.md5()
        with open(filepath) as f:
            checksum.update(f.read())
        with open(md5path) as f:
            return f.readline().strip() == checksum.digest()

    def fetch(self):
        if not "fetch" in dir(self.fetcher):
            return True
        print "Fetching", str(self)
        return self.fetcher.fetch()

    def unpack(self, cmd):
        if "unpack" in dir(self.fetcher):
            return self.fetcher.unpack()
        print "Unpacking", self.fetcher.localpath
        srcpath = os.getcwd()
        self.srcfile = None
        if "subdir" in self.params:
            srcpath = os.path.join(srcpath, self.params["subdir"])
            bb.utils.mkdirhier(srcpath)
            os.chdir(srcpath)
        if not cmd:
            if os.path.isdir(self.fetcher.localpath):
                shutil.rmtree(srcpath, True)
                shutil.copytree(self.fetcher.localpath, self.srcpath())
                return True
            else:
                shutil.copy2(self.fetcher.localpath, self.srcpath())
                return True
        if "unpack_to" in self.params:
            cmd = cmd%(self.fetcher.localpath, self.srcpath())
        else:
            cmd = cmd%(self.fetcher.localpath)
        rc = oe.process.run(cmd)
        return rc == 0

    def srcpath(self):
        if "subdir" in self.params:
            srcdir = os.path.join(self.srcdir, self.params["subdir"])
        else:
            srcdir = self.srcdir
        if "unpack_to" in self.params:
            return os.path.join(srcdir, self.params["unpack_to"])
        else:
            return os.path.join(srcdir,
                                os.path.basename(self.fetcher.localpath))

    def patchpath(self):
        srcpath = self.srcpath()
        assert srcpath.startswith(self.patchdir + "/")
        return srcpath[len(self.patchdir) + 1:]

    def patch(self):
        with open("%s/series"%(self.patchdir), "a") as series:
            series.write("%s -p%s\n"%(
                    self.patchpath(), self.params["striplevel"]))

        rc = oe.process.run("quilt --quiltrc %s push"%(self.quiltrc))
        if rc != 0:
            # FIXME: proper error handling
            raise Exception("quilt push failed: %d"%(rc))
        return True


def patch_init(d):
    quiltrc = d.get("QUILTRC")
    patchdir = d.get("PATCHDIR")
    with open(quiltrc, "w") as quiltrcfile:
        quiltrcfile.write("QUILT_PATCHES=%s\n"%(patchdir))
    s = d.get("S")
    os.chdir(s)
    if os.path.exists(".pc"):
        while os.path.exists(".pc/applied-patches"):
            rc = oe.process.run("quilt --quiltrc %s pop"%(quiltrc))
            if rc != 0:
                # FIXME: proper error handling
                raise Exception("quilt pop failed")
        if not os.path.exists(".pc/series"):
            # FIXME: proper error handling
            raise Exception("Bad quilt .pc dir")
