#
# Copyright (c) 2021 Incisive Technology Ltd
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
This program generates all the 'model' package & api version modules

This program works off a specified Kubernetes swagger file and from there
builds out the model sub-package of hikaru. It first removes all existing
content of this package and then re-creates it from scratch. If the swagger
file hasn't changed, then these generated modules will be identical, otherwise
they will contain the new contents from the swagger file.

Usage is:

    python build.py <path to swagger file>

The assumption is to create the 'build' package in the cwd.

Just some notes to remember how this all works:

For the collection types, you must parameterize the
types from typing (List, Dict, etc).

If you want an optional type, you can use typing.Optional,
which turns into Union[T, NoneType].

You can use dataclasses.field(default_factory=list) to indicate
where optional args should be defaulted to new empty lists.

You can acquire the fields of class X with
dataclasses.fields(X). The type annotation for the field is
stored in the 'type' attribute.

You now want to understand Union and List types. There are two
different ways to do this; the change comes at Py3.8. This
are both performed on the type object found in the above
mentioned attribute:

Operation           Pre-3.8         3.8 and later
========================================================
get origin          __origin__      typing.get_origin()
get args            __args__        typing.get_args()

inspect.signature() can give the argument signature for a
method; can find how many required positional args there are.
"""
from pathlib import Path
import sys
from typing import Union, List, Optional
import json
import networkx
from hikaru.naming import process_swagger_name, full_swagger_name
from hikaru.meta import HikaruBase, HikaruDocumentBase


python_reserved = {"except", "continue", "from"}


types_map = {"boolean": "bool",
             "integer": "int",
             "string": "str",
             "float": "float",
             "number": "float"}


NoneType = type(None)


unversioned_module_name = "unversioned"


def _clean_directory(dirpath: str, including_dirpath=False):
    path = Path(dirpath)
    for p in path.iterdir():
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            _clean_directory(str(p), including_dirpath=True)
            if including_dirpath:
                p.rmdir()


_package_init_code = \
"""
try:
    from .v1 import *
except ImportError:
    pass"""


def prep_package(directory: str):
    """
    This function empties the directory named 'directory', creating it if needed
    :param directory: string; name of an empty directory to create. Creates it
        if needed, and removes any existing content if it's already there.
    """
    path = Path(directory)
    if not path.exists():
        path.mkdir(parents=True)
    else:
        if not path.is_dir():
            path.unlink()
            path.mkdir(parents=True)
    # once here, the directory exists and is a directory; clean it out
    _clean_directory(str(path))
    init = path / "__init__.py"
    init.touch()
    f = init.open('w')
    print(_module_docstring, file=f)
    print(_package_init_code, file=f)
    print(file=f)
    output_footer(stream=f)


_copyright_string = \
"""#
# Copyright (c) 2021 Incisive Technology Ltd
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE."""

_module_docstring = f'''{_copyright_string}
"""
DO NOT EDIT THIS FILE!

