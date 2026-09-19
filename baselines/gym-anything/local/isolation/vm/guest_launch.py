"""Service entry point for one software's official build inside the guest."""
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
JOB=Path('/home/ga/job')


def main():
    os.umask(0o077)
    os.environ.update(json.loads((JOB/'environment.json').read_text()))
    from local.isolation.vm.guest_run import main as build
    result={'started':time.time()}
    try:
        result['returncode']=build()
    except BaseException as error:
        result.update(returncode=1,error_type=type(error).__name__)
        traceback.print_exc()
    finally:
        result['finished']=time.time()
        (JOB/'exit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result['returncode']


if __name__=='__main__':raise SystemExit(main())
