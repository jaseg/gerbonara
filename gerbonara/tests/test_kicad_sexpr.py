
from ..cad.kicad.sexp import parse_sexp, build_sexp

def test_sexp_round_trip():
    test_sexp = '''(()() (foo) (23)\t(foo 23) (foo 23 bar baz) (foo bar baz) ("foo bar") (" foo " bar) (23 " baz ")
    (foo ( bar ( baz 23) 42) frob) (() (foo) ()()) foo 23 23.0 23.000001 "foo \\"( ))bar"  "foo\\"bar\\"baz" "23" "23foo"
    "" "" ("") ("" 0 0.0)
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data"
    "lots of data" "lots of data" "lots of data" "lots of data" "lots of data" "lots of data")
    '''
    parsed = parse_sexp(test_sexp)
    sexp1 = build_sexp(parsed)
    re_parsed = parse_sexp(sexp1)
    sexp2 = build_sexp(parsed)
    
    assert re_parsed == parsed
    assert sexp1 == sexp2

