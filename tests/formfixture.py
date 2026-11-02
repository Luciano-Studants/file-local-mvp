"""PDF com formulário (AcroForm) criado à mão para os testes: texto, texto em campo hierárquico, caixa, opções e lista."""
import io

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject)


def _stream(writer, content: bytes, bbox):
    stream = DecodedStreamObject(); stream.set_data(content)
    stream[NameObject('/Type')] = NameObject('/XObject'); stream[NameObject('/Subtype')] = NameObject('/Form')
    stream[NameObject('/BBox')] = ArrayObject([FloatObject(v) for v in bbox])
    return writer._add_object(stream)


def form_pdf(width=400, height=300, rotate=0, signature_field=False, readonly_name=False) -> bytes:
    w = PdfWriter(); page = w.add_blank_page(width, height)
    if rotate:
        page.rotate(rotate)
    helv = w._add_object(DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')}))

    def widget(rect, ft=None, name=None, parent=None, flags=0, **extra):
        d = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'), NameObject('/Rect'): ArrayObject([FloatObject(v) for v in rect]), NameObject('/F'): NumberObject(4)})
        if ft: d[NameObject('/FT')] = NameObject(ft)
        if name is not None: d[NameObject('/T')] = TextStringObject(name)
        if flags: d[NameObject('/Ff')] = NumberObject(flags)
        if ft == '/Tx': d[NameObject('/DA')] = TextStringObject('/Helv 12 Tf 0 g')
        for key, value in extra.items(): d[NameObject(key)] = value
        return d

    refs = []
    nome = w._add_object(widget([20, 250, 300, 272], '/Tx', 'nome')); refs.append(nome)
    pai = w._add_object(DictionaryObject({NameObject('/T'): TextStringObject('endereco'), NameObject('/Kids'): ArrayObject()}))
    cidade = widget([20, 215, 300, 237], '/Tx', 'cidade', **{'/Parent': pai}); cidade_ref = w._add_object(cidade); refs.append(cidade_ref)
    pai.get_object()[NameObject('/Kids')].append(cidade_ref)
    on, off = _stream(w, b'0 0 20 20 re S 4 4 m 16 16 l S 16 4 m 4 16 l S', [0, 0, 20, 20]), _stream(w, b'0 0 20 20 re S', [0, 0, 20, 20])
    aceito = w._add_object(widget([20, 180, 40, 200], '/Btn', 'aceito', **{'/V': NameObject('/Off'), '/AS': NameObject('/Off'),
                                                                    '/AP': DictionaryObject({NameObject('/N'): DictionaryObject({NameObject('/Yes'): on, NameObject('/Off'): off})})}))
    refs.append(aceito)
    radio_parent = w._add_object(DictionaryObject({NameObject('/FT'): NameObject('/Btn'), NameObject('/Ff'): NumberObject(1 << 15), NameObject('/T'): TextStringObject('turno'), NameObject('/Kids'): ArrayObject(), NameObject('/V'): NameObject('/Off')}))
    for index, (state, y) in enumerate((('manha', 140), ('tarde', 110))):
        kid = w._add_object(widget([20, y, 40, y + 20], None, None, **{'/Parent': radio_parent, '/AS': NameObject('/Off'),
                                                                 '/AP': DictionaryObject({NameObject('/N'): DictionaryObject({NameObject('/' + state): on, NameObject('/Off'): off})})}))
        radio_parent.get_object()['/Kids'].append(kid); refs.append(kid)
    estado = w._add_object(widget([20, 70, 200, 92], '/Ch', 'estado', 1 << 17, **{'/Opt': ArrayObject([TextStringObject('PA'), TextStringObject('SP'), TextStringObject('AM')]), '/DA': TextStringObject('/Helv 12 Tf 0 g')}))
    refs.append(estado)
    fixed = [nome, pai, aceito, radio_parent, estado]
    if readonly_name:
        w.get_object(nome)[NameObject('/Ff')] = NumberObject(1)
    if signature_field:
        sig = w._add_object(widget([250, 20, 380, 60], '/Sig', 'assinatura_digital')); refs.append(sig); fixed.append(sig)
    page[NameObject('/Annots')] = ArrayObject(refs)
    w._root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject(fixed), NameObject('/DA'): TextStringObject('/Helv 0 Tf 0 g'),
                                                                NameObject('/DR'): DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/Helv'): helv})})})
    buffer = io.BytesIO(); w.write(buffer); return buffer.getvalue()
