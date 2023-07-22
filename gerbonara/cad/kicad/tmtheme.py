
from xml.etree import ElementTree
import base64
from pathlib import Path

def _map_primitive(element):
    match element.tag:
        case 'data':
            return base64.b64decode(element.text)
        case 'date':
            return element.text
        case 'true':
            return True
        case 'false':
            return False
        case 'real':
            return float(element.text)
        case 'integer':
            return int(element.text)
        case 'string':
            return element.text
        case 'array':
            return [_map_primitive(child) for child in element]
        case 'dict':
            children = list(element)
            return {k.text: _map_primitive(v) for k, v in zip(children[0::2], children[1::2])}


def parse_shitty_json(data):
    # Parse apple plist XML
    root = ElementTree.fromstring(data)
    return _map_primitive(root[0])

class TmThemeSchematic:
    def __init__(self, data):
        self.theme = parse_shitty_json(data)
        s = self.theme['settings'][0]['settings']
        by_scope = {}
        for elem in self.theme['settings']:
            if 'scope' not in elem:
                continue
            for scope in elem['scope'].split(','):
                by_scope[scope.strip()] = elem.get('settings', {})

        def lookup(default, *scopes):
            for scope in scopes:
                if not (elem := by_scope.get(scope)):
                    continue

                if 'foreground' not in elem:
                    continue

                return elem['foreground']
            return default

        self.background = s.get('background', 'white')
        self.bus = lookup('black', 'constant.other', 'storage.type')
        self.wire = self.lines = lookup('black', 'constant.other')
        self.no_connect = lookup('black', 'constant.language', 'variable')
        self.text = lookup('black', 'constant.numeric', 'constant.numeric.hex', 'storage.type.number')
        self.pin_numbers = lookup('black', 'constant.character', 'constant.other')
        self.pin_names = lookup('black', 'constant.character.format.placeholder', 'constant.other.placeholder')
        self.values = lookup('black', 'constant.character.format.placeholder', 'constant.other.placeholder')
        self.labels = lookup('black', 'constant.numeric', 'constant.numeric.hex', 'storage.type.number')
        self.fill = s.get('background')
        print(f'{self.background=} {self.wire=} {self.bus=} {self.lines=} {self.no_connect=} {self.labels=} {self.fill=}')

if __name__ == '__main__':
    print(parse_shitty_json(Path('/tmp/witchhazelhypercolor.tmTheme').read_text()))

