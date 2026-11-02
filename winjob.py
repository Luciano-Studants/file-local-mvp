"""Objeto de trabalho (Job Object) do Windows para o processo worker — limites de memória, de processos filhos e de tempo de CPU.

Núcleo puro (sem Qt, sem importar o motor). No Linux o worker se limita sozinho (`RLIMIT_AS`, `RLIMIT_CPU` em app.py); no Windows não há
`setrlimit`, então o processo que lança o worker o coloca num Job Object logo depois de criá-lo:

* memória confirmada (commit) por processo: `PROCESS_MEMORY_LIMIT` (3 GiB — mais folgado que os 1,5 GiB de memória virtual do Linux, porque o
  commit do Windows conta de outro jeito; ajustar com medições reais no Windows);
* no máximo 4 processos ativos no job (o worker + o Tesseract do OCR + folga);
* tempo de CPU por processo: 170 s (o tempo total de relógio continua limitado pelo `timeout` do runner);
* `KILL_ON_JOB_CLOSE`: se o aplicativo fechar ou travar, o Windows encerra o worker e os filhos.

**Isto nunca foi executado no Windows real** (a 0.9.26 foi feita no Linux): o tamanho das estruturas e a sequência de chamadas são conferidos por
testes, e qualquer falha (permissão, job já aninhado, Windows antigo) **não impede a conversão** — o worker segue sem os limites e o motivo fica em
`last_error`. Nada aqui usa rede nem executa arquivos do usuário.
"""
from __future__ import annotations

import ctypes
import os

JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

MEMORY_LIMIT = 3 * 1024 ** 3
ACTIVE_PROCESS_LIMIT = 4
CPU_SECONDS = 170
last_error = ''


class BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64), ('LimitFlags', ctypes.c_uint32),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', ctypes.c_uint32),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', ctypes.c_uint32), ('SchedulingClass', ctypes.c_uint32)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters), ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


def build_limits(memory=MEMORY_LIMIT, processes=ACTIVE_PROCESS_LIMIT, cpu_seconds=CPU_SECONDS):
    """Estrutura de limites pronta para `SetInformationJobObject` (testável em qualquer sistema)."""
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_PROCESS_TIME | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    limits.BasicLimitInformation.ActiveProcessLimit = int(processes)
    limits.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu_seconds) * 10_000_000      # unidades de 100 ns
    limits.ProcessMemoryLimit = int(memory)
    return limits


def _kernel32():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    return kernel32


def attach(process, kernel32=None):
    """Põe o processo (um `subprocess.Popen`) num Job Object com limites. Devolve o identificador do job (guardar até o fim do worker e chamar
    `release`) ou None se não foi possível — nesse caso o worker roda sem os limites e `last_error` diz por quê."""
    global last_error
    last_error = ''
    if kernel32 is None:
        if os.name != 'nt':
            last_error = 'Job Object só existe no Windows.'
            return None
        try:
            kernel32 = _kernel32()
        except (OSError, AttributeError) as error:
            last_error = f'kernel32 indisponível: {error}'
            return None
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        last_error = 'CreateJobObjectW falhou.'
        return None
    limits = build_limits()
    if not kernel32.SetInformationJobObject(handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(limits), ctypes.sizeof(limits)):
        last_error = 'SetInformationJobObject falhou.'
        kernel32.CloseHandle(handle)
        return None
    process_handle = getattr(process, '_handle', None)
    if process_handle is None or not kernel32.AssignProcessToJobObject(handle, int(process_handle)):
        last_error = 'AssignProcessToJobObject falhou (o processo pode já estar em outro job sem aninhamento).'
        kernel32.CloseHandle(handle)
        return None
    return handle


def release(handle, kernel32=None):
    """Fecha o job (com KILL_ON_JOB_CLOSE, encerra o que ainda estiver nele)."""
    if not handle:
        return
    try:
        (kernel32 or _kernel32()).CloseHandle(handle)
    except (OSError, AttributeError):
        pass
