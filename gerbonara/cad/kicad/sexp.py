import math
import re
import functools
from typing import Any, Optional
import uuid
from dataclasses import dataclass, fields, field
from copy import deepcopy


class SexpError(ValueError):
    """ Low-level error parsing S-Expression format """ 
    pass


class FormatError(ValueError):
    """ Semantic error in S-Expression structure """
    pass


class AtomType(type):
    def __getattr__(cls, key):
        return cls(key)


@functools.total_ordering
class Atom(metaclass=AtomType):
    def __init__(self, obj=''):
        if isinstance(obj, str):
            self.value = obj
        elif isinstance(obj, Atom):
            self.value = obj.value
        else:
            raise TypeError(f'Atom argument must be str, not {type(obj)}')

    def __str__(self):
        return self.value

    def __repr__(self):
        return f'@{self.value}'

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        if not isinstance(other, (Atom, str)):
            return self.value == other
        return self.value == str(other)

    def __lt__(self, other):
        if not isinstance(other, (Atom, str)):
            raise TypeError(f'Cannot compare Atom and {type(other)}')
        return self.value < str(other)

    def __gt__(self, other):
        if not isinstance(other, (Atom, str)):
            raise TypeError(f'Cannot compare Atom and {type(other)}')
        return self.value > str(other)


term_regex = r"""(?mx)
    \s*(?:
        "((?:\\\\|\\"|[^"])*)"|
        (\()|
        (\))|
        ([+-]?\d+\.\d+(?=[\s\)]))|
        (\-?\d+(?=[\s\)]))|
        ([^0-9"\s()][^"\s)]*)
       )"""


def parse_sexp(sexp: str) -> Any:
    re_iter = re.finditer(term_regex, sexp)
    rv = list(_parse_sexp_internal(re_iter))

    for leftover in re_iter:
        quoted_str, lparen, rparen, *rest = leftover.groups()
        if quoted_str or lparen or any(rest):
            raise SexpError(f'Leftover garbage after end of expression at position {leftover.start()}')  # noqa: E501

        elif rparen:
            raise SexpError(f'Unbalanced closing parenthesis at position {leftover.start()}')

    if len(rv) == 0:
        raise SexpError('No or empty expression')

    if len(rv) > 1:
        print(rv[0])
        print(rv[1])
        raise SexpError('Missing initial opening parenthesis')

    return rv[0]


def _parse_sexp_internal(re_iter) -> Any:
    for match in re_iter:
        quoted_str, lparen, rparen, float_num, integer_num, bare_str = match.groups()

        if lparen:
            yield list(_parse_sexp_internal(re_iter))
        elif rparen:
            break
        elif bare_str is not None:
            yield Atom(bare_str)
        elif quoted_str is not None:
            yield quoted_str.replace('\\"', '"')
        elif float_num:
            yield float(float_num)
        elif integer_num:
            yield int(integer_num)


def build_sexp(exp, indent='  ') -> str:
    # Special case for multi-values
    if isinstance(exp, (list, tuple)):
        joined = '('
        for i, elem in enumerate(exp):
            if 1 <= i <= 5 and len(joined) < 120 and not isinstance(elem, (list, tuple)):
                joined += ' '
            elif i >= 1:
                joined += '\n' + indent
            joined += build_sexp(elem, indent=f'{indent}  ')
        return joined + ')'

    if exp == '':
        return '""'

    if isinstance(exp, str):
        exp = exp.replace('"', r'\"')
        return f'"{exp}"'

    if isinstance(exp, float):
        # python whyyyy
        val = f'{exp:.6f}'
        val = val.rstrip('0')
        if val[-1] == '.':
            val += '0'
        return val
    else:
        return str(exp)


if __name__ == "__main__":
    sexp = """ ( ( Winson_GM-402B_5x5mm_P1.27mm data "quoted data" 123 4.5)
         (data "with \\"escaped quotes\\"")
         (data (123 (4.5) "(more" "data)")))"""

    print("Input S-expression:")
    print(sexp)
    parsed = parse_sexp(sexp)
    print("\nParsed to Python:", parsed)

    print("\nThen back to: '%s'" % build_sexp(parsed))