This module is automatically generated using the hikaru.build program that turns
a Kubernetes swagger spec into the code for the hikaru.model module.
"""
'''


def output_boilerplate(stream=sys.stdout, other_imports=None):
    """
    Write out the standard module header imports
    :param stream: where to write; sys.stdout default
    :param other_imports: None, or a list of strings to generate import
        statements for
    """
    print(_module_docstring, file=stream)
    print(file=stream)
    print(f"from hikaru.meta import {HikaruBase.__name__}, {HikaruDocumentBase.__name__}",
          file=stream)
    print("from typing import Optional, List, Dict", file=stream)
    print("from dataclasses import dataclass, field", file=stream)
    if other_imports is not None:
        for line in other_imports:
            print(line, file=stream)
    print(file=stream)
    print(file=stream)


_module_footer = '''globs = dict(globals())
__all__ = [c.__name__ for c in globs.values()
           if type(c) == type]
del globs'''


def output_footer(stream=sys.stdout):
    """
    Write out the footer that defines '__all__'
    :param stream: file to write the footer to
    """
    print(_module_footer, file=stream)


def build_digraph(all_classes: dict) -> networkx.DiGraph:
    dg = networkx.DiGraph()
    for cd in all_classes.values():
        assert isinstance(cd, ClassDescriptor)
        deps = cd.depends_on(include_external=True)
        dg.add_node(cd)
        for c in deps:
            dg.add_edge(cd, c)

    return dg


def write_classes(class_list, stream=sys.stdout):
    for dc in class_list:
        print(dc.as_python_class(), file=stream)


def load_stable(swagger_file_path: str) -> NoneType:
    f = open(swagger_file_path, 'r')
    d = json.load(f)
    for k, v in d["definitions"].items():
        if 'apiextensions' not in k:
            group, version, name = process_swagger_name(k)
            mod_def = get_module_def(version)
            cd = mod_def.get_class_desc(name)
            if cd is None:
                cd = ClassDescriptor(k, v)
                mod_def.save_class_desc(cd)
            else:
                cd.update(v)
            cd.process_properties()


def write_modules(pkgpath: str):
    pkg = Path(pkgpath)
    d = module_defs()
    mod_names = []
    base = d.get(None)
    # first, create the module with un-versioned object defs
    if base:
        unversioned = pkg / f'{unversioned_module_name}.py'
        assert isinstance(base, ModuleDef)
        f = unversioned.open('w')
        base.as_python_module(stream=f)
        f.close()

    # next, write out all the version-specific object defs
    for k, md in d.items():
        if k is not None:
            assert isinstance(md, ModuleDef)
            mod_names.append(md.version)
            mod = pkg / f'{md.version}.py'
            f = mod.open('w')
            md.as_python_module(stream=f)
            f.close()

    # finally, capture the names of all the version modules in version module
    versions = pkg / 'versions.py'
    f = versions.open('w')
    print(f"versions = {str(mod_names)}", file=f)
    f.close()


class ClassDescriptor(object):
    def __init__(self, key, d):
        self.full_name = full_swagger_name(key)
        group, version, name = process_swagger_name(self.full_name)
        self.short_name = name
        self.group = group
        self.version = version
        self.description = None
        self.all_properties = None
        self.required = None
        self.type = None
        self.is_subclass_of = None
        self.is_document = False

        self.required_props = []
        self.optional_props = []
        self.update(d)

    def update(self, d: dict):
        self.description = d.get("description")
        self.all_properties = d.get("properties", {})
        self.required = d.get("required", [])
        self.type = d.get('type', None)
        if self.type in types_map:
            self.is_subclass_of = types_map[self.type]

    _doc_markers = ("apiVersion", "kind", "metadata")

    def process_properties(self):
        self.required_props = []
        self.optional_props = []
        seen_markers = set(self._doc_markers)
        if self.is_subclass_of is None:  # then there are properties
            for k, v in self.all_properties.items():
                if k in seen_markers:
                    seen_markers.remove(k)
                    if not seen_markers:
                        self.is_document = True
                fd = PropertyDescriptor(self, k, v)
                if k in self.required:
                    self.required_props.append(fd)
                else:
                    self.optional_props.append(fd)
            self.required_props.sort(key=lambda x: x.name)
            self.optional_props.sort(key=lambda x: x.name)

    @staticmethod
    def split_line(line, prefix: str = "   ", hanging_indent: str = "") -> List[str]:
        parts = []
        if line is not None:
            words = line.split()
            current_line = [prefix]
            for w in words:
                if sum(len(s) for s in current_line) + len(current_line) + len(w) > 90:
                    parts.append(" ".join(current_line))
                    current_line = [prefix]
                    if hanging_indent:
                        current_line.append(hanging_indent)
                current_line.append(w)
            else:
                if current_line:
                    parts.append(" ".join(current_line))
        return parts

    def as_python_class(self) -> str:
        lines = list()
        # start of class statement
        if self.is_subclass_of is not None:
            base = self.is_subclass_of
        else:
            # then it is to be a dataclass
            base = (HikaruDocumentBase.__name__
                    if self.is_document else
                    HikaruBase.__name__)
            lines.append("@dataclass")
        lines.append(f"class {self.short_name}({base}):")
        # now the docstring
        ds_parts = ['    """']
        ds_parts.extend(self.split_line(self.description))
        ds_parts.append("")
        ds_parts.append(f'    Full name: {self.full_name.split("/")[-1]}')
        if self.is_subclass_of is None:
            ds_parts.append("")
            ds_parts.append("    Attributes:")
            for p in self.required_props:
                ds_parts.extend(self.split_line(f'{p.name}: {p.description}',
                                                hanging_indent="   "))
            for p in (x for x in self.optional_props if x.container_type is None):
                ds_parts.extend(self.split_line(f'{p.name}: {p.description}',
                                                hanging_indent="   "))
            for p in (x for x in self.optional_props if x.container_type is not None):
                ds_parts.extend(self.split_line(f'{p.name}: {p.description}',
                                                hanging_indent="   "))
        ds_parts.append('    """')
        lines.extend(ds_parts)
        if self.is_subclass_of is None:
            if self.required_props or self.optional_props:
                lines.append("")
            if self.is_document:
                lines.append(f"    _version = '{self.version}'")
            for p in self.required_props:
                lines.append(p.as_python_typeanno(True))
            for p in (x for x in self.optional_props if x.container_type is None):
                lines.append(p.as_python_typeanno(False))
            for p in (x for x in self.optional_props if x.container_type is not None):
                lines.append(p.as_python_typeanno(False))
        lines.append("")
        lines.append("")

        return "\n".join(lines)

    def depends_on(self, include_external=False) -> list:
        r = [p.depends_on() for p in self.required_props]
        deps = [p for p in r
                if p is not None]
        o = [p.depends_on() for p in self.optional_props]
        deps.extend(p for p in o
                    if p is not None and (True
                                          if include_external else
                                          self.version == p.version))
        return deps


