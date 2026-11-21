"""Builds a tiny synthetic input tree (invented names only) to smoke-test the whole pipeline: python tests/make_fixture.py <dir>"""
import io, os, sys, zipfile, gzip
root = sys.argv[1]
def w(rel, data):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data if isinstance(data, bytes) else data.encode())
R = "sources/github/Zorblax-Labs__quantum-gizmo-3000"
step = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
FILE_NAME('/home/qwertyuiop/work/part.step','2021-04-18T15:55:18',('Wilhelmina Zxyvarsky'),('Zorblax Labs GmbH'),'Open CASCADE STEP processor 7.4','FreeCAD','Unknown');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
#1 = PRODUCT('quantum-gizmo-3000 housing','quantum-gizmo-3000 housing','',(#2));
#2 = PRODUCT_CONTEXT('',#3,'mechanical');
#3 = CARTESIAN_POINT('',(1.5,2.5,3.5));
ENDSEC;
END-ISO-10303-21;
"""
w(R + "/cad/housing.step", step)
w(R + "/cad/Wilhelmina Zxyvarsky notes.txt", "Contact wilhelmina.zxyvarsky@zorblax-labs.example.org or tel: +49 30 1234567\nCopyright 2020 Zorblax Labs GmbH\n")
zb = io.BytesIO()
with zipfile.ZipFile(zb, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("quantum-gizmo-3000/readme.txt", "by Wilhelmina Zxyvarsky (Zorblax Labs GmbH)")
    z.writestr("quantum-gizmo-3000/part.stp", step)
w(R + "/archive/bundle.zip", zb.getvalue())
w(R + "/archive/bundle.tar.gz", gzip.compress(b"hello Wilhelmina Zxyvarsky"))
import pikepdf
pdf = pikepdf.new(); pdf.add_blank_page(page_size=(200, 200))
pdf.docinfo["/Author"] = "Wilhelmina Zxyvarsky"; pdf.docinfo["/Title"] = "quantum-gizmo-3000 drawing"
cs = pdf.make_stream(b"BT /F1 12 Tf 10 100 Td [(Wilhelmina Zx)-20(yvarsky)] TJ ET")
pdf.pages[0].Contents = cs
pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
b = io.BytesIO(); pdf.save(b); w(R + "/doc/drawing.pdf", b.getvalue())
w(R + "/mesh/part.stl", "solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n")
w("sources/github/Plain-Owner__other-thing/readme.md", "nothing identifying here\n")
