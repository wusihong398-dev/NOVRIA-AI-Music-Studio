from pathlib import Path
import re

# Make artifact cache destinations unique per worker so stale .part files from an
# older worker can never collide with a newly opened song.
main_path = Path('app/main.py')
main = main_path.read_text(encoding='utf-8')
main = re.sub(r'VERSION = "3\.5\.[0-9]+"', 'VERSION = "3.5.4"', main, count=1)
main = main.replace(
    '        self.destination = Path(destination)\n',
    "        self.destination = Path(destination) / f'session_{os.getpid()}_{time.time_ns()}_{os.urandom(3).hex()}'\n",
    1,
)
main_path.write_text(main, encoding='utf-8')

# Override the desktop close path at launcher level.  v3.5.2 could wait forever
# for a model/cache QThread to release resources.  v3.5.4 requests interruption,
# then terminates remaining QThreads after a short grace period and accepts the
# close event immediately.
launcher_path = Path('app/launcher.py')
launcher = launcher_path.read_text(encoding='utf-8')
launcher = re.sub(r'VERSION = "3\.5\.[0-9]+"', 'VERSION = "3.5.4"', launcher, count=1)
marker = '    m.SeparationWorker = ProcessSeparationWorker\n'
if marker not in launcher:
    raise SystemExit('launcher patch marker not found')
insert = r'''    m.SeparationWorker = ProcessSeparationWorker

    def _v354_fast_close(self, event):
        # Stop audio engines first so WAV files are released before cache workers.
        for name in ('engine', 'multi_stem_engine', 'stem_engine', 'audio_engine'):
            obj = getattr(self, name, None)
            if obj is not None:
                for method in ('stop', 'close'):
                    fn = getattr(obj, method, None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:
                            pass
        threads = []
        for value in list(getattr(self, '__dict__', {}).values()):
            if isinstance(value, QThread):
                threads.append(value)
            elif isinstance(value, (list, tuple, set)):
                threads.extend(v for v in value if isinstance(v, QThread))
        seen = set()
        for thread in threads:
            if id(thread) in seen:
                continue
            seen.add(id(thread))
            try:
                thread.requestInterruption()
                thread.quit()
                if not thread.wait(250):
                    thread.terminate()
                    thread.wait(500)
            except Exception:
                pass
        try:
            event.accept()
        except Exception:
            pass

    m.MainWindow.closeEvent = _v354_fast_close
'''
launcher = launcher.replace(marker, insert, 1)
launcher_path.write_text(launcher, encoding='utf-8')
print('PATCH_WINDOWS_EXIT_V354_OK')
