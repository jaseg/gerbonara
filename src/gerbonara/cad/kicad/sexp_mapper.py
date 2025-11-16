
import textwrap

import copy
from dataclasses import MISSING, replace, fields
from .sexp import *


SEXP_END = type('SEXP_END', (), {})


class AtomChoice:
    def __init__(self, *choices):
        self.choices = choices

    def __contains__(self, value):
        return value in self.choices

    def __atoms__(self):
        return self.choices

    def __map__(self, obj, parent=None):
        obj, = obj
        if obj not in self:
            raise TypeError(f'Invalid atom {obj} for {type(self)}, valid choices are: {", ".join(map(str, self.choices))}')
        return obj

    def __sexp__(self, value):
        yield value


class Flag:
    def __init__(self, atom=None, invert=None):
        self.atom, self.invert = atom, invert

    def __bind_field__(self, field):
        if self.atom is None:
            self.atom = Atom(field.name)
        if self.invert is None:
            self.invert = bool(field.default)

    def __atoms__(self):
        return [self.atom]

    def __map__(self, obj, parent=None):
        return not self.invert

    def __sexp__(self, value):
        if bool(value) == (not self.invert):
            yield self.atom


def sexp(t, v):
    try:
        if v is None:
            return []
        elif t in (int, float, str, Atom):
            return [t(v)]
        elif hasattr(t, '__sexp__'):
            return list(t.__sexp__(v))
        elif isinstance(t, list):
            t, = t
            return [sexp(t, elem) for elem in v]
        else:
            raise TypeError(f'Python type {t} of value {v!r} has no defined s-expression serialization')

    except MappingError as e:
        raise e

    except Exception as e:
        raise MappingError(f'Error trying to serialize {textwrap.shorten(str(v), width=120)} into type {t}', t, v) from e


class MappingError(TypeError):
    def __init__(self, msg, t, sexp):
        super().__init__(msg)
        self.t, self.sexp = t, sexp

def map_sexp(t, v, parent=None):
    try:
        if t is not Atom and hasattr(t, '__map__'):
            return t.__map__(v, parent=parent)

        elif t in (int, float, str, Atom):
            v, = v
            if not isinstance(v, t):
                types = set({type(v), t})
                if types == {int, float} or types == {str, Atom}:
                    v = t(v)
                else:
                    raise TypeError(f'Cannot map s-expression value {v} of type {type(v)} to Python type {t}')
            return v

        elif isinstance(t, list):
            t, = t
            return [map_sexp(t, elem, parent=parent) for elem in v]

        else:
            raise TypeError(f'Python type {t} has no defined s-expression deserialization')

    except MappingError as e:
        raise e

    except Exception as e:
        raise MappingError(f'Error trying to map {textwrap.shorten(str(v), width=120)} into type {t}', t, v) from e


class WrapperType:
    def __init__(self, next_type):
        self.next_type = next_type

    def __bind_field__(self, field):
        self.field = field
        getattr(self.next_type, '__bind_field__', lambda x: None)(field)

    def __atoms__(self):
        if hasattr(self, 'name_atom'):
            return [self.name_atom]
        elif self.next_type is Atom:
            return []
        else:
            return getattr(self.next_type, '__atoms__', lambda: [])()

class Named(WrapperType):
    def __init__(self, next_type, name=None, omit_empty=True):
        super().__init__(next_type)
        self.name_atom = Atom(name) if name else None
        self.omit_empty = omit_empty

    def __bind_field__(self, field):
        if self.next_type is not Atom:
            getattr(self.next_type, '__bind_field__', lambda x: None)(field)
        if self.name_atom is None:
            self.name_atom = Atom(field.name)

    def __map__(self, obj, parent=None):
        k, *obj = obj
        if self.next_type in (int, float, str, Atom) or isinstance(self.next_type, AtomChoice):
            return map_sexp(self.next_type, [*obj], parent=parent)
        else:
            return map_sexp(self.next_type, obj, parent=parent)

    def __sexp__(self, value):
        value = sexp(self.next_type, value)
        if value is None:
            return

        if self.omit_empty and not value:
            return

        yield [self.name_atom, *value]


class Rename(WrapperType):
    def __init__(self, next_type, name=None):
        super().__init__(next_type)
        self.name_atom = Atom(name) if name else None

    def __bind_field__(self, field):
        if self.name_atom is None:
            self.name_atom = Atom(field.name)
        if hasattr(self.next_type, '__bind_field__'):
            self.next_type.__bind_field__(field)

    def __map__(self, obj, parent=None):
        return map_sexp(self.next_type, obj, parent=parent)

    def __sexp__(self, value):
        value, = sexp(self.next_type, value)
        if self.next_type in (str, float, int, Atom): 
            yield [self.name_atom, *value]
        else:
            key, *rest = value
            yield [self.name_atom, *rest]


class OmitDefault(WrapperType):
    def __bind_field__(self, field):
        getattr(self.next_type, '__bind_field__', lambda x: None)(field)
        if field.default_factory != MISSING:
            self.default = field.default_factory()
        else:
            self.default = field.default

    def __map__(self, obj, parent=None):
        return map_sexp(self.next_type, obj, parent=parent)

    def __sexp__(self, value):
        if value != self.default:
            yield from sexp(self.next_type, value)


