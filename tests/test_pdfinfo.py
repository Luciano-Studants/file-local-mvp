"""Base da categoria PDF (0.9.29): leitura segura, informações, miniaturas e prévia pelo worker.

Os PDFs são montados à mão (`make_pdf` de test_illustrator) ou pelo pypdf; o worker é o de verdade (subprocesso), então a leitura
de ponta a ponta — pedido JSON → worker → PNG → bytes — é exercitada sem dublês.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image
from pypdf import PdfWriter

import engine
import pdfinfo
import runner
from engine import ConversionError, convert
from test_illustrator import make_pdf

TEXT = b'BT /F1 24 Tf 10 40 Td (Texto de teste para a camada de texto do PDF) Tj ET'
NEEDS_PDFIUM = unittest.skipUnless(pdfinfo.preview_available(), 'pypdfium2 não instalado')


class PdfBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def write(self, name, data):
        path = self.root / name; path.write_bytes(data); return path

    def blank(self, name='blank.pdf', pages=3, width=595, height=842, rotate=0, metadata=None):
        writer = PdfWriter()
        for _ in range(pages):
            page = writer.add_blank_page(width, height)
            if rotate: page.rotate(rotate)
        if metadata: writer.add_metadata(metadata)
        path = self.root / name
        with path.open('wb') as handle: writer.write(handle)
        return path


class InfoTests(PdfBase):
    def test_basic_summary_in_portuguese(self):
        info = pdfinfo.inspect_pdf(self.blank())
        self.assertEqual((info['pages'], info['page_size'], info['encrypted']), (3, 'A4', False))
        text = pdfinfo.summary_text(info)
        self.assertIn('3 páginas', text); self.assertIn('A4', text); self.assertIn('sem camada de texto', text)
        self.assertEqual(pdfinfo.summary_text(pdfinfo.inspect_pdf(self.blank('one.pdf', pages=1))).split(' · ')[0], '1 página')

    def test_paper_names_ignore_orientation_and_fall_back_to_millimetres(self):
        self.assertEqual(pdfinfo.paper_name(595, 842), 'A4'); self.assertEqual(pdfinfo.paper_name(842, 595), 'A4')
        self.assertEqual(pdfinfo.paper_name(612, 792), 'Carta'); self.assertEqual(pdfinfo.paper_name(612, 1008), 'Ofício')
        self.assertEqual(pdfinfo.paper_name(842, 1191), 'A3'); self.assertEqual(pdfinfo.paper_name(300, 300), '106 × 106 mm')

    def test_rotation_swaps_the_page_dimensions(self):
        info = pdfinfo.inspect_pdf(self.blank(rotate=90))
        self.assertEqual(info['page_points'], [842.0, 595.0]); self.assertEqual(info['page_size'], 'A4')

    def test_mixed_page_sizes_are_flagged(self):
        writer = PdfWriter(); writer.add_blank_page(595, 842); writer.add_blank_page(300, 300)
        path = self.root / 'mixed.pdf'
        with path.open('wb') as handle: writer.write(handle)
        info = pdfinfo.inspect_pdf(path)
        self.assertTrue(info['mixed_sizes']); self.assertIn('tamanhos variados', pdfinfo.summary_text(info))
        self.assertFalse(pdfinfo.inspect_pdf(self.blank())['mixed_sizes'])

    def test_text_layer_detection(self):
        self.assertEqual(pdfinfo.inspect_pdf(self.write('t.pdf', make_pdf(content=TEXT, font=True)))['text_layer'], 'sim')
        self.assertEqual(pdfinfo.inspect_pdf(self.blank())['text_layer'], 'não')
        self.assertIn('com texto', pdfinfo.summary_text(pdfinfo.inspect_pdf(self.write('t2.pdf', make_pdf(content=TEXT, font=True)))))

    def test_metadata_is_read_cleaned_and_dates_simplified(self):
        path = self.blank(metadata={'/Title': 'Relatório\x00 de\nteste', '/Author': 'Maria', '/CreationDate': "D:20240131154500-03'00'", '/Producer': 'Gerador ' + 'x' * 400})
        meta = pdfinfo.inspect_pdf(path)['metadata']
        self.assertEqual(meta['title'], 'Relatório de teste'); self.assertEqual(meta['author'], 'Maria'); self.assertEqual(meta['created'], '2024-01-31')
        self.assertLessEqual(len(meta['producer']), 200)
        self.assertEqual(pdfinfo.pdf_date('D:2023'), '2023'); self.assertEqual(pdfinfo.pdf_date('D:20231345'), '2023'); self.assertEqual(pdfinfo.pdf_date(None), '')

    def test_structure_flags_form_javascript_and_attachments(self):
        plain = pdfinfo.inspect_pdf(self.write('p.pdf', make_pdf()))
        self.assertEqual((plain['forms'], plain['javascript'], plain['attachments']), (False, False, False))
        form = pdfinfo.inspect_pdf(self.write('f.pdf', make_pdf(extra_catalog='/AcroForm << /Fields [] >>')))
        self.assertTrue(form['forms'])
        script = pdfinfo.inspect_pdf(self.write('j.pdf', make_pdf(extra_catalog='/OpenAction << /S /JavaScript /JS (app.alert\\(1\\)) >>')))
        self.assertTrue(script['javascript'])
        names = pdfinfo.inspect_pdf(self.write('a.pdf', make_pdf(extra_catalog='/Names << /EmbeddedFiles << /Names [] >> /JavaScript << /Names [] >> >> >>')))
        self.assertTrue(names['attachments'] and names['javascript'])
        text = pdfinfo.summary_text(names)
        self.assertIn('contém', text); self.assertIn('JavaScript', text); self.assertIn('anexos', text)

    def test_leading_junk_before_the_header_is_accepted(self):
        info = pdfinfo.inspect_pdf(self.write('junk.pdf', b'\x00\x01lixo\n' * 10 + make_pdf()))
        self.assertEqual(info['pages'], 1)

    def test_encrypted_pdf_is_described_not_opened(self):
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('segredo')
        path = self.root / 'locked.pdf'
        with path.open('wb') as handle: writer.write(handle)
        info = pdfinfo.inspect_pdf(path)
        self.assertTrue(info['encrypted']); self.assertIsNone(info['pages']); self.assertIn('senha', pdfinfo.summary_text(info))
        with self.assertRaisesRegex(pdfinfo.PdfError, 'senha'): pdfinfo.open_reader(path)

    def test_bad_files_get_clear_portuguese_errors(self):
        with self.assertRaisesRegex(pdfinfo.PdfError, 'cabeçalho'): pdfinfo.inspect_pdf(self.write('x.pdf', b'isto nao e um pdf' * 50))
        with self.assertRaisesRegex(pdfinfo.PdfError, 'vazio'): pdfinfo.inspect_pdf(self.write('empty.pdf', b''))
        good = make_pdf(pages=3)
        for cut in (len(good) // 2, len(good) - 40):               # truncado: ou lê o que dá, ou recusa com mensagem; nunca exceção técnica
            try:
                info = pdfinfo.inspect_pdf(self.write(f'cut{cut}.pdf', good[:cut]))
                self.assertIsInstance(info, dict)
            except pdfinfo.PdfError as error:
                self.assertRegex(str(error), r'PDF|página|arquivo')

    def test_open_reader_enforces_the_page_limit(self):
        with self.assertRaisesRegex(pdfinfo.PdfError, '200'): pdfinfo.open_reader(self.blank('big.pdf', pages=201, width=50, height=50))
        self.assertEqual(len(pdfinfo.open_reader(self.blank('ok.pdf', pages=2)).pages), 2)
        info = pdfinfo.inspect_pdf(self.root / 'big.pdf'); self.assertTrue(info['too_many_pages']); self.assertIn('200', pdfinfo.summary_text(info))

    def test_engine_read_pdf_names_the_file_in_errors(self):
        path = self.write('quebrado.pdf', b'nada')
        with self.assertRaisesRegex(ConversionError, 'quebrado.pdf'): engine.read_pdf(path)
        with self.assertRaisesRegex(ConversionError, 'quebrado.pdf'): convert({'paths': [str(path)], 'target': 'PDF → Text', 'output': str(self.root)})

    def test_human_bytes(self):
        self.assertEqual(pdfinfo.human_bytes(10), '1 KB'); self.assertEqual(pdfinfo.human_bytes(1536 * 1024), '1,5 MB')


@NEEDS_PDFIUM
class RenderTests(PdfBase):
    def test_render_draws_the_page_in_the_requested_size(self):
        path = self.write('rb.pdf', make_pdf())                       # 200 × 100 pt: vermelho à esquerda, azul embaixo à direita
        (number, image), = pdfinfo.render_pages(path, [1], 200)
        self.assertEqual((number, image.size, image.mode), (1, (200, 100), 'RGB'))
        red, blue, white = image.getpixel((50, 50)), image.getpixel((125, 75)), image.getpixel((190, 10))
        self.assertTrue(red[0] > 200 and red[1] < 60 and red[2] < 60, red)
        self.assertTrue(blue[2] > 200 and blue[0] < 60, blue)
        self.assertEqual(white, (255, 255, 255))
        image.close()
        (_n, small), = pdfinfo.render_pages(path, [1], 100); self.assertEqual(small.size, (100, 50)); small.close()

    def test_render_several_pages_in_order(self):
        path = self.write('three.pdf', make_pdf(pages=3))
        result = pdfinfo.render_pages(path, [3, 1], 100)
        self.assertEqual([n for n, _ in result], [3, 1])
        self.assertGreater(result[0][1].getpixel((10, 10))[1], 200); self.assertGreater(result[1][1].getpixel((20, 20))[0], 200)       # a página 3 é verde; a 1, vermelha
        for _n, image in result: image.close()

    def test_render_rejects_bad_requests(self):
        path = self.write('one.pdf', make_pdf())
        for pages, side, pattern in (([2], 100, 'não existe'), ([0], 100, 'inválido'), ([True], 100, 'inválido'), ([], 100, 'inválido'), (list(range(1, 26)), 100, 'inválido'), ([1], 8, 'entre'), ([1], 5000, 'entre'), ([1], 100.5, 'entre')):
            with self.subTest(pages=pages, side=side), self.assertRaisesRegex(pdfinfo.PdfError, pattern): pdfinfo.render_pages(path, pages, side)

    def test_render_refuses_gigantic_pages_and_locked_files(self):
        with self.assertRaisesRegex(pdfinfo.PdfError, 'grande demais'): pdfinfo.render_pages(self.write('giant.pdf', make_pdf(width=20000, height=20000)), [1], 100)
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('segredo')
        locked = self.root / 'locked.pdf'
        with locked.open('wb') as handle: writer.write(handle)
        with self.assertRaisesRegex(pdfinfo.PdfError, 'senha'): pdfinfo.render_pages(locked, [1], 100)

    def test_pixel_budget_caps_huge_renders(self):
        path = self.write('wide.pdf', make_pdf(width=14000, height=14000))
        (_n, image), = pdfinfo.render_pages(path, [1], 2400)
        self.assertLessEqual(image.width * image.height, pdfinfo.MAX_RENDER_PIXELS * 1.01); image.close()

    def test_forms_and_annotations_are_not_drawn(self):
        # a anotação de carimbo vermelha cobriria a página inteira se fosse desenhada
        annot = '/Annots [<< /Type /Annot /Subtype /Square /Rect [0 0 200 100] /C [1 0 0] /IC [1 0 0] /F 4 >>]'
        pdf = make_pdf(content=b'1 1 1 rg 0 0 200 100 re f').replace(b'/Type /Page /Parent', f'{annot} /Type /Page /Parent'.encode(), 1)
        path = self.write('annot.pdf', pdf)
        (_n, image), = pdfinfo.render_pages(path, [1], 200)
        self.assertEqual(image.getpixel((100, 50)), (255, 255, 255)); image.close()


@NEEDS_PDFIUM
class WorkerOpTests(PdfBase):
    def preview_dir(self):
        self._dirs = getattr(self, '_dirs', 0) + 1
        folder = self.root / (pdfinfo.PREVIEW_DIR_PREFIX + f'teste{self._dirs}'); folder.mkdir(); return folder

    def test_info_op_isolates_each_files_errors(self):
        good, bad = self.blank(), self.write('ruim.pdf', b'nao sou pdf')
        result = pdfinfo.run_op({'op': 'pdf_info', 'paths': [str(good), str(bad), str(self.root / 'sumiu.pdf')]}, engine.source_file)
        infos = result['infos']
        self.assertEqual(infos[0]['pages'], 3); self.assertIn('cabeçalho', infos[1]['error'])
        self.assertIn('foi movido', infos[2]['error']); self.assertNotIn('Errno', infos[2]['error'])
        for bad_paths in ([], 'x', list(range(101))):
            with self.assertRaises(pdfinfo.PdfError): pdfinfo.run_op({'op': 'pdf_info', 'paths': bad_paths}, engine.source_file)

    def test_preview_op_writes_named_pngs_and_reports_sizes(self):
        path, out = self.write('p.pdf', make_pdf(pages=3)), self.preview_dir()
        result = pdfinfo.run_op({'op': 'pdf_preview', 'path': str(path), 'out': str(out), 'thumbs': 5, 'page': 2}, engine.source_file)
        names = sorted(item['file'] for item in result['files'])
        self.assertEqual(names, ['page-002.png', 'thumb-001.png', 'thumb-002.png', 'thumb-003.png'])
        self.assertEqual(sorted(p.name for p in out.iterdir()), names)
        page = next(item for item in result['files'] if item['kind'] == 'page')
        with Image.open(out / page['file']) as image: self.assertEqual(list(image.size), page['size']); self.assertEqual(max(image.size), pdfinfo.PAGE_SIDE)
        thumb = next(item for item in result['files'] if item['kind'] == 'thumb')
        self.assertEqual(max(thumb['size']), pdfinfo.THUMB_SIDE)
        self.assertEqual(result['info']['pages'], 3)

    def test_preview_op_validates_the_request(self):
        path = self.write('p.pdf', make_pdf())
        ok = {'op': 'pdf_preview', 'path': str(path), 'out': str(self.preview_dir())}
        for patch in ({'out': str(self.root)}, {'out': str(self.root / 'nao-existe')}, {'thumbs': 25}, {'thumbs': -1}, {'page': 201}, {'page': 'a'}, {'thumb_side': 5}, {'path': ''}):
            with self.subTest(patch=patch), self.assertRaises((pdfinfo.PdfError, ConversionError)): pdfinfo.run_op({**ok, **patch}, engine.source_file)
        with self.assertRaisesRegex(pdfinfo.PdfError, 'desconhecida'): pdfinfo.run_op({'op': 'outra'}, engine.source_file)
        link = self.root / (pdfinfo.PREVIEW_DIR_PREFIX + 'link')
        try: link.symlink_to(self.root)
        except OSError: return
        with self.assertRaises(pdfinfo.PdfError): pdfinfo.run_op({**ok, 'out': str(link)}, engine.source_file)

    def test_preview_op_with_locked_or_missing_renderer_still_returns_info(self):
        writer = PdfWriter(); writer.add_blank_page(100, 100); writer.encrypt('segredo')
        locked = self.root / 'locked.pdf'
        with locked.open('wb') as handle: writer.write(handle)
        result = pdfinfo.run_op({'op': 'pdf_preview', 'path': str(locked), 'out': str(self.preview_dir()), 'thumbs': 3, 'page': 1}, engine.source_file)
        self.assertTrue(result['info']['encrypted']); self.assertEqual(result['files'], [])
        path = self.write('p.pdf', make_pdf())
        with mock.patch.object(pdfinfo, '_pdfium', side_effect=pdfinfo.PdfError('A prévia das páginas precisa do pacote pypdfium2')):
            result = pdfinfo.run_op({'op': 'pdf_preview', 'path': str(path), 'out': str(self.preview_dir()), 'thumbs': 3, 'page': 1}, engine.source_file)
        self.assertEqual(result['files'], []); self.assertIn('pypdfium2', result['info']['preview_note']); self.assertEqual(result['info']['pages'], 1)

    def test_more_than_200_pages_still_previews_the_first_ones(self):
        big = self.blank('big.pdf', pages=201, width=60, height=60)
        result = pdfinfo.run_op({'op': 'pdf_preview', 'path': str(big), 'out': str(self.preview_dir()), 'thumbs': 4, 'page': 1}, engine.source_file)
        self.assertEqual(len(result['files']), 5); self.assertIn('200', result['info']['preview_note'])


@NEEDS_PDFIUM
class RunnerTests(PdfBase):
    def test_real_worker_round_trip_returns_png_bytes_and_leaves_no_folder(self):
        import tempfile as tf
        path = self.write('p.pdf', make_pdf(pages=2))
        before = {p.name for p in Path(tf.gettempdir()).glob(pdfinfo.PREVIEW_DIR_PREFIX + '*')}
        result = runner.run_pdf_op({'op': 'pdf_preview', 'path': str(path), 'thumbs': 24, 'page': 1})
        self.assertEqual(result['info']['pages'], 2)
        kinds = sorted((p['kind'], p['page']) for p in result['pages'])
        self.assertEqual(kinds, [('page', 1), ('thumb', 1), ('thumb', 2)])
        for item in result['pages']: self.assertTrue(item['data'].startswith(b'\x89PNG'))
        self.assertEqual({p.name for p in Path(tf.gettempdir()).glob(pdfinfo.PREVIEW_DIR_PREFIX + '*')}, before)

    def test_real_worker_info_and_errors(self):
        good = self.write('p.pdf', make_pdf())
        result = runner.run_pdf_op({'op': 'pdf_info', 'paths': [str(good), str(self.root / 'x.pdf')]})
        self.assertEqual(result['infos'][0]['pages'], 1); self.assertIn('error', result['infos'][1])
        with self.assertRaisesRegex(ValueError, 'inválid|desconhecida|PDF'): runner.run_pdf_op({'op': 'pdf_preview', 'path': str(good), 'thumbs': 99, 'page': 1})

    def test_runner_refuses_files_that_escape_the_preview_folder(self):
        def fake(job, cancel=None, timeout=60, command=None):
            return {'info': {}, 'files': [{'page': 1, 'kind': 'page', 'file': '../fora.png', 'size': [1, 1]}]}
        with mock.patch.object(runner, '_run_job', fake), self.assertRaisesRegex(ValueError, 'inválida'):
            runner.run_pdf_op({'op': 'pdf_preview', 'path': str(self.root / 'x.pdf')})

    def test_real_worker_cancellation_is_honoured(self):
        from threading import Event
        cancel = Event(); cancel.set()
        with self.assertRaises(runner.Cancelled): runner.run_pdf_op({'op': 'pdf_info', 'paths': [str(self.write('p.pdf', make_pdf()))]}, cancel=cancel)


if __name__ == '__main__':
    unittest.main()
