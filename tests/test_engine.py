import concurrent.futures, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import convert, source_file, output_folder, publish, ConversionError, MAX_BYTES, OPERATIONS
from runner import run_job, Cancelled
from PIL import Image
from pypdf import PdfReader, PdfWriter

class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.src=self.root/'源 image ; $danger.png';Image.new('RGBA',(32,24),(255,0,0,128)).save(self.src)
    def tearDown(self):self.tmp.cleanup()
    def job(self,target,paths=None,**kw):return dict(paths=[str(p) for p in (paths or [self.src])],target=target,output=str(self.root),**kw)
    def pdf(self,name='input.pdf',pages=2):
        p=self.root/name;w=PdfWriter()
        for _ in range(pages):w.add_blank_page(100,100)
        with p.open('wb') as f:w.write(f)
        return p
    def test_all_image_outputs(self):
        for target in ('PNG','JPEG','WEBP','TIFF','BMP'):
            with self.subTest(target=target):
                p=Path(convert(self.job(target))[0]);im=Image.open(p);im.load();self.assertEqual(im.size,(32,24));im.close()
    def test_jpeg_alpha_white(self):
        p=convert(self.job('JPEG'))[0]
        with Image.open(p) as im:self.assertGreater(im.getpixel((0,0))[1],100)
    def test_resize_rotate(self):
        p=convert(self.job('PNG',width=16,rotation=90))[0]
        with Image.open(p) as im:self.assertEqual(im.size,(12,16))
    def test_crop_png_bounds_dimensions_and_original_preserved(self):
        before=self.src.read_bytes()
        output=convert(self.job('Crop → PNG',crop_x=2,crop_y=3,crop_width=12,crop_height=10))[0]
        with Image.open(output) as im:
            self.assertEqual(im.format,'PNG');self.assertEqual(im.size,(12,10))
        self.assertEqual(self.src.read_bytes(),before)
        with self.assertRaisesRegex(ConversionError,'área de recorte'):
            convert(self.job('Crop → PNG',crop_x=31,crop_y=0,crop_width=2,crop_height=2))
    def test_canvas_centers_image_and_uses_selected_background(self):
        output=convert(self.job('Canvas → PNG',canvas_width=40,canvas_height=36,background='#00FF00'))[0]
        with Image.open(output) as im:
            self.assertEqual(im.size,(40,36));self.assertEqual(im.getpixel((0,0)),(0,255,0,255))
            self.assertGreater(im.getpixel((4,6))[0],100);self.assertGreater(im.getpixel((4,6))[1],100)
        with self.assertRaisesRegex(ConversionError,'canvas'):
            convert(self.job('Canvas → PNG',canvas_width=10,canvas_height=10))
    def test_annotation_is_flattened_into_png(self):
        output=convert(self.job('Annotate → PNG',annotation='Teste',annotation_x=0,annotation_y=0,annotation_color='#0000FF'))[0]
        with Image.open(output) as im:
            self.assertEqual(im.size,(32,24));self.assertEqual(im.format,'PNG')
            rgb=im.convert('RGB');pixels=rgb.tobytes();rgb.close()
            self.assertTrue(any(pixels[index+2]>200 and pixels[index]<20 for index in range(0,len(pixels),3)))
        with self.assertRaisesRegex(ConversionError,'anotação'):
            convert(self.job('Annotate → PNG',annotation=''))
    def test_annotation_size_scales_text_and_is_validated(self):
        def blue_pixels(size):
            output=convert(self.job('Annotate → PNG',annotation='Teste',annotation_x=0,annotation_y=0,annotation_color='#0000FF',annotation_size=size))[0]
            with Image.open(output) as im:
                rgb=im.convert('RGB');data=rgb.tobytes();rgb.close();count=sum(1 for i in range(0,len(data),3) if data[i+2]>200 and data[i]<20)
            return count
        self.assertGreater(blue_pixels(24),blue_pixels(8))
        for bad in (7,401):
            with self.assertRaisesRegex(ConversionError,'tamanho'):
                convert(self.job('Annotate → PNG',annotation='x',annotation_size=bad))
    def test_compress_jpeg_quality_writes_jpeg_and_preserves_source(self):
        before=self.src.read_bytes()
        output=convert(self.job('Compress → JPEG',quality=65))[0]
        with Image.open(output) as im:self.assertEqual(im.format,'JPEG')
        self.assertEqual(self.src.read_bytes(),before)
        with self.assertRaisesRegex(ConversionError,'Opções de imagem inválidas'):
            convert(self.job('Compress → JPEG',quality=0))
    def test_original_unchanged(self):
        before=self.src.read_bytes();convert(self.job('JPEG'));self.assertEqual(before,self.src.read_bytes())
    def test_never_overwrite(self):
        a=Path(convert(self.job('JPEG'))[0]);before=a.read_bytes();b=convert(self.job('JPEG'))[0];self.assertNotEqual(str(a),b);self.assertEqual(a.read_bytes(),before)
    def test_parallel_publication(self):
        stage=self.root/'stage';stage.write_bytes(b'safe')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:out=list(pool.map(lambda _:publish(stage,self.root,'same','txt'),range(20)))
        self.assertEqual(len(set(out)),20);self.assertTrue(all(Path(p).read_bytes()==b'safe' for p in out))
    def test_image_pdf(self):self.assertEqual(len(PdfReader(convert(self.job('Image → PDF'))[0]).pages),1)
    def test_pdf_merge_split_text(self):
        a=self.pdf();b=self.pdf('two.pdf',1);merged=convert(self.job('Merge PDFs',[a,b]))[0];self.assertEqual(len(PdfReader(merged).pages),3)
        pages=convert(self.job('Split PDF',[a]));self.assertEqual(len(pages),2);self.assertTrue(all(len(PdfReader(p).pages)==1 for p in pages))
        with self.assertRaisesRegex(ConversionError,'não há texto'):convert(self.job('PDF → Text',[a]))      # páginas em branco: nada é salvo (0.9.34)
        from test_illustrator import make_pdf
        t=self.root/'com-texto.pdf';t.write_bytes(make_pdf(b'BT /F1 24 Tf 10 40 Td (Ola mundo) Tj ET',font=True))
        text=convert(self.job('PDF → Text',[t]))[0];self.assertTrue(Path(text).exists());self.assertIn('Ola mundo',Path(text).read_text(encoding='utf8'))
    def test_encrypted_pdf(self):
        p=self.root/'locked.pdf';w=PdfWriter();w.add_blank_page(100,100);w.encrypt('password')
        with p.open('wb') as f:w.write(f)
        with self.assertRaisesRegex(ConversionError,'senha'):convert(self.job('PDF → Text',[p]))
    def test_pdf_page_limit(self):
        with self.assertRaisesRegex(ConversionError,'200'):convert(self.job('Split PDF',[self.pdf(pages=201)]))
    def test_only_images_pdfs_and_audio_are_enabled(self):
        self.assertEqual(set(OPERATIONS), {'PNG', 'JPEG', 'WEBP', 'TIFF', 'BMP', 'Image → PDF', 'Crop → PNG', 'Canvas → PNG', 'Annotate → PNG', 'Compress → JPEG', 'Collage → PNG', 'Backdrop → PNG', 'Remove Background → PNG', 'Redact → PNG', 'Clean → PNG', 'Adjust → PNG', 'Resize → PNG', 'Rotate → PNG', 'Watermark → PNG', 'Sharpen → PNG', 'Levels → PNG', 'Shapes → PNG', 'Images → One PDF', 'OCR → Text', 'OCR → PDF', 'PDF → Text', 'PDF → Images', 'Merge PDFs', 'Split PDF', 'Organize PDF', 'Extract PDF Images', 'PDF OCR → PDF', 'PDF OCR → Text', 'Clean PDF', 'Compress PDF', 'Stamp PDF', 'Protect PDF', 'Unprotect PDF', 'Redact PDF', 'Fill PDF', 'Convert Audio', 'Audio Tags', 'Audio Channels', 'Audio Trim', 'Audio Normalize', 'Compress Audio'})
        for target in ('MP3', 'SRT → VTT', 'SHA-256'):
            with self.subTest(target=target), self.assertRaises(ConversionError):
                convert(self.job(target))
    def test_unc_output_path_rejected_on_windows(self):
        unc=chr(92)*2+'server'+chr(92)+'share'
        with patch('engine.os.name','nt'), self.assertRaisesRegex(ConversionError,'Pastas de saída em rede'):
            output_folder(unc)
    def test_corrupt_image(self):
        self.src.write_text('not an image')
        with self.assertRaises(Exception):convert(self.job('JPEG'))
        self.assertFalse(list(self.root.glob('*converted*')))
    def test_unsupported_svg(self):
        p=self.root/'bad.svg';p.write_text('<svg/>')
        with self.assertRaises(ConversionError):convert(self.job('PNG',[p]))
    def test_symlink_input(self):
        p=self.root/'link.png'
        try:p.symlink_to(self.src)
        except OSError:self.skipTest('Account cannot create symbolic links')
        with self.assertRaises(ConversionError):source_file(p)
    def test_symlink_destination_not_followed(self):
        stage=self.root/'stage';stage.write_bytes(b'converted');victim=self.root/'victim';victim.write_bytes(b'original');link=self.root/'output.txt'
        try:link.symlink_to(victim)
        except OSError:self.skipTest('Account cannot create symbolic links')
        dest=publish(stage,self.root,'output','txt');self.assertNotEqual(dest,str(link));self.assertEqual(victim.read_bytes(),b'original')
    def test_empty_large_directory_relative(self):
        p=self.root/'empty';p.touch()
        for path in (p,self.root,Path('relative.png')):
            with self.assertRaises(Exception):source_file(path)
        with p.open('wb') as f:f.truncate(MAX_BYTES+1)
        with self.assertRaises(ConversionError):source_file(p)
    def test_image_bomb_limit(self):
        # Header-only PNG with excessive dimensions fails before allocating pixels.
        import struct,zlib
        data=struct.pack('>IIBBBBB',10000,10000,8,2,0,0,0);crc=zlib.crc32(b'IHDR'+data)
        self.src.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+data+struct.pack('>I',crc))
        with self.assertRaises(Exception):convert(self.job('PNG'))
    def test_bad_target_and_options(self):
        for target,opts in [('evil',{}),('JPEG',{'rotation':13}),('JPEG',{'width':999999})]:
            with self.assertRaises(ConversionError):convert(self.job(target,**opts))
    def test_subprocess_worker(self):
        result=run_job(self.job('JPEG'));self.assertTrue(Path(result[0]).is_file())
    def test_runner_publishes_all_split_pdf_outputs_after_success(self):
        source=self.pdf('two-pages.pdf',pages=2)
        outputs=run_job(self.job('Split PDF',[source]))
        self.assertEqual(len(outputs),2)
        self.assertTrue(all(Path(path).is_file() and Path(path).parent==self.root/'two-pages - partes' for path in outputs))      # várias partes vão para a pasta «- partes» (0.9.32)
        self.assertFalse(list(self.root.glob('.arquivo-local-job-*')))
    def test_worker_failure_then_success(self):
        bad=self.root/'bad.png';bad.write_bytes(b'broken')
        with self.assertRaises(ValueError):run_job(self.job('JPEG',[bad]))
        self.assertTrue(run_job(self.job('JPEG')))
    def test_timeout(self):
        with self.assertRaises(TimeoutError):run_job({},timeout=.15,command=[sys.executable,'-c','import time;time.sleep(30)'])
    def test_cancellation(self):
        event=threading.Event();event.set()
        with self.assertRaises(Cancelled):run_job({},cancel=event,command=[sys.executable,'-c','import time;time.sleep(30)'])
    def test_animated_image_rejected(self):
        p=self.root/'animated.webp'
        a=Image.new('RGB',(8,8),'red');b=Image.new('RGB',(8,8),'blue');a.save(p,save_all=True,append_images=[b],duration=100,loop=0)
        with self.assertRaisesRegex(ConversionError,'animadas'):convert(self.job('JPEG',[p]))
    def test_batch_limit(self):
        with self.assertRaises(ConversionError):convert(self.job('Merge PDFs',[self.src]*101))
if __name__=='__main__':unittest.main()
