# -*- coding: utf-8 -*-
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(content)
    print(f'Successfully wrote {path} ({len(content)} chars)')

print('Ready to generate READMEs')
