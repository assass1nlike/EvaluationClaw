"""Run the official four phases inside one independent generation VM."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from dotenv import dotenv_values
from local import generate
from local.seed_batch import record_claude, seed_everything
from extras.research.task_generation.propose_and_amplify import method


def main():
    job=Path('/home/ga/job')
    config=json.loads((job/'config.json').read_text())
    api=dotenv_values(ROOT/'local/.env')
    seed_everything(42)
    os.environ.update(SCREENSHOT_QUERY_PROVIDER='openai',SCREENSHOT_QUERY_MODEL=api['DEEPSEEK_MODEL'],
                      SCREENSHOT_QUERY_BASE_URL=api['DEEPSEEK_BASE_URL'],SCREENSHOT_QUERY_API_KEY=api['DEEPSEEK_API_KEY'],
                      GYM_SCREENSHOT_AUDIT=str(job/'screenshot-api.jsonl'))
    official=method.propose_cc.run_claude
    phase=0

    def observed(binary,args,*,cwd,timeout):
        nonlocal phase
        phase+=1
        return record_claude(official,binary,args,cwd=cwd,timeout=timeout,job=job,phase=phase)

    method.propose_cc.run_claude=observed
    return generate.main([
        '--deepseek','--requirement-file',str(job/'requirement.txt'),
        '--software',config['software'],'--env-dir',config['env'],
        '--workspace',str(ROOT),'--stage','propose','--task-type','enterprise',
        '--output-dir',str(job/'generation'),'--timeout-sec','36000',
        '--claude-bin','/home/ga/.local/bin/claude',
    ])


if __name__=='__main__':raise SystemExit(main())
