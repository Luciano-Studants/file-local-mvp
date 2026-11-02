import errno, json, os, signal, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine, runner
from engine import convert, publish, ConversionError
from PIL import Image
from pypdf import PdfWriter

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.src=self.root/'input.png';Image.new('RGB',(8,8),'red').save(self.src)
    def tearDown(self):self.tmp.cleanup()
    def job(self,target='JPEG',path=None):return {'paths':[str(path or self.src)],'target':target,'output':str(self.root)}
    def test_exclusive_copy_fallback_collision(self):
        stage=self.root/'stage';stage.write_bytes(b'new');existing=self.root/'out.txt';existing.write_bytes(b'original')
        with patch('engine.os.link',side_effect=OSError(errno.EOPNOTSUPP,'unsupported')):
            out=Path(publish(stage,self.root,'out','txt'))
        self.assertEqual(existing.read_bytes(),b'original');self.assertEqual(out.read_bytes(),b'new');self.assertNotEqual(out,existing)
    def test_copy_failure_removes_only_partial_output(self):
        stage=self.root/'stage';stage.write_bytes(b'new')
        with patch('engine.os.link',side_effect=OSError(errno.EPERM,'unsupported')),patch('engine.shutil.copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):publish(stage,self.root,'out','txt')
        self.assertFalse((self.root/'out.txt').exists());self.assertEqual(stage.read_bytes(),b'new')
    def test_copy_fallback_does_not_follow_destination_symlink(self):
        victim=self.root/'victim';victim.write_bytes(b'original');link=self.root/'out.txt'
        try:link.symlink_to(victim)
        except OSError:self.skipTest('Symlink privilege unavailable')
        with patch('engine.os.link',side_effect=OSError(errno.EPERM,'unsupported')):out=publish(self.src,self.root,'out','txt')
        self.assertNotEqual(out,str(link));self.assertEqual(victim.read_bytes(),b'original')
    def test_changed_identity_rejected(self):
        other=self.root/'other';other.write_bytes(b'other')
        with patch.object(Path,'resolve',return_value=other):
            with self.assertRaisesRegex(ConversionError,'O caminho mudou'):engine.source_file(self.src)
            with self.assertRaisesRegex(ConversionError,'O caminho mudou'):engine.output_folder(self.root)
    def test_pdf_recoverable_xref(self):
        p=self.root/'input.pdf';w=PdfWriter();w.add_blank_page(10,10)
        with p.open('wb') as f:w.write(f)
        data=p.read_bytes();import re
        data=re.sub(rb'startxref\n\d+',b'startxref\n1',data);p.write_bytes(data)
        with self.assertRaisesRegex(ConversionError,'não há texto'):convert(self.job('PDF → Text',p))      # o PDF com xref quebrado foi lido (sem erro de leitura); só não tem texto
    def test_worker_staging_cleanup_success_and_failure(self):
        runner.run_job(self.job());self.assertFalse(list(self.root.glob('.arquivo-local-*')))
        self.src.write_bytes(b'bad')
        with self.assertRaises(ValueError):runner.run_job(self.job())
        self.assertFalse(list(self.root.glob('.arquivo-local-*')))
    def test_cancelled_worker_staging_cleanup(self):
        event=threading.Event();event.set()
        with self.assertRaises(runner.Cancelled):runner.run_job(self.job(),cancel=event)
        self.assertFalse(list(self.root.glob('.arquivo-local-*')))
    def test_cancelled_job_never_publishes_staged_output(self):
        event=threading.Event()
        staged_seen=[]
        def cancel_after_stage():
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if list(self.root.glob('.arquivo-local-job-*/partial.txt')):
                    staged_seen.append(True);event.set();return
                time.sleep(.01)
            staged_seen.append(False);event.set()
        timer=threading.Thread(target=cancel_after_stage);timer.start()
        script=("import json,pathlib,sys,time; j=json.loads(sys.stdin.buffer.read()); "
                "p=pathlib.Path(j['output'])/'partial.txt'; p.write_text('staged'); "
                "print(json.dumps({'ok':True,'outputs':[str(p)]}),flush=True); time.sleep(30)")
        try:
            with self.assertRaises(runner.Cancelled):
                runner.run_job(self.job('JPEG'),cancel=event,command=[sys.executable,'-c',script])
        finally:
            timer.join(timeout=5)
        self.assertEqual(staged_seen, [True])
        self.assertFalse(list(self.root.glob('partial*.txt')))
        self.assertFalse(list(self.root.glob('.arquivo-local-job-*')))
        self.assertFalse(list(self.root.glob('.arquivo-local-*')))
    @unittest.skipIf(os.name=='nt','POSIX signal reporting')
    def test_cpu_signal_message(self):
        with self.assertRaisesRegex(ValueError,'limite de tempo de CPU'):
            runner.run_job({},command=[sys.executable,'-c','import os,signal;os.kill(os.getpid(),signal.SIGXCPU)'])
    @unittest.skipUnless(os.name=='nt','Windows taskkill fallback')
    def test_taskkill_failure_still_kills_worker(self):
        for error in [FileNotFoundError(),subprocess.TimeoutExpired('taskkill',10)]:
            proc=Mock();proc.poll.return_value=None
            with patch('runner.subprocess.run',side_effect=error):runner.stop(proc)
            proc.kill.assert_called_once();proc.wait.assert_called_once()
if __name__=='__main__':unittest.main()
