"""One disposable worker per job; cancellation kills the entire process tree."""
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from contextlib import ExitStack
from engine import output_folder, publish, create_pages_folder, output_group_suffix, PDF_LONG_TARGETS, PDF_OCR_TIMEOUT
import tool_registry
import winjob

class Cancelled(Exception): pass

def worker_command():
    if getattr(sys,'frozen',False): return [sys.executable,'--worker']
    executable=sys.executable
    if os.name=='nt' and Path(executable).name.lower()=='pythonw.exe':
        executable=str(Path(executable).with_name('python.exe'))
    return [executable,str(Path(__file__).with_name('app.py')),'--worker']

def stop(proc):
    if proc.poll() is not None: return
    if os.name=='nt':
        taskkill=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'taskkill.exe'
        try:
            if not taskkill.is_absolute():raise OSError('Invalid Windows system directory')
            subprocess.run([str(taskkill),'/PID',str(proc.pid),'/T','/F'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        except (OSError,subprocess.TimeoutExpired):pass
    else:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    try:
        if proc.poll() is None:proc.kill()
        proc.wait(timeout=10)
    except (OSError,subprocess.TimeoutExpired):pass

def run_job(job,cancel=None,timeout=180,command=None):
    with ExitStack() as cleanup:
        job=dict(job)
        if job.get('paths'):
            folder=output_folder(job.get('output') or Path(job['paths'][0]).parent)
            job_root=Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='.arquivo-local-job-',dir=folder)))
            job['output']=str(job_root)
            job['_work_root']=cleanup.enter_context(tempfile.TemporaryDirectory(prefix='.arquivo-local-work-',dir=job_root))
            staged_outputs=_run_job(job,cancel,max(timeout,PDF_OCR_TIMEOUT) if job.get('target') in PDF_LONG_TARGETS else timeout,command)
            if cancel is not None and cancel.is_set():
                raise Cancelled('Cancelado antes da publicação; nenhuma saída ficou visível.')
            published=[];pages_folder=None
            try:
                suffix=output_group_suffix(job)
                if suffix and staged_outputs:
                    pages_folder=create_pages_folder(folder,Path(job['paths'][0]).stem,suffix)      # «<nome> - páginas»: criada só depois de todas as páginas estarem prontas
                for raw in staged_outputs:
                    stage=Path(raw)
                    if stage.parent.resolve()!=job_root.resolve():
                        raise ValueError('O worker devolveu uma saída fora da pasta privada de preparo.')
                    info=stage.lstat()
                    if not stage.is_file() or stage.is_symlink() or not 0<info.st_size<=512*1024*1024:
                        raise ValueError('O worker devolveu uma saída inválida ou grande demais.')
                    published.append(publish(stage,pages_folder or folder,stage.stem,stage.suffix.lstrip('.')))
            except BaseException:
                if pages_folder is not None:
                    for done in published:
                        try: Path(done).unlink()
                        except OSError: pass
                    try: pages_folder.rmdir()
                    except OSError: pass
                raise
            return published
        return _run_job(job,cancel,timeout,command)

def _run_job(job,cancel=None,timeout=180,command=None):
    payload=json.dumps(job).encode()
    if len(payload)>65536: raise ValueError('Pedido do job grande demais.')
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
        proc=subprocess.Popen(command or worker_command(),stdin=subprocess.PIPE,stdout=out,stderr=err,**kwargs)
        job_handle=winjob.attach(proc) if os.name=='nt' else None      # limites de memória/processos/CPU no Windows (0.9.26; falha não impede o trabalho)
        start=time.monotonic()
        try:
            proc.stdin.write(payload);proc.stdin.close()
            while proc.poll() is None:
                if cancel is not None and cancel.is_set(): raise Cancelled('Cancelado; as saídas já concluídas foram mantidas.')
                if time.monotonic()-start>timeout: raise TimeoutError('A conversão excedeu o tempo limite; tente um arquivo menor.')
                if os.fstat(out.fileno()).st_size>131072 or os.fstat(err.fileno()).st_size>131072: raise ValueError('O worker excedeu os limites de diagnóstico.')
                time.sleep(.04)
            out.seek(0)
            if proc.returncode<0:
                label={getattr(signal,'SIGXCPU',-100):'limite de tempo de CPU',getattr(signal,'SIGXFSZ',-101):'limite de tamanho de saída',signal.SIGKILL:'encerramento forçado (possível falta de memória ou término externo)'}.get(-proc.returncode,'sinal '+str(-proc.returncode))
                raise ValueError('O worker de conversão parou: '+label+'.')
            result=json.loads(out.read(131073))
            if not result.get('ok'): raise ValueError(result.get('error','A conversão falhou.'))
            if proc.returncode!=0: raise ValueError('O worker de conversão terminou de forma inesperada.')
            return result['outputs']
        except (json.JSONDecodeError,UnicodeDecodeError) as e:
            raise ValueError('O worker de conversão falhou. O arquivo pode não ser suportado ou exceder os limites de recursos.') from e
        finally:
            stop(proc)
            winjob.release(job_handle)

def run_media_op(job,cancel=None,timeout=60,command=None):
    """Leitura de áudio para a interface (`audio_info` → `{'infos': [...]}`) em worker descartável; nada é gravado ao lado dos arquivos do usuário."""
    return _run_job(dict(job),cancel,timeout,command)

def run_pdf_op(job,cancel=None,timeout=60,command=None):
    """Leitura de PDF para a interface (informações e prévia) em worker descartável, sem abrir o PDF no processo da interface.

    `pdf_info` devolve `{'infos': [...]}`; `pdf_preview` devolve `{'info': ..., 'pages': [{'page','kind','data'(PNG),'size'}]}` com as imagens já lidas
    (a pasta temporária de prévia some ao fim). Nada é gravado ao lado dos arquivos do usuário.
    """
    import pdfinfo
    job=dict(job)
    if job.get('op')!='pdf_preview': return _run_job(job,cancel,timeout,command)
    with tempfile.TemporaryDirectory(prefix=pdfinfo.PREVIEW_DIR_PREFIX) as folder:
        job['out']=folder
        result=_run_job(job,cancel,timeout,command)
        pages=[]
        for item in result.get('files',[]):
            name=str(item.get('file',''))
            path=Path(folder)/name
            if Path(name).name!=name or not path.is_file() or path.is_symlink() or path.stat().st_size>32*1024*1024: raise ValueError('O worker devolveu uma imagem de prévia inválida.')
            pages.append({'page':item['page'],'kind':item['kind'],'data':path.read_bytes(),'size':item['size']})
        return {'info':result.get('info',{}),'pages':pages}