class ModuleDef(object):
    def __init__(self, version):
        self.version = version
        self.all_classes = {}

    def get_class_desc(self, sname: str) -> Optional[ClassDescriptor]:
        return self.all_classes.get(sname)

    def save_class_desc(self, class_def: ClassDescriptor):
        assert isinstance(class_def, ClassDescriptor)
        self.all_classes[class_def.short_name] = class_def

    def external_versions_used(self) -> List[str]:
        ext_ver = set()
        for cd in self.all_classes.values():
            for dep in cd.depends_on(include_external=True):
                assert isinstance(dep, ClassDescriptor)
                if dep.version != self.version:
                    ext_ver.add(dep.version)
        return list(ext_ver)

    def as_python_module(self, stream=sys.stdout):
        externals = self.external_versions_used()
        other_imports = []
        if None in externals:
            other_imports.append(f'from .{unversioned_module_name} import *')
            externals.remove(None)
        externals.sort()
        all_classes = {}
        for ext in externals:
            emod = _all_module_defs[ext]
            assert isinstance(emod, ModuleDef)
            all_classes.update(emod.all_classes)
        all_classes.update(self.all_classes)
        g = build_digraph(all_classes)
        output_boilerplate(stream=stream, other_imports=other_imports)
        traversal = list(reversed(list(networkx.topological_sort(g))))
        if not traversal:
            traversal = list(self.all_classes.values())
        write_classes(traversal, stream=stream)
        output_footer(stream=stream)


_all_module_defs = {}


def get_module_def(version) -> ModuleDef:
    md = _all_module_defs.get(version)
    if md is None:
        md = _all_module_defs[version] = ModuleDef(version)
    return md