class YesNoAtom:
    def __init__(self, yes=Atom.yes, no=Atom.no):
        self.yes, self.no = yes, no

    def __map__(self, value, parent=None):
        value, = value
        return value == self.yes

    def __sexp__(self, value):
        yield self.yes if value else self.no


class LegacyCompatibleFlag:
    '''Variant of YesNoAtom that accepts both the `(flag <yes/no>)` variant and the bare `flag` variant for compatibility.'''

    def __init__(self, yes=Atom.yes, no=Atom.no, value_when_empty=True):
        self.yes, self.no = yes, no
        self.value_when_empty = value_when_empty

    def __map__(self, value, parent=None):
        if value == []:
            return self.value_when_empty

        value, = value
        return value == self.yes

    def __sexp__(self, value):
        yield self.yes if value else self.no


class Wrap(WrapperType):
    def __map__(self, value, parent=None):
        value, = value
        return map_sexp(self.next_type, value, parent=parent)

    def __sexp__(self, value):
        for inner in sexp(self.next_type, value):
            yield [inner]


class Array(WrapperType):
    def __map__(self, value, parent=None):
        return [map_sexp(self.next_type, [elem], parent=parent) for elem in value]
    
    def __sexp__(self, value):
        for e in value:
            yield from sexp(self.next_type, e)


class Untagged(WrapperType):
    def __map__(self, value, parent=None):
        value, = value
        return self.next_type.__map__([self.next_type.name_atom, *value], parent=parent)
    
    def __sexp__(self, value):
        for inner in sexp(self.next_type, value):
            _tag, *rest = inner
            yield rest

class List(WrapperType):
    def __bind_field__(self, field):
        self.attr = field.name

    def __map__(self, value, parent):
        l = getattr(parent, self.attr, [])
        mapped = map_sexp(self.next_type, value, parent=parent)
        l.append(mapped)
        setattr(parent, self.attr, l)

    def __sexp__(self, value):
        for elem in value:
            yield from sexp(self.next_type, elem)


class _SexpTemplate:
    @staticmethod
    def __atoms__(kls):
        return [kls.name_atom]

    @staticmethod
    def __map__(kls, value, *args, parent=None, **kwargs):
        positional = iter(kls.positional)
        inst = kls(*args, **kwargs)

        for v in value[1:]: # skip key
            if isinstance(v, Atom) and v in kls.keys:
                name, etype = kls.keys[v]
                mapped = map_sexp(etype, [v], parent=inst)
                if mapped is not None:
                    setattr(inst, name, mapped)

            elif isinstance(v, list):
                name, etype = kls.keys[v[0]]
                mapped = map_sexp(etype, v, parent=inst)
                if mapped is not None:
                    setattr(inst, name, mapped)

            else:
                try:
                    pos_key = next(positional)
                    setattr(inst, pos_key.name, v)
                except StopIteration:
                    raise TypeError(f'Unhandled positional argument {v!r} while parsing {kls}')

        getattr(inst, '__after_parse__', lambda x: None)(parent)
        return inst

    @staticmethod
    def __sexp__(kls, value):
        getattr(value, '__before_sexp__', lambda: None)()

        out = [kls.name_atom]
        for f in fields(kls):
            if f.type is SEXP_END:
                break
            out += sexp(f.type, getattr(value, f.name))
        yield out

    @staticmethod
    def parse(kls, data, *args, **kwargs):
        return kls.__map__(parse_sexp(data), *args, **kwargs)

    @staticmethod
    def sexp(self):
        return next(self.__sexp__(self))

    @staticmethod
    def __deepcopy__(self, memo):
        return replace(self, **{f.name: copy.deepcopy(getattr(self, f.name), memo) for f in fields(self) if not f.kw_only})

    @staticmethod
    def __copy__(self):
        # Even during a shallow copy, we need to deep copy any fields whose types have a __before_sexp__ method to avoid
        # those from being called more than once on the same object.
        return replace(self, **{f.name: copy.copy(getattr(self, f.name)) for f in fields(self) if not f.kw_only and hasattr(f.type, '__before_sexp__')})

def sexp_type(name=None):
    def register(cls):
        cls = dataclass(cls)
        cls.name_atom = Atom(name) if name is not None else None
        for key in '__sexp__', '__map__', '__atoms__', 'parse':
            if not hasattr(cls, key):
                setattr(cls, key, classmethod(getattr(_SexpTemplate, key)))

        for key in 'sexp', '__deepcopy__', '__copy__':
            if not hasattr(cls, key):
                setattr(cls, key, getattr(_SexpTemplate, key))

        cls.positional = []
        cls.keys = {}
        for f in fields(cls):
            f_type = f.type
            if f_type is SEXP_END:
                break

            if hasattr(f_type, '__bind_field__'):
                f_type.__bind_field__(f)

            atoms = getattr(f_type, '__atoms__', lambda: [])
            atoms = list(atoms())
            for atom in atoms:
                cls.keys[atom] = (f.name, f_type)
            if not atoms:
                cls.positional.append(f)

        return cls
    return register


