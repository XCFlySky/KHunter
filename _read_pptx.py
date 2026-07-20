# -*- coding: utf-8 -*-
"""提取 PPTX 文本"""
import sys, zipfile, re
sys.stdout.reconfigure(encoding='utf-8')
from xml.etree import ElementTree as ET

NS = '{http://schemas.openxmlformats.org/drawingml/2006/main}'

def extract(path):
    print('=' * 70)
    print(path)
    print('=' * 70)
    with zipfile.ZipFile(path) as z:
        slides = sorted([n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)],
                        key=lambda x: int(re.search(r'\d+', x.split('/')[-1]).group()))
        for s in slides:
            xml = z.read(s)
            root = ET.fromstring(xml)
            texts = [t.text for t in root.iter(f'{NS}t') if t.text]
            if texts:
                print(f'\n--- {s.split("/")[-1]} ---')
                print(' | '.join(texts))

for p in sys.argv[1:-1]:
    try:
        extract(p)
    except Exception as e:
        print(f'读取失败: {e}')

# 直接写入文件避免 PowerShell 管道乱码
import io
out_path = sys.argv[-1]
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for p in sys.argv[1:-1]:
        try:
            extract(p)
        except Exception as e:
            print(f'读取失败: {e}')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(buf.getvalue())
print('已写入', out_path, len(buf.getvalue()), '字符')