def module_defs() -> dict:
    return dict(_all_module_defs)


class PropertyDescriptor(object):
    def __init__(self, containing_class, name, d):
        """
        capture the information
        :param containing_class:
        :param d:
        """
        self.name = f'{name}_' if name in python_reserved else name
        self.containing_class = containing_class
        self.description = d.get('description', "")
        # all possible attributes that could be populated
        self.container_type = self.item_type = self.prop_type = None
        ctype = d.get("type")
        if ctype == "array":
            self.container_type = list
            items = d["items"]
            self.item_type = items.get('type')
            if self.item_type is None:
                # then it is a list of objects; possibly of one of the defs
                ref = items["$ref"]  # should become get when we know this is true
                group, version, short_name = process_swagger_name(ref)
                fullname = full_swagger_name(ref)
                mod_def = get_module_def(version)
                item_ref = mod_def.get_class_desc(short_name)
                if item_ref is None:
                    item_ref = ClassDescriptor(fullname, {})  # make a placeholder
                    mod_def.save_class_desc(item_ref)
                self.item_type = item_ref
            elif self.item_type in types_map:
                self.item_type = types_map[self.item_type]
            else:
                raise TypeError(f"Unknown type of {self.item_type} in {self.name}")
        elif ctype == "object":
            self.container_type = dict
        else:
            self.container_type = None

        if self.container_type is None:
            if ctype in types_map:
                self.prop_type = types_map[ctype]
            else:
                group, version, short_name = process_swagger_name(d["$ref"])
                fullname = full_swagger_name(d["$ref"])
                mod_def = get_module_def(version)
                ref_class = mod_def.get_class_desc(short_name)
                if ref_class is None:
                    ref_class = ClassDescriptor(fullname, {})
                    mod_def.save_class_desc(ref_class)
                self.prop_type = ref_class

    @staticmethod
    def as_required(anno: str, as_required: bool) -> str:
        return anno if as_required else f"Optional[{anno}]"

    def depends_on(self) -> Union[ClassDescriptor, NoneType]:
        result = None
        if isinstance(self.item_type, ClassDescriptor):
            result = self.item_type
        elif isinstance(self.prop_type, ClassDescriptor):
            result = self.prop_type
        return result

    def as_python_typeanno(self, as_required: bool) -> str:
        parts = ["    ", self.name, ": "]
        if self.container_type is None:
            # then a straight-up type, either scalar or another object
            if isinstance(self.prop_type, str):
                parts.append(self.as_required(self.prop_type, as_required))
            elif isinstance(self.prop_type, ClassDescriptor):
                parts.append(self.as_required(self.prop_type.short_name,
                                              as_required))
        elif self.container_type is list:
            if isinstance(self.item_type, ClassDescriptor):
                parts.append(self.as_required(f"List[{self.item_type.short_name}]",
                                              as_required))
            else:
                parts.append(self.as_required(f"List[{self.item_type}]",
                                              as_required))
        elif self.container_type is dict:
            parts.append(self.as_required("Dict[str, str]", as_required))
        else:
            raise TypeError(f"Unknown attribute {self.name} in "
                            f"{self.containing_class.short_name}")
        # now check if we should add a field default
        if not as_required:
            # then we need to add a default value so we don't have to
            # supply this argument when creating it programmatically
            if self.container_type is not None:
                # then we need a field
                factory = "list" if self.container_type is list else "dict"
                parts.append(f" = field(default_factory={factory})")
            else:
                # just default it to None
                parts.append(" = None")
        return "".join(parts)


model_package = "hikaru/model"


def build_it(swagger_file: str):
    """
    Initiate the swagger-file-driven model package build

    :param swagger_file: string; path to the swagger file to process
    """
    load_stable(swagger_file)
    prep_package(model_package)
    write_modules(model_package)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <path-to-swagger-json-file>")
        sys.exit(1)
    build_it(sys.argv[1])
    sys.exit(0)
